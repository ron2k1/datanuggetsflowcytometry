"""The API's error shape, {"error": {"code", "message", "param"}}, the handlers that give every
failure that shape, and the scrubbing that keeps absolute paths out of every message and record."""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Iterable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("dnapp")

STATUS = {
    "invalid_host": 400,
    "no_workspace": 401,
    "not_found": 404,
    "wrong_state": 409,
    "workspace_expired": 410,
    "length_required": 411,
    "too_large": 413,
    "unsupported_type": 415,
    "invalid_setting": 422,
    "unreadable_file": 422,
    "rate_limited": 429,
    "busy": 503,
    "out_of_space": 507,
    "internal": 500,
}
# half a UTF-16 surrogate pair: a JSON escape can carry one, but UTF-8 cannot encode it, so a
# message that names a refused value holding one would fail its own answer
LONE = re.compile(r"[\ud800-\udfff]")


class ApiError(Exception):
    """An error the API answers with its pinned status and shape. The message holds U+FFFD for a
    lone surrogate, so it can always be sent."""

    def __init__(
        self,
        code: str,
        message: str,
        param: str | None = None,
        *,
        headers: dict[str, str] | None = None,
    ):
        message = LONE.sub("�", message)
        super().__init__(message)
        self.code, self.message, self.param = code, message, param
        self.status = STATUS[code]
        self.headers = headers or {}

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "param": self.param}}


def internal_ref() -> str:
    """The 8-character reference an internal error's message and log line share."""
    return secrets.token_hex(4)


def internal_message(ref: str) -> str:
    return f"Something went wrong (ref {ref})"


def not_found(what: str) -> ApiError:
    return ApiError("not_found", f"No {what} with that id.")


class Scrubber:
    """Replaces every path under one of roots with its last part, so no folder of the server
    reaches a client. Names the app writes hold no whitespace or quotes, so a path ends at the
    first character that is not part of a safe name or a separator."""

    def __init__(self, roots: Iterable[Path | str]):
        variants = set()
        for root in roots:
            text = str(root)
            for v in (text, text.replace("\\", "/"), text.replace("/", "\\")):
                if v:
                    variants.add(v.rstrip("\\/"))
        alts = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
        self._re = re.compile(rf"(?:{alts})((?:[\\/][^\\/\s'\",;:()<>\[\]{{}}]*)*)", re.IGNORECASE)

    def text(self, s: str) -> str:
        def last(m: re.Match) -> str:
            parts = [p for p in re.split(r"[\\/]", m.group(1)) if p]
            return parts[-1] if parts else ""

        return self._re.sub(last, s)

    def obj(self, v):
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, list):
            return [self.obj(x) for x in v]
        if isinstance(v, tuple):
            return [self.obj(x) for x in v]
        if isinstance(v, dict):
            # a key can name a path too
            return {self.text(k) if isinstance(k, str) else k: self.obj(x) for k, x in v.items()}
        return v


# ---- the handlers that give every failure the pinned shape --------------------------------


def _error(e: ApiError) -> JSONResponse:
    return JSONResponse(e.body(), status_code=e.status, headers=e.headers)


def _param(loc) -> str | None:
    """The first name after where the value was read from; only loc[0] is that, so a body field
    can be called body, query or path."""
    if loc and loc[0] in ("body", "query", "path", "header", "cookie"):
        loc = loc[1:]
    parts = [p for p in loc if isinstance(p, str)]
    return parts[0] if parts else None


def install_errors(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, e: ApiError):
        return _error(e)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, e: RequestValidationError):
        errs = e.errors()
        first = errs[0] if errs else {}
        param = _param(first.get("loc", ()))
        msg = first.get("msg", "Invalid request")
        text = f"{param}: {msg}" if param else msg
        return _error(ApiError("invalid_setting", text, param))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, e: StarletteHTTPException):
        if e.status_code == 404:
            return _error(ApiError("not_found", "Not found."))
        code = "wrong_state" if e.status_code == 405 else "internal"
        err = ApiError(code, str(e.detail))
        resp = _error(err)
        resp.status_code = e.status_code
        return resp

    @app.exception_handler(Exception)
    async def crash(request: Request, e: Exception):
        ref = internal_ref()
        log.exception("internal error (ref %s) on %s %s", ref, request.method, request.url.path)
        return _error(ApiError("internal", internal_message(ref)))
