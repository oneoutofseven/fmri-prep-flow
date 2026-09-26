"""Export product locations and explicit review state; no implicit approval."""

import csv
from pathlib import Path

from ..common.io import read_json, sha256
from .review import completed_products, validate_review


def collect(plan_path, output):
    index, products = completed_products(plan_path)
    review_path = Path(plan_path).resolve().parent / "review.json"
    review = {}
    if review_path.exists():
        value = read_json(review_path)
        validate_review(value, products, sha256(index))
        review = {r["run_id"]: r["decision"] for r in value["runs"]}
    rows = []
    for run_id, product in products.items():
        for space, entry in product["spaces"].items():
            rows.append(
                {
                    "run_id": run_id,
                    "subject": product["subject"],
                    "session": product["entities"].get("session", ""),
                    "space": space,
                    "bold": entry["bold"],
                    "brain_mask": entry["brain_mask"],
                    "confounds": product["confounds_tsv"],
                    "processing": "completed",
                    "human_qc": review.get(run_id, "pending"),
                    "requested_sdc": product["sdc"]["requested_sdc"],
                    "actual_sdc": product["sdc"]["actual_sdc"],
                    "temporal_denoising": "not_performed",
                }
            )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"catalog": str(output.resolve()), "rows": len(rows)}
