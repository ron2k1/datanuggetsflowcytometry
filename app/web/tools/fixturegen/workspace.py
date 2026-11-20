"""GET /workspace (trial and local): everything the other parts wrote, with its expiry times. No
dataset has a given name, so datasets is []."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .common import write_json


def write_workspace(
    out: Path, t_ws: str, t_last: str, uploads: list, gate: dict, summaries: list, jobs: list
) -> None:
    """Writes both workspaces."""
    t0 = datetime.fromisoformat(t_ws)
    t1 = datetime.fromisoformat(t_last)

    def stamp(t):
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")

    ws = {
        "created": t_ws,
        "uploads": uploads,
        "gates": [gate],
        "runs": summaries,
        "jobs": jobs,
        "datasets": [],
    }
    write_json(
        out / "GET__workspace.json",
        {
            "mode": "trial",
            **ws,
            "idle_expires_at": stamp(t1 + timedelta(seconds=21_600)),
            "expires_at": stamp(t0 + timedelta(seconds=86_400)),
        },
    )
    write_json(
        out / "GET__workspace.local.json",
        {"mode": "local", **ws, "idle_expires_at": None, "expires_at": None},
    )
