"""Which events the run keeps and how they are grouped: --pops as population numbers, file by
file, the events in the populations chosen, and --groups as one group name per file."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.settings import check_groups


def parse_pops(text: str, n: int) -> list[int]:
    """'1', '1,2', '1 2', '1-3' or 'all' as the sorted population numbers, 1 to n. 'none' gives
    no populations, which leaves the file out."""
    t = text.strip().lower()
    if t == "all":
        return list(range(1, n + 1))
    if t == "none":
        return []
    pops = set()
    for part in t.replace(",", " ").split():
        lo, dash, hi = part.partition("-")
        if not lo.isdigit() or (dash and not hi.isdigit()):
            raise ValueError(f"{part!r} isn't a population number or a range like 1-3")
        a, b = int(lo), int(hi) if dash else int(lo)
        pops.update(range(min(a, b), max(a, b) + 1))
    if not pops:
        raise ValueError("no population given; type numbers like 1,2, or all, or none")
    bad = [p for p in sorted(pops) if not 1 <= p <= n]
    if bad:
        has = f"Pop 1 to Pop {n}" if n else "no populations; choose none for it"
        raise ValueError(f"there is no Pop {bad[0]}; this file has {has}")
    return sorted(pops)


def pick_events(masks: np.ndarray, pops: Sequence[int]) -> np.ndarray:
    """The events in any of the populations pops (numbered from 1), as one bool per event. An
    event in two of them counts once."""
    masks = np.asarray(masks, dtype=bool)
    if not pops:
        return np.zeros(len(masks), dtype=bool)
    return masks[:, [p - 1 for p in pops]].any(axis=1)


def selection_choices(spec: str, n_files: int) -> list[str]:
    """spec's choices, separated by ;, when it gives one for every file or one for each of
    n_files, and a FlowError naming pops when it gives neither. The rule is kept here alone: the
    CLI counts --pops with it before any file is read, and parse_selection reads its choices."""
    choices = spec.split(";")
    if len(choices) not in (1, n_files):
        raise FlowError(
            f"{{param}} gives {len(choices)} choices for {n_files} files; give one for all of "
            "them or one per file, separated by ;",
            "pops",
        )
    return choices


def parse_selection(spec: str, counts: Sequence[int]) -> list[list[int]]:
    """The populations to keep in each file, from one choice for every file ("1,2") or one per
    file separated by ; ("1,2;none;1"), each read by parse_pops. counts holds each file's number
    of populations."""
    choices = selection_choices(spec, len(counts))
    try:
        return [parse_pops(choices[0 if len(choices) == 1 else i], n) for i, n in enumerate(counts)]
    except ValueError as e:
        raise FlowError(f"{{param}}: {e}", "pops") from e


def parse_groups(spec: str, n_files: int) -> tuple[str, ...]:
    """--groups as ClusterSettings takes it: one group name per file, in file order, separated by
    ; ("ctrl;ctrl;treated"), each name stripped of the spaces around it. A count other than
    n_files, or a name check_groups refuses, is a FlowError naming groups."""
    names = tuple(name.strip() for name in spec.split(";"))
    if len(names) != n_files:
        raise FlowError(
            f"{{param}} gives {len(names)} names for {n_files} files; give one per file, "
            "separated by ;",
            "groups",
        )
    check_groups(names)
    return names


def pops_spec(chosen: Sequence[Sequence[int]]) -> str:
    """chosen as parse_selection reads it, one choice per file: [[1, 2], [], [1]] is
    "1,2;none;1"."""
    return ";".join(",".join(map(str, pops)) or "none" for pops in chosen)
