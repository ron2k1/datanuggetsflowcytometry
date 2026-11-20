"""Datasets as the server checks them (contract section 3.3): the FCS uploads whose colour
channels are the same set are one dataset, and a gate takes files from one dataset."""

from __future__ import annotations

from dnapp.core.errors import ApiError
from dnapp.core.package import flow


def colour_set(rec: dict) -> list[str]:
    """An FCS upload's colour channels, sorted: its dataset's channel set."""
    return flow.colour_channels([c["name"] for c in rec["columns"]])


def named(channels: list[str]) -> str:
    """At most three channels, in their order, then how many more there are."""
    more = f" and {len(channels) - 3} more" if len(channels) > 3 else ""
    return ", ".join(channels[:3]) + more


def channel_diff(a: list[str], b: list[str]) -> str:
    """What b's colour channels lack and add against a's, each named in sorted order: "lacks X",
    "adds Y", or both as "lacks X; adds Y"."""
    lacks, adds = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    return "; ".join(f"{verb} {named(c)}" for verb, c in (("lacks", lacks), ("adds", adds)) if c)


def check_one_dataset(recs: list[dict], what: str, param: str) -> None:
    """422 on param for the first upload whose colour channels differ from the first one's: "A
    <what> takes files from one dataset"."""
    first = colour_set(recs[0])
    for rec in recs[1:]:
        these = colour_set(rec)
        if these != first:
            raise ApiError(
                "invalid_setting",
                f"{rec['name']} has different colour channels from {recs[0]['name']} "
                f"(it {channel_diff(first, these)}). A {what} takes files from one dataset.",
                param,
            )
