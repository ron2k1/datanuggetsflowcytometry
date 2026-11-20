"""GET /runs, GET and DELETE /runs/{rid} (contract section 3.4). Runs are created by the flow
feature; their payloads are served by plot, compare and downloads. A local workspace from before
the app was flow-only can still hold general runs: they are listed, deleted and downloaded like
any run, but their details are refused."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from dnapp.core.deps import WS, st
from dnapp.core.errors import ApiError
from dnapp.core.protocols import ACTIVE
from dnapp.core.run_outputs import clusters, file_entries
from dnapp.features.runs.service import remove

router = APIRouter()


@router.get("/runs")
def list_runs(request: Request, ws: WS):
    with ws.lock:  # the records, which other requests' threads change
        return {"runs": st(request).runs.listing(ws)}


@router.get("/runs/{rid}")
def get_run(rid: str, request: Request, ws: WS):
    s = st(request)
    runs = s.runs
    rec = runs.record(ws, rid)
    if rec["kind"] != "flow":
        raise ApiError("wrong_state", "Run details are for flow runs.")
    status = runs.status(ws, rec)
    done = status == "done"
    out = runs.folder(ws, rid)
    return {
        "id": rid,
        "kind": rec["kind"],
        "status": status,
        "created": rec["created"],
        "title": rec["title"],
        "settings": rec["settings"],
        "record": runs.run_json(ws, rid) if done else {},
        "k": runs.k(ws, rec),
        "clusters": clusters(out) if done else [],
        "files": file_entries(out) if done else [],
        "warnings": s.scrub.obj(runs.warnings(ws, rec)),
    }


@router.delete("/runs/{rid}", status_code=204)
def delete_run(rid: str, request: Request, ws: WS):
    runs = st(request).runs
    with ws.lock:
        rec = runs.record(ws, rid)
        if runs.status(ws, rec) in ACTIVE:
            raise ApiError("wrong_state", "The run is still running; cancel it first.")
        remove(ws, rid)
    return Response(status_code=204)
