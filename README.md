# fmri-prep-flow

Run **fMRIPrep 25.2.5 with Singularity** on selected BIDS subjects, then inspect and catalog the results.

You provide **raw T1w + BOLD images in BIDS format**, choose the subjects and correction settings, and run the commands below. The workflow copies and validates the selected inputs, launches fMRIPrep, checks its outputs, and generates QC plots. Image processing is performed by [fMRIPrep](https://fmriprep.org/); this repository manages the steps around it.

**The result is spatially preprocessed BOLD, confounds, and reports.** Temporal denoising, smoothing, functional connectivity, and cross-site harmonization are separate downstream steps.

[Input requirements](#input-requirements) · [Installation](#installation) · [First run](#first-run-one-subject) · [Outputs](#where-to-find-the-outputs) · [Troubleshooting](#troubleshooting)

## Input requirements

Start with a raw BIDS dataset. For a single subject without sessions, the relevant files might look like this:

```text
/data/my-bids/
├── dataset_description.json
└── sub-001/
    ├── anat/
    │   ├── sub-001_T1w.nii.gz
    │   └── sub-001_T1w.json
    └── func/
        ├── sub-001_task-rest_bold.nii.gz
        └── sub-001_task-rest_bold.json
```

This is a layout example, not a dataset included in the repository. Your files and metadata must pass BIDS validation. Metadata inherited from higher-level BIDS JSON files is supported.

| Input | What this workflow requires |
| --- | --- |
| Anatomy | At least one raw 3D T1w image in the same session as each selected BOLD acquisition. |
| BOLD | A 4D image with a constant TR, or a complete group of multi-echo images. |
| BOLD metadata | `TaskName`, `RepetitionTime`, and `EchoTime`. Timing values are in seconds; TR must agree with the NIfTI header. |
| Slice timing | Valid `SliceTiming` values to perform slice timing correction; the default skips it when these values are absent. |
| Distortion correction | Fieldmaps and/or acquisition metadata, depending on the selected SDC policy below. |

With sessions, put the images under `sub-001/ses-01/anat/` and `sub-001/ses-01/func/`, including `ses-01` in their filenames. Anatomy is not borrowed automatically from another session.

A standalone `.nii.gz` file is not sufficient. Convert it to BIDS with its acquisition metadata first. Use raw T1w images, not outputs from `t1prep-flow` or another preprocessing tool.

## Installation

You need:

- Linux and Python **3.10 or newer**.
- **Singularity**, installed separately and able to execute containers. The tested runtime is Singularity CE 4.5.1.
- Your own **FreeSurfer license file**, even though this workflow disables surface reconstruction.
- Writable storage for a copy of the selected data, derivatives, container caches, and working files. The first run needs network access for the image and templates.

```bash
git clone https://github.com/oneoutofseven/fmri-prep-flow.git
cd fmri-prep-flow

python -m venv .venv
source .venv/bin/activate
pip install -e '.[validator]'

export FS_LICENSE=/absolute/path/to/license.txt
singularity --version
fmri-prep-flow --version
```

Replace the license path with your actual file. The `validator` extra installs the official BIDS validator and its Deno runtime. Python installation does not install Singularity or obtain a license.

The fMRIPrep image is pinned to a SHA256 digest. Singularity retrieves it automatically when needed; you do not need to build a SIF manually or run a Docker daemon. `docker://` in the generated command refers to the image source.

## First run: one subject

This example uses `sub-001_task-rest_bold.nii.gz` from the layout above. Run the commands from the same working directory, with the virtual environment activated.

### 1. Create a project and select the data

```bash
fmri-prep-flow init --output project
```

This creates two files you edit:

| File | Purpose |
| --- | --- |
| `project/selection.json` | Which dataset and acquisitions to process. |
| `project/config.json` | How to process them: resources and correction policies. |

Set `project/selection.json` to:

```json
{
  "source_bids": "/data/my-bids",
  "subjects": ["001"],
  "tasks": ["rest"]
}
```

Replace the dataset path and labels with your own. Labels omit BIDS prefixes: use `"001"`, not `"sub-001"`. The task must match the filename; it does not have to be named `rest`.

### 2. Choose distortion correction explicitly

Susceptibility distortion correction (**SDC**) addresses geometric distortion in BOLD images. It is separate from registration to MNI space.

**The generated default is `"sdc": "auto"`. SyN is not enabled by default.** In this wrapper, `auto` requires usable fieldmaps; it does not fall back to SyN or to no correction.

| Your intended processing | Setting in `config.json` | Requirements |
| --- | --- | --- |
| Use acquired fieldmaps | `"sdc": "auto"` | Associated, supported fieldmaps and valid acquisition metadata. Missing or unsupported fieldmaps block planning. |
| Use anatomy-based SyN | `"sdc": "syn"` | Explicitly ignores fieldmaps and requests SyN. This wrapper requires BOLD `PhaseEncodingDirection` and `TotalReadoutTime`. |
| Omit distortion correction | `"sdc": "none"` | A nonempty `sdc_reason` documenting that decision. |

Supported fieldmap sets are reverse-encoding EPI, phasediff with magnitude images, and fieldmap with magnitude. The images must be associated with the BOLD acquisition through BIDS metadata; placing files in an `fmap/` directory alone is not enough.

For **an explicitly uncorrected pilot**, replace `project/config.json` with:

```json
{
  "nprocs": 8,
  "omp_nthreads": 4,
  "mem_mb": 32000,
  "sdc": "none",
  "sdc_reason": "Uncorrected pilot specified by the study protocol; residual distortion will be reviewed."
}
```

This makes the no-fieldmap example concrete; it is not a general recommendation to disable SDC. Write the actual reason for your study. If using SyN instead, set `"sdc": "syn"` after confirming its required metadata. If using fieldmaps, keep `"sdc": "auto"`.

Unspecified settings retain their defaults: slice timing correction when metadata is available, additional individual-echo outputs for multi-echo data, and volume outputs in `T1w` and `MNI152NLin2009cAsym:res-2`. CPU and memory values are scheduling budgets, not hard operating-system limits. See the [full configuration reference](docs/configuration.md) (Chinese).

### 3. Check the environment and prepare the inputs

```bash
fmri-prep-flow doctor --config project/config.json
fmri-prep-flow prepare --selection project/selection.json --output project/prepared
```

`doctor` checks the Singularity executable and license path. It does not launch a container or guarantee that downloads will succeed.

`prepare` checks the images and metadata, copies the selected inputs to `project/prepared/bids/`, and runs the official BIDS validator. It leaves the source dataset unchanged. A successful preparation writes `staging.json`, which is the input to the next step. Inspect validator warnings in `project/prepared/validation.json` as well as any errors.

### 4. Create and execute a plan

```bash
fmri-prep-flow plan \
  --staging project/prepared/staging.json \
  --config project/config.json \
  --output project/run-01
```

Planning checks the correction policy and writes `plan.json` plus `commands.sh`. This step does **not** process the images. You can inspect `commands.sh` to see the Singularity/fMRIPrep command that will run.

```bash
fmri-prep-flow run --plan project/run-01/plan.json
```

This command launches fMRIPrep and waits for completion. Subjects run sequentially, with all selected acquisitions for a subject in the same container job. Use tmux or a scheduler such as Slurm for long server jobs.

From another terminal with the environment activated, or after the command returns:

```bash
fmri-prep-flow status --plan project/run-01/plan.json
```

After successful execution and output checks, the status includes:

```json
{
  "status": "completed",
  "human_qc": "pending"
}
```

These are two separate results: processing has completed, but a person still needs to assess image quality. Inspect `sub-001/engine.log` inside the run directory if processing fails. The workflow also attempts to generate QC plots; a plot failure is recorded separately from preprocessing.

## Where to find the outputs

For the example above, the main files are:

```text
project/
├── selection.json
├── config.json
├── prepared/
│   ├── bids/                         Selected raw inputs, copied from the source
│   ├── manifest.json                 Source files and acquisition metadata
│   ├── staging.json                  Prepared input inventory
│   └── validation.json               Official validator report
└── run-01/
    ├── plan.json                      Saved processing plan
    ├── commands.sh                    Container commands for inspection
    ├── state.json                     Processing status
    ├── products.json                  Index of checked acquisitions
    ├── sub-001/
    │   ├── engine.log                 fMRIPrep execution log
    │   ├── work/                      Intermediate processing files
    │   └── derivatives/
    │       ├── sub-001.html            Open this report first
    │       └── sub-001/
    │           ├── anat/
    │           ├── func/              Preprocessed BOLD and confounds
    │           └── figures/           Images used by the HTML report
    └── products/
        └── sub-001_task-rest/
            ├── products.json         Verified paths and acquisition metrics
            └── qc/
                ├── bold_reference.png
                ├── timeseries_qc.png
                └── metrics.json
```

Cache directories and some additional files are omitted. Session, run, acquisition, and direction labels will appear in output paths when present in the inputs.

| Result | What it is for |
| --- | --- |
| `*_space-T1w_desc-preproc_bold.nii.gz` | BOLD aligned to the anatomical reference. |
| `*_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz` | BOLD in the supported 2 mm MNI space. |
| `*_desc-brain_mask.nii.gz` and `*_boldref.nii.gz` | Brain masks and reference images in each output space. |
| `*_desc-confounds_timeseries.tsv` and `.json` | Candidate nuisance regressors and their descriptions; these have **not** been regressed out by this workflow. |
| `sub-001.html` and `products/*/qc/` | fMRIPrep reports and additional descriptive QC plots. |

Preprocessed BOLD retains its time points, including any initial non-steady-state frames. Choose and document their treatment, nuisance regression, filtering, and motion censoring in your downstream analysis. Multi-echo combination is not equivalent to ICA denoising.

## Review image quality and export a catalog

### 1. Inspect the images

Open `project/run-01/sub-001/derivatives/sub-001.html` in a browser. Keep its `sub-001/figures/` directory with it if copying the report to another computer. Also inspect the two QC PNGs under `products/sub-001_task-rest/qc/`.

Check brain extraction, BOLD-to-T1 alignment, alignment to standard space, residual distortion, signal dropout, and the motion/time-series plots. The 0.5 mm FD line in the plot is a descriptive reference, not an automatic exclusion rule.

### 2. Record your review

```bash
fmri-prep-flow review \
  --plan project/run-01/plan.json \
  --template project/review-form.json
```

Edit the generated form after inspecting the reports:

- Set `reviewer` to the human reviewer's name.
- For **every acquisition**, set each item in `checks` to `pass` or `fail`.
- Set `decision` to `pass` only if every check passes; otherwise use `fail`.
- Add nonempty `notes` describing the assessment. Preserve the generated identifiers, report paths, and product hash.

Then submit it:

```bash
fmri-prep-flow review \
  --plan project/run-01/plan.json \
  --review project/review-form.json
```

This writes `project/run-01/review.json`. An existing submitted review is not overwritten. The [QC protocol](docs/protocol.md#5-人工-qc) provides more detail in Chinese.

### 3. Export the result paths

```bash
fmri-prep-flow collect \
  --plan project/run-01/plan.json \
  --output project/catalog.csv
```

The catalog contains **one row per acquisition per output space**: two rows for this one-acquisition example. It includes BOLD/mask/confounds paths, processing status, human QC status, and requested/actual SDC. It exports paths and metadata, not copies of the images.

You may run `collect` before reviewing; those rows will say `human_qc=pending`. Failed QC rows also remain in the catalog. Select eligible rows explicitly for downstream analysis.

## Multiple subjects, sessions, and echoes

To expand the selection, edit `selection.json` and prepare a new output directory:

```json
{
  "source_bids": "/data/my-bids",
  "subjects": ["001", "002"],
  "sessions": ["01"],
  "tasks": ["rest"],
  "runs": ["01", "02"]
}
```

Only include filters that exist in your dataset. `acquisitions` and `directions` are also supported. Omitted filters select all matching values; selected labels must be found. Use separate projects for different source BIDS datasets.

For multi-echo data, filenames contain `echo-1`, `echo-2`, etc., and metadata must provide the corresponding echo times. Select the acquisition normally: **do not select a single echo**. Echoes must form a complete group with matching grids, frame counts, and required metadata. They are processed as one acquisition, with combined outputs plus individual-echo outputs when `me_output_echos=true` (the default).

## Troubleshooting

| Symptom | What to check or do |
| --- | --- |
| No BOLD acquisitions / selected labels not found | Check `source_bids` and the exact labels in filenames. Do not include `sub-` or `ses-` in selection values. |
| No raw T1w in the same session | Provide raw anatomy for that session; do not substitute a preprocessed T1w. |
| No associated fieldmaps | The default is `sdc=auto`. Review the SDC choices above; SyN is not an automatic fallback. |
| SyN requires metadata | Confirm `PhaseEncodingDirection` and `TotalReadoutTime` from acquisition records. Do not infer them from MNI space or copy another subject's values. |
| BIDS validation fails | Inspect `prepared/validation.json` when available, fix the source data/metadata, and prepare a new directory. |
| Singularity or license check fails | Activate the environment, check `singularity --version`, and confirm that `FS_LICENSE` points to a readable file. |
| Output already exists / only a fresh plan can run | Keep the failed run for inspection and plan a new directory such as `project/run-02`. Automatic resume is not implemented. |
| Input, configuration, code, environment, or plan changed | Create a new plan; if prepared inputs changed, prepare a new dataset copy first. Plans are also tied to their absolute paths. |
| QC plots missing after successful processing | Check the recorded preview error. Generate plots again in a new directory using `qc` below. |

To regenerate descriptive QC plots for this example:

```bash
fmri-prep-flow qc \
  --products project/run-01/products/sub-001_task-rest/products.json \
  --output project/qc-retry
```

The `init`, `prepare`, and `plan` output directories must be new. Prepared inputs and output directories must not overlap the source dataset. To inspect any command's arguments, use `fmri-prep-flow <command> --help`.

## Scope and validation

This workflow supports volume-based T1w/BOLD processing with fixed TR, single or multiple echoes, and session-specific anatomical references. It does not generate FreeSurfer surfaces or CIFTI, reuse preprocessed anatomy, or run task GLMs, temporal denoising, connectivity estimation, or site harmonization.

Two real-data pilots using the source workflow completed with `sdc=none`: one single-echo and one three-echo acquisition. Their outputs were checked again with this package. These pilots do not establish image quality for every scanner/protocol or validate the fieldmap paths end to end; formal human QC remains pending. See [validation evidence](docs/validation.md) (Chinese).

## Code and documentation

```text
src/fmri_prep_flow/
├── cli.py        Command-line arguments and dispatch
├── config.py     Default settings and validation
├── models.py     Acquisition identities
├── inputs/       Selection, image checks, copying, and BIDS validation
├── pipeline/     Correction policies, container commands, plans, and execution
├── outputs/      Output checks, plots, review forms, and CSV export
└── common/       File I/O, hashes, and environment records
```

Additional documentation is in Chinese: [configuration and caches](docs/configuration.md), [processing protocol](docs/protocol.md), [code reading guide](docs/reading-guide.md), and [development/testing](CONTRIBUTING.md).

## License and citation

Repository code uses the [MIT License](LICENSE). fMRIPrep, container dependencies, and input datasets retain their own licenses. Imaging data, container images, caches, participant reports, and FreeSurfer licenses are not distributed here.

For publications, cite fMRIPrep and the tools used in your run. Start with `logs/CITATION.md` in the derivatives directory, and report the workflow version, container version, and correction settings.
