"""POST /uploads, GET /uploads, GET and DELETE /uploads/{uid} (contract section 3.3)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from dnapp.core.deps import WS, st
from dnapp.core.errors import ApiError
from dnapp.core.limits import check_space
from dnapp.features.uploads.receive import receive
from dnapp.features.uploads.service import keep, public, remove

router = APIRouter()


@router.post("/uploads", status_code=201)
async def post_upload(request: Request, ws: WS):
    s = st(request)
    check_space(s.settings, s.free_bytes)
    uid = ws.next_id("uploads")
    path, kind = await receive(request, ws, s.settings, uid)
    return await keep(ws, uid, path, kind, s.settings, s.clock, None)


@router.get("/uploads")
def list_uploads(request: Request, ws: WS):
    with ws.lock:  # the records, which other requests' threads change
        return {"uploads": st(request).uploads.listing(ws)}


@router.get("/uploads/{uid}")
def get_upload(uid: str, request: Request, ws: WS):
    return public(st(request).uploads.record(ws, uid))


@router.delete("/uploads/{uid}", status_code=204)
def delete_upload(uid: str, request: Request, ws: WS):
    s = st(request)
    with ws.lock:
        rec = s.uploads.record(ws, uid)
        for user in s.upload_users:  # in main.py's order; the first reason refuses
            why = user.upload_in_use(ws, uid)
            if why:
                raise ApiError("wrong_state", why)
        remove(ws, rec)
    return Response(status_code=204)
