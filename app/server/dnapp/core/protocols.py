"""The interfaces features share. A feature that needs another's service asks for it by one of
these Protocols; main.py hands it the implementation (on app.state.dn, read through core.deps).
No feature imports another, so each can change behind its interface."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from dnapp.core.workspace import Workspace

ACTIVE = ("queued", "running")
FINAL = ("done", "failed", "cancelled")


# ---- jobs (implemented by features/jobs) ---------------------------------------------------


class Reporter(Protocol):
    """What a job's work function reports through, inside its worker process."""

    p: float  # the progress reported so far

    def check(self) -> None:
        """Raises when the job was asked to stop; call it between steps."""

    def log(self, text: str) -> None: ...

    def progress(self, p: float, stage: str | None, message: str | None = None) -> None: ...


# A job kind's work: (spec, reporter, out folder) -> info for the job record, run in a worker
# process. It must be a module-level function, so the pool can send it by name.
Work = Callable[[dict, Reporter, Path], "dict | None"]


class Job(Protocol):
    record: dict  # the Job JSON, plus _warnings and _info for the server's own use

    @property
    def status(self) -> str: ...


class JobRunner(Protocol):
    def submit(
        self,
        ws: Workspace,
        kind: str,
        spec: dict,
        ip: str,
        *,
        run_id: str | None = None,
        gate_id: str | None = None,
    ) -> Job:
        """Queues a job of a registered kind; 503 busy when the queue is full."""

    def get(self, ws: Workspace, jid: str) -> Job:
        """The job, or 404."""

    def status(self, ws: Workspace, jid: str) -> str:
        """The job's status; "failed" for a job this server does not know."""

    def info(self, ws: Workspace, jid: str) -> dict:
        """The job's record, {} for a job this server does not know."""

    def view(self, job: Job) -> dict:
        """The public Job JSON."""

    def of(self, ws: Workspace) -> list[Job]: ...

    def active(self, ws: Workspace) -> list[Job]: ...

    def busy(self, ws: Workspace) -> bool:
        """Whether a job of ws is running."""

    def forget(self, ws: Workspace) -> None:
        """Drops every job of ws, queued ones included."""

    def cancel(self, job: Job) -> bool:
        """Cancels a queued job and asks a running one to stop: True. A job that has already
        ended is left as it is: False."""

    def pending_for_ip(self, ip: str) -> int: ...

    def counts(self) -> dict[str, int]: ...

    def check_timeouts(self) -> None: ...

    def shutdown(self) -> None: ...

    def listing(self, ws: Workspace) -> list[dict]:
        """Every job of ws as public Job JSON, for the workspace body."""


# ---- the workspace body and its record kinds ---------------------------------------------


class WorkspaceSection(Protocol):
    """A record kind listed in GET /workspace under its key (main.py's sections table)."""

    def listing(self, ws: Workspace) -> list[dict]: ...


# ---- uploads (implemented by features/uploads) ----------------------------------------------


class UploadStore(Protocol):
    def find(self, ws: Workspace, uid: str) -> dict | None:
        """The upload's record, None when ws has none of that id."""

    def record(self, ws: Workspace, uid: str) -> dict:
        """The upload's record, or 404."""

    def path(self, ws: Workspace, rec: dict) -> Path:
        """Where the upload's file is."""

    def listing(self, ws: Workspace) -> list[dict]: ...

    async def add_copy(self, ws: Workspace, src: Path, name: str, demo_id: str) -> dict:
        """One of the server's own files (a demo) copied in as a new upload, without the
        upload size caps; its public record."""


class UploadUser(Protocol):
    """A feature that keeps an upload from being deleted while it uses the file."""

    def upload_in_use(self, ws: Workspace, uid: str) -> str | None:
        """Why uid cannot be deleted now (the 409 message), or None."""


# ---- gates (implemented by features/gates) --------------------------------------------------


class GateStore(Protocol):
    def find(self, ws: Workspace, gid: str) -> dict | None:
        """The gate's record, None when ws has none of that id."""

    def record(self, ws: Workspace, gid: str) -> dict:
        """The gate's record, or 404."""

    def status(self, ws: Workspace, rec: dict) -> str:
        """The status of the gate's job."""

    def folder(self, ws: Workspace, gid: str) -> Path:
        """Where the gate job wrote gates.json, its figures and its per-file outputs."""

    def files(self, ws: Workspace, rec: dict) -> list[dict]:
        """A done gate's files as the Gate JSON lists them (unscrubbed)."""

    def view(self, ws: Workspace, rec: dict) -> dict:
        """The public Gate JSON."""

    def listing(self, ws: Workspace) -> list[dict]: ...


class GateUser(Protocol):
    """A feature that keeps a gate from being deleted while it uses the gate, and is told when
    the gate goes."""

    def gate_in_use(self, ws: Workspace, gid: str) -> str | None:
        """Why gid cannot be deleted now (the 409 message), or None."""

    def gate_deleted(self, ws: Workspace, gid: str) -> None:
        """Drops what the feature keeps for gid. The gate's delete calls it under ws.lock, once
        every user has let the gate go and before the gate's folder is removed."""


# ---- runs (implemented by features/runs) ----------------------------------------------------


class RunStore(Protocol):
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
        """Queues a run's job of kind and records the run; {"job", "run_id"}. 409 when the
        workspace holds its most runs. The caller has checked the job room for ip."""

    def record(self, ws: Workspace, rid: str) -> dict:
        """The run's record, or 404."""

    def status(self, ws: Workspace, rec: dict) -> str: ...

    def done(self, ws: Workspace, rid: str) -> dict:
        """The run's record, 404 or 409 unless the run is done."""

    def folder(self, ws: Workspace, rid: str) -> Path:
        """The run's output folder."""

    def run_json(self, ws: Workspace, rid: str) -> dict:
        """The run's run.json, scrubbed; {} before it is written."""

    def warnings(self, ws: Workspace, rec: dict) -> list[str]:
        """The warnings the run's job reported."""

    def k(self, ws: Workspace, rec: dict) -> int | None:
        """The run's cluster count; None for a legacy general run whose job recorded none."""

    def summary(self, ws: Workspace, rec: dict) -> dict:
        """The run's line in GET /runs and the workspace body."""

    def listing(self, ws: Workspace) -> list[dict]: ...
