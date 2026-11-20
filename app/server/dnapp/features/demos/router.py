"""GET /demos and POST /demos/{demo_id}/load (contract section 3.6). A demo's files become uploads
through the UploadStore."""

from __future__ import annotations

from fastapi import APIRouter, Request

from dnapp.core.deps import WS, st
from dnapp.core.errors import ApiError
from dnapp.core.limits import check_space
from dnapp.features.demos.service import available, find, listing

router = APIRouter()


@router.get("/demos")
def list_demos(request: Request):
    return {"demos": listing(st(request).settings.demo_dir)}


@router.post("/demos/{demo_id}/load", status_code=201)
async def load_demo(demo_id: str, request: Request, ws: WS):
    s = st(request)
    demo = find(s.settings.demo_dir, demo_id)
    if not available(s.settings.demo_dir, demo):
        raise ApiError("wrong_state", "This demo's files are not on this server.")
    check_space(s.settings, s.free_bytes)
    root = s.settings.demo_dir.resolve()
    out = []
    for f in demo["files"]:
        src = (root / f["path"]).resolve()
        if root not in src.parents:
            raise ApiError("not_found", "No demo file at that path.")
        out.append(await s.uploads.add_copy(ws, src, f["name"], demo_id))
    return {"uploads": out}
