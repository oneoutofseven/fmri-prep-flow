"""Accept complete fMRIPrep products for each exact BIDS acquisition."""

import re
from pathlib import Path

import nibabel as nib
import numpy as np
from bids.layout import parse_file_entities

from ..common.io import now, read_json, sha256
from ..inputs.audit import inspect_image
from ..models import identity
from .confounds import confounds


def one(paths, description):
    if len(paths) != 1:
        raise ValueError(f"Expected one {description}, found {len(paths)}")
    return paths[0]


def entities(path):
    return parse_file_entities(str(path), config=["bids", "derivatives"])


def evidence(files, policy):
    summary = one(
        [p for p in files if p.name.endswith("_desc-summary_bold.html")],
        "functional summary report",
    )
    text = summary.read_text()
    match = re.search(r"Susceptibility distortion correction:\s*([^<\n]+)", text)
    method = match.group(1).strip() if match else "unknown"
    actual = "unknown"
    if method.lower() == "none":
        actual = "none"
    elif re.search(r"syn|fieldmap.less|anatomical", method, re.IGNORECASE):
        actual = "syn"
    elif re.search(r"pepolar|phase|fieldmap", method, re.IGNORECASE):
        actual = "fieldmap"
    requested = policy["requested_sdc"]
    if (
        requested == "syn"
        and actual != "syn"
        or requested == "auto"
        and actual != "fieldmap"
        or requested == "none"
        and actual not in ("none", "unknown")
    ):
        raise ValueError(f"SDC request {requested} not confirmed by report: {method}")
    checked = [summary]
    if actual in ("syn", "fieldmap"):
        correction = one(
            [p for p in files if p.name.endswith("_desc-sdc_bold.svg")],
            "distortion correction figure",
        )
        if correction.stat().st_size < 100:
            raise ValueError("Empty distortion correction figure")
        checked.append(correction)
    match = re.search(r"Slice timing correction:\s*([^<\n]+)", text)
    stc = match.group(1).strip() if match else "unknown"
    if policy["requested_slice_timing"] == "require" and stc.lower() != "applied":
        raise ValueError("Required slice timing correction not confirmed in report")
    if policy["requested_slice_timing"] == "skip" and stc.lower() == "applied":
        raise ValueError("Slice timing correction was applied despite skip policy")
    return {
        **policy,
        "actual_sdc": actual,
        "sdc_method": method,
        "actual_slice_timing": stc,
        "summary": str(summary),
    }, checked


def check_run(derivatives, run, config, policy):
    root = Path(derivatives).resolve()
    subject = run["entities"]["subject"]
    files = [
        p
        for p in sorted((root / f"sub-{subject}").rglob("*"))
        if p.is_file() and identity(entities(p)) == run["entities"]
    ]
    nframes = run["echoes"][0]["image"]["shape"][3]
    tr = run["echoes"][0]["metadata"]["RepetitionTime"]
    groups, checked = {}, []
    for space in ("T1w", "MNI152NLin2009cAsym"):
        candidates = [
            p for p in files if entities(p).get("space") == space and "echo" not in entities(p)
        ]
        if space != "T1w":
            candidates = [p for p in candidates if str(entities(p).get("res")) == "2"]
        bold = one(
            [p for p in candidates if p.name.endswith("_desc-preproc_bold.nii.gz")],
            f"{run['id']} {space} BOLD",
        )
        mask = one(
            [p for p in candidates if p.name.endswith("_desc-brain_mask.nii.gz")], "brain mask"
        )
        reference = one(
            [p for p in candidates if p.name.endswith("_boldref.nii.gz")], "BOLD reference"
        )
        sidecar = bold.with_name(bold.name.replace(".nii.gz", ".json"))
        meta = read_json(sidecar)
        info = inspect_image(bold, 4)
        if info["shape"][3] != nframes:
            raise ValueError("Output frame count differs from input")
        factor = {"sec": 1, "msec": 0.001, "usec": 0.000001}.get(info["units"][1])
        if (
            factor is None
            or not np.isclose(info["zooms"][3] * factor, tr, atol=1e-4, rtol=0)
            or not np.isclose(meta.get("RepetitionTime", -1), tr)
        ):
            raise ValueError("Output TR differs from input")
        image = nib.load(bold)
        for path in (mask, reference):
            other = nib.load(path)
            values = np.asarray(other.dataobj)
            if (
                image.shape[:3] != other.shape
                or not np.allclose(image.affine, other.affine, atol=1e-4, rtol=0)
                or not np.isfinite(values).all()
            ):
                raise ValueError("BOLD, mask and reference grids/data disagree")
            if path == mask and (not np.isin(values, [0, 1]).all() or not values.any()):
                raise ValueError("Empty/nonbinary brain mask")
        if space != "T1w" and not np.allclose(info["zooms"][:3], 2, atol=1e-4):
            raise ValueError("Requested MNI 2 mm grid not produced")
        groups[space] = {
            "bold": str(bold),
            "brain_mask": str(mask),
            "boldref": str(reference),
            "metadata": str(sidecar),
            "image": info,
        }
        checked.extend([bold, mask, reference, sidecar])
    conf = one(
        [p for p in files if p.name.endswith("_desc-confounds_timeseries.tsv")], "confounds TSV"
    )
    conf_json = conf.with_suffix(".json")
    if not isinstance(read_json(conf_json), dict):
        raise ValueError("Confounds metadata must be an object")
    metrics, _ = confounds(conf, nframes)
    echoes = []
    if len(run["echoes"]) > 1 and config["me_output_echos"]:
        for echo in run["echoes"]:
            number = str(echo["entities"]["echo"])
            selected = [
                p
                for p in files
                if str(entities(p).get("echo")) == number
                and p.name.endswith("_desc-preproc_bold.nii.gz")
            ]
            if not selected:
                raise ValueError(f"Missing preprocessed echo {number}")
            for path in selected:
                info = inspect_image(path, 4)
                if info["shape"][3] != nframes:
                    raise ValueError("Echo output frame count mismatch")
            echoes.extend(selected)
    transform = one(
        [p for p in files if p.name.endswith("_from-boldref_to-T1w_mode-image_desc-coreg_xfm.txt")],
        "BOLD-to-T1w transform",
    )
    anat = root / f"sub-{subject}"
    if run["entities"].get("session"):
        anat /= "ses-" + run["entities"]["session"]
    transforms = sorted((anat / "anat").glob("*_from-T1w_to-MNI152NLin2009cAsym_mode-image_xfm.h5"))
    if not transforms or any(p.stat().st_size == 0 for p in [transform, *transforms]):
        raise ValueError("Missing/empty spatial transforms")
    reports = sorted(root.glob(f"sub-{subject}*.html"))
    # Sessionwise reports may be named sub-01_ses-01.html.
    if not reports or any(p.stat().st_size == 0 for p in reports):
        raise ValueError("fMRIPrep HTML report missing/empty")
    correction, report_files = evidence(files, policy)
    checked += [conf, conf_json, transform, *transforms, *echoes, *reports, *report_files]
    return {
        "schema_version": 2,
        "created_at": now(),
        "run_id": run["id"],
        "entities": run["entities"],
        "subject": subject,
        "echo_count": len(run["echoes"]),
        "spaces": groups,
        "confounds_tsv": str(conf),
        "confounds_json": str(conf_json),
        "metrics": metrics,
        "echo_bold": [str(p) for p in echoes],
        "reports": [str(p) for p in reports],
        "transforms": [str(p) for p in [transform, *transforms]],
        "sdc": correction,
        "inventory": [{"path": str(p), "sha256": sha256(p)} for p in sorted(set(checked))],
        "processing": "completed",
        "human_qc": "pending",
        "temporal_denoising": "not_performed",
    }
