"""Gate g1, from the gating CLI's gates.json and its two figures."""

from __future__ import annotations

import shutil
from pathlib import Path

from datanuggets_flow._defaults import FLOW_CHANNEL_SUFFIX, FLOW_SCATTER_PREFIXES
from datanuggets_flow.colors import population_colors

from .common import sig, write_json


def write_gate(
    out: Path, mock: Path, gates: dict, up_ids: dict, by_name: dict, t_gate: str
) -> dict:
    """Writes GET /flow/gates/g1 and copies its figures; returns the gate."""
    gate_files = []
    for g in gates["files"]:
        pnn, pns = g["pnn"], g["pns"]
        pops = g["populations"]
        colors = population_colors([p["events"] for p in pops])
        gate_files.append(
            {
                "number": g["number"],
                "upload": up_ids[g["name"]],
                "name": g["name"],
                "n_events": g["n_events"],
                "channels": [{"pnn": n, "pns": s or ""} for n, s in zip(pnn, pns)],
                "default_channels": [
                    c
                    for c in pnn
                    if c.endswith(FLOW_CHANNEL_SUFFIX) and not c.startswith(FLOW_SCATTER_PREFIXES)
                ],
                "local_maxima": g["local_maxima"],
                "populations": [
                    {
                        "pop": p["pop"],
                        "events": p["events"],
                        "percent": sig(p["percent"]),
                        "median_fsc": sig(p["median_fsc"]),
                        "median_ssc": sig(p["median_ssc"]),
                        "peak": p["peak"],
                        "color": colors[i],
                    }
                    for i, p in enumerate(pops)
                ],
            }
        )
        if by_name[g["name"]]["rows"] != g["n_events"]:
            raise SystemExit(
                f"{g['name']}: the FCS read gives {by_name[g['name']]['rows']} events, gates.json {g['n_events']}"
            )
    for f in ("local_maxima.png", "gates.png"):
        shutil.copyfile(mock / "out" / "flow-gates-1" / f, out / "png" / f)
    gate = {
        "id": "g1",
        "status": "done",
        "created": t_gate,
        "settings": gates["settings"],
        "files": gate_files,
        "figures": {
            "local_maxima": "fixtures/png/local_maxima.png",
            "gates": "fixtures/png/gates.png",
        },
    }
    write_json(out / "GET__flow__gates__g1.json", gate)
    return gate
