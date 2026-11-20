"""The uploads of a workspace: their records in meta.json, their public JSON, and Uploads, the
UploadStore other features read uploads through."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from dnapp.core.config import Settings
from dnapp.core.errors import not_found
from dnapp.core.workspace import Workspace, iso, safe_name
from dnapp.features.uploads.describe import describe

# a CSV upload's record in a legacy workspace also holds a preview, which is no longer sent
PUBLIC_UPLOAD = ("id", "name", "kind", "bytes", "rows", "columns", "created", "demo")


def make_record(uid: str, path: Path, kind: str, info: dict, now: float, demo: str | None) -> dict:
    return {
        "id": uid,
        "name": path.name,
        "kind": kind,
        "bytes": path.stat().st_size,
        **info,
        "created": iso(now),
        "demo": demo,
        "path": f"uploads/{uid}/{path.name}",
    }


def public(record: dict) -> dict:
    return {k: record[k] for k in PUBLIC_UPLOAD}


def copy_into(src: Path, folder: Path, name: str) -> Path:
    folder.mkdir(parents=True)
    dest = folder / name
    shutil.copyfile(src, dest)
    return dest


def no_size_caps(settings: Settings) -> Settings:
    """Demo files are the server's own, so the upload size caps do not apply to them."""
    return replace(settings, caps=replace(settings.caps, fcs_events=None))


async def keep(
    ws: Workspace,
    uid: str,
    path: Path,
    kind: str,
    settings: Settings,
    clock: Callable[[], float],
    demo: str | None,
) -> dict:
    """A stored file described and recorded as upload uid; its public record. A file that cannot
    be described is removed with its folder."""
    try:
        info = await describe(path, settings)
    except BaseException:
        shutil.rmtree(path.parent, ignore_errors=True)
        raise
    rec = make_record(uid, path, kind, info, clock(), demo)
    with ws.lock:
        ws.records("uploads")[uid] = rec
        ws.save()
    return public(rec)


def remove(ws: Workspace, rec: dict) -> None:
    """Drops the upload's folder and record; the caller holds ws.lock."""
    shutil.rmtree((ws.path / rec["path"]).parent, ignore_errors=True)
    del ws.records("uploads")[rec["id"]]
    ws.save()


class Uploads:
    """The UploadStore, and the uploads list of GET /workspace."""

    def __init__(self, settings: Settings, clock: Callable[[], float]):
        self.settings, self.clock = settings, clock

    def find(self, ws: Workspace, uid: str) -> dict | None:
        return ws.records("uploads").get(uid)

    def record(self, ws: Workspace, uid: str) -> dict:
        rec = self.find(ws, uid)
        if rec is None:
            raise not_found("upload")
        return rec

    def path(self, ws: Workspace, rec: dict) -> Path:
        return ws.path / rec["path"]

    def listing(self, ws: Workspace) -> list[dict]:
        return [public(u) for u in ws.records("uploads").values()]

    async def add_copy(self, ws: Workspace, src: Path, name: str, demo_id: str) -> dict:
        uid = ws.next_id("uploads")
        with ws.lock:
            taken = {u["name"] for u in ws.records("uploads").values()}
            path = copy_into(src, ws.dir("uploads") / uid, safe_name(name, taken))
        return await keep(ws, uid, path, "fcs", no_size_caps(self.settings), self.clock, demo_id)
