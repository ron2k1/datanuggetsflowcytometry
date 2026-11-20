"""Workspaces: one folder per trial cookie (or the single local one) holding meta.json, uploads/,
gates/, runs/ and jobs/. meta.json keeps the uploads, gates, runs, live-cells and dataset-name
records and the id counters; jobs keep their own JSON files (features/jobs). A live-cells set's
files sit in its gate's folder, so it has no folder of its own here, and a dataset name has no
files at all."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from dnapp.core.config import (
    COOKIE_TOKEN_BYTES,
    LOCAL_DIR,
    LOCAL_WORKSPACE,
    SAFE_NAME_MAX,
    TRIAL_DIR,
    Settings,
)

META = "meta.json"
SUBDIRS = ("uploads", "gates", "runs", "jobs")
# a meta.json from before livecells or datasets reads each as {}
KINDS = ("uploads", "gates", "runs", "livecells", "datasets")
PREFIX = {"uploads": "u", "gates": "g", "runs": "r", "jobs": "j", "livecells": "l", "datasets": "d"}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def iso(t: float | None) -> str | None:
    """Epoch seconds as an ISO 8601 UTC string."""
    if t is None:
        return None
    return datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_name(name: str, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """A file name of [A-Za-z0-9._-], at most SAFE_NAME_MAX characters, not starting with . or -,
    made unique against taken with -2, -3 before the extension."""
    base = _UNSAFE.sub("_", Path(name.replace("\\", "/")).name).lstrip(".-")
    if not base or base.strip("_") == "":
        base = "file"
    stem, dot, ext = base.rpartition(".")
    if not dot or not stem:
        stem, ext = base, ""
    ext = ("." + ext) if ext else ""
    stem = stem[: SAFE_NAME_MAX - len(ext)] or "file"
    candidate, n = stem + ext, 1
    while candidate in taken:
        n += 1
        tail = f"-{n}"
        candidate = stem[: SAFE_NAME_MAX - len(ext) - len(tail)] + tail + ext
    return candidate


def write_json(path: Path, record) -> None:
    """record as UTF-8 JSON, written to a temporary file first and moved into place."""
    tmp = path.with_name(path.name + f".{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(record, indent=1, allow_nan=False), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: a reader holds the old file for a moment
            time.sleep(0.01 * (attempt + 1))
    os.replace(tmp, path)


def folder_bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class Workspace:
    """One workspace's folder and records. Every change holds lock and ends with save(), and a
    request that goes over a kind's records holds it too, since other requests' threads change
    them."""

    def __init__(self, wid: str, path: Path, meta: dict):
        self.id, self.path, self.meta = wid, path, meta
        self.lock = threading.RLock()

    @property
    def created(self) -> float:
        return self.meta["created"]

    @property
    def last_seen(self) -> float:
        return self.meta["last_seen"]

    def records(self, kind: str) -> dict[str, dict]:
        return self.meta[kind]

    def next_id(self, kind: str) -> str:
        with self.lock:
            n = self.meta["counters"].get(kind, 0) + 1
            self.meta["counters"][kind] = n
            return f"{PREFIX[kind]}{n}"

    def save(self) -> None:
        with self.lock:
            write_json(self.path / META, self.meta)

    def touch(self, now: float) -> None:
        with self.lock:
            self.meta["last_seen"] = now

    def dir(self, kind: str) -> Path:
        return self.path / kind

    def bytes(self) -> int:
        return folder_bytes(self.path)

    def reset(self) -> None:
        """Empties the workspace: every folder and record goes. The id counters stay, so an id
        is never used twice."""
        with self.lock:
            for kind in SUBDIRS:
                shutil.rmtree(self.dir(kind), ignore_errors=True)
                self.dir(kind).mkdir(parents=True, exist_ok=True)
            for kind in KINDS:
                self.records(kind).clear()
            self.save()


class Workspaces:
    """Every workspace of this server. Trial: created per cookie under DATA_DIR/trial, which is
    wiped at boot, and expired by idle time and age. Local: the one workspace DATA_DIR/ws/local,
    which survives restarts. The two folders never overlap, so neither mode's start touches the
    other's files."""

    def __init__(self, settings: Settings, clock: Callable[[], float]):
        self.settings, self.clock = settings, clock
        self.root = settings.data_dir / (TRIAL_DIR if settings.trial else LOCAL_DIR)
        self.lock = threading.RLock()
        self.by_id: dict[str, Workspace] = {}
        self.expired_ids: dict[str, float] = {}  # tombstones, so a swept cookie gets 410
        if settings.trial and self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        if not settings.trial:
            self.by_id[LOCAL_WORKSPACE] = self._open_or_create(LOCAL_WORKSPACE)

    # ---- identity ----

    @staticmethod
    def id_for_token(token: str) -> str:
        """The folder name for a cookie token, so the secret itself is not written to disk."""
        return hashlib.sha256(token.encode()).hexdigest()[:32]

    def local(self) -> Workspace:
        return self.by_id[LOCAL_WORKSPACE]

    def _open_or_create(self, wid: str) -> Workspace:
        path = self.root / wid
        meta_path = path / META
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            now = self.clock()
            meta = {"created": now, "last_seen": now, "counters": {}}
        for kind in KINDS:
            meta.setdefault(kind, {})
        for sub in SUBDIRS:
            (path / sub).mkdir(parents=True, exist_ok=True)
        ws = Workspace(wid, path, meta)
        ws.save()
        return ws

    def create(self) -> tuple[str, Workspace]:
        """A new trial workspace and its cookie token."""
        token = secrets.token_urlsafe(COOKIE_TOKEN_BYTES)
        wid = self.id_for_token(token)
        with self.lock:
            ws = self._open_or_create(wid)
            self.by_id[wid] = ws
        return token, ws

    def lookup(self, token: str | None) -> tuple[str, Workspace | None]:
        """("ok", ws), ("expired", ws or None) or ("unknown", None) for a cookie token."""
        if not token:
            return "unknown", None
        wid = self.id_for_token(token)
        with self.lock:
            ws = self.by_id.get(wid)
            if ws is None:
                return ("expired", None) if wid in self.expired_ids else ("unknown", None)
            if self.is_expired(ws):
                return "expired", ws
            return "ok", ws

    # ---- expiry ----

    def idle_expires_at(self, ws: Workspace) -> float | None:
        ttl = self.settings.caps.ttl_idle_s
        return None if ttl is None else ws.last_seen + ttl

    def expires_at(self, ws: Workspace) -> float | None:
        ttl = self.settings.caps.ttl_max_s
        return None if ttl is None else ws.created + ttl

    def is_expired(self, ws: Workspace) -> bool:
        if not self.settings.trial:
            return False
        now = self.clock()
        ends = [t for t in (self.idle_expires_at(ws), self.expires_at(ws)) if t is not None]
        return any(now >= t for t in ends)

    def remove(self, ws: Workspace) -> None:
        """Deletes a trial workspace's folder and remembers its id as expired."""
        with self.lock:
            self.by_id.pop(ws.id, None)
            self.expired_ids[ws.id] = self.clock()
        shutil.rmtree(ws.path, ignore_errors=True)

    def sweep(self, busy: Callable[[Workspace], bool]) -> list[str]:
        """Deletes every expired workspace whose jobs are not running; their ids."""
        if not self.settings.trial:
            return []
        gone = []
        with self.lock:
            candidates = [ws for ws in self.by_id.values() if self.is_expired(ws)]
        for ws in candidates:
            if not busy(ws):
                self.remove(ws)
                gone.append(ws.id)
        cutoff = self.clock() - 2 * (self.settings.caps.ttl_max_s or 0)
        with self.lock:
            for wid, t in list(self.expired_ids.items()):
                if t < cutoff:
                    del self.expired_ids[wid]
        return gone

    def all(self) -> list[Workspace]:
        with self.lock:
            return list(self.by_id.values())
