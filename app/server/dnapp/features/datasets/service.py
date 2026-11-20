"""The dataset names of a workspace: one record per channel set in meta.json, {id, channels,
name} with the channels sorted, and Datasets, the datasets list of GET /workspace. A record says
nothing about uploads, so a name given to a set no upload has is kept, and the page leaves it
out, until the names reach DATASETS_MAX."""

from __future__ import annotations

from dnapp.core.config import DATASETS_MAX
from dnapp.core.datasets import colour_set
from dnapp.core.errors import ApiError
from dnapp.core.protocols import UploadStore
from dnapp.core.workspace import Workspace

KIND = "datasets"  # the meta.json record kind


def listing(ws: Workspace) -> list[dict]:
    return [dict(r) for r in ws.records(KIND).values()]


def set_name(ws: Workspace, channels: list[str], name: str, uploads: UploadStore) -> list[dict]:
    """Names the set of channels (sorted, each once): the set's record renamed, or a new record;
    a blank name removes the set's record. The names it leaves, read before it lets ws.lock go.
    A new record at DATASETS_MAX first removes the records of the sets no FCS upload in ws has;
    422 on name when it would still pass DATASETS_MAX, and then nothing is removed."""
    with ws.lock:
        records = ws.records(KIND)
        rec = next((r for r in records.values() if r["channels"] == channels), None)
        if not name:
            if rec is not None:
                del records[rec["id"]]
        elif rec is not None:
            rec["name"] = name
        else:
            if len(records) >= DATASETS_MAX:
                held = {tuple(colour_set(u)) for u in uploads.listing(ws) if u["kind"] == "fcs"}
                unheld = [r["id"] for r in records.values() if tuple(r["channels"]) not in held]
                if len(records) - len(unheld) >= DATASETS_MAX:
                    raise ApiError(
                        "invalid_setting",
                        f"This workspace holds {DATASETS_MAX} dataset names, the most it can; "
                        "remove one first.",
                        "name",
                    )
                for rid in unheld:
                    del records[rid]
            did = ws.next_id(KIND)
            records[did] = {"id": did, "channels": channels, "name": name}
        ws.save()
        return listing(ws)


class Datasets:
    """The datasets list of GET /workspace."""

    def listing(self, ws: Workspace) -> list[dict]:
        return listing(ws)
