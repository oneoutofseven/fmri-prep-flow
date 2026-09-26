"""Explicit human review, tied to the complete set of accepted run products."""

from pathlib import Path

from ..common.io import now, read_json, sha256, verify, write_json

CHECKS = (
    "brain_extraction",
    "bold_to_t1",
    "standard_alignment",
    "distortion",
    "signal_dropout",
    "motion_and_timeseries",
)


def completed_products(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = read_json(plan_path)
    state = read_json(plan_path.parent / "state.json")
    if state["status"] != "completed" or state["plan_sha256"] != sha256(plan_path):
        raise ValueError("A completed, unchanged plan is required")
    index_path = plan_path.parent / "products.json"
    index = read_json(index_path)
    expected = {r for job in plan["jobs"] for r in job["runs"]}
    ids = [r["run_id"] for r in index["runs"]]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("Product index does not cover exactly the planned runs")
    products = {}
    for row in index["runs"]:
        if sha256(row["path"]) != row["sha256"]:
            raise ValueError("Product record changed")
        product = read_json(row["path"])
        if product["run_id"] != row["run_id"] or product["processing"] != "completed":
            raise ValueError("Invalid product record")
        verify(product["inventory"])
        products[row["run_id"]] = product
    return index_path, products


def template(plan_path, output):
    index, products = completed_products(plan_path)
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    value = {
        "reviewer": "",
        "reviewer_type": "human",
        "products_sha256": sha256(index),
        "runs": [
            {
                "run_id": key,
                "decision": "pending",
                "checks": dict.fromkeys(CHECKS, "pending"),
                "notes": "",
                "reports": value["reports"],
            }
            for key, value in products.items()
        ],
    }
    write_json(output, value)
    return {
        "template": str(output.resolve()),
        "instruction": "A human reviewer must inspect the reports and fill every check before submission.",
    }


def validate_review(value, products, index_hash):
    if (
        value.get("reviewer_type") != "human"
        or not isinstance(value.get("reviewer"), str)
        or not value["reviewer"].strip()
    ):
        raise ValueError(
            "A named human reviewer is required; AI observations are not human approval"
        )
    if value.get("products_sha256") != index_hash:
        raise ValueError("Review refers to different products")
    rows = value.get("runs", [])
    ids = [r["run_id"] for r in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(products):
        raise ValueError("Review must cover every planned run exactly once")
    for row in rows:
        checks = row.get("checks", {})
        if set(checks) != set(CHECKS) or any(v not in ("pass", "fail") for v in checks.values()):
            raise ValueError("Complete every review check with pass or fail")
        expected = "pass" if all(v == "pass" for v in checks.values()) else "fail"
        if (
            row.get("decision") != expected
            or not isinstance(row.get("notes"), str)
            or not row["notes"].strip()
        ):
            raise ValueError("Review decision must agree with checks and include notes")
        if row["decision"] == "pass" and products[row["run_id"]]["sdc"]["actual_sdc"] == "unknown":
            raise ValueError("Resolve missing SDC evidence before approving a run")


def submit(plan_path, review_path):
    index, products = completed_products(plan_path)
    value = read_json(review_path)
    validate_review(value, products, sha256(index))
    target = Path(plan_path).resolve().parent / "review.json"
    if target.exists():
        raise FileExistsError(
            "Review already submitted; preserve it rather than silently overwriting"
        )
    write_json(
        target,
        {
            **value,
            "submitted_at": now(),
            "source": str(Path(review_path).resolve()),
            "source_sha256": sha256(review_path),
        },
    )
    return {"review": str(target), "runs": len(products)}
