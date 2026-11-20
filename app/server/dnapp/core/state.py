"""The server's shared state on app.state.dn: the core services, and each feature service another
feature uses, typed by its interface. main.py builds it; features read it through core.deps."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dnapp.core.config import Settings
from dnapp.core.errors import Scrubber
from dnapp.core.limits import Limits
from dnapp.core.protocols import (
    GateStore,
    GateUser,
    JobRunner,
    RunStore,
    UploadStore,
    UploadUser,
    WorkspaceSection,
)
from dnapp.core.workspace import Workspaces


def disk_free(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free


@dataclass
class State:
    settings: Settings
    clock: Callable[[], float]
    free_bytes: Callable[[Path], int]
    workspaces: Workspaces
    limits: Limits
    scrub: Scrubber
    jobs: JobRunner
    uploads: UploadStore
    gates: GateStore
    runs: RunStore
    # GET /workspace's lists by key, in the body's order
    sections: dict[str, WorkspaceSection]
    # asked in order before an upload or a gate is deleted; the first reason refuses it
    upload_users: list[UploadUser]
    gate_users: list[GateUser]
    # a feature's own service that keeps state between requests and that no other feature
    # reads, by the feature's name; the feature reads its entry with core.deps.own
    features: dict[str, object]
