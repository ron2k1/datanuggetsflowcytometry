"""The live-cells sets of a workspace's gates: their records in meta.json, their JSON, the cache
that answers a repeated request with the set the gate already has, the eviction past the per-gate
cap, the last loaded sets kept in memory for counts, and LiveCells, the gates' GateUser."""

from __future__ import annotations

import shutil
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from dnapp.core.config import LIVECELLS_DIR, LIVECELLS_HISTOGRAMS, LIVECELLS_VALUES, Settings
from dnapp.core.errors import ApiError, Scrubber, not_found
from dnapp.core.package import livecells
from dnapp.core.package.errors import refusals
from dnapp.core.payload import r4, read_json
from dnapp.core.protocols import ACTIVE, GateStore, Job, JobRunner
from dnapp.core.workspace import Workspace

KIND = "livecells"  # the job kind and the meta.json record kind
CACHED = (*ACTIVE, "done")  # a set in one of these answers a request equal to its own


class _Load:
    """One set being loaded; the other askers for it wait on done."""

    def __init__(self):
        self.done = threading.Event()
        self.value: object = None
        self.ok = False


class LoadedSets:
    """The last `size` value sets loaded for counts, by (workspace, set id), the least recently
    used dropped first. A size of 0 keeps none.

    Loading is bounded too, since a set not loaded yet is read whole into memory: one load per
    set at a time (a second asker for it waits for that load and shares its values), and at
    most max(size, 1) loads of different sets at once (the rest wait for a slot)."""

    def __init__(self, size: int):
        self.size = size
        self.lock = threading.Lock()
        self.sets: OrderedDict[tuple[str, str], object] = OrderedDict()
        self.loading: dict[tuple[str, str], _Load] = {}
        self.slots = threading.BoundedSemaphore(max(size, 1))

    def get(self, key: tuple[str, str], load: Callable[[], object]) -> object:
        while True:
            with self.lock:
                if key in self.sets:
                    self.sets.move_to_end(key)
                    return self.sets[key]
                pending = self.loading.get(key)
                if pending is None:
                    mine = self.loading[key] = _Load()
            if pending is None:
                return self._load(key, load, mine)
            pending.done.wait()
            if pending.ok:
                return pending.value
            # that load raised: try again, so this asker gets the error (or the set) itself

    def _load(self, key: tuple[str, str], load: Callable[[], object], mine: _Load) -> object:
        """Runs load in a slot, outside the lock so loaded sets stay readable, and wakes the
        askers waiting for the same set."""
        try:
            with self.slots:
                found = load()
        except BaseException:
            with self.lock:
                del self.loading[key]
            mine.done.set()
            raise
        with self.lock:
            del self.loading[key]
            if self.size > 0:
                self.sets[key] = found
                self.sets.move_to_end(key)
                while len(self.sets) > self.size:
                    self.sets.popitem(last=False)
        mine.value, mine.ok = found, True
        mine.done.set()
        return found

    def drop(self, key: tuple[str, str]) -> None:
        with self.lock:
            self.sets.pop(key, None)


class LiveCells:
    def __init__(self, settings: Settings, jobs: JobRunner, gates: GateStore, scrub: Scrubber):
        self.settings, self.jobs, self.gates, self.scrub = settings, jobs, gates, scrub
        self.loaded = LoadedSets(settings.caps.livecells_memory_sets)

    # ---- records ----

    def of_gate(self, ws: Workspace, gid: str) -> list[dict]:
        """The gate's sets, oldest first."""
        sets = [r for r in ws.records(KIND).values() if r["gate_id"] == gid]
        return sorted(sets, key=lambda r: int(r["id"][1:]))

    def record(self, ws: Workspace, gid: str, lid: str) -> dict:
        """The set, or 404 for an unknown id or a set of another gate."""
        rec = ws.records(KIND).get(lid)
        if rec is None or rec["gate_id"] != gid:
            raise not_found("live-cells set")
        return rec

    def status(self, ws: Workspace, rec: dict) -> str:
        return self.jobs.status(ws, rec["job"])

    def folder(self, ws: Workspace, gid: str, lid: str) -> Path:
        return self.gates.folder(ws, gid) / LIVECELLS_DIR / lid

    def matching(self, ws: Workspace, gid: str, request: dict) -> dict | None:
        """The gate's set made from request, unless it failed or was cancelled, or was asked for
        "auto" and drawn under the earlier header rule."""
        for rec in self.of_gate(ws, gid):
            status = self.status(ws, rec)
            stale = status == "done" and self._header_rule(ws, rec)
            if rec["request"] == request and status in CACHED and not stale:
                return rec
        return None

    def _header_rule(self, ws: Workspace, rec: dict) -> bool:
        """True for a finished set asked for "auto" whose histograms are drawn on one number,
        the one the earlier header rule picked for every channel: auto now picks each channel's
        own, so that set no longer shows what the request asks for. Its job wrote no cofactors."""
        if rec["request"].get("cofactor") != "auto":
            return False
        path = self.folder(ws, rec["gate_id"], rec["id"]) / LIVECELLS_HISTOGRAMS
        try:
            return "cofactors" not in read_json(path)
        except FileNotFoundError:  # deleted with its gate since the record was read
            return False

    def create(
        self, ws: Workspace, ip: str, gid: str, request: dict, spec: dict
    ) -> tuple[dict, bool]:
        """(the set for request, whether its job is new): the gate's matching set, or a new one
        with its job queued. Past livecells_per_gate the gate's oldest finished sets go, with
        their folders; 409 when every set it holds is still queued or running. The caller has
        checked the job room, and notes a new job against the address's hour."""
        cap = self.settings.caps.livecells_per_gate
        with ws.lock:
            hit = self.matching(ws, gid, request)
            if hit is not None:
                return hit, False
            held = self.of_gate(ws, gid)
            excess = len(held) - cap + 1
            evict = [r for r in held if self.status(ws, r) not in ACTIVE][: max(excess, 0)]
            if len(evict) < excess:
                raise ApiError(
                    "wrong_state",
                    f"This gate holds {len(held)} live-cells sets and each is still loading; "
                    "wait for one to finish or cancel it.",
                )
            lid = ws.next_id(KIND)
            out = self.folder(ws, gid, lid)
            job = self.jobs.submit(ws, KIND, {**spec, "out": str(out)}, ip, gate_id=gid)
            for old in evict:  # once the new job is in: a full queue evicts nothing
                self._drop(ws, old)
            rec = {
                "id": lid,
                "gate_id": gid,
                "created": job.record["created"],
                "job": job.record["id"],
                "request": request,
            }
            ws.records(KIND)[lid] = rec
            ws.save()
        return rec, True

    def job(self, ws: Workspace, rec: dict) -> Job:
        return self.jobs.get(ws, rec["job"])

    def recover(self, ws: Workspace) -> None:
        """At boot, once the jobs are loaded: removes every set folder that is not a done set's.
        A job the server's stop cut off (a crash or a kill, which skip the job's own cleanup)
        leaves its folder half written, and its job is failed by now; a folder with no record
        is a set whose job started just before the server stopped, before the set was saved.
        Neither is ever read (a set is read only when done), but both hold disk."""
        with ws.lock:
            for gid in ws.records("gates"):
                sets = self.gates.folder(ws, gid) / LIVECELLS_DIR
                if not sets.is_dir():
                    continue
                done = {r["id"] for r in self.of_gate(ws, gid) if self.status(ws, r) == "done"}
                for folder in sets.iterdir():
                    if folder.name not in done:
                        shutil.rmtree(folder, ignore_errors=True)

    def _drop(self, ws: Workspace, rec: dict) -> None:
        """Removes a set's folder, record and loaded values; the caller holds ws.lock and saves."""
        shutil.rmtree(self.folder(ws, rec["gate_id"], rec["id"]), ignore_errors=True)
        del ws.records(KIND)[rec["id"]]
        self.loaded.drop((ws.id, rec["id"]))

    # ---- JSON ----

    def summary(self, ws: Workspace, rec: dict) -> dict:
        """A set's line in GET /flow/gates/{gid}/livecells."""
        return {
            "id": rec["id"],
            "status": self.status(ws, rec),
            "created": rec["created"],
            "request": rec["request"],
        }

    def view(self, ws: Workspace, rec: dict) -> dict:
        """The set's JSON. histograms is null until the job is done; its lo, hi and edges go out
        unrounded, so the bars stand on the edges the package counted with, and so do the auto
        cofactors per channel, with which a client turns t back into raw values. A set drawn on
        one number has it rounded, beside how it was chosen and range: the widest marker channel
        range the earlier header rule picked an auto number by, unrounded, or None for a number
        set. A set made before the cofactor could be auto was asked for a number, so it reads as
        set, with no range."""
        status = self.status(ws, rec)
        histograms = None
        if status == "done":
            folder = self.folder(ws, rec["gate_id"], rec["id"])
            histograms = read_json(folder / LIVECELLS_HISTOGRAMS)
            how = {"cofactor_from": histograms.pop("cofactor_from", "set")}
            if "cofactors" in histograms:  # auto per channel, as the job wrote it
                histograms = how | histograms
            else:
                how["range"] = histograms.pop("range", None)
                histograms = {"cofactor": r4(histograms.pop("cofactor")), **how, **histograms}
        return {
            "id": rec["id"],
            "gate_id": rec["gate_id"],
            "status": status,
            "created": rec["created"],
            "job": rec["job"],
            "request": rec["request"],
            "histograms": self.scrub.obj(histograms),
        }

    # ---- counts ----

    def counts(self, ws: Workspace, rec: dict, specs: list[str]) -> dict:
        """count_kept on the set's saved values, which the last few counts keep in memory. It
        reads values.npz and never an FCS file."""
        path = self.folder(ws, rec["gate_id"], rec["id"]) / LIVECELLS_VALUES
        try:
            kept = self.loaded.get((ws.id, rec["id"]), lambda: livecells.load(path))
        except FileNotFoundError:  # deleted with its gate since the record was read
            raise not_found("live-cells set") from None
        with refusals():
            return self.scrub.obj(livecells.count(kept, specs))

    # ---- GateUser ----

    def gate_in_use(self, ws: Workspace, gid: str) -> str | None:
        for rec in self.of_gate(ws, gid):
            if self.status(ws, rec) in ACTIVE:
                return (
                    f"Live-cells set {rec['id']} of this gate is still loading; "
                    f"cancel job {rec['job']} first."
                )
        return None

    def gate_deleted(self, ws: Workspace, gid: str) -> None:
        for rec in self.of_gate(ws, gid):
            self._drop(ws, rec)
        ws.save()
