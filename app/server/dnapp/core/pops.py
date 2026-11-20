"""The populations chosen in each file of a done gate, as POST /flow/runs and the live-cells POST
both take them: one list per gate file, each number a population that file has, and a choice in
at least one file."""

from __future__ import annotations

from dnapp.core.errors import ApiError


def check_pops(files: list[dict], pops: list[list[int]]) -> None:
    """422 on pops unless pops fits the gate's files (the Gate JSON's files)."""
    if len(pops) != len(files):
        raise ApiError(
            "invalid_setting",
            f"pops gives {len(pops)} choices for {len(files)} files; give one per file.",
            "pops",
        )
    for f, chosen in zip(files, pops):
        n = len(f["populations"])
        bad = [p for p in chosen if not 1 <= p <= n]
        if bad:
            has = f"Pop 1 to Pop {n}" if n else "no populations"
            raise ApiError(
                "invalid_setting", f"{f['name']} has {has}; there is no Pop {bad[0]}.", "pops"
            )
    if not any(pops):
        raise ApiError("invalid_setting", "Choose populations in at least one file.", "pops")
