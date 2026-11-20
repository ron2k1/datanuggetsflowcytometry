"""GET /runs/{rid}/plot and GET /runs/{rid}/cells (contract section 3.5)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from dnapp.core.deps import WS, st
from dnapp.core.errors import ApiError
from dnapp.core.state import State
from dnapp.core.workspace import Workspace
from dnapp.features.plot.cells import cells
from dnapp.features.plot.service import flow_plot

router = APIRouter()


def _done_flow_run(s: State, ws: Workspace, rid: str, what: str) -> dict:
    """The record of a done flow run; a legacy workspace's general run is refused, as /compare
    refuses it."""
    rec = s.runs.done(ws, rid)
    if rec["kind"] != "flow":
        raise ApiError("wrong_state", f"{what} are for flow runs.")
    return rec


@router.get("/runs/{rid}/plot")
def get_plot(rid: str, request: Request, ws: WS):
    s = st(request)
    rec = _done_flow_run(s, ws, rid, "Plots")
    body = flow_plot(rid, s.runs.folder(ws, rid), s.runs.run_json(ws, rid), rec["settings"])
    body["warnings"] = body["warnings"] + s.runs.warnings(ws, rec)
    return s.scrub.obj(body)


@router.get("/runs/{rid}/cells")
def get_cells(rid: str, request: Request, ws: WS):
    s = st(request)
    rec = _done_flow_run(s, ws, rid, "Cells")
    body = cells(
        rid,
        s.runs.folder(ws, rid),
        s.runs.run_json(ws, rid),
        rec["settings"].get("cells_per_file") or 0,
        s.settings.caps.cells_max_total,
    )
    return s.scrub.obj(body)
