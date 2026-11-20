"""Reading a stored upload: its rows (events) and columns (channels), through the package."""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
from starlette.concurrency import run_in_threadpool

from dnapp.core.config import Settings
from dnapp.core.errors import ApiError
from dnapp.core.package.flow import read_fcs, read_ranges
from dnapp.core.payload import r4


def _stats(values: np.ndarray) -> dict:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return {"min": None, "max": None, "mean": None}
    return {"min": r4(finite.min()), "max": r4(finite.max()), "mean": r4(finite.mean())}


def describe_fcs(path: Path, settings: Settings) -> dict:
    failed = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            events, pnn, pns = read_fcs(path)
    except Exception as e:  # noqa: BLE001 - flowio raises many kinds for a broken file
        failed = type(e).__name__
    # raised out here, not in the except block: there the refusal's context would hold flowio's
    # error, its traceback and so the reader's open file, which on Windows keeps the caller's
    # rmtree from removing the upload
    if failed is not None:
        raise ApiError("unreadable_file", f"The FCS file could not be read: {failed}.")
    caps = settings.caps
    if caps.fcs_events is not None and len(events) > caps.fcs_events:
        raise ApiError("too_large", f"FCS files are limited to {caps.fcs_events:,} events.")
    ranges = _ranges(path, len(pnn))
    columns = [
        {
            "name": n,
            "label": s,
            "numeric": True,
            **_stats(events[:, j]),
            "missing": 0,
            "range": ranges[j],
        }
        for j, (n, s) in enumerate(zip(pnn, pns))
    ]
    return {"rows": len(events), "columns": columns}


def _ranges(path: Path, n: int) -> list[float | None]:
    """Each of the n channels' range from its $PnR, decoded as the package's read_ranges decodes
    it and left unrounded, as the header gives it; None for a channel whose header gives no
    usable range, and for every channel when the header can't be read for ranges or gives
    another number of them."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            found = read_ranges(path)
    except Exception:  # noqa: BLE001 - the events were read; the ranges are extra
        return [None] * n
    return found if len(found) == n else [None] * n


async def describe(path: Path, settings: Settings) -> dict:
    return await run_in_threadpool(describe_fcs, path, settings)
