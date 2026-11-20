"""The runs of a workspace: their records, their job's status and result, and Runs, the RunStore
the flow feature creates runs through and the payload features read them by."""

from __future__ import annotations

import shutil
from pathlib import Path

from dnapp.core.config import Settings
from dnapp.core.errors import ApiError, Scrubber, not_found
from dnapp.core.limits import Limits
from dnapp.core.payload import read_json
from dnapp.core.protocols import ACTIVE, JobRunner
from dnapp.core.workspace import Workspace


def remove(ws: Workspace, rid: str) -> None:
    """Drops the run's folder and record; the caller holds ws.lock."""
    shutil.rmtree(ws.dir("runs") / rid, ignore_errors=True)
    del ws.records("runs")[rid]
    ws.save()


class Runs:
    """The RunStore, the runs list of GET /workspace, and a running run's claim on its gate."""

    def __init__(self, settings: Settings, jobs: JobRunner, limits: Limits, scrub: Scrubber):
        self.settings, self.jobs, self.limits, self.scrub = settings, jobs, limits, scrub

    def create(
        self,
        ws: Workspace,
        ip: str,
        kind: str,
        spec: dict,
        settings: dict,
        title: str,
        source: str,
    ) -> dict:
        with ws.lock:
            cap = self.settings.caps.runs_per_workspace
            if cap is not None and len(ws.records("runs")) >= cap:
                raise ApiError(
                    "wrong_state", f"A workspace holds at most {cap} runs; delete one first."
                )
            rid = ws.next_id("runs")
            spec = {"out": str(self.folder(ws, rid)), **spec}
            job = self.jobs.submit(ws, kind, spec, ip, run_id=rid)
            ws.records("runs")[rid] = {
                "id": rid,
                "kind": kind,
                "created": job.record["created"],
                "title": title,
                "source": source,
                "settings": settings,
                "job": job.record["id"],
            }
            ws.save()
        self.limits.note_job(ip)
        return {"job": self.jobs.view(job), "run_id": rid}

    def record(self, ws: Workspace, rid: str) -> dict:
        rec = ws.records("runs").get(rid)
        if rec is None:
            raise not_found("run")
        return rec

    def status(self, ws: Workspace, rec: dict) -> str:
        return self.jobs.status(ws, rec["job"])

    def done(self, ws: Workspace, rid: str) -> dict:
        rec = self.record(ws, rid)
        if self.status(ws, rec) != "done":
            raise ApiError("wrong_state", f"Run {rid} is not done.")
        return rec

    def folder(self, ws: Workspace, rid: str) -> Path:
        return ws.dir("runs") / rid

    def run_json(self, ws: Workspace, rid: str) -> dict:
        path = self.folder(ws, rid) / "run.json"
        return self.scrub.obj(read_json(path)) if path.is_file() else {}

    def warnings(self, ws: Workspace, rec: dict) -> list[str]:
        return list(self.jobs.info(ws, rec["job"]).get("_warnings") or [])

    def k(self, ws: Workspace, rec: dict) -> int | None:
        info = self.jobs.info(ws, rec["job"]).get("_info") or {}
        if "k" in info:
            return int(info["k"])
        k = rec["settings"].get("k")  # a legacy general run's settings have none
        return int(k) if k is not None else None

    def summary(self, ws: Workspace, rec: dict) -> dict:
        return {
            "id": rec["id"],
            "kind": rec["kind"],
            "status": self.status(ws, rec),
            "created": rec["created"],
            "title": rec["title"],
            "source": rec["source"],
            "k": self.k(ws, rec),
        }

    def listing(self, ws: Workspace) -> list[dict]:
        return [self.summary(ws, r) for r in ws.records("runs").values()]

    def gate_in_use(self, ws: Workspace, gid: str) -> str | None:
        for r in ws.records("runs").values():
            status = self.status(ws, r) if r["source"] == gid else None
            if status in ACTIVE:
                state = "still running" if status == "running" else "queued"
                return f"Run {r['id']} from this gate is {state}."
        return None

    def gate_deleted(self, ws: Workspace, gid: str) -> None:
        """Nothing to drop: a done run copied what it took from its gate, so it outlives it."""
