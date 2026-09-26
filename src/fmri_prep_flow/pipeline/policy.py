"""Resolve requested preprocessing policies against audited acquisition metadata."""

from ..inputs.audit import positive


def check_fieldmaps(run):
    maps = run["fieldmaps"]
    suffixes = {e["entities"]["suffix"] for e in maps}
    bold = run["echoes"][0]["metadata"]
    if not maps:
        raise ValueError(
            f"{run['id']}: no associated fieldmaps; select sdc=syn or explicitly sdc=none"
        )
    if "PhaseEncodingDirection" not in bold or not positive(bold.get("TotalReadoutTime")):
        raise ValueError(
            "Fieldmap correction requires explicit BOLD PhaseEncodingDirection and TotalReadoutTime"
        )
    if suffixes <= {"epi"}:
        directions = {bold["PhaseEncodingDirection"]}
        for fieldmap in maps:
            meta = fieldmap["metadata"]
            direction = meta.get("PhaseEncodingDirection")
            if direction not in ("i", "i-", "j", "j-", "k", "k-") or not positive(
                meta.get("TotalReadoutTime")
            ):
                raise ValueError("PEPOLAR fieldmaps require valid phase encoding and readout time")
            directions.add(direction)
        bold_direction = bold["PhaseEncodingDirection"]
        opposite = bold_direction.rstrip("-") + ("" if bold_direction.endswith("-") else "-")
        if any(d[0] != bold_direction[0] for d in directions) or opposite not in directions:
            raise ValueError(
                "PEPOLAR requires opposing directions along the BOLD phase-encoding axis"
            )
    elif (
        suffixes <= {"phasediff", "magnitude1", "magnitude2"}
        and {"phasediff", "magnitude1"} <= suffixes
    ):
        meta = next(e["metadata"] for e in maps if e["entities"]["suffix"] == "phasediff")
        if (
            not positive(meta.get("EchoTime1"))
            or not positive(meta.get("EchoTime2"))
            or meta["EchoTime1"] >= meta["EchoTime2"]
        ):
            raise ValueError("Phasediff requires increasing EchoTime1/EchoTime2")
    elif suffixes == {"fieldmap", "magnitude"}:
        meta = next(e["metadata"] for e in maps if e["entities"]["suffix"] == "fieldmap")
        if meta.get("Units") not in ("Hz", "rad/s", "T"):
            raise ValueError("Fieldmap Units must be Hz, rad/s or T")
    else:
        raise ValueError(
            "Unsupported or incomplete fieldmap set; supported: EPI pairs, phasediff+magnitude1, fieldmap+magnitude"
        )


def resolve_policies(config, manifest):
    result = {}
    for run in manifest["runs"]:
        meta = run["echoes"][0]["metadata"]
        if config["sdc"] == "auto":
            check_fieldmaps(run)
        elif config["sdc"] == "syn":
            if meta.get("PhaseEncodingDirection") not in (
                "i",
                "i-",
                "j",
                "j-",
                "k",
                "k-",
            ) or not positive(meta.get("TotalReadoutTime")):
                raise ValueError(
                    f"{run['id']}: SyN policy requires explicit phase encoding and TotalReadoutTime"
                )
        if config["slice_timing"] == "require" and "SliceTiming" not in meta:
            raise ValueError(f"{run['id']}: SliceTiming required by policy")
        result[run["id"]] = {
            "requested_sdc": config["sdc"],
            "sdc_reason": config["sdc_reason"],
            "requested_slice_timing": config["slice_timing"],
            "expected_slice_timing": "applied"
            if "SliceTiming" in meta and config["slice_timing"] != "skip"
            else "skipped",
        }
    return result
