from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from conftest import acquisition, image

from fmri_prep_flow.common.io import read_json, write_json
from fmri_prep_flow.config import DEFAULTS
from fmri_prep_flow.inputs.bids import discover
from fmri_prep_flow.inputs.prepare import prepare
from fmri_prep_flow.pipeline.policy import resolve_policies


def test_inherited_metadata_and_multiple_acquisitions(dataset):
    root, selection = dataset
    acquisition(root, acq="mb", echoes=3)
    manifest = discover(selection)
    assert len(manifest["runs"]) == 2
    multi = next(r for r in manifest["runs"] if r["entities"]["acquisition"] == "mb")
    assert len(multi["echoes"]) == 3
    assert multi["entities"]["run"] == "1"
    assert "session" not in multi["entities"]
    assert len(multi["echoes"][0]["metadata_sources"]) == 2
    assert multi["echoes"][0]["metadata"]["RepetitionTime"] == 2
    assert len(manifest["anatomy"]) == 1


def test_session_and_subject_selection(dataset):
    root, selection = dataset
    acquisition(root, subject="02", session="A", task="memory")
    write_json(
        selection,
        {"source_bids": str(root), "subjects": ["02"], "sessions": ["A"], "tasks": ["memory"]},
    )
    result = discover(selection)
    assert [r["entities"]["subject"] for r in result["runs"]] == ["02"]
    assert result["runs"][0]["entities"]["session"] == "A"


@pytest.mark.parametrize(
    "problem", ["slice", "tr", "nan", "truncated", "echo_time", "missing_echo", "grid"]
)
def test_bad_acquisitions_rejected(dataset, problem):
    root, selection = dataset
    paths = acquisition(root, acq="multi", echoes=3)
    side = paths[1].with_name(paths[1].name.replace(".nii.gz", ".json"))
    meta = read_json(side)
    if problem == "slice":
        meta["SliceTiming"] = [0, 0.1]
    elif problem == "tr":
        meta["RepetitionTime"] = 3
    elif problem == "echo_time":
        meta["EchoTime"] = 0.01
    elif problem == "missing_echo":
        paths[1].unlink()
    elif problem == "grid":
        image(paths[1], (5, 5, 6, 12))
    elif problem == "nan":
        im = nib.load(paths[1])
        data = im.get_fdata()
        data[0, 0, 0, 0] = np.nan
        nib.save(nib.Nifti1Image(data, im.affine, im.header), paths[1])
    else:
        paths[1].write_bytes(paths[1].read_bytes()[:-30])
    write_json(side, meta)
    with pytest.raises((ValueError, OSError, EOFError)):
        discover(selection)


def test_ambiguous_inheritance_fails(dataset):
    root, selection = dataset
    write_json(root / "acq-seq_bold.json", {"RepetitionTime": 3})
    with pytest.raises(ValueError, match="Ambiguous"):
        discover(selection)


def test_prepare_materializes_without_changing_sources(dataset, validator, tmp_path):
    root, selection = dataset
    original = (root / "task-restingstate_bold.json").read_bytes()
    result = prepare(selection, tmp_path / "prepared", validator)
    staged = read_json(result["staging"])
    side = next(Path(staged["bids_root"]).rglob("*_bold.json"))
    assert read_json(side)["RepetitionTime"] == 2
    assert read_json(side)["EchoTime"] == 0.01
    assert (root / "task-restingstate_bold.json").read_bytes() == original
    assert result["validation"]["passed"]


@pytest.mark.parametrize("association", ["IntendedFor", "B0FieldSource", "bids_uri"])
def test_fieldmap_association_and_subset_references(dataset, validator, tmp_path, association):
    root, selection = dataset
    bold = next(root.rglob("*_bold.nii.gz"))
    target = str(bold.relative_to(root / "sub-01"))
    fmap = image(root / "sub-01/fmap/sub-01_dir-PA_epi.nii.gz", (4, 5, 6))
    metadata = {"PhaseEncodingDirection": "j-", "TotalReadoutTime": 0.03}
    if association == "B0FieldSource":
        side = bold.with_name(bold.name.replace(".nii.gz", ".json"))
        write_json(side, {"EchoTime": 0.01, "B0FieldSource": "pepair"})
        metadata["B0FieldIdentifier"] = "pepair"
    else:
        metadata["IntendedFor"] = [
            ("bids::sub-01/" + target) if association == "bids_uri" else target,
            "func/unselected_bold.nii.gz",
        ]
    write_json(fmap.with_name(fmap.name.replace(".nii.gz", ".json")), metadata)
    manifest = discover(selection)
    assert len(manifest["runs"][0]["fieldmaps"]) == 1
    assert resolve_policies(DEFAULTS, manifest)
    result = prepare(selection, tmp_path / "prepared", validator)
    side = Path(read_json(result["staging"])["bids_root"]) / "sub-01/fmap/sub-01_dir-PA_epi.json"
    if association != "B0FieldSource":
        assert len(read_json(side)["IntendedFor"]) == 1


def test_missing_fieldmap_does_not_silently_disable_sdc(dataset):
    _, selection = dataset
    manifest = discover(selection)
    with pytest.raises(ValueError, match="no associated fieldmaps"):
        resolve_policies(DEFAULTS, manifest)
    assert resolve_policies({**DEFAULTS, "sdc": "syn"}, manifest)


def test_slice_timing_policies(dataset):
    root, selection = dataset
    path = root / "task-restingstate_bold.json"
    meta = read_json(path)
    del meta["SliceTiming"]
    write_json(path, meta)
    manifest = discover(selection)
    policy = {**DEFAULTS, "sdc": "syn"}
    assert (
        next(iter(resolve_policies(policy, manifest).values()))["expected_slice_timing"]
        == "skipped"
    )
    with pytest.raises(ValueError, match="SliceTiming required"):
        resolve_policies({**policy, "slice_timing": "require"}, manifest)


def test_validator_error_is_blocking(dataset, validator, tmp_path):
    Path(validator).write_text(
        '#!/usr/bin/env python3\nimport json,sys\nprint("fixture" if "--version" in sys.argv else json.dumps({"issues":{"issues":[{"severity":"error"}]}}))\n'
    )
    with pytest.raises(ValueError, match="validation failed"):
        prepare(dataset[1], tmp_path / "prepared", validator)


def test_inherited_events_and_matching_sbref(dataset):
    root, selection = dataset
    (root / "task-restingstate_events.tsv").write_text("onset\tduration\n0\t1\n")
    image(root / "sub-01/func/sub-01_task-restingstate_acq-seq_run-01_sbref.nii.gz", (4, 5, 6))
    image(root / "sub-01/func/sub-01_task-restingstate_acq-other_run-01_sbref.nii.gz", (4, 5, 6))
    run = discover(selection)["runs"][0]
    suffixes = [e["entities"]["suffix"] for e in run["auxiliary"]]
    assert sorted(suffixes) == ["events", "sbref"]


def test_b0_identifier_phasediff_includes_magnitude_companion(dataset):
    root, selection = dataset
    bold = next(root.rglob("*_bold.nii.gz"))
    write_json(
        bold.with_name(bold.name.replace(".nii.gz", ".json")),
        {"EchoTime": 0.01, "B0FieldSource": "gre"},
    )
    phasediff = image(root / "sub-01/fmap/sub-01_phasediff.nii.gz", (4, 5, 6))
    image(root / "sub-01/fmap/sub-01_magnitude1.nii.gz", (4, 5, 6))
    write_json(
        phasediff.with_name("sub-01_phasediff.json"),
        {"B0FieldIdentifier": "gre", "EchoTime1": 0.005, "EchoTime2": 0.008},
    )
    manifest = discover(selection)
    assert {e["entities"]["suffix"] for e in manifest["runs"][0]["fieldmaps"]} == {
        "phasediff",
        "magnitude1",
    }
    assert resolve_policies(DEFAULTS, manifest)
