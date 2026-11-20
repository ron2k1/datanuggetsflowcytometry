"""datanuggets_flow.livecells: the channels whose names look like a viability dye or CD45, the
step's defaults, the cells a set's populations keep, and a set's values, histograms and counts.
suggest, defaults, load and count run in the FastAPI process; the rest run in a job worker. None
of them places or proposes a threshold."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np


def suggest(pnn: Sequence[str], pns: Sequence[str]) -> dict:
    """suggest_channels as is: channel names for each role, or None, and the candidates."""
    from datanuggets_flow.livecells import suggest_channels

    return suggest_channels(list(pnn), list(pns))


def defaults() -> dict:
    """The bins and the cofactor a request that leaves them out gets: the step's own bins, and
    the cofactor ClusterSettings uses ("auto"), so each channel's histogram is on the cofactor a
    run clustering the kept cells would pick for it."""
    from datanuggets_flow.livecells import LIVECELLS_BINS
    from datanuggets_flow.settings import ClusterSettings

    return {"bins": int(LIVECELLS_BINS), "cofactor": ClusterSettings().cofactor}


def check_cofactor(value) -> None:
    """Refuses, naming cofactor, anything but "auto" or a finite number from 0."""
    from datanuggets_flow.settings import check_cofactor as check

    check(value)


def check_cells(samples: Sequence[Mapping], chosen: Sequence[Sequence[int]], cap: int | None):
    """Refuses, naming pops, a choice whose populations keep more than cap cells summed over the
    files, counted with pick_events as the run counts them. A choice kept_values would refuse
    is left for it to refuse."""
    from datanuggets_flow.exceptions import FlowError
    from datanuggets_flow.pipeline import pick_events

    if cap is None or len(chosen) != len(samples):
        return
    total = 0
    for s, pops in zip(samples, chosen):
        n = np.shape(s["masks"])[1]
        if not all(isinstance(p, int) and 1 <= p <= n for p in pops):
            return
        total += int(pick_events(s["masks"], pops).sum())
    if total > cap:
        raise FlowError(
            f"{{param}} keep {total:,} cells; this server reads at most {cap:,} for live cells",
            "pops",
        )


def values(samples: Sequence[Mapping], chosen: Sequence[Sequence[int]], channels: Sequence[str]):
    """kept_values: the raw values on channels of the cells the populations keep, with each
    channel's auto cofactor picked from them."""
    from datanuggets_flow.livecells import kept_values

    return kept_values(samples, chosen, channels)


def save(kept, path: Path) -> None:
    from datanuggets_flow.livecells import save_kept_values

    save_kept_values(kept, path)


def histograms(kept, bins: int, cofactor: float | str) -> dict:
    """channel_histograms on cofactor ("auto" or a number), with how the cofactors were chosen
    first. "auto" draws each channel on its own cofactor, the one a run clustering the kept cells
    would pick: cofactor_from "auto" first, then the bins, then cofactors, negative_fraction and
    negative_sd, one per channel, with no single cofactor and no range. A number draws every
    channel on it: cofactor, cofactor_from "set" and range None first. Values saved under the
    header rule draw on their one auto number, with the widest marker channel range it was picked
    by (None when a header gave none); values saved before a cofactor was recorded draw on the
    package's fallback, 6000, as auto with range None."""
    from datanuggets_flow.livecells import channel_histograms

    out = channel_histograms(kept, bins=bins, cofactor=cofactor)
    how = {"cofactor_from": out.pop("cofactor_from")}
    if "cofactors" in out:
        return how | out
    picked = kept.cofactor if isinstance(cofactor, str) else None
    how["range"] = picked.range if picked is not None else None
    return {"cofactor": out.pop("cofactor"), **how, **out}


def load(path: Path):
    """The values a set's job saved. FileNotFoundError when they are gone."""
    from datanuggets_flow.livecells import load_kept_values

    return load_kept_values(path)


def count(kept, specs: Sequence[str]) -> dict:
    """count_kept: how many of each file's kept cells pass every filter spec."""
    from datanuggets_flow.livecells import count_kept

    return count_kept(kept, specs)
