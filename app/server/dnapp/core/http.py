"""What every HTTP response shares: the Host check, the security headers and CSP, the page's
Cache-Control, the trial cookie, download headers, and the guard that keeps a downloaded CSV from
running as spreadsheet formulas."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse, Response

from dnapp.core.config import (
    ANY_HOST,
    COOKIE_NAME,
    COOKIE_PATH,
    CSV_INJECTION_PREFIXES,
    ENV_ALLOWED_HOSTS,
    INVALID_HOST_MESSAGE,
    LOOPBACK_HOSTS,
    Settings,
)
from dnapp.core.errors import ApiError

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
COMMON_HEADERS = ((b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"))
WEB_CACHE_CONTROL = "no-cache"
# a Host header: a bracketed IPv6 address or a plain name, then an optional port
HOST_RE = re.compile(r"(\[[0-9A-Za-z:.%]+\]|[A-Za-z0-9._-]+)(?::[0-9]{1,5})?")


def host_name(value: str) -> str | None:
    """The name in a Host header or a DN_ALLOWED_HOSTS entry, in lower case and without its port,
    or None when it is not a host. An IPv6 address keeps its brackets and its port starts after
    the closing one. Starlette's own check splits at the first colon, which cuts [::1]:8000 to
    "[" and refuses the loopback address."""
    m = HOST_RE.fullmatch(value)
    return m.group(1).lower() if m else None


def allowed_names(settings: Settings) -> frozenset[str] | None:
    """The Host names the app answers, or None for any name. A port in a listed entry is
    ignored. An entry that is not a host stops the start, since a typo there would otherwise
    lock the page out with no clue why."""
    entries = settings.allowed_hosts
    if ANY_HOST in entries or (settings.trial and not entries):
        return None
    names = set(LOOPBACK_HOSTS)
    for entry in entries:
        name = host_name(entry)
        if name is None:
            raise SystemExit(f"{ENV_ALLOWED_HOSTS} lists {entry!r}, which is not a host name")
        names.add(name)
    return frozenset(names)


class HostCheck:
    """A 400 in the API's error shape for a request whose Host the app does not answer for,
    before any route runs. The app has no websocket routes, so only HTTP requests are checked."""

    def __init__(self, app, names: frozenset[str] | None):
        self.app = app
        self.names = names

    async def __call__(self, scope, receive, send):
        if self.names is not None and scope["type"] == "http":
            host = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"host"), "")
            if host_name(host) not in self.names:
                e = ApiError("invalid_host", INVALID_HOST_MESSAGE)
                response = JSONResponse(e.body(), status_code=e.status)
                return await response(scope, receive, send)
        await self.app(scope, receive, send)


class WebFiles(StaticFiles):
    """The page and its assets, each revalidated on every load. The page is ES modules with no
    build step and no hashed names, so a cached old module beside a newer one that imports it
    stops the page ("does not provide an export named ..."); no-cache keeps the ETag round trip
    and drops the guess."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = WEB_CACHE_CONTROL
        return response


class SecurityHeaders:
    """nosniff and no-referrer on every response; the CSP on HTML ones."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, v) for k, v in message.get("headers", [])
                    if k.lower() not in (b"x-content-type-options", b"referrer-policy")
                ]  # fmt: skip
                headers += list(COMMON_HEADERS)
                ctype = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if ctype.startswith(b"text/html"):
                    headers.append((b"content-security-policy", CSP.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped)


# ---- the trial cookie ---------------------------------------------------------------------


def clear_cookie_header(settings: Settings) -> str:
    secure = "; Secure" if settings.cookie_secure else ""
    return f'{COOKIE_NAME}=""; Max-Age=0; Path={COOKIE_PATH}; HttpOnly; SameSite=Strict{secure}'


def set_cookie(response: Response, settings: Settings, token: str, max_age: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max(0, int(max_age)),
        path=COOKIE_PATH,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
    )


# ---- downloads ----------------------------------------------------------------------------


def attachment(name: str) -> dict[str, str]:
    """The header that makes a browser save the response as name."""
    return {"Content-Disposition": f'attachment; filename="{name}"'}


def _is_number(cell: str) -> bool:
    """True for any cell that reads as a float, finite or not: -inf (pandas), -Infinity (JSON) and
    -nan (C) are values a run writes, not formulas, and a spreadsheet cannot run them."""
    try:
        float(cell)
    except ValueError:
        return False
    return True


def safe_csv(path: Path) -> bytes:
    """The CSV with every cell that starts like a formula prefixed with ', numbers excepted."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            writer.writerow(
                [
                    "'" + c if c.startswith(CSV_INJECTION_PREFIXES) and not _is_number(c) else c
                    for c in row
                ]
            )
    return out.getvalue().encode("utf-8")
