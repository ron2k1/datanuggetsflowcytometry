"""A live-cells job's work inside its job worker: the trial's cap on the cells read, the kept
cells' raw values saved to values.npz, then their histograms to histograms.json, all in the set's
folder. run_job removes the folder when the job fails or is cancelled."""

from __future__ import annotations

from pathlib import Path

from dnapp.core.config import (
    LIVECELLS_HISTOGRAMS,
    LIVECELLS_REQUEST,
    LIVECELLS_SHARE,
    LIVECELLS_VALUES,
)
from dnapp.core.package import flow, livecells
from dnapp.core.protocols import Reporter
from dnapp.core.workspace import write_json


def livecells_work(spec: dict, rep: Reporter, out: Path) -> dict:
    samples = flow.load_gates(Path(spec["gates"])).samples
    livecells.check_cells(samples, spec["pops"], spec["cells_max"])
    rep.check()
    out.mkdir(parents=True)
    write_json(out / LIVECELLS_REQUEST, spec["request"])
    kept = livecells.values(samples, spec["pops"], spec["channels"])
    rep.check()
    livecells.save(kept, out / LIVECELLS_VALUES)
    rep.progress(LIVECELLS_SHARE, "values", "Read the kept cells")
    rep.check()
    hist = livecells.histograms(kept, spec["bins"], spec["cofactor"])
    rep.log(cofactor_line(hist))
    write_json(out / LIVECELLS_HISTOGRAMS, hist)
    return {}


def cofactor_line(hist: dict) -> str:
    """The log's line for the cofactors the histograms were drawn on: the span of the channels'
    own (one number when they are all the same), rounded as the run's Transform lines round
    them, or the one number with how it was chosen."""
    if "cofactors" in hist:
        lo, hi = (f"{c:,.0f}" for c in (min(hist["cofactors"]), max(hist["cofactors"])))
        span = lo if lo == hi else f"{lo}-{hi}"
        return f"Histogram cofactor per channel ({hist['cofactor_from']}): {span}"
    return f"Histogram cofactor {hist['cofactor']:g} ({hist['cofactor_from']})"
