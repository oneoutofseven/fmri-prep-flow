# fmri-prep-flow

Preprocess BIDS **T1w + BOLD** data with **Singularity and fMRIPrep 25.2.5**. Supports single-echo and multi-echo data; produces preprocessed images, confounds, QC reports, and a results CSV.

## 1. Install

You need Linux, Python ≥ 3.10, Singularity, a FreeSurfer license, and a raw BIDS dataset with T1w and BOLD from the same session. The first run downloads the container and templates.

```bash
git clone https://github.com/oneoutofseven/fmri-prep-flow.git
cd fmri-prep-flow
python -m venv .venv
source .venv/bin/activate
pip install -e '.[validator]'
export FS_LICENSE=/absolute/path/to/license.txt
```

Replace the license path with your own. Singularity must already be installed; Docker is not required.

## 2. Configure

```bash
fmri-prep-flow init --output project
```

Edit **`project/selection.json`** with your dataset path and subject/task labels:

```json
{
  "source_bids": "/data/my-bids",
  "subjects": ["001"],
  "tasks": ["rest"]
}
```

Use `"001"` for `sub-001` and `"rest"` for `task-rest`. Add subjects to the list to process more people. Multi-echo acquisitions are selected automatically as complete groups.

In **`project/config.json`**, choose the `sdc` setting:

| Value | When to use it |
| --- | --- |
| `"auto"` (default) | You have valid, associated fieldmaps. Planning stops if they are missing. |
| `"syn"` | You explicitly want anatomy-based correction. Requires `PhaseEncodingDirection` and `TotalReadoutTime` in the BOLD metadata. |
| `"none"` | You explicitly want no distortion correction. Also fill in `sdc_reason`. |

**SyN is not enabled automatically.** For an intentionally uncorrected pilot, a complete `config.json` can be:

```json
{
  "sdc": "none",
  "sdc_reason": "Uncorrected pilot; residual distortion will be reviewed."
}
```

Other settings use their defaults: 8 CPU, 32 GB memory budget, and volume outputs in T1w and MNI152NLin2009cAsym 2 mm space. Choose the correction policy appropriate for your study.

## 3. Run

```bash
fmri-prep-flow doctor --config project/config.json
fmri-prep-flow prepare --selection project/selection.json --output project/prepared
fmri-prep-flow plan --staging project/prepared/staging.json \
  --config project/config.json --output project/run-01
fmri-prep-flow run --plan project/run-01/plan.json
fmri-prep-flow status --plan project/run-01/plan.json
```

`prepare` copies and validates your selected inputs; `plan` saves the processing settings; `run` launches fMRIPrep and waits for completion. Use tmux or a scheduler for long jobs. Output directories must be new; use `run-02` for a retry.

## 4. Check and export

For the example above:

- **HTML report:** `project/run-01/sub-001/derivatives/sub-001.html`
- **BOLD and confounds:** `project/run-01/sub-001/derivatives/sub-001/func/`
- **QC plots:** `project/run-01/products/sub-001_task-rest/qc/`
- **Execution log:** `project/run-01/sub-001/engine.log`

Inspect the reports, then generate and complete a review form:

```bash
fmri-prep-flow review --plan project/run-01/plan.json --template project/review-form.json
```

Edit the form: enter your name in `reviewer`, mark every check `pass` or `fail`, add `notes`, and set each run's `decision` to `pass` only if all its checks pass. Then submit and export:

```bash
fmri-prep-flow review --plan project/run-01/plan.json --review project/review-form.json
fmri-prep-flow collect --plan project/run-01/plan.json --output project/catalog.csv
```

The CSV lists output paths and QC status. You can export before reviewing; the status remains `pending`.

**Preprocessed BOLD is not temporally denoised.** Nuisance regression, filtering, functional connectivity, and site harmonization are downstream steps.

[Full usage guide and troubleshooting](docs/usage.md) · [Configuration reference (Chinese)](docs/configuration.md) · [Validation](docs/validation.md) · [MIT License](LICENSE)
