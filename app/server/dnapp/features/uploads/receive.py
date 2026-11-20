"""Receiving an upload: a multipart body streamed straight to disk with its size checked as it
arrives, and server-generated ids and names only."""

from __future__ import annotations

import shutil
from pathlib import Path

from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import Request

from dnapp.core.config import FCS_MAGIC, KB, MB, UPLOAD_KIND, Settings
from dnapp.core.errors import ApiError
from dnapp.core.workspace import Workspace, safe_name

PARTIAL = ".partial"


class _TooLarge(Exception):
    pass


class _BadMagic(Exception):
    pass


def used_bytes(ws: Workspace) -> int:
    """The workspace's bytes on disk less its demo uploads, which the cap does not count."""
    with ws.lock:  # the records, which other requests' threads change
        demo = sum(u["bytes"] for u in ws.records("uploads").values() if u.get("demo"))
    return max(0, ws.bytes() - demo)


class _Receiver:
    """python-multipart callbacks that write the part named "file" to folder."""

    def __init__(self, folder: Path, settings: Settings, room: int | None):
        self.folder, self.settings, self.room = folder, settings, room
        self.headers: dict[str, str] = {}
        self.field, self.value = b"", b""
        self.in_file = False
        self.done = False
        self.name: str | None = None
        self.cap: int | None = None
        self.handle = None
        self.size = 0
        self.head = b""

    def callbacks(self) -> dict:
        return {
            "on_part_begin": self.part_begin,
            "on_header_field": self.header_field,
            "on_header_value": self.header_value,
            "on_header_end": self.header_end,
            "on_headers_finished": self.headers_finished,
            "on_part_data": self.part_data,
            "on_part_end": self.part_end,
        }

    def part_begin(self):
        self.headers, self.field, self.value = {}, b"", b""

    def header_field(self, data, start, end):
        self.field += data[start:end]

    def header_value(self, data, start, end):
        self.value += data[start:end]

    def header_end(self):
        self.headers[self.field.decode("latin-1").lower()] = self.value.decode("utf-8", "replace")
        self.field, self.value = b"", b""

    def headers_finished(self):
        _, params = parse_options_header(self.headers.get("content-disposition", ""))
        field = params.get(b"name", b"").decode("utf-8", "replace")
        filename = params.get(b"filename")
        if field != "file" or self.done or filename is None:
            self.in_file = False
            return
        self.name = filename.decode("utf-8", "replace")
        caps = [c for c in (self.settings.caps.upload_fcs_bytes, self.room) if c is not None]
        self.cap = min(caps) if caps else None
        self.handle = open(self.folder / PARTIAL, "wb")  # noqa: SIM115 (closed in close())
        self.in_file = True

    def part_data(self, data, start, end):
        if not self.in_file:
            return
        chunk = data[start:end]
        self.size += len(chunk)
        if self.cap is not None and self.size > self.cap:
            raise _TooLarge()
        if len(self.head) < 6:
            self.head += chunk[: 6 - len(self.head)]
            if len(self.head) >= 6 and self.head[:6] not in FCS_MAGIC:
                raise _BadMagic()
        self.handle.write(chunk)

    def part_end(self):
        if self.in_file:
            self.in_file, self.done = False, True
            self.handle.close()

    def close(self):
        if self.handle is not None and not self.handle.closed:
            self.handle.close()


async def receive(
    request: Request, ws: Workspace, settings: Settings, uid: str
) -> tuple[Path, str]:
    """The uploaded file streamed into uploads/<uid>/, as (path, kind). It is taken as an FCS file
    by its header, whatever its name. Every refusal removes the folder."""
    ctype, params = parse_options_header(request.headers.get("content-type", ""))
    if ctype != b"multipart/form-data" or b"boundary" not in params:
        raise ApiError(
            "unsupported_type", "Send the file as multipart/form-data in a field 'file'."
        )
    length = request.headers.get("content-length")
    caps = settings.caps
    room = None
    if caps.workspace_bytes is not None:
        room = caps.workspace_bytes - used_bytes(ws)
        if room <= 0:
            raise ApiError("too_large", "This workspace is full; delete files or runs first.")
    if settings.trial:
        if length is None:
            raise ApiError("length_required", "The upload needs a Content-Length header.")
        limits = [c for c in (caps.upload_fcs_bytes, room) if c is not None]
        try:
            n = int(length)
        except ValueError:
            raise ApiError(
                "length_required", "The Content-Length header is not a number."
            ) from None
        if limits and n > min(limits) + 64 * 1024:  # the multipart framing around the file
            raise ApiError("too_large", _too_large_message(settings, room))
    folder = ws.dir("uploads") / uid
    folder.mkdir(parents=True)
    rec = _Receiver(folder, settings, room)
    parser = MultipartParser(params[b"boundary"], rec.callbacks())
    try:
        async for chunk in request.stream():
            parser.write(chunk)
        parser.finalize()
    except _TooLarge:
        _drop(folder, rec)
        raise ApiError("too_large", _too_large_message(settings, room)) from None
    except _BadMagic:
        _drop(folder, rec)
        raise ApiError("unsupported_type", "This is not an FCS 2.0, 3.0 or 3.1 file.") from None
    except BaseException:
        _drop(folder, rec)
        raise
    rec.close()
    if not rec.done or rec.name is None:
        _drop(folder, rec)
        raise ApiError("invalid_setting", "The form has no file in a field 'file'.", "file")
    if rec.head[:6] not in FCS_MAGIC:
        _drop(folder, rec)
        raise ApiError("unsupported_type", "This is not an FCS 2.0, 3.0 or 3.1 file.")
    with ws.lock:
        taken = {u["name"] for u in ws.records("uploads").values()}
    name = safe_name(rec.name, taken)
    dest = folder / name
    try:
        (folder / PARTIAL).replace(dest)
    except OSError:  # a name the system keeps for itself, as Windows keeps NUL for a device
        _drop(folder, rec)
        raise ApiError(
            "invalid_setting",
            "This file's name can't be saved here; rename it and try again.",
            "file",
        ) from None
    return dest, UPLOAD_KIND


def _too_large_message(settings: Settings, room: int | None) -> str:
    """The cap an upload passed: the per-file one when it is the smaller, else the workspace's
    room. Only called when one of them is set."""
    cap = settings.caps.upload_fcs_bytes
    if cap is not None and (room is None or cap <= room):
        unit, name = (MB, "MB") if cap >= MB else (KB, "KB")  # never "0 MB"
        size = f"{cap / unit:.1f}".removesuffix(".0")
        return f"FCS uploads are limited to {size} {name}."
    return "This upload does not fit in the workspace's space; delete files or runs first."


def _drop(folder: Path, rec: _Receiver | None = None) -> None:
    if rec is not None:
        rec.close()
    shutil.rmtree(folder, ignore_errors=True)
