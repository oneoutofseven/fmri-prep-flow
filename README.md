# fmri-prep-flow

Preprocess T1w and BOLD images with **fMRIPrep 25.2.5 and Singularity**. Supports single-echo and multi-echo data, with QC reports and a CSV of output paths.

[Detailed usage](docs/usage.md) · [Configuration](docs/configuration.md) · [Protocol](docs/protocol.md)

## Install

Requires Linux, Python 3.10+, Singularity, and a FreeSurfer license. The first run needs network access to download the container and templates. Docker is not required.

```bash
git clone https://github.com/oneoutofseven/fmri-prep-flow.git
cd fmri-prep-flow
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[validator]'
export FS_LICENSE=/absolute/path/to/license.txt
singularity --version
```

Replace the license path with your own. Run the following commands from this repository directory.

## One subject: which files do I need?

For a single-echo resting-state scan, start with these files from the **same subject and session**:

| Your file | Contents |
| --- | --- |
| `T1w.nii.gz` | Raw 3D T1-weighted anatomical image. |
| `rest.nii.gz` | Raw 4D BOLD image: all time points in one file. |
| `rest.json` | Acquisition metadata for that BOLD image. Required fields include `TaskName`, `RepetitionTime`, and `EchoTime`. |
| `T1w.json` | Anatomical acquisition metadata, if available. |

Use the actual acquisition metadata; TR and TE are in seconds, and TR must match the NIfTI header. This example assumes `TaskName` is `rest`. If you only have a BOLD NIfTI without its metadata, obtain the metadata before proceeding.

### 1. Put the files into a BIDS directory

**Already have a raw BIDS dataset?** Skip this step and use its directory as `source_bids` in step 2.

Otherwise, replace the `/path/to/` paths below with your files. These commands copy a single subject's images into the expected layout:

```bash
mkdir -p data/bids/sub-001/anat data/bids/sub-001/func
cp /path/to/T1w.nii.gz data/bids/sub-001/anat/sub-001_T1w.nii.gz
cp /path/to/rest.nii.gz data/bids/sub-001/func/sub-001_task-rest_bold.nii.gz
cp /path/to/rest.json data/bids/sub-001/func/sub-001_task-rest_bold.json
# If available:
# cp /path/to/T1w.json data/bids/sub-001/anat/sub-001_T1w.json

cat > data/bids/dataset_description.json <<'JSON'
{
  "Name": "My resting-state study",
  "BIDSVersion": "1.9.0",
  "DatasetType": "raw"
}
JSON
```

You now have:

```text
data/bids/
├── dataset_description.json
└── sub-001/
    ├── anat/
    │   └── sub-001_T1w.nii.gz
    └── func/
        ├── sub-001_task-rest_bold.nii.gz
        └── sub-001_task-rest_bold.json
```

The optional T1w JSON goes next to the T1w image. `prepare` will check the images and validate this dataset; renaming files does not fix invalid images or missing metadata.

### 2. Tell the tool which subject to process

Create a project:

```bash
fmri-prep-flow init --output study
```

This generates `study/selection.json` and `study/config.json`. Replace **`study/selection.json`** with:

```json
{
  "source_bids": "../data/bids",
  "subjects": ["001"],
  "tasks": ["rest"]
}
```

`source_bids` points to the directory containing `dataset_description.json`. Relative paths are resolved from `selection.json`, so `../data/bids` selects the directory above. For an existing dataset, use its absolute path instead. `"001"` selects `sub-001`; `"rest"` selects `task-rest`.

For **this example without fieldmaps and with distortion correction explicitly disabled**, replace **`study/config.json`** with:

```json
{
  "nprocs": 8,
  "omp_nthreads": 4,
  "mem_mb": 32000,
  "sdc": "none",
  "sdc_reason": "Uncorrected pilot; residual distortion will be reviewed."
}
```

Choose SDC according to your study: `auto` uses valid associated fieldmaps; `syn` requests anatomy-based correction and requires `PhaseEncodingDirection` and `TotalReadoutTime`; `none` disables it and requires a reason. **The generated default is `auto`, not SyN; without fieldmaps it stops rather than switching methods.**

### 3. Run these files through fMRIPrep

```bash
fmri-prep-flow doctor --config study/config.json
fmri-prep-flow prepare --selection study/selection.json --output study/prepared
fmri-prep-flow plan --staging study/prepared/staging.json \
  --config study/config.json --output study/run-01
fmri-prep-flow run --plan study/run-01/plan.json
fmri-prep-flow status --plan study/run-01/plan.json
fmri-prep-flow collect --plan study/run-01/plan.json --output study/catalog.csv
```

`prepare` makes a validated copy of the inputs, `plan` saves the settings and commands, and `run` executes fMRIPrep in the foreground. Use new output directories; for a retry, create a new plan under `study/run-02`.

## Multiple subjects or echoes

For another subject, add `sub-002/anat/` and `sub-002/func/` under the same BIDS root, with `sub-002` filenames. Set `"subjects": ["001", "002"]` in the selection, then use new preparation and run directories. Subjects are processed sequentially.

For multi-echo BOLD, supply **all** echoes with their corresponding metadata:

```text
sub-001/func/
├── sub-001_task-rest_echo-1_bold.nii.gz
├── sub-001_task-rest_echo-1_bold.json
├── sub-001_task-rest_echo-2_bold.nii.gz
└── sub-001_task-rest_echo-2_bold.json
```

Include `echo-3`, etc. when present. Each JSON must resolve the correct `EchoTime`; the echoes must have matching grids, frame counts, and TR. The same selection and run commands process them as one acquisition. Do not also include a single-echo copy of that acquisition.

If your dataset has sessions, keep its `sub-001/ses-01/anat/` and `func/` structure and include the session label in filenames. Each selected session needs raw T1w anatomy. See the [usage guide](docs/usage.md#multiple-subjects-sessions-and-echoes) for selection filters.

## Outputs and QC

For the one-subject example:

| Result | Location |
| --- | --- |
| Preprocessed BOLD and confounds | `study/run-01/sub-001/derivatives/sub-001/func/` |
| fMRIPrep HTML report | `study/run-01/sub-001/derivatives/sub-001.html` |
| Additional QC plots | `study/run-01/products/sub-001_task-rest/qc/` |
| Execution log | `study/run-01/sub-001/engine.log` |
| Output paths and QC status | `study/catalog.csv` |

BOLD outputs are in T1w and MNI152NLin2009cAsym 2 mm space. They are **not temporally denoised**; nuisance regression, filtering, and connectivity analysis are downstream steps.

Open the HTML report and QC plots to inspect alignment, brain coverage, and motion. The initial CSV records `human_qc=pending`. To record a review, generate a form:

```bash
fmri-prep-flow review --plan study/run-01/plan.json --template study/review-form.json
```

Fill in your name, every check, the overall decision, and notes. Submit it and export an updated CSV:

```bash
fmri-prep-flow review --plan study/run-01/plan.json --review study/review-form.json
fmri-prep-flow collect --plan study/run-01/plan.json --output study/catalog-reviewed.csv
```

[Review instructions](docs/usage.md#review-image-quality-and-export-a-catalog) · [Troubleshooting](docs/usage.md#troubleshooting) · [Validation](docs/validation.md) · [MIT License](LICENSE)
