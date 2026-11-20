"""GET /jobs, GET /jobs/{jid} and POST /jobs/{jid}/cancel (contract section 3.4)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from dnapp.core.deps import WS, st

router = APIRouter()


@router.get("/jobs")
def list_jobs(request: Request, ws: WS):
    s = st(request)
    return {"jobs": s.jobs.listing(ws)}


@router.get("/jobs/{jid}")
def get_job(jid: str, request: Request, ws: WS):
    s = st(request)
    return s.jobs.view(s.jobs.get(ws, jid))


@router.post("/jobs/{jid}/cancel", status_code=202)
def cancel_job(jid: str, request: Request, response: Response, ws: WS):
    s = st(request)
    job = s.jobs.get(ws, jid)
    if not s.jobs.cancel(job):
        response.status_code = 200  # it had already ended, and is left as it is
    return s.jobs.view(job)
