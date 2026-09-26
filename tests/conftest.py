from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from fmri_prep_flow.common.io import write_json
from fmri_prep_flow.config import DEFAULTS


def image(path, shape=(4, 5, 6, 12), tr=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.random.default_rng(7).uniform(10, 100, shape).astype("float32")
    im = nib.Nifti1Image(data, np.diag([2, 2, 2, 1]))
    im.header.set_xyzt_units("mm", "sec")
    if len(shape) == 4:
        im.header.set_zooms([2, 2, 2, tr])
    nib.save(im, path)
    return path


def acquisition(
    root, subject="01", session=None, task="restingstate", acq="seq", run="01", echoes=1
):
    base = root / ("sub-" + subject)
    prefix = "sub-" + subject
    if session:
        base /= "ses-" + session
        prefix += "_ses-" + session
    t1 = base / "anat" / (prefix + "_T1w.nii.gz")
    if not t1.exists():
        image(t1, (6, 7, 8))
    prefix += "_task-" + task + "_acq-" + acq + "_run-" + run
    paths = []
    for echo in range(1, echoes + 1):
        name = prefix + (f"_echo-{echo}" if echoes > 1 else "") + "_bold.nii.gz"
        path = image(base / "func" / name)
        write_json(path.with_name(name.replace(".nii.gz", ".json")), {"EchoTime": 0.01 * echo})
        paths.append(path)
    write_json(
        root / ("task-" + task + "_bold.json"),
        {
            "TaskName": task,
            "RepetitionTime": 2,
            "SliceTiming": [0, 0.2, 0.4, 0.6, 0.8, 1],
            "PhaseEncodingDirection": "j",
            "TotalReadoutTime": 0.03,
        },
    )
    return paths


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    write_json(root / "dataset_description.json", {"Name": "Test BIDS", "BIDSVersion": "1.9.0"})
    acquisition(root)
    selection = tmp_path / "selection.json"
    write_json(selection, {"source_bids": str(root), "subjects": ["01"]})
    return root, selection


@pytest.fixture
def config(tmp_path):
    license_file = tmp_path / "license.txt"
    license_file.write_text("test fixture; not a real license")
    path = tmp_path / "config.json"
    write_json(
        path,
        {
            **DEFAULTS,
            "fs_license": str(license_file),
            "sdc": "none",
            "sdc_reason": "Synthetic test without fieldmaps",
        },
    )
    return path


@pytest.fixture
def validator(tmp_path):
    script = tmp_path / "validator-fixture"
    script.write_text(
        '#!/usr/bin/env python3\nimport json, sys\nprint("fixture validator" if "--version" in sys.argv else json.dumps({"issues":{"issues":[]}}))\n'
    )
    script.chmod(0o755)
    return str(script)
