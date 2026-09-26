import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fmri_prep_flow.common.io import read_json, write_json
from fmri_prep_flow.config import load_config
from fmri_prep_flow.inputs.prepare import prepare
from fmri_prep_flow.pipeline import runner
from fmri_prep_flow.pipeline.planning import create_plan, verify_plan
from fmri_prep_flow.pipeline.runtime import command


def planned(dataset, config, validator, tmp_path):
    staging = prepare(dataset[1], tmp_path / "prepared", validator)["staging"]
    return Path(create_plan(staging, config, tmp_path / "run")["plan"])


def test_singularity_policy_mapping(dataset, config, validator, tmp_path):
    plan_path = planned(dataset, config, validator, tmp_path)
    plan, _, staging, _ = verify_plan(plan_path)
    argv = plan["jobs"][0]["argv"]
    assert argv[0] == "singularity"
    assert "fieldmaps" in argv and "--task-id" not in argv and "--session-label" not in argv
    syn = command({**plan["config"], "sdc": "syn"}, staging, "01", tmp_path / "job")
    assert syn[syn.index("--use-syn-sdc") + 1] == "error"
    assert syn[syn.index("--force") + 1] == "syn-sdc"


@pytest.mark.parametrize(
    "change", ["plan", "input", "extra_file", "config", "manifest", "validation"]
)
def test_frozen_evidence_rejected(dataset, config, validator, tmp_path, change):
    path = planned(dataset, config, validator, tmp_path)
    plan = read_json(path)
    staged = read_json(plan["staging_path"])
    if change == "plan":
        plan["jobs"][0]["argv"].append("--bad")
        write_json(path, plan)
    elif change == "input":
        target = next(Path(staged["bids_root"]).rglob("*bold.json"))
        target.write_text("{}")
    elif change == "extra_file":
        (Path(staged["bids_root"]) / "extra.txt").write_text("changed")
    elif change == "config":
        config.write_text("{}")
    elif change == "manifest":
        Path(staged["manifest_path"]).write_text("{}")
    else:
        Path(plan["validation_path"]).write_text("{}")
    with pytest.raises(ValueError):
        verify_plan(path)


def test_engine_failure_does_not_complete(dataset, config, validator, tmp_path, monkeypatch):
    path = planned(dataset, config, validator, tmp_path)
    monkeypatch.setattr(runner, "doctor", lambda config: {"ready": True})
    monkeypatch.setattr(runner, "execute", lambda *args: 4)
    with pytest.raises(RuntimeError, match="status 4"):
        runner.run(path)
    assert read_json(path.parent / "state.json")["status"] == "failed"
    with pytest.raises(ValueError, match="fresh plan"):
        runner.run(path)


def test_missing_products_does_not_complete(dataset, config, validator, tmp_path, monkeypatch):
    path = planned(dataset, config, validator, tmp_path)
    monkeypatch.setattr(runner, "doctor", lambda config: {"ready": True})
    monkeypatch.setattr(runner, "execute", lambda *args: 0)
    with pytest.raises(ValueError, match="Expected one"):
        runner.run(path)
    assert read_json(path.parent / "state.json")["status"] == "failed"


def test_real_signal_cleanup(tmp_path):
    pidfile = tmp_path / "child.pid"
    script = tmp_path / "execute.py"
    script.write_text(
        'from fmri_prep_flow.pipeline.executor import execute\nfrom pathlib import Path\nimport sys\nexecute([sys.executable,"-c","import time; time.sleep(120)"],sys.argv[1],on_start=lambda pid: Path(sys.argv[2]).write_text(str(pid)))\n'
    )
    p = subprocess.Popen(
        [sys.executable, str(script), str(tmp_path / "engine.log"), str(pidfile)],
        env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child = None
    try:
        deadline = time.monotonic() + 10
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pidfile.exists()
        child = int(pidfile.read_text())
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=15) != 0
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        if child:
            try:
                os.killpg(child, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize(
    "override",
    [
        {"nprocs": 0},
        {"nprocs": True},
        {"omp_nthreads": 100},
        {"sdc": "none", "sdc_reason": ""},
        {"slice_timing": "guess"},
        {"runtime": "docker"},
        {"me_output_echos": "yes"},
    ],
)
def test_bad_config(config, override):
    write_json(config, {**read_json(config), **override})
    with pytest.raises(ValueError):
        load_config(config)


def test_same_plan_is_locked(dataset, config, validator, tmp_path):
    import fcntl

    path = planned(dataset, config, validator, tmp_path)
    with (path.parent / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            runner.run(path)
    assert read_json(path.parent / "state.json")["status"] == "planned"


def test_multiple_subject_jobs_are_explicit(dataset, config, validator, tmp_path):
    from conftest import acquisition

    root, selection = dataset
    acquisition(root, subject="02", session="A")
    write_json(selection, {"source_bids": str(root), "subjects": ["01", "02"]})
    path = planned(dataset, config, validator, tmp_path)
    plan, _, _, _ = verify_plan(path)
    assert [j["subject"] for j in plan["jobs"]] == ["01", "02"]
    assert all(len(j["runs"]) == 1 for j in plan["jobs"])


def test_template_cache_is_copied_not_shared(tmp_path, monkeypatch):
    seed = tmp_path / "existing-templateflow"
    seed.mkdir()
    (seed / "template.txt").write_text("original template")
    monkeypatch.setenv("TEMPLATEFLOW_HOME", str(seed))
    job = tmp_path / "job"
    runner.prepare_directories(job)
    assert (job / "templateflow/template.txt").read_text() == "original template"
    (job / "templateflow/template.txt").write_text("job modification")
    assert (seed / "template.txt").read_text() == "original template"
    assert read_json(job / "templateflow-seed.json")["inventory"]


def test_missing_template_cache_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPLATEFLOW_HOME", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="TEMPLATEFLOW_HOME"):
        runner.prepare_directories(tmp_path / "job")
