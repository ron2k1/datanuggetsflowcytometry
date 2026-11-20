"""GET /runs/{rid}/compare (contract section 3.5)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from dnapp.core.deps import WS, st
from dnapp.core.errors import ApiError
from dnapp.features.compare.service import compare

router = APIRouter()


@router.get("/runs/{rid}/compare")
def get_compare(rid: str, request: Request, ws: WS):
    s = st(request)
    rec = s.runs.done(ws, rid)
    if rec["kind"] != "flow":
        raise ApiError("wrong_state", "Comparisons are for flow runs.")
    body = compare(rid, s.runs.folder(ws, rid), s.runs.run_json(ws, rid), rec["settings"])
    return s.scrub.obj(body)
