"""BIDS identity helpers shared by input selection and output matching."""

from pathlib import Path

# Exclude format/processing entities only. Acquisition, direction, part, etc. remain.
FORMAT_ENTITIES = {
    "extension",
    "suffix",
    "datatype",
    "echo",
    "space",
    "res",
    "resolution",
    "desc",
    "from",
    "to",
    "mode",
}


def identity(entities):
    return {
        key: str(int(value)) if key == "run" else str(value)
        for key, value in entities.items()
        if key not in FORMAT_ENTITIES
    }


def run_id(path):
    stem = Path(path).name.split(".")[0]
    return "_".join(part for part in stem.split("_")[:-1] if not part.startswith("echo-"))


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
