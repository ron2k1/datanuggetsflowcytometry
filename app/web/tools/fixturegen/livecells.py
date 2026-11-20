"""Live cells on gate g1 (contract-livecells.md section 4), from a real run of
datanuggets_flow.livecells on the gated PBMC files with the pops the flow run r3 used.

The request leaves the cofactor on "auto", as the step does, so each channel's histogram is drawn
on the cofactor auto picks for it from the kept cells (the SD of the cells below 0 where at least
1% of them are below 0, at least 150), and the set gives each channel's own and says so.

Nothing here places a threshold for the user. The counts fixture's two filters sit at each
channel's middle bin edge, edges[bins // 2], turned to raw as that channel's cofactor * sinh(t)
and rounded to four significant digits, as section 4 asks: a derived position that shows the
counts table, never a default the page offers.
"""

from __future__ import annotations

import math
from pathlib import Path

from datanuggets.filters import RowFilter
from datanuggets_flow.livecells import LIVECELLS_BINS, count_kept, kept_values, suggest_channels
from datanuggets_flow.settings import ClusterSettings
from datanuggets_flow.state import load_gates

from dnapp.core.package.livecells import histograms

from .common import sig, write_json
from .jobs import job

# The step's direction per role (contract-livecells.md section 3): keep cells below the dye's
# line, above CD45's.
KEEP = {"viability": "<", "cd45": ">"}
CELLS_MAX = 6_000_000  # LIVECELLS_CELLS_MAX in trial mode, which the real request must pass


def write_livecells(out: Path, mock: Path, gate: dict, pops: list, t_last: str) -> None:
    """Writes the step's GET, the POST that queues j9, j9 done, the record l1 with its
    histograms, and one counts response."""
    folder = load_gates(mock / "out" / "flow-gates-1")
    first = folder.samples[0]
    pnn, pns = list(first["pnn"]), list(first["pns"])
    if [c["pnn"] for c in gate["files"][0]["channels"]] != pnn:
        raise SystemExit("gate fixture file 1's channels differ from the gate folder's")
    suggested = suggest_channels(pnn, pns)
    roles = [r for r in KEEP if suggested[r]]
    if len(roles) != len(KEEP):
        raise SystemExit(f"the demo files should suggest both channels, got {suggested}")
    channels = [suggested[r] for r in roles]

    # The request a step with no cofactor of its own sends: the clustering's default, "auto".
    request = {
        "pops": [sorted(p) for p in pops],
        "channels": channels,
        "bins": LIVECELLS_BINS,
        "cofactor": ClusterSettings().cofactor,
    }
    kept = kept_values(folder.samples, request["pops"], channels)
    total = sum(f.kept for f in kept.files)
    if total > CELLS_MAX:
        raise SystemExit(f"{total} kept cells is over the trial cap {CELLS_MAX}")
    # As the server's job writes them and GET .../livecells/{lid} reads them back: how the
    # cofactors were chosen, then each channel's own, unrounded, as the API sends them.
    hist = histograms(kept, LIVECELLS_BINS, request["cofactor"])
    if len(hist.get("cofactors") or ()) != len(channels):
        raise SystemExit(
            f"auto should give each channel its own cofactor, not {hist.get('cofactor')}"
        )

    queued = job("j9", "livecells", "queued", t_last, gate_id="g1")
    done = job("j9", "livecells", "done", t_last, gate_id="g1", stage="done")
    record = {
        "id": "l1",
        "gate_id": "g1",
        "status": "done",
        "created": t_last,
        "job": "j9",
        "request": request,
    }
    write_json(
        out / "GET__flow__gates__g1__livecells.json",
        {
            "gate_id": "g1",
            "channels": gate["files"][0]["channels"],
            "suggested": suggested,
            "livecells": [{k: record[k] for k in ("id", "status", "created", "request")}],
        },
    )
    write_json(out / "POST__flow__gates__g1__livecells.json", {"job": queued, "livecells_id": "l1"})
    write_json(out / "GET__jobs__j9.json", done)
    # lo, hi and edges go out unrounded (section 2.3), so the bars stand on the package's edges.
    write_json(out / "GET__flow__gates__g1__livecells__l1.json", record | {"histograms": hist})

    filters = []
    for role, ch, cofactor in zip(roles, hist["channels"], hist["cofactors"]):
        t = ch["edges"][LIVECELLS_BINS // 2]
        raw = sig(cofactor * math.sinh(t))
        filters.append(RowFilter(ch["channel"], KEEP[role], raw))
    write_json(out / "POST__flow__gates__g1__livecells__l1__counts.json", count_kept(kept, filters))
