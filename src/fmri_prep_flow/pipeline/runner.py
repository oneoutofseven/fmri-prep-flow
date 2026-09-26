"""Sequential subject jobs, independent processing and preview statuses."""

import fcntl
import os
import shutil
from pathlib import Path

from ..common.io import disjoint, inventory, now, sha256, verify, write_json
from ..outputs.products import check_run
from ..outputs.qc import preview
from .executor import execute
from .planning import verify_plan
from .runtime import doctor


def prepare_directories(root):
    """Create fresh job directories, optionally copying an existing template cache."""
    root = Path(root)
    seed = os.environ.get("TEMPLATEFLOW_HOME")
    if seed:
        seed = Path(seed).expanduser().resolve()
        if not seed.is_dir():
            raise ValueError("TEMPLATEFLOW_HOME must point to an existing template cache")
        disjoint(seed, root)
    for folder in ("work", "derivatives", "singularity-cache", "singularity-tmp"):
        (root / folder).mkdir(parents=True, exist_ok=False)
    target = root / "templateflow"
    if seed:
        shutil.copytree(seed, target)
        write_json(
            root / "templateflow-seed.json",
            {
                "source": str(seed),
                "copied_at": now(),
                "inventory": inventory(target),
            },
        )
    else:
        target.mkdir()


def run(path):
    path = Path(path).resolve()
    root = path.parent
    with (root / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan, state, staging, manifest = verify_plan(path)
        if state["status"] != "planned":
            raise ValueError("Only a fresh plan can run; create a new output directory to retry")
        preflight = doctor(plan["config"])
        if not preflight["ready"]:
            raise ValueError(f"Runtime preflight failed: {preflight['checks']}")
        state.update(status="running", started_at=now(), runner_pid=os.getpid())
        write_json(root / "state.json", state)
        index = {"schema_version": 2, "runs": []}
        current = None
        try:
            for job in plan["jobs"]:
                current = state["subjects"][job["subject"]]
                job_root = Path(job["root"])
                prepare_directories(job_root)
                current.update(status="running", started_at=now())
                write_json(root / "state.json", state)
                env = os.environ.copy()
                # Shared caches may be configured by the scheduler; isolated defaults are portable.
                env.setdefault("SINGULARITY_CACHEDIR", str(job_root / "singularity-cache"))
                env.setdefault("SINGULARITY_TMPDIR", str(job_root / "singularity-tmp"))

                def started(pid, job_state=current):
                    job_state["engine_pid"] = pid
                    write_json(root / "state.json", state)

                code = execute(job["argv"], job_root / "engine.log", env, started)
                current["engine_returncode"] = code
                if code:
                    raise RuntimeError(
                        f"fMRIPrep exited with status {code}; see {job_root / 'engine.log'}"
                    )
                verify(staging["inventory"], staging["bids_root"])
                for acquisition in manifest["runs"]:
                    if acquisition["id"] not in job["runs"]:
                        continue
                    products = check_run(
                        job_root / "derivatives",
                        acquisition,
                        plan["config"],
                        plan["policies"][acquisition["id"]],
                    )
                    product_path = root / "products" / acquisition["id"] / "products.json"
                    write_json(product_path, products)
                    entry = {
                        "run_id": acquisition["id"],
                        "path": str(product_path),
                        "sha256": sha256(product_path),
                    }
                    index["runs"].append(entry)
                    write_json(root / "products.json", index)
                    try:
                        entry["preview"] = preview(product_path, product_path.parent / "qc")
                    except Exception as error:
                        entry["preview_error"] = str(error)
                    write_json(root / "products.json", index)
                current.update(status="completed", finished_at=now())
                write_json(root / "state.json", state)
            state.update(status="completed", finished_at=now())
        except BaseException as error:
            if current is not None and current["status"] == "running":
                current.update(status="failed", error=str(error), finished_at=now())
            state.update(status="failed", error=str(error), finished_at=now())
            raise
        finally:
            state["updated_at"] = now()
            write_json(root / "state.json", state)
    return state
