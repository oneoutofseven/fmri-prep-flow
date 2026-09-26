"""Image integrity and acquisition metadata checks."""

import gzip
from itertools import pairwise
from pathlib import Path

import nibabel as nib
import numpy as np

from ..common.io import sha256


def inspect_image(path, dimensions, allow_constant=False, allow_single_volume=False):
    path = Path(path)
    before = sha256(path)
    img = nib.load(path)
    if (
        len(img.shape) != dimensions
        or min(img.shape[:3]) < 2
        or dimensions == 4
        and img.shape[3] < (1 if allow_single_volume else 2)
    ):
        raise ValueError(f"Expected nonempty {dimensions}D NIfTI: {path.name}")
    if not np.isfinite(img.affine).all() or abs(np.linalg.det(img.affine[:3, :3])) < 1e-9:
        raise ValueError("Nonfinite or singular affine")
    zooms = np.asarray(img.header.get_zooms(), dtype=float)
    if not np.isfinite(zooms).all() or (zooms <= 0).any():
        raise ValueError("Invalid voxel sizes or TR")
    if img.header.get_xyzt_units()[0] != "mm":
        raise ValueError("Spatial units must be explicit millimeters")
    q, qc = img.get_qform(coded=True)
    s, sc = img.get_sform(coded=True)
    if not qc and not sc:
        raise ValueError("Missing spatial transform codes")
    if qc and sc and not np.allclose(q, s, atol=1e-4, rtol=0):
        raise ValueError("qform/sform disagree; resolve provenance before preprocessing")
    size = 0
    with gzip.open(path, "rb") if path.name.endswith(".gz") else path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            size += len(block)  # Read through gzip footer: CRC and truncation detection.
    if size < int(img.dataobj.offset) + int(np.prod(img.shape)) * img.get_data_dtype().itemsize:
        raise ValueError("Truncated image payload")
    data = np.asarray(img.dataobj)
    if not np.isfinite(data).all() or (not allow_constant and data.max() == data.min()):
        raise ValueError("Nonfinite or constant image")
    if (
        dimensions == 4
        and not allow_constant
        and any(data[..., i].max() == data[..., i].min() for i in range(data.shape[-1]))
    ):
        raise ValueError("Constant BOLD volume")
    if sha256(path) != before:
        raise ValueError("Image changed during audit")
    return {
        "sha256": before,
        "shape": list(img.shape),
        "zooms": zooms.tolist(),
        "affine": img.affine.tolist(),
        "units": list(img.header.get_xyzt_units()),
        "orientation": "".join(nib.aff2axcodes(img.affine)),
        "all_finite": True,
    }


def positive(value):
    return type(value) in (int, float) and np.isfinite(value) and value > 0


def check_bold_metadata(metadata, info):
    """Reject malformed supplied metadata; missing STC/SDC data is handled by policy."""
    tr = metadata.get("RepetitionTime")
    if not positive(tr) or "VolumeTiming" in metadata:
        raise ValueError(
            "A constant positive RepetitionTime is required; VolumeTiming is unsupported"
        )
    factor = {"sec": 1, "msec": 0.001, "usec": 0.000001}.get(info["units"][1])
    if factor is None or not np.isclose(info["zooms"][3] * factor, tr, atol=1e-4, rtol=0):
        raise ValueError("JSON RepetitionTime disagrees with NIfTI time spacing/units")
    te = metadata.get("EchoTime")
    if not positive(te) or te >= tr:
        raise ValueError("A positive EchoTime smaller than RepetitionTime is required")
    if not isinstance(metadata.get("TaskName"), str) or not metadata["TaskName"].strip():
        raise ValueError("TaskName is required")
    for key in ("PhaseEncodingDirection", "SliceEncodingDirection"):
        if key in metadata and metadata[key] not in ("i", "i-", "j", "j-", "k", "k-"):
            raise ValueError(f"Invalid {key}")
    for key in ("TotalReadoutTime", "EffectiveEchoSpacing"):
        if key in metadata and not positive(metadata[key]):
            raise ValueError(f"Invalid {key}")
    if "SliceTiming" in metadata:
        timing = metadata["SliceTiming"]
        # Match fMRIPrep's default slice axis (k); preserve the absent field in copied metadata.
        axis = "ijk".index(metadata.get("SliceEncodingDirection", "k")[0])
        if not isinstance(timing, list) or len(timing) != info["shape"][axis]:
            raise ValueError("SliceTiming length does not match slice axis")
        if any(
            type(t) not in (int, float) or not np.isfinite(t) or not 0 <= t < tr for t in timing
        ):
            raise ValueError("SliceTiming must contain finite seconds in [0, TR)")
    warnings = []
    if all(k in metadata for k in ("EffectiveEchoSpacing", "TotalReadoutTime", "ReconMatrixPE")):
        matrix = metadata["ReconMatrixPE"]
        if type(matrix) is not int or matrix < 2:
            raise ValueError("ReconMatrixPE must be an integer greater than one")
        estimate = metadata["EffectiveEchoSpacing"] * (matrix - 1)
        if not np.isclose(estimate, metadata["TotalReadoutTime"], rtol=0.02, atol=1e-6):
            warnings.append(
                "TotalReadoutTime differs from EffectiveEchoSpacing * (ReconMatrixPE - 1); review acquisition provenance"
            )
    return warnings


def check_echoes(echoes):
    if len(echoes) == 1:
        if "echo" in echoes[0]["entities"]:
            raise ValueError("A lone echo-labelled image is not a complete multi-echo acquisition")
        return
    numbers = [int(e["entities"].get("echo", 0)) for e in echoes]
    if numbers != list(range(1, len(echoes) + 1)):
        raise ValueError("Echo indices must be unique and contiguous from 1")
    tes = [e["metadata"]["EchoTime"] for e in echoes]
    if any(a >= b for a, b in pairwise(tes)):
        raise ValueError("EchoTime must increase with echo index")
    first = echoes[0]
    for echo in echoes[1:]:
        if echo["image"]["shape"] != first["image"]["shape"] or not np.allclose(
            echo["image"]["affine"], first["image"]["affine"], atol=1e-4, rtol=0
        ):
            raise ValueError("Echo grids or frame counts differ")
        for key in (
            "RepetitionTime",
            "SliceTiming",
            "SliceEncodingDirection",
            "PhaseEncodingDirection",
            "TotalReadoutTime",
            "B0FieldSource",
        ):
            if echo["metadata"].get(key) != first["metadata"].get(key):
                raise ValueError(f"Echo metadata differ: {key}")
