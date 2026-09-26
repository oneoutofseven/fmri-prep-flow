"""Freeze prepared inputs and create sequential subject jobs."""

import shlex
from pathlib import Path

from ..common.io import disjoint, fresh, now, read_json, sha256, verify, write_json
from ..common.provenance import environment
from ..config import IMAGE, load_config
from ..inputs.validation import error_issues
from .policy import resolve_policies
from .runtime import command, doctor


def validate_staging(path):
    path = Path(path).resolve()
    staging = read_json(path)
    if staging.get("schema_version") != 2:
        raise ValueError("Unsupported staging schema; prepare a new dataset with this installation")
    verify(staging["inventory"], staging["bids_root"])
    if sha256(staging["manifest_path"]) != staging["manifest_sha256"]:
        raise ValueError("Manifest changed after preparation")
    manifest = read_json(staging["manifest_path"])
    evidence_path = path.parent / "validation.json"
    evidence = read_json(evidence_path)
    if (
        evidence.get("passed") is not True
        or evidence["returncode"] != 0
        or error_issues(evidence["report"])
        or evidence["staging_sha256"] != sha256(path)
    ):
        raise ValueError("Official validator must pass for these exact staged inputs")
    return staging, manifest, evidence_path


def source_inventory():
    return [
        {"path": str(p), "sha256": sha256(p)}
        for p in sorted(Path(__file__).resolve().parents[1].rglob("*.py"))
    ]


def create_plan(staging_path, config_path, output):
    staging_path, config_path = Path(staging_path).resolve(), Path(config_path).resolve()
    config = load_config(config_path)
    staging, manifest, validation = validate_staging(staging_path)
    policies = resolve_policies(config, manifest)
    for source in (staging_path.parent, manifest["source_root"]):
        disjoint(source, output)
    subjects = sorted({r["entities"]["subject"] for r in manifest["runs"]})
    # Validate commands before reserving the output directory.
    jobs = [
        {
            "subject": s,
            "root": str(Path(output).resolve() / f"sub-{s}"),
            "runs": [r["id"] for r in manifest["runs"] if r["entities"]["subject"] == s],
            "argv": command(config, staging, s, Path(output).resolve() / f"sub-{s}"),
        }
        for s in subjects
    ]
    root = fresh(output)
    plan = {
        "schema_version": 2,
        "created_at": now(),
        "root": str(root),
        "image": IMAGE,
        "config": config,
        "staging_path": str(staging_path),
        "staging_sha256": sha256(staging_path),
        "validation_path": str(validation),
        "validation_sha256": sha256(validation),
        "config_path": str(config_path),
        "config_sha256": sha256(config_path),
        "code_inventory": source_inventory(),
        "environment": environment(),
        "jobs": jobs,
        "policies": policies,
        "warnings": manifest["warnings"],
    }
    write_json(root / "plan.json", plan)
    write_json(
        root / "state.json",
        {
            "status": "planned",
            "updated_at": now(),
            "plan_sha256": sha256(root / "plan.json"),
            "subjects": {s: {"status": "planned"} for s in subjects},
        },
    )
    (root / "commands.sh").write_text(
        "#!/bin/sh\n# For inspection; execute through fmri-prep-flow run to retain checks.\n"
        + "\n".join(shlex.join(j["argv"]) for j in jobs)
        + "\n"
    )
    write_json(root / "preflight.json", doctor(config))
    return {
        "plan": str(root / "plan.json"),
        "subjects": subjects,
        "runs": len(policies),
        "status": "planned",
    }


def verify_plan(path):
    path = Path(path).resolve()
    plan = read_json(path)
    if plan.get("schema_version") != 2 or path != Path(plan["root"]) / "plan.json":
        raise ValueError("Old or moved plan; create a new plan")
    state = read_json(path.parent / "state.json")
    if sha256(path) != state["plan_sha256"]:
        raise ValueError("Plan changed after creation")
    if plan["environment"] != environment():
        raise ValueError("Python environment changed; create a new plan")
    verify(plan["code_inventory"])
    if plan["code_inventory"] != source_inventory():
        raise ValueError("Installed source set changed; create a new plan")
    for key in ("staging", "validation", "config"):
        if sha256(plan[key + "_path"]) != plan[key + "_sha256"]:
            raise ValueError(f"Frozen {key} changed")
    staging, manifest, _ = validate_staging(plan["staging_path"])
    # The resolved license is frozen; later FS_LICENSE changes do not alter the plan.
    config = load_config(plan["config_path"], {"FS_LICENSE": plan["config"]["fs_license"]})
    if config != plan["config"] or resolve_policies(config, manifest) != plan["policies"]:
        raise ValueError("Frozen configuration or policies changed")
    for job in plan["jobs"]:
        if command(config, staging, job["subject"], job["root"]) != job["argv"]:
            raise ValueError("Noncanonical execution command")
    return plan, state, staging, manifest
