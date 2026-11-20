"""The gates of a workspace: their records, the Gate JSON built from the gate job's gates.json, and
Gates, the GateStore other features read gates through."""

from __future__ import annotations

import shutil
from pathlib import Path

from dnapp.core.config import API_PREFIX, GATE_FIGURES
from dnapp.core.errors import Scrubber, not_found
from dnapp.core.package.colors import population_colors
from dnapp.core.package.flow import default_channels
from dnapp.core.payload import r4, read_json
from dnapp.core.protocols import JobRunner
from dnapp.core.workspace import Workspace


def gate_files(folder: Path, uploads: list[str]) -> list[dict]:
    record = read_json(folder / "gates.json")
    files = []
    for i, entry in enumerate(record["files"]):
        pops = entry["populations"]
        colors = population_colors([p["events"] for p in pops])
        files.append(
            {
                "number": int(entry["number"]),
                "upload": uploads[i] if i < len(uploads) else None,
                "name": entry["name"],
                "n_events": int(entry["n_events"]),
                "channels": [{"pnn": n, "pns": s} for n, s in zip(entry["pnn"], entry["pns"])],
                "default_channels": default_channels(entry["pnn"], entry["pns"], entry["name"]),
                "local_maxima": int(entry["local_maxima"]),
                "populations": [
                    {
                        "pop": int(p["pop"]),
                        "events": int(p["events"]),
                        "percent": r4(p["percent"]),
                        "median_fsc": r4(p["median_fsc"]),
                        "median_ssc": r4(p["median_ssc"]),
                        "peak": [int(p["peak"][0]), int(p["peak"][1])],
                        "color": colors[j],
                    }
                    for j, p in enumerate(pops)
                ],
            }
        )
    return files


def remove(ws: Workspace, gid: str) -> None:
    """Drops the gate's folder and record; the caller holds ws.lock."""
    shutil.rmtree(ws.dir("gates") / gid, ignore_errors=True)
    del ws.records("gates")[gid]
    ws.save()


class Gates:
    """The GateStore, the gates list of GET /workspace, and the gates' claim on their uploads."""

    def __init__(self, jobs: JobRunner, scrub: Scrubber):
        self.jobs, self.scrub = jobs, scrub

    def find(self, ws: Workspace, gid: str) -> dict | None:
        return ws.records("gates").get(gid)

    def record(self, ws: Workspace, gid: str) -> dict:
        rec = self.find(ws, gid)
        if rec is None:
            raise not_found("gate")
        return rec

    def status(self, ws: Workspace, rec: dict) -> str:
        return self.jobs.status(ws, rec["job"])

    def folder(self, ws: Workspace, gid: str) -> Path:
        return ws.dir("gates") / gid

    def files(self, ws: Workspace, rec: dict) -> list[dict]:
        return gate_files(self.folder(ws, rec["id"]), rec["uploads"])

    def view(self, ws: Workspace, rec: dict) -> dict:
        status = self.status(ws, rec)
        files = self.files(ws, rec) if status == "done" else []
        base = f"{API_PREFIX}/flow/gates/{rec['id']}/figures"
        return {
            "id": rec["id"],
            "status": status,
            "created": rec["created"],
            "settings": rec["settings"],
            "files": self.scrub.obj(files),
            "figures": {n.removesuffix(".png"): f"{base}/{n}" for n in GATE_FIGURES},
        }

    def listing(self, ws: Workspace) -> list[dict]:
        return [self.view(ws, g) for g in ws.records("gates").values()]

    def upload_in_use(self, ws: Workspace, uid: str) -> str | None:
        for g in ws.records("gates").values():
            if uid in g["uploads"]:
                return f"Gate {g['id']} uses this file; delete it first."
        return None
