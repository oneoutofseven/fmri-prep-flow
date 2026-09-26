"""Official local BIDS Validator; unexpected report schemas fail closed."""

import json
import shutil
import subprocess
from pathlib import Path

from ..common.io import now, read_json, sha256, verify, write_json


def error_issues(report):
    issues = report.get("issues") if isinstance(report, dict) else None
    if isinstance(issues, dict) and "issues" in issues:
        issues = issues["issues"]
    if isinstance(issues, list):
        if any(
            not isinstance(i, dict) or i.get("severity") not in {"error", "warning", "ignore"}
            for i in issues
        ):
            raise ValueError("Unknown validator issue schema")
        return [i for i in issues if i["severity"] == "error"]
    if isinstance(issues, dict) and isinstance(issues.get("errors"), list):
        return issues["errors"]
    raise ValueError("Unknown validator report schema")


def validate(staging_path, executable="bids-validator-deno"):
    staging_path = Path(staging_path).resolve()
    staged = read_json(staging_path)
    target = staging_path.parent / "validation.json"
    if target.exists():
        raise FileExistsError("Validation already recorded; use a new staging version")
    verify(staged["inventory"], staged["bids_root"])
    binary = shutil.which(executable)
    if not binary:
        raise ValueError("Install the official validator extra or specify prepare --validator")
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, timeout=30, check=True
    )
    proc = subprocess.run(
        [binary, staged["bids_root"], "--json"], capture_output=True, text=True, timeout=600
    )
    report = json.loads(proc.stdout)
    errors = error_issues(report)
    verify(staged["inventory"], staged["bids_root"])
    result = {
        "checked_at": now(),
        "passed": proc.returncode == 0 and not errors,
        "returncode": proc.returncode,
        "staging_sha256": sha256(staging_path),
        "executable": binary,
        "executable_sha256": sha256(binary),
        "version": version.stdout.strip(),
        "report": report,
        "stderr": proc.stderr[-4000:],
    }
    write_json(target, result)
    return {
        "passed": result["passed"],
        "report_path": str(target),
        "errors": len(errors),
        "version": result["version"],
    }
