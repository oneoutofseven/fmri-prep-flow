"""One container backend and one pinned fMRIPrep interface."""

import os
import shutil
import subprocess
from pathlib import Path

from ..common.io import now
from ..config import IMAGE


def doctor(config):
    binary = shutil.which("singularity")
    license_path = config.get("fs_license")
    checks = {
        "singularity_available": bool(binary),
        "version_probe": False,
        "license_readable": bool(
            license_path and Path(license_path).is_file() and os.access(license_path, os.R_OK)
        ),
    }
    version = ""
    if binary:
        probe = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=20)
        version = (probe.stdout + probe.stderr).strip()
        checks["version_probe"] = probe.returncode == 0
    return {
        "checked_at": now(),
        "ready": all(checks.values()),
        "checks": checks,
        "runtime": version,
        "container_execution_verified": False,
        "note": "Host checks only; resource settings are scheduling budgets, not OS quotas.",
    }


def mount(path):
    value = str(Path(path).resolve())
    if any(c in value for c in (",", ":", "\n", "\r")):
        raise ValueError("Unsupported character in Singularity bind path")
    return value


def command(config, staging, subject, root):
    root = Path(root)
    if not config["fs_license"]:
        raise ValueError("Set fs_license or FS_LICENSE before creating a plan")
    argv = [
        "singularity",
        "run",
        "--cleanenv",
        "--containall",
        "--home",
        mount(root / "work") + ":/work",
        "--pwd",
        "/work",
        "--env",
        f"TEMPLATEFLOW_HOME=/templateflow,OMP_NUM_THREADS={config['omp_nthreads']}",
    ]
    for host, target, mode in [
        (staging["bids_root"], "/data", "ro"),
        (root / "derivatives", "/out", "rw"),
        (root / "work", "/work", "rw"),
        (root / "templateflow", "/templateflow", "rw"),
        (config["fs_license"], "/license.txt", "ro"),
    ]:
        argv += ["--bind", f"{mount(host)}:{target}:{mode}"]
    argv += [
        "docker://" + IMAGE,
        "/data",
        "/out",
        "participant",
        "--participant-label",
        subject,
        "--subject-anatomical-reference",
        "sessionwise",
        "--track-sessions",
        "--output-layout",
        "bids",
        "--nprocs",
        str(config["nprocs"]),
        "--omp-nthreads",
        str(config["omp_nthreads"]),
        "--mem-mb",
        str(config["mem_mb"]),
        "--output-spaces",
        *config["output_spaces"],
        "--fs-no-reconall",
        "--fs-license-file",
        "/license.txt",
        "--skull-strip-t1w",
        "force",
        "--skull-strip-fixed-seed",
        "--random-seed",
        "1729",
        "--bold2anat-init",
        "t1w",
        "--notrack",
        "--stop-on-first-crash",
        "-w",
        "/work",
    ]
    ignore = []
    if config["sdc"] in ("none", "syn"):
        ignore.append("fieldmaps")
    if config["slice_timing"] == "skip":
        ignore.append("slicetiming")
    if ignore:
        argv += ["--ignore", *ignore]
    if config["sdc"] == "syn":
        argv += ["--use-syn-sdc", "error", "--force", "syn-sdc"]
    if config["me_output_echos"]:
        argv += ["--me-output-echos"]
    return argv
