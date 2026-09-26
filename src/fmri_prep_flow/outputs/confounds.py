"""Frame-aligned confounds checks; undefined first FD remains undefined."""

import csv
from pathlib import Path

import numpy as np


def confounds(path, expected_frames):
    with Path(path).open() as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        rows = list(reader)
        fields = reader.fieldnames or []
    required = [
        "trans_x",
        "trans_y",
        "trans_z",
        "rot_x",
        "rot_y",
        "rot_z",
        "framewise_displacement",
    ]
    if not rows or len(rows) != expected_frames or not set(required) <= set(fields):
        raise ValueError("Confounds length/columns do not match input BOLD")
    values = {}
    for key in required + (["dvars"] if "dvars" in fields else []):
        column = []
        for i, row in enumerate(rows):
            value = row[key]
            # FD and DVARS are undefined at the first volume; do not replace them with zero.
            if value in {"n/a", "NaN", "nan", ""}:
                if key not in {"framewise_displacement", "dvars"} or i != 0:
                    raise ValueError(f"Unexpected missing confound {key} at row {i}")
                column.append(float("nan"))
            else:
                x = float(value)
                if not np.isfinite(x) or (key in {"framewise_displacement", "dvars"} and x < 0):
                    raise ValueError("Invalid confound: " + key)
                column.append(x)
        values[key] = np.asarray(column)
    fd = values["framewise_displacement"]
    finite = np.isfinite(fd)
    if not finite.any():
        raise ValueError("No defined FD values")
    metrics = {
        "frames": len(rows),
        "fd_mean_mm": float(fd[finite].mean()),
        "fd_max_mm": float(fd[finite].max()),
        "fd_over_0_5mm_count": int((fd[finite] > 0.5).sum()),
        "fd_over_0_5mm_fraction_of_defined": float((fd[finite] > 0.5).mean()),
        "fd_defined_frames": int(finite.sum()),
        "fd_threshold_note": "Descriptive only; no exclusion or censoring policy applied",
    }
    return metrics, values
