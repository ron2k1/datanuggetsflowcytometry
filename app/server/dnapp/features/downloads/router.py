"""GET /runs/{rid}/files/{name} and GET /runs/{rid}/download.zip (contract section 3.6).
CSVs go out formula-safe and JSON scrubbed of server paths, alone or zipped."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from dnapp.core.deps import WS, st
from dnapp.core.errors import Scrubber, not_found
from dnapp.core.http import attachment, safe_csv
from dnapp.core.payload import read_json
from dnapp.core.run_outputs import run_files

router = APIRouter()


def _allowed(out: Path, name: str) -> Path:
    files = run_files(out)
    if "/" in name or "\\" in name or name not in files:
        raise not_found("file")
    return out / files[name]


def _json(scrub: Scrubber, path: Path) -> str:
    """A JSON file scrubbed value by value, as the manifest's record is: in the file's text a
    Windows path has its backslashes doubled, which no root the scrubber knows matches. Written
    back as the package writes run.json."""
    return json.dumps(scrub.obj(read_json(path)), indent=2, ensure_ascii=False) + "\n"


@router.get("/runs/{rid}/files/{name}")
def get_file(rid: str, name: str, request: Request, ws: WS):
    s = st(request)
    s.runs.done(ws, rid)
    path = _allowed(s.runs.folder(ws, rid), name)
    headers = attachment(name)
    if path.suffix.lower() == ".csv":
        return Response(safe_csv(path), media_type="text/csv; charset=utf-8", headers=headers)
    if path.suffix.lower() == ".json":
        text = _json(s.scrub, path)
        return Response(text.encode("utf-8"), media_type="application/json", headers=headers)
    media = {".png": "image/png", ".txt": "text/plain; charset=utf-8"}.get(path.suffix.lower())
    return FileResponse(path, media_type=media, headers=headers)


@router.get("/runs/{rid}/download.zip")
def get_zip(rid: str, request: Request, ws: WS):
    s = st(request)
    s.runs.done(ws, rid)
    out = s.runs.folder(ws, rid)
    tmp = tempfile.TemporaryFile()  # noqa: SIM115 - chunks() below closes it once streamed
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, rel in run_files(out).items():
            path = out / rel
            if path.suffix.lower() == ".csv":
                z.writestr(name, safe_csv(path))
            elif path.suffix.lower() == ".json":
                z.writestr(name, _json(s.scrub, path))
            else:
                z.write(path, name)
    tmp.seek(0)

    def chunks():
        try:
            while block := tmp.read(1 << 16):
                yield block
        finally:
            tmp.close()

    headers = attachment(f"{rid}.zip")
    return StreamingResponse(chunks(), media_type="application/zip", headers=headers)
