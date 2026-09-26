"""Copy an audited selection into an independently validated BIDS subset."""

import copy
import shutil

from ..common.io import disjoint, fresh, inventory, now, sha256, verify, write_json
from ..models import as_list
from .bids import all_records, discover, load_selection, reference_path
from .validation import validate


def sidecar(path):
    name = path.name
    for extension in (".nii.gz", ".tsv.gz", ".nii", ".tsv"):
        if name.endswith(extension):
            return path.with_name(name[: -len(extension)] + ".json")
    raise ValueError(f"Unsupported input extension: {path}")


def prepare(selection_path, output, validator="bids-validator-deno"):
    selection = load_selection(selection_path)
    disjoint(selection["source_bids"], output)
    manifest = discover(selection_path)
    out = fresh(output)
    root = out / "bids"
    root.mkdir()
    entries = all_records(manifest)
    selected = {e["path"] for e in entries}
    provenance = []
    for entry in entries:
        target = root / entry["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry["path"], target)
        if sha256(target) != entry["sha256"]:
            raise ValueError("Copied image differs from audited input")
        metadata = copy.deepcopy(entry["metadata"])
        if "IntendedFor" in metadata:
            subject = entry["entities"]["subject"]
            retained = [
                ref
                for ref in as_list(metadata["IntendedFor"])
                if reference_path(manifest["source_root"], subject, ref) in selected
            ]
            if retained:
                metadata["IntendedFor"] = retained
            else:
                del metadata["IntendedFor"]
        # Do not copy inherited JSON verbatim: write the resolved values next to each file.
        if metadata:
            write_json(sidecar(target), metadata)
        provenance.append(
            {
                "source": entry["path"],
                "path": str(target),
                "sha256": entry["sha256"],
                "metadata_sources": entry["metadata_sources"],
                "resolved_metadata": metadata,
            }
        )
    description = {**manifest["dataset"], "DatasetType": "raw"}
    description["Name"] = (
        description.get("Name", "BIDS dataset") + " (selected preprocessing inputs)"
    )
    write_json(root / "dataset_description.json", description)
    subjects = sorted({r["entities"]["subject"] for r in manifest["runs"]})
    (root / "participants.tsv").write_text(
        "participant_id\n" + "".join(f"sub-{s}\n" for s in subjects)
    )
    (root / "README").write_text(
        "Selected raw inputs. Effective metadata is materialized from BIDS inheritance.\nSelection and source hashes are recorded outside this BIDS directory in manifest.json.\nEvents and physiological recordings are retained when associated; no physiological regression is performed.\n"
    )
    verify(manifest["sources"])
    write_json(out / "manifest.json", manifest)
    staged = {
        "schema_version": 2,
        "created_at": now(),
        "bids_root": str(root),
        "manifest_path": str(out / "manifest.json"),
        "manifest_sha256": sha256(out / "manifest.json"),
        "inventory": inventory(root),
        "copies": provenance,
    }
    write_json(out / "staging.json", staged)
    result = validate(out / "staging.json", validator)
    if not result["passed"]:
        raise ValueError(f"Official BIDS validation failed; inspect {out / 'validation.json'}")
    return {
        "staging": str(out / "staging.json"),
        "subjects": subjects,
        "runs": len(manifest["runs"]),
        "validation": result,
    }
