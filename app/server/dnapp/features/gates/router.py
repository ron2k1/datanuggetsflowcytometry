"""POST /flow/gates, GET and DELETE /flow/gates/{gid} and its figures (contract section 3.4)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from dnapp.core.config import GATE_FIGURES
from dnapp.core.datasets import check_one_dataset
from dnapp.core.deps import WS, check_job_room, st
from dnapp.core.errors import ApiError, not_found
from dnapp.core.limits import check_max
from dnapp.core.package import flow
from dnapp.core.package.errors import refusals
from dnapp.core.protocols import ACTIVE
from dnapp.features.gates.schemas import GateRequest
from dnapp.features.gates.service import remove

router = APIRouter()


@router.post("/flow/gates", status_code=202)
def post_gate(body: GateRequest, request: Request, ws: WS):
    s = st(request)
    if not body.uploads:
        raise ApiError("invalid_setting", "Choose at least one FCS file.", "uploads")
    if len(set(body.uploads)) != len(body.uploads):
        raise ApiError("invalid_setting", "Each file can be gated once per gate.", "uploads")
    check_max("uploads", len(body.uploads), s.settings.caps.fcs_files_per_gate)
    recs = []
    for uid in body.uploads:
        rec = s.uploads.find(ws, uid)
        if rec is None or rec["kind"] != "fcs":
            raise ApiError(
                "invalid_setting", f"{uid} is not an FCS upload in this workspace.", "uploads"
            )
        recs.append(rec)
    check_one_dataset(recs, "gate", "uploads")
    paths = [str(s.uploads.path(ws, rec)) for rec in recs]
    with refusals():
        settings = flow.gate_settings(body.settings, len(paths))
    ip = check_job_room(request)
    gid = ws.next_id("gates")
    spec = {
        "out": str(s.gates.folder(ws, gid)),
        "paths": paths,
        "settings": settings.to_dict(),
        "param_names": list(settings.to_dict()),
    }
    with ws.lock:
        job = s.jobs.submit(ws, "gate", spec, ip, gate_id=gid)
        ws.records("gates")[gid] = {
            "id": gid,
            "created": job.record["created"],
            "uploads": list(body.uploads),
            "settings": settings.to_dict(),
            "job": job.record["id"],
        }
        ws.save()
    s.limits.note_job(ip)
    return {"job": s.jobs.view(job), "gate_id": gid}


@router.get("/flow/gates/{gid}")
def get_gate(gid: str, request: Request, ws: WS):
    gates = st(request).gates
    return gates.view(ws, gates.record(ws, gid))


@router.get("/flow/gates/{gid}/figures/{name}")
def gate_figure(gid: str, name: str, request: Request, ws: WS):
    gates = st(request).gates
    rec = gates.record(ws, gid)
    if name not in GATE_FIGURES:
        raise not_found("figure")
    if gates.status(ws, rec) != "done":
        raise ApiError("wrong_state", "The gate is not done yet.")
    path = gates.folder(ws, gid) / name
    if not path.is_file():
        raise not_found("figure")
    return FileResponse(path, media_type="image/png")


@router.delete("/flow/gates/{gid}", status_code=204)
def delete_gate(gid: str, request: Request, ws: WS):
    s = st(request)
    with ws.lock:
        rec = s.gates.record(ws, gid)
        if s.gates.status(ws, rec) in ACTIVE:
            raise ApiError("wrong_state", "The gate job is still running; cancel it first.")
        for user in s.gate_users:
            why = user.gate_in_use(ws, gid)
            if why:
                raise ApiError("wrong_state", why)
        for user in s.gate_users:
            user.gate_deleted(ws, gid)
        remove(ws, gid)
    return Response(status_code=204)
