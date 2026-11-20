"""The Transform stage's cofactor for a run: a number as given, for every channel, or "auto",
picked per channel, once and before any arcsinh, from the raw values of the cells the run
clusters. NegativeTally counts them as the files are read, and auto_cofactor applies the rule
_defaults.py gives to the counts."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from datanuggets_flow._defaults import (
    FLOW_COFACTOR_AUTO,
    FLOW_COFACTOR_FLOOR,
    FLOW_COFACTOR_HIST,
    FLOW_COFACTOR_MAD_Z,
    FLOW_COFACTOR_MIN_NEGATIVE,
)
from datanuggets_flow._pipeline.records import Cofactor
from datanuggets_flow.settings import check_cofactor

LOW, HIGH, PER_DECADE = FLOW_COFACTOR_HIST
LOG_LOW = float(np.log10(LOW))
# the bins inside [LOW, HIGH); the tally keeps one more below them and one above
BINS = round((np.log10(HIGH) - LOG_LOW) * PER_DECADE)


def _bins(a: np.ndarray) -> np.ndarray:
    """Each positive value's bin: 0 below LOW, BINS + 1 from HIGH (inf too), and in between the
    log-spaced bin it falls in, from 1."""
    found = np.empty(len(a), dtype=np.intp)
    under, over = a < LOW, a >= HIGH
    inside = ~(under | over)
    at = np.floor((np.log10(a[inside]) - LOG_LOW) * PER_DECADE)
    found[inside] = 1 + np.clip(at, 0, BINS - 1).astype(np.intp)
    found[under], found[over] = 0, BINS + 1
    return found


def _median(counts: np.ndarray, m: int) -> float:
    """The median of the m values counts holds, by bin: the bin where the cumulative count
    reaches m / 2, and the place in it found linearly in log10, as if its values were spread
    evenly over it. The bin below LOW reads as LOW and the one above HIGH as HIGH."""
    rank = m / 2
    cumulative = np.cumsum(counts)
    b = int(np.searchsorted(cumulative, rank, side="left"))
    if b == 0:
        return LOW
    if b == BINS + 1:
        return HIGH
    share = (rank - (cumulative[b] - counts[b])) / counts[b]
    return float(10 ** (LOG_LOW + (b - 1 + share) / PER_DECADE))


class NegativeTally:
    """Each of p channels' cells, its cells below 0 and a histogram of |x| over those, in the
    bins FLOW_COFACTOR_HIST sets, summed as cells are added, so the files can come one at a time
    and in any order and give the same counts. A NaN is a cell but not one below 0."""

    def __init__(self, p: int):
        self.cells = np.zeros(p, dtype=np.int64)
        self.negative = np.zeros(p, dtype=np.int64)
        self.counts = np.zeros((p, BINS + 2), dtype=np.int64)

    def add(self, x) -> None:
        """Counts x, raw values with one row per cell and one column per channel."""
        x = np.asarray(x, dtype=np.float64)
        p = len(self.cells)
        if x.ndim != 2 or x.shape[1] != p:
            raise ValueError(f"the tally takes cells by {p} channels, not an array of {x.shape}")
        self.cells += len(x)
        for j in range(p):
            column = x[:, j]
            below = column[column < 0]
            self.negative[j] += len(below)
            self.counts[j] += np.bincount(_bins(-below), minlength=BINS + 2)


def auto_cofactor(tally: NegativeTally) -> Cofactor:
    """The auto cofactor of the cells tally counted, per channel: the share f of its cells below
    0, their spread, the median of |x| over them divided by FLOW_COFACTOR_MAD_Z (None with none),
    and the cofactor, that spread but at least FLOW_COFACTOR_FLOOR when f is at least
    FLOW_COFACTOR_MIN_NEGATIVE, and FLOW_COFACTOR_FLOOR otherwise. A tally of no cells gives the
    floor for every channel."""
    values, negative, spread = [], [], []
    for n, m, counts in zip(tally.cells, tally.negative, tally.counts):
        f = float(m / n) if n else 0.0
        sd = _median(counts, int(m)) / FLOW_COFACTOR_MAD_Z if m else None
        wide = sd is not None and f >= FLOW_COFACTOR_MIN_NEGATIVE
        values.append(max(FLOW_COFACTOR_FLOOR, sd) if wide else FLOW_COFACTOR_FLOOR)
        negative.append(f)
        spread.append(sd)
    return Cofactor(
        FLOW_COFACTOR_FLOOR, FLOW_COFACTOR_AUTO, None, tuple(values), tuple(negative), tuple(spread)
    )


def resolve_cofactor(
    cofactor: float | str, tally: NegativeTally | Callable[[], NegativeTally] | None = None
) -> Cofactor:
    """The cofactor a run uses. A number, 0 included, is taken as set for every channel, and
    tally isn't used. "auto" is auto_cofactor of tally, the run's NegativeTally or a function
    that makes it, called only then, so a run given a number never makes the extra pass over its
    files; without one ValueError is raised. Anything other than "auto" or a finite number from 0
    is refused with a FlowError naming cofactor before tally is used."""
    check_cofactor(cofactor)
    if not isinstance(cofactor, str):
        return Cofactor(float(cofactor), "set")
    if tally is None:
        raise ValueError(
            "auto picks each channel's cofactor from the run's cells; give their tally"
        )
    return auto_cofactor(tally if isinstance(tally, NegativeTally) else tally())
