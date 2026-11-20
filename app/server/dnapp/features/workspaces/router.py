"""GET and DELETE /workspace (contract section 3.1). The body lists each record kind through the
WorkspaceSection main.py registered for it, so this feature knows none of them."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from dnapp.core.deps import WS, ip_of, st, workspace
from dnapp.core.errors import ApiError
from dnapp.core.http import set_cookie
from dnapp.core.state import State
from dnapp.core.workspace import Workspace, iso

router = APIRouter()


def workspace_body(s: State, ws: Workspace) -> dict:
    # under the lock: the sections go over the live records, which other requests' threads
    # change, and a gate's files are read from a folder its delete removes
    with ws.lock:
        sections = {key: section.listing(ws) for key, section in s.sections.items()}
    return {
        "mode": s.settings.mode,
        "created": iso(ws.created),
        "idle_expires_at": iso(s.workspaces.idle_expires_at(ws)),
        "expires_at": iso(s.workspaces.expires_at(ws)),
        **sections,
    }


@router.get("/workspace")
def get_workspace(request: Request):
    s = st(request)
    if not s.settings.trial:
        return workspace_body(s, s.workspaces.local())
    try:
        ws = workspace(request)
        return workspace_body(s, ws)
    except ApiError as e:
        if e.code not in ("no_workspace", "workspace_expired"):
            raise
    ip = ip_of(request)
    s.limits.check_workspace(ip)
    token, ws = s.workspaces.create()
    s.limits.note_workspace(ip)
    response = JSONResponse(workspace_body(s, ws))
    set_cookie(response, s.settings, token, s.workspaces.expires_at(ws) - s.clock())
    return response


@router.delete("/workspace", status_code=204)
def delete_workspace(request: Request, ws: WS):
    s = st(request)
    with ws.lock:
        if s.jobs.busy(ws):
            raise ApiError("wrong_state", "A job is running; cancel it or wait for it to finish.")
        s.jobs.forget(ws)
        ws.reset()
    return Response(status_code=204)
