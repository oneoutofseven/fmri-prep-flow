"""CLI recipe: declare arguments, parse once, call one application function."""

import argparse
import json
from pathlib import Path

from . import __version__
from .common.io import fresh, read_json, write_json
from .config import DEFAULTS, load_config
from .inputs.prepare import prepare
from .outputs.catalog import collect
from .outputs.qc import preview
from .outputs.review import submit, template
from .pipeline.planning import create_plan
from .pipeline.runner import run
from .pipeline.runtime import doctor


def initialize(output):
    root = fresh(output)
    write_json(root / "config.json", DEFAULTS)
    write_json(
        root / "selection.json",
        {"source_bids": "/path/to/raw-bids", "subjects": ["001"], "tasks": ["rest"]},
    )
    return {"project": str(root), "next": "Edit selection.json and config.json, then run prepare."}


def _init(args):
    return initialize(args.output)


def _prepare(args):
    return prepare(args.selection, args.output, args.validator)


def _doctor(args):
    result = doctor(load_config(args.config))
    if not result["ready"]:
        raise ValueError(f"Runtime is not ready: {result['checks']}")
    return result


def _plan(args):
    return create_plan(args.staging, args.config, args.output)


def _run(args):
    return run(args.plan)


def _status(args):
    root = Path(args.plan).resolve().parent
    value = read_json(root / "state.json")
    review = root / "review.json"
    value["review"] = read_json(review) if review.exists() else {"status": "pending"}
    value["human_qc"] = "pending"
    if review.exists():
        decisions = [row["decision"] for row in value["review"]["runs"]]
        value["human_qc"] = "pass" if decisions and all(d == "pass" for d in decisions) else "fail"
    return value


def _qc(args):
    return preview(args.products, args.output)


def _review(args):
    if args.template:
        return template(args.plan, args.template)
    return submit(args.plan, args.review)


def _collect(args):
    return collect(args.plan, args.output)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="fmri-prep-flow", description="BIDS fMRI preprocessing with Singularity and fMRIPrep."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(title="commands", required=True)

    p = commands.add_parser("init", help="Create editable selection and configuration files")
    p.add_argument("--output", required=True)
    p.set_defaults(func=_init)

    p = commands.add_parser("prepare", help="Audit, copy and officially validate a BIDS selection")
    p.add_argument("--selection", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--validator", default="bids-validator-deno")
    p.set_defaults(func=_prepare)

    p = commands.add_parser("doctor", help="Check Singularity and the FreeSurfer license path")
    p.add_argument("--config", required=True)
    p.set_defaults(func=_doctor)

    p = commands.add_parser("plan", help="Freeze inputs and create one job per subject")
    p.add_argument("--staging", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=_plan)

    p = commands.add_parser("run", help="Execute a frozen plan; no automatic temporal denoising")
    p.add_argument("--plan", required=True)
    p.set_defaults(func=_run)

    p = commands.add_parser("status", help="Read processing state and submitted human review")
    p.add_argument("--plan", required=True)
    p.set_defaults(func=_status)

    p = commands.add_parser("qc", help="Generate descriptive plots for one run")
    p.add_argument("--products", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=_qc)

    p = commands.add_parser(
        "review", help="Create a review form or submit a completed human review"
    )
    p.add_argument("--plan", required=True)
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument("--template", metavar="OUTPUT_JSON")
    choice.add_argument("--review", metavar="COMPLETED_JSON")
    p.set_defaults(func=_review)

    p = commands.add_parser("collect", help="Export paths and QC status to CSV")
    p.add_argument("--plan", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=_collect)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"error: {error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Interrupted; the container process group was stopped.\n")
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
