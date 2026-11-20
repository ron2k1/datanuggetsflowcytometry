"""Reading an FCS file for the run: its events, its channels' $PnN names and $PnS labels, and,
from its TEXT segment alone, each channel's range. flowio, the FCS reader, loads only when a file
is read."""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from pathlib import Path

import numpy as np
from datanuggets import DataNuggetWarning

from datanuggets_flow._defaults import FLOW_SPILL_TOL


def _flowio():
    try:
        import flowio
    except ImportError as e:  # a dependency of the package, so missing only from a damaged install
        raise ImportError("reading FCS files needs flowio: pip install datanuggets-flow") from e
    return flowio


def _name(text: Mapping[str, str], k: int) -> str:
    """Channel k's $PnN, or P and k when the file has none, as FCS 2.0 allows and as the app's
    in-tab reader names it."""
    return text.get(f"p{k}n") or f"P{k}"


def _range(text: Mapping[str, str], k: int, name: str) -> float | None:
    """Channel k's top value as flowio's preprocess gives it, or None (see decode_ranges)."""
    try:
        stored = float(text[f"p{k}r"])
        decades, log0 = (float(v) for v in text.get(f"p{k}e", "0,0").split(","))
        gain = float(text.get(f"p{k}g", 1.0))
        if not (math.isfinite(stored) and stored > 0):
            return None
        top = stored
        if name.lower() == "time":  # flowio's Time: no gain, scaled by $TIMESTEP
            gain = 1.0
            step = text.get("timestep")
            if step is not None and str(step).strip():
                top *= float(step)
        if log0 == 0 and decades != 0:
            log0 = 1.0
        if decades > 0:
            top = 10 ** (decades * top / stored) * log0
        if gain not in (1.0, 0.0):
            top /= gain
    except (KeyError, ValueError, OverflowError):
        return None
    return top if math.isfinite(top) and top > 0 else None


def decode_ranges(text: Mapping[str, str]) -> tuple[list[str], list[float | None]]:
    """Each channel's $PnN, as read_fcs names it, and its range: the largest value flowio's
    preprocess gives it, from a file's TEXT keywords, in any case, with or without the $. That
    is $PnR as stored for a linear channel, 10 ** f1 * f2 for one $PnE stores on a log scale (f2
    taken as 1 when it is 0), divided by $PnG when that is neither 1 nor 0. A channel named Time
    has no gain and is scaled by $TIMESTEP, as flowio scales it. The range is None where $PnR is
    missing, or $PnR, $PnE or $PnG doesn't read as numbers flowio takes, or the range isn't a
    positive finite number. A missing $PnE is linear and a missing $PnG 1, as flowio reads them."""
    t = {str(k).lower().lstrip("$"): v for k, v in text.items()}
    names = [_name(t, k) for k in range(1, int(t["par"]) + 1)]
    return names, [_range(t, k, name) for k, name in enumerate(names, 1)]


def read_ranges(path) -> tuple[list[str], list[float | None]]:
    """A file's channels, by $PnN as read_fcs names them, and each one's range as decode_ranges
    gives it, from the file's TEXT segment: no event is read. flowio refuses a header whose $PnR
    is missing or whose $PnR, $PnE or $PnG isn't a number, so its error is raised here, as
    read_fcs raises it; None comes from values flowio takes that give no usable range."""
    fd = _flowio().FlowData(str(path), only_text=True)
    return decode_ranges(fd.text)


def read_fcs(path) -> tuple[np.ndarray, list[str], list[str]]:
    """A file's events, one column per channel, with each channel's $PnN name (P and its number
    when it has none) and $PnS label ('' when it has none). The events are flowio's, as stored: a
    spillover matrix further than FLOW_SPILL_TOL from the identity gives a DataNuggetWarning,
    since nothing compensates them."""
    fd = _flowio().FlowData(str(path))
    c = fd.channel_count
    pnn = [_name(fd.text, k) for k in range(1, c + 1)]
    pns = [fd.text.get(f"p{k}s", "").strip() for k in range(1, c + 1)]
    spill = fd.text.get("spillover") or fd.text.get("spill")
    if spill:
        v = spill.split(",")
        m = int(v[0])
        s = np.asarray(v[1 + m :], dtype=float).reshape(m, m)
        if np.abs(s - np.eye(m)).max() > FLOW_SPILL_TOL:
            warnings.warn(
                f"{Path(path).name} has a compensation matrix, but its events are clustered as "
                "stored, uncompensated",
                DataNuggetWarning,
                stacklevel=2,
            )
    return np.asarray(fd.as_array(preprocess=True), dtype=float), pnn, pns
