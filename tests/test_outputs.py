import csv
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from conftest import acquisition, image
from test_pipeline import planned

from fmri_prep_flow.common.io import read_json, write_json
from fmri_prep_flow.outputs.catalog import collect
from fmri_prep_flow.outputs.products import check_run
from fmri_prep_flow.outputs.review import submit, template
from fmri_prep_flow.pipeline import runner
from fmri_prep_flow.pipeline.planning import verify_plan


def fake_products(root, run, sdc="None"):
    prefix = run["id"]
    ent = run["entities"]
    base = root / ("sub-" + ent["subject"])
    if ent.get("session"):
        base /= "ses-" + ent["session"]
    func = base / "func"
    for space in ["T1w", "MNI152NLin2009cAsym_res-2"]:
        stem = prefix + "_space-" + space
        image(func / (stem + "_desc-preproc_bold.nii.gz"))
        write_json(func / (stem + "_desc-preproc_bold.json"), {"RepetitionTime": 2})
        image(func / (stem + "_boldref.nii.gz"), (4, 5, 6))
        nib.save(
            nib.Nifti1Image(np.ones((4, 5, 6), dtype="uint8"), np.diag([2, 2, 2, 1])),
            func / (stem + "_desc-brain_mask.nii.gz"),
        )
    for echo in run["echoes"] if len(run["echoes"]) > 1 else []:
        image(
            func / (prefix + "_echo-" + str(echo["entities"]["echo"]) + "_desc-preproc_bold.nii.gz")
        )
    fields = [
        "trans_x",
        "trans_y",
        "trans_z",
        "rot_x",
        "rot_y",
        "rot_z",
        "framewise_displacement",
        "dvars",
    ]
    tsv = func / (prefix + "_desc-confounds_timeseries.tsv")
    with tsv.open("w") as stream:
        w = csv.writer(stream, delimiter="\t")
        w.writerow(fields)
        w.writerows([[0.1] * 6 + (["n/a", "n/a"] if i == 0 else [0.2, 1.1]) for i in range(12)])
    write_json(tsv.with_suffix(".json"), {})
    (func / (prefix + "_from-boldref_to-T1w_mode-image_desc-coreg_xfm.txt")).write_text(
        "synthetic transform"
    )
    anat = base / "anat"
    anat.mkdir(exist_ok=True)
    (
        anat / ("sub-" + ent["subject"] + "_from-T1w_to-MNI152NLin2009cAsym_mode-image_xfm.h5")
    ).write_text("synthetic transform")
    (root / ("sub-" + ent["subject"] + ".html")).write_text("<html>synthetic report</html>")
    figures = root / ("sub-" + ent["subject"]) / "figures"
    figures.mkdir(exist_ok=True)
    (figures / (prefix + "_desc-summary_bold.html")).write_text(
        f"<li>Susceptibility distortion correction: {sdc}</li><li>Slice timing correction: Applied</li>"
    )
    if sdc != "None":
        (figures / (prefix + "_desc-sdc_bold.svg")).write_text("<svg>" + " " * 200 + "</svg>")


def completed(dataset, config, validator, tmp_path, monkeypatch):
    path = planned(dataset, config, validator, tmp_path)
    plan, _, _, manifest = verify_plan(path)
    monkeypatch.setattr(runner, "doctor", lambda config: {"ready": True})

    def execute(argv, log, env, start):
        for run in manifest["runs"]:
            fake_products(Path(log).parent / "derivatives", run)
        return 0

    monkeypatch.setattr(runner, "execute", execute)
    monkeypatch.setattr(
        runner, "preview", lambda *args: (_ for _ in ()).throw(ValueError("plot unavailable"))
    )
    runner.run(path)
    return path


def test_multiple_runs_and_qc_failure_preserve_processing(
    dataset, config, validator, tmp_path, monkeypatch
):
    acquisition(dataset[0], acq="mb", echoes=3)
    path = completed(dataset, config, validator, tmp_path, monkeypatch)
    assert read_json(path.parent / "state.json")["status"] == "completed"
    index = read_json(path.parent / "products.json")
    assert len(index["runs"]) == 2
    for row in index["runs"]:
        assert row["preview_error"] == "plot unavailable"
        product = read_json(row["path"])
        assert product["human_qc"] == "pending"
        assert product["metrics"]["fd_defined_frames"] == 11
    catalog = tmp_path / "catalog.csv"
    assert collect(path, catalog)["rows"] == 4
    assert all(r["human_qc"] == "pending" for r in csv.DictReader(catalog.open()))


def test_matching_does_not_accept_other_acquisition(dataset, config, validator, tmp_path):
    acquisition(dataset[0], acq="mb")
    path = planned(dataset, config, validator, tmp_path)
    plan, _, _, manifest = verify_plan(path)
    root = tmp_path / "derivatives"
    fake_products(root, manifest["runs"][0])
    with pytest.raises(ValueError, match="Expected one"):
        check_run(
            root, manifest["runs"][1], plan["config"], plan["policies"][manifest["runs"][1]["id"]]
        )


@pytest.mark.parametrize("problem", ["frames", "mask", "tr", "transform", "confounds", "sdc"])
def test_bad_products_fail(dataset, config, validator, tmp_path, problem):
    path = planned(dataset, config, validator, tmp_path)
    plan, _, _, manifest = verify_plan(path)
    run = manifest["runs"][0]
    root = tmp_path / "derivatives"
    fake_products(root, run)
    if problem == "frames":
        image(next(root.rglob("*space-T1w_desc-preproc_bold.nii.gz")), (4, 5, 6, 10))
    elif problem == "mask":
        image(next(root.rglob("*space-T1w_desc-brain_mask.nii.gz")), (4, 5, 6))
    elif problem == "tr":
        write_json(next(root.rglob("*space-T1w_desc-preproc_bold.json")), {"RepetitionTime": 3})
    elif problem == "transform":
        next(root.rglob("*desc-coreg_xfm.txt")).unlink()
    elif problem == "confounds":
        tsv = next(root.rglob("*timeseries.tsv"))
        tsv.write_text(tsv.read_text().replace("n/a", "999", 1).replace("0.2", "n/a", 1))
    else:
        plan["policies"][run["id"]]["requested_sdc"] = "syn"
    with pytest.raises(ValueError):
        check_run(root, run, plan["config"], plan["policies"][run["id"]])


def test_human_review_requires_full_coverage(dataset, config, validator, tmp_path, monkeypatch):
    acquisition(dataset[0], run="02")
    path = completed(dataset, config, validator, tmp_path, monkeypatch)
    form = tmp_path / "form.json"
    template(path, form)
    with pytest.raises(ValueError, match="named human"):
        submit(path, form)
    review = read_json(form)
    review["reviewer"] = "Fixture reviewer"
    for row in review["runs"]:
        row.update(
            decision="pass",
            checks=dict.fromkeys(row["checks"], "pass"),
            notes="Synthetic test approval only",
        )
    full = list(review["runs"])
    review["runs"] = full[:1]
    write_json(form, review)
    with pytest.raises(ValueError, match="every planned run"):
        submit(path, form)
    review["runs"] = full
    write_json(form, review)
    submit(path, form)
    csv_path = tmp_path / "reviewed.csv"
    collect(path, csv_path)
    assert all(r["human_qc"] == "pass" for r in csv.DictReader(csv_path.open()))
