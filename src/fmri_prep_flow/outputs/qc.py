"""Descriptive plots, independent of processing and human approval."""

import nibabel as nib
import numpy as np

from ..common.io import fresh, read_json, verify, write_json
from .confounds import confounds


def preview(products_path, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    products = read_json(products_path)
    verify(products["inventory"])
    out = fresh(output)
    entry = products["spaces"]["MNI152NLin2009cAsym"]
    im = nib.load(entry["bold"])
    data = np.asarray(im.dataobj, dtype=np.float32)
    mask = np.asarray(nib.load(entry["brain_mask"]).dataobj) > 0
    series = data[mask]
    # Evenly spaced brain voxels; no clustering, smoothing, filtering or regression.
    chosen = np.linspace(0, len(series) - 1, min(800, len(series)), dtype=int)
    carpet = series[chosen]
    sd = carpet.std(axis=1, keepdims=True)
    carpet = (carpet - carpet.mean(axis=1, keepdims=True)) / np.maximum(sd, 1e-6)
    metrics, values = confounds(products["confounds_tsv"], data.shape[3])
    t = np.arange(data.shape[3]) * im.header.get_zooms()[3]
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [1, 1, 3]})
    axes[0].plot(t, values["framewise_displacement"])
    axes[0].axhline(0.5, color="orange", linestyle="--", label="0.5 mm descriptive reference")
    axes[0].legend(fontsize=8)
    axes[0].set_ylabel("FD (mm)")
    if "dvars" in values:
        axes[1].plot(t, values["dvars"])
        axes[1].set_ylabel("DVARS")
    else:
        axes[1].plot(t, series.mean(axis=0))
        axes[1].set_ylabel("Mean signal")
    axes[2].imshow(
        carpet,
        aspect="auto",
        cmap="gray",
        vmin=-2,
        vmax=2,
        extent=[0, float(t[-1]), len(carpet), 0],
    )
    axes[2].set_ylabel("Sampled brain voxels")
    axes[2].set_xlabel("Time (s)")
    fig.suptitle(
        f"sub-{products['subject']} | Preprocessed BOLD, no temporal denoising | Human QC pending"
    )
    fig.tight_layout()
    fig.savefig(out / "timeseries_qc.png", dpi=160)
    plt.close(fig)
    mean = data.mean(axis=3)
    sd_map = data.std(axis=3)
    tsnr = np.divide(mean, sd_map, out=np.zeros_like(mean), where=sd_map > 1e-6)
    finite_tsnr = tsnr[mask & np.isfinite(tsnr)]
    metrics["temporal_snr_median_descriptive"] = float(np.median(finite_tsnr))
    metrics["tsnr_note"] = (
        "Mean/std after spatial preprocessing, before temporal denoising; not an independent accuracy measure"
    )
    coords = np.array(np.nonzero(mask))
    centers = np.median(coords, axis=1).astype(int)
    fig, axes = plt.subplots(2, 3, figsize=(12, 8))
    for axis in range(3):
        cut = np.take(mean, centers[axis], axis=axis).T
        cutmask = np.take(mask, centers[axis], axis=axis).T
        axes[0, axis].imshow(
            cut, cmap="gray", origin="lower", vmin=0, vmax=np.percentile(mean[mask], 99)
        )
        axes[0, axis].contour(cutmask, levels=[0.5], colors=["lime"], linewidths=0.7)
        axes[0, axis].set_title(["Sagittal", "Coronal", "Axial"][axis])
        axes[1, axis].imshow(
            np.take(tsnr * mask, centers[axis], axis=axis).T,
            origin="lower",
            cmap="magma",
            vmin=0,
            vmax=np.percentile(finite_tsnr, 95),
        )
        axes[1, axis].set_title("Temporal SNR (descriptive)")
        axes[0, axis].axis("off")
        axes[1, axis].axis("off")
    fig.suptitle(f"sub-{products['subject']} | MNI BOLD mean / mask / tSNR | Human QC pending")
    fig.tight_layout()
    fig.savefig(out / "bold_reference.png", dpi=160)
    plt.close(fig)
    write_json(
        out / "metrics.json", {**metrics, "functional_qc": "pending", "sdc": products["sdc"]}
    )
    verify(products["inventory"])
    return {
        "directory": str(out),
        "timeseries_png": str(out / "timeseries_qc.png"),
        "reference_png": str(out / "bold_reference.png"),
        "human_qc": "pending",
    }
