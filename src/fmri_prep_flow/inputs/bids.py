"""Select complete BIDS acquisitions and retain their effective metadata provenance."""

import json
from collections import defaultdict
from pathlib import Path

import nibabel as nib
from bids import BIDSLayout

from ..common.io import now, read_json, sha256, verify
from ..models import as_list, identity, run_id
from .audit import check_bold_metadata, check_echoes, inspect_image

SELECTORS = {
    "subjects": "subject",
    "sessions": "session",
    "tasks": "task",
    "runs": "run",
    "acquisitions": "acquisition",
    "directions": "direction",
}


def load_selection(path):
    path = Path(path).resolve()
    selection = read_json(path)
    if not isinstance(selection, dict) or set(selection) - {"source_bids", *SELECTORS}:
        raise ValueError("Unknown selection fields")
    if not isinstance(selection.get("source_bids"), str):
        raise ValueError("source_bids is required")
    if not selection.get("subjects"):
        raise ValueError("Select subjects explicitly (labels without sub-)")
    for key in SELECTORS:
        if key in selection and (
            not isinstance(selection[key], list)
            or not selection[key]
            or any(not isinstance(x, str) or not x.isalnum() for x in selection[key])
        ):
            raise ValueError(f"{key}: use a nonempty list of alphanumeric BIDS labels")
    selection["source_bids"] = str(
        (path.parent / Path(selection["source_bids"]).expanduser()).resolve()
    )
    return selection


def metadata_sources(layout, file):
    sources = file.get_associations(kind="Metadata", include_parents=True)
    sources = sorted({Path(f.path) for f in sources if f.path.endswith(".json")})
    # Do not let directory iteration order resolve ambiguous same-level inheritance.
    for i, left in enumerate(sources):
        le = layout.get_file(str(left)).get_entities(metadata=False)
        lm = read_json(left)
        for right in sources[i + 1 :]:
            if left.parent != right.parent:
                continue
            re = layout.get_file(str(right)).get_entities(metadata=False)
            if set(le) < set(re) or set(re) < set(le):
                continue
            rm = read_json(right)
            if any(lm[k] != rm[k] for k in lm.keys() & rm.keys()):
                raise ValueError(f"Ambiguous metadata inheritance: {left.name}, {right.name}")
    return [{"path": str(p), "sha256": sha256(p)} for p in sources]


def record(layout, file, dimensions=None):
    origins = metadata_sources(layout, file)
    verify(origins) if origins else None
    value = {
        "path": file.path,
        "relative_path": str(Path(file.path).relative_to(layout.root)),
        "entities": file.get_entities(metadata=False),
        "metadata": json.loads(json.dumps(layout.get_metadata(file.path))),
        "metadata_sources": origins,
        "sha256": sha256(file.path),
    }
    suffix = value["entities"].get("suffix")
    auxiliary_image = suffix == "sbref" or value["entities"].get("datatype") == "fmap"
    if auxiliary_image:
        dimensions = len(nib.load(file.path).shape)
        if dimensions not in (3, 4):
            raise ValueError("SBRef and fieldmaps must be 3D or 4D images")
    if dimensions:
        value["image"] = inspect_image(
            file.path,
            dimensions,
            allow_constant=auxiliary_image,
            allow_single_volume=auxiliary_image,
        )
        if value["image"]["sha256"] != value["sha256"]:
            raise ValueError("Source changed while indexing")
    return value


def reference_path(root, subject, reference):
    if not isinstance(reference, str):
        raise ValueError("IntendedFor must contain paths")
    if reference.startswith("bids::"):
        candidate = Path(root) / reference[6:]
    elif reference.startswith("bids:"):
        raise ValueError("External-dataset IntendedFor references are unsupported")
    else:
        candidate = Path(root) / f"sub-{subject}" / reference
    resolved = candidate.resolve()
    if Path(root).resolve() not in resolved.parents:
        raise ValueError("IntendedFor escapes the source dataset")
    return str(resolved)


def related_fieldmaps(layout, echoes):
    first = echoes[0]
    subject = first["entities"]["subject"]
    paths = {e["path"] for e in echoes}
    identifiers = set(as_list(first["metadata"].get("B0FieldSource")))
    maps = layout.get(subject=subject, datatype="fmap", extension=[".nii", ".nii.gz"])
    selected = {}
    matched_ids = set()
    for file in maps:
        metadata = layout.get_metadata(file.path)
        ids = set(as_list(metadata.get("B0FieldIdentifier")))
        targets = {
            reference_path(layout.root, subject, r) for r in as_list(metadata.get("IntendedFor"))
        }
        matched_ids |= ids & identifiers
        associated = bool(ids & identifiers) if identifiers else bool(paths & targets)
        if associated:
            selected[file.path] = file
    if identifiers - matched_ids:
        raise ValueError(f"Unresolved B0FieldSource: {sorted(identifiers - matched_ids)}")
    # Include phase/magnitude companions for both association conventions.
    for file in list(selected.values()):
        ent = file.get_entities(metadata=False)
        if ent.get("suffix") in ("phasediff", "phase1", "phase2", "fieldmap"):
            key = {k: v for k, v in ent.items() if k not in ("suffix", "extension", "fmap")}
            for other in maps:
                oe = other.get_entities(metadata=False)
                if {k: v for k, v in oe.items() if k not in ("suffix", "extension", "fmap")} == key:
                    selected[other.path] = other
    return [record(layout, selected[p]) for p in sorted(selected)]


def auxiliary_files(layout, run):
    result = []
    entities = run["entities"]
    for file in layout.get(suffix=["sbref", "events", "physio", "stim"]):
        ent = file.get_entities(metadata=False)
        if ent.get("extension") == ".json":
            continue
        common = identity(ent)
        # Missing acquisition entities allow shared events/physio; session never crosses.
        if (ent.get("suffix") == "sbref" or "session" in common) and common.get(
            "session"
        ) != entities.get("session"):
            continue
        if any(entities.get(k) != v for k, v in common.items() if k != "recording"):
            continue
        if (
            ent.get("suffix") == "sbref"
            and "echo" in ent
            and str(ent["echo"]) not in {str(e["entities"].get("echo")) for e in run["echoes"]}
        ):
            continue
        result.append(record(layout, file))
    return result


def discover(selection_path):
    selection = load_selection(selection_path)
    root = Path(selection["source_bids"])
    description = read_json(root / "dataset_description.json")
    if description.get("DatasetType", "raw") != "raw":
        raise ValueError("Expected raw BIDS; do not relabel anatomical derivatives as raw T1w")
    layout = BIDSLayout(root, validate=False, derivatives=False)
    query = {entity: selection[key] for key, entity in SELECTORS.items() if key in selection}
    files = layout.get(**query, datatype="func", suffix="bold", extension=[".nii", ".nii.gz"])
    if not files:
        raise ValueError("Selection contains no BOLD acquisitions")
    for key, entity in SELECTORS.items():
        if key in selection:
            found = {
                str(int(f.get_entities(metadata=False)[entity]))
                if entity == "run"
                else str(f.get_entities(metadata=False).get(entity))
                for f in files
            }
            missing = {str(int(v)) if entity == "run" else v for v in selection[key]} - found
            if missing:
                raise ValueError(f"Selected {key} not found: {sorted(missing)}")
    grouped = defaultdict(list)
    for file in files:
        grouped[run_id(file.path)].append(file)
    runs, warnings, anatomy = [], [], {}
    for label, members in sorted(grouped.items()):
        members.sort(key=lambda f: int(f.get_entities(metadata=False).get("echo", 0)))
        echoes = [record(layout, f, 4) for f in members]
        for echo in echoes:
            if echo["entities"].get("part") not in (None, "mag"):
                raise ValueError("Only magnitude BOLD inputs are supported")
            warnings.extend(
                f"{label}: {w}" for w in check_bold_metadata(echo["metadata"], echo["image"])
            )
        check_echoes(echoes)
        run = {
            "id": label,
            "entities": identity(echoes[0]["entities"]),
            "echoes": echoes,
            "fieldmaps": related_fieldmaps(layout, echoes),
        }
        run["auxiliary"] = auxiliary_files(layout, run)
        # Sessionwise anatomy: no implicit borrowing from another visit.
        ent = run["entities"]
        t1s = [
            f
            for f in layout.get(
                subject=ent["subject"], suffix="T1w", datatype="anat", extension=[".nii", ".nii.gz"]
            )
            if str(f.get_entities(metadata=False).get("session", "")) == ent.get("session", "")
        ]
        if not t1s:
            raise ValueError(f"{label}: no raw T1w in the same session")
        for t1 in t1s:
            if t1.path not in anatomy:
                anatomy[t1.path] = record(layout, t1, 3)
        runs.append(run)
    sources = {str(root / "dataset_description.json"): sha256(root / "dataset_description.json")}
    for entry in all_records({"anatomy": list(anatomy.values()), "runs": runs}):
        sources[entry["path"]] = entry["sha256"]
        for origin in entry["metadata_sources"]:
            sources[origin["path"]] = origin["sha256"]
    manifest = {
        "schema_version": 2,
        "created_at": now(),
        "source_root": str(root),
        "selection": selection,
        "dataset": description,
        "anatomy": list(anatomy.values()),
        "runs": runs,
        "warnings": sorted(set(warnings)),
        "sources": [{"path": p, "sha256": h} for p, h in sorted(sources.items())],
    }
    verify(manifest["sources"])
    return manifest


def all_records(manifest):
    entries = {e["path"]: e for e in manifest["anatomy"]}
    for run in manifest["runs"]:
        for key in ("echoes", "fieldmaps", "auxiliary"):
            entries.update({e["path"]: e for e in run[key]})
    return list(entries.values())
