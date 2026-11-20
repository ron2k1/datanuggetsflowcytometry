"""The FastAPI dependencies and request helpers every feature uses: the shared state, the
request's workspace and client address, and the room check every new job passes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from starlette.requests import Request

from dnapp.core.config import COOKIE_NAME
from dnapp.core.errors import ApiError
from dnapp.core.http import clear_cookie_header
from dnapp.core.limits import check_space, client_ip
from dnapp.core.state import State
from dnapp.core.workspace import Workspace


def st(request: Request) -> State:
    return request.app.state.dn


def own[T](request: Request, name: str, kind: type[T]) -> T:
    """The feature name's own service (State.features), checked to be a kind."""
    service = st(request).features[name]
    if not isinstance(service, kind):
        raise TypeError(f"State.features[{name!r}] is a {type(service).__name__}, not a {kind}")
    return service


def ip_of(request: Request) -> str:
    return client_ip(request, st(request).settings)


def workspace(request: Request) -> Workspace:
    """The request's workspace: the local one, or the trial cookie's. 401 without a known
    cookie, 410 (and the cookie cleared) once it has expired."""
    s = st(request)
    if not s.settings.trial:
        return s.workspaces.local()
    status, ws = s.workspaces.lookup(request.cookies.get(COOKIE_NAME))
    if status == "ok":
        ws.touch(s.clock())
        return ws
    if status == "expired":
        if ws is not None and not s.jobs.busy(ws):
            s.jobs.forget(ws)
            s.workspaces.remove(ws)
        raise ApiError(
            "workspace_expired",
            "This workspace has expired and its files were deleted.",
            headers={"Set-Cookie": clear_cookie_header(s.settings)},
        )
    raise ApiError("no_workspace", "No workspace yet; open the app to start one.")


WS = Annotated[Workspace, Depends(workspace)]  # a route's `ws: WS` parameter


def check_job_room(request: Request) -> str:
    """Refuses a new job for this address (pending and hourly limits, the day's budget) or for a
    low disk; the address, for the job and limits.note_job."""
    s = st(request)
    ip = ip_of(request)
    s.limits.check_job(ip, s.jobs.pending_for_ip(ip))
    check_space(s.settings, s.free_bytes)
    return ip
