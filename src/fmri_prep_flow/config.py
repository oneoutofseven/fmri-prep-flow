"""Small, explicit configuration for the supported volumetric protocol."""

import os
from pathlib import Path

from .common.io import read_json

IMAGE = "nipreps/fmriprep@sha256:15cbf8dcd17440d26ff5e80e9f7313f1cb3c54f13673f1ec4aed4465e8e12d77"
DEFAULTS = {
    "nprocs": 8,
    "omp_nthreads": 8,
    "mem_mb": 32000,
    "output_spaces": ["T1w", "MNI152NLin2009cAsym:res-2"],
    "fs_license": None,
    "sdc": "auto",
    "sdc_reason": "",
    "slice_timing": "auto",
    "me_output_echos": True,
}


def load_config(path, environ=None):
    """Read overrides; relative license paths are relative to the config file."""
    path = Path(path).resolve()
    overrides = read_json(path)
    if not isinstance(overrides, dict) or set(overrides) - set(DEFAULTS):
        raise ValueError("Configuration must be an object with documented keys")
    config = {**DEFAULTS, **overrides}
    for key in ("nprocs", "omp_nthreads", "mem_mb"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key}: expected a positive integer")
    if config["omp_nthreads"] > config["nprocs"]:
        raise ValueError("omp_nthreads cannot exceed nprocs")
    # Keep the validated output contract small; arbitrary templates require new checks.
    if config["output_spaces"] != DEFAULTS["output_spaces"]:
        raise ValueError(
            "output_spaces: supported protocol requires T1w and MNI152NLin2009cAsym:res-2"
        )
    if config["sdc"] not in ("auto", "syn", "none"):
        raise ValueError("sdc: expected auto, syn or none")
    if not isinstance(config["sdc_reason"], str):
        raise ValueError("sdc_reason: expected text")
    if config["sdc"] == "none" and not config["sdc_reason"].strip():
        raise ValueError("sdc_reason: explain the explicit decision to omit distortion correction")
    if config["slice_timing"] not in ("auto", "require", "skip"):
        raise ValueError("slice_timing: expected auto, require or skip")
    if type(config["me_output_echos"]) is not bool:
        raise ValueError("me_output_echos: expected true or false")
    env = os.environ if environ is None else environ
    license_path = config["fs_license"] or env.get("FS_LICENSE")
    if license_path:
        if not isinstance(license_path, str):
            raise ValueError("fs_license: expected a path or null")
        p = Path(license_path).expanduser()
        config["fs_license"] = str((path.parent / p).resolve())
    return config
