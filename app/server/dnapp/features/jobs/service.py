"""Jobs: a queue the server owns, and a spawn ProcessPoolExecutor that runs at most `workers` of
them at once, so the event loop stays free. A job is submitted to the pool only when a worker is
idle, so a queued job is never inside the pool and cancelling it is immediate. Each job's record
is kept in memory and in jobs/<jid>.json; its progress and log come from the files the worker
appends to (worker.py). JobManager is the JobRunner every feature submits through; which work
each kind runs is the table main.py passes in."""

from __future__ import annotations

import contextlib
import json
import logging
import multiprocessing
import shutil
import threading
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from dnapp.core.config import (
    BUSY_RETRY_S,
    CANCEL_GRACE_S,
    LOG_TAIL,
    RESTART_MESSAGE,
    TIMEOUT_MESSAGE,
    WORKER_DIED_MESSAGE,
    Settings,
)
from dnapp.core.errors import ApiError, internal_ref
from dnapp.core.limits import Limits
from dnapp.core.protocols import ACTIVE, FINAL, Work
from dnapp.core.workspace import Workspace, iso, write_json
from dnapp.features.jobs.worker import init_worker, run_job

log = logging.getLogger("dnapp.jobs")

PUBLIC_JOB = (
    "id", "kind", "status", "progress", "stage", "message", "log_tail", "created", "started",
    "finished", "run_id", "gate_id", "error",
)  # fmt: skip


class Job:
    def __init__(self, ws: Workspace, record: dict, spec: dict | None, ip: str | None):
        self.ws, self.record, self.spec, self.ip = ws, record, spec, ip
        self.future: Future | None = None
        self.started_at: float | None = None
        self.cancel_requested_at: float | None = None
        self.timed_out = False

    @property
    def key(self) -> tuple[str, str]:
        return self.ws.id, self.record["id"]

    @property
    def status(self) -> str:
        return self.record["status"]

    def path(self, suffix: str) -> Path:
        return self.ws.dir("jobs") / f"{self.record['id']}{suffix}"


def _kill_workers(ex: ProcessPoolExecutor) -> None:
    """Kills the pool's own worker processes by their PIDs; one already gone is skipped."""
    for p in list(getattr(ex, "_processes", {}).values()):
        with contextlib.suppress(OSError, ValueError, AttributeError):
            p.kill()


class JobManager:
    def __init__(
        self,
        settings: Settings,
        limits: Limits,
        clock: Callable[[], float],
        roots: list[str],
        kinds: Mapping[str, Work],
    ):
        self.settings, self.limits, self.clock, self.roots = settings, limits, clock, roots
        self.kinds = dict(kinds)
        self.lock = threading.RLock()
        self.jobs: dict[tuple[str, str], Job] = {}
        self.queue: deque[tuple[str, str]] = deque()
        self.executor: ProcessPoolExecutor | None = None
        self.closed = False

    # ---- pool ----

    def _pool(self) -> ProcessPoolExecutor:
        if self.executor is None:
            self.executor = ProcessPoolExecutor(
                max_workers=self.settings.workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=init_worker,
            )
        return self.executor

    def _kill_pool(self) -> None:
        """Stops this pool's own worker processes, by their PIDs, and drops the pool."""
        ex, self.executor = self.executor, None
        if ex is None:
            return
        _kill_workers(ex)
        ex.shutdown(wait=False, cancel_futures=True)

    def shutdown(self) -> None:
        with self.lock:
            self.closed = True
            for job in self.jobs.values():
                if job.status == "running":
                    job.path(".cancel").touch(exist_ok=True)
        ex, self.executor = self.executor, None
        if ex is not None:
            _kill_workers(ex)
            ex.shutdown(wait=True, cancel_futures=True)

    # ---- records ----

    def _save(self, job: Job) -> None:
        try:
            write_json(job.path(".json"), job.record)
        except OSError:  # the workspace was deleted under it
            pass

    def load(self, ws: Workspace) -> None:
        """Reads a workspace's job files at boot. A job that was queued or running when the
        server stopped did not finish: it becomes failed."""
        for path in sorted(ws.dir("jobs").glob("j*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            job = Job(ws, record, None, None)
            if record.get("status") in ACTIVE:
                record.update(
                    status="failed",
                    finished=iso(self.clock()),
                    error={"code": "internal", "message": RESTART_MESSAGE, "param": None},
                )
                self._save(job)
            self.jobs[job.key] = job

    def get(self, ws: Workspace, jid: str) -> Job:
        job = self.jobs.get((ws.id, jid))
        if job is None:
            raise ApiError("not_found", "No job with that id.")
        return job

    def status(self, ws: Workspace, jid: str) -> str:
        job = self.jobs.get((ws.id, jid))
        return job.status if job else "failed"

    def info(self, ws: Workspace, jid: str) -> dict:
        job = self.jobs.get((ws.id, jid))
        return job.record if job else {}

    def listing(self, ws: Workspace) -> list[dict]:
        return [self.view(j) for j in self.of(ws)]

    def of(self, ws: Workspace) -> list[Job]:
        with self.lock:
            jobs = [j for (w, _), j in self.jobs.items() if w == ws.id]
        return sorted(jobs, key=lambda j: int(j.record["id"][1:]))

    def busy(self, ws: Workspace) -> bool:
        return any(j.status == "running" for j in self.of(ws))

    def active(self, ws: Workspace) -> list[Job]:
        return [j for j in self.of(ws) if j.status in ACTIVE]

    def pending_for_ip(self, ip: str) -> int:
        with self.lock:
            return sum(1 for j in self.jobs.values() if j.ip == ip and j.status in ACTIVE)

    def counts(self) -> dict[str, int]:
        with self.lock:
            running = sum(1 for j in self.jobs.values() if j.status == "running")
            return {"running": running, "queued": len(self.queue)}

    def forget(self, ws: Workspace) -> None:
        with self.lock:
            for key in [k for k in self.jobs if k[0] == ws.id]:
                job = self.jobs.pop(key)
                if key in self.queue:
                    self.queue.remove(key)
                job.record["status"] = "cancelled"

    # ---- lifecycle ----

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
        with self.lock:
            cap = self.settings.caps.queue_max
            if cap is not None and len(self.queue) >= cap:
                raise ApiError(
                    "busy",
                    "The server's job queue is full; try again in a minute.",
                    headers={"Retry-After": str(BUSY_RETRY_S)},
                )
            jid = ws.next_id("jobs")
            record = {
                "id": jid,
                "kind": kind,
                "status": "queued",
                "progress": 0.0,
                "stage": None,
                "message": None,
                "log_tail": [],
                "created": iso(self.clock()),
                "started": None,
                "finished": None,
                "run_id": run_id,
                "gate_id": gate_id,
                "error": None,
                "_warnings": [],
                "_info": {},
            }
            full = dict(spec) | {
                "jid": jid,
                "jobs_dir": str(ws.dir("jobs")),
                "roots": self.roots,
            }
            job = Job(ws, record, full, ip)
            self.jobs[job.key] = job
            self.queue.append(job.key)
            ws.save()
            self._save(job)
        self._dispatch()
        return job

    def _running(self) -> int:
        return sum(1 for j in self.jobs.values() if j.status == "running")

    def _dispatch(self) -> None:
        with self.lock:
            while not self.closed and self.queue and self._running() < self.settings.workers:
                key = self.queue.popleft()
                job = self.jobs.get(key)
                if job is None or job.status != "queued":
                    continue
                kind = job.record["kind"]
                try:
                    fut = self._pool().submit(run_job, kind, self.kinds[kind], job.spec)
                except (BrokenProcessPool, RuntimeError):
                    self._kill_pool()
                    fut = self._pool().submit(run_job, kind, self.kinds[kind], job.spec)
                job.future = fut
                job.started_at = self.clock()
                job.record.update(status="running", started=iso(job.started_at))
                self._save(job)
                fut.add_done_callback(lambda f, key=key: self._finished(key, f))

    def _finished(self, key: tuple[str, str], fut: Future) -> None:
        with self.lock:
            job = self.jobs.get(key)
            if job is None:  # its workspace was deleted
                return
            now = self.clock()
            try:
                result = fut.result()
            except BrokenProcessPool:
                # the server stopping kills its workers too; that is not the job running out
                code, message = (
                    ("internal", RESTART_MESSAGE)
                    if self.closed
                    else ("out_of_memory", WORKER_DIED_MESSAGE)
                )
                result = {
                    "status": "failed",
                    "error": {"code": code, "message": message, "param": None},
                }
                shutil.rmtree(job.spec["out"], ignore_errors=True)
                if self._broken():
                    self.executor = None
            except Exception as e:  # noqa: BLE001 - pickling and the like: the job could not run
                ref = internal_ref()
                log.error("job %s failed outside its worker (ref %s): %r", key, ref, e)
                result = {
                    "status": "failed",
                    "error": {
                        "code": "internal",
                        "message": f"Something went wrong (ref {ref})",
                        "param": None,
                    },
                }
            if job.timed_out:
                limit = self.settings.caps.job_timeout_s
                result["status"] = "failed"
                result["error"] = {
                    "code": "timeout",
                    "message": TIMEOUT_MESSAGE.format(s=limit),
                    "param": None,
                }
                shutil.rmtree(job.spec["out"], ignore_errors=True)
            if result.get("detail"):
                log.error(
                    "job %s/%s: %s\n%s",
                    key[0],
                    key[1],
                    result["error"]["message"],
                    result["detail"],
                )
            status = result["status"]
            job.record.update(
                status=status,
                finished=iso(now),
                error=result.get("error"),
                _warnings=result.get("warnings", []),
                _info=result.get("info", {}),
            )
            last = self._progress(job)
            job.record.update(last)
            if status == "done":
                job.record.update(progress=1.0, stage="done", message="Done")
            if job.started_at is not None:
                self.limits.spend(now - job.started_at)
            job.record["log_tail"] = self._tail(job)
            self._save(job)
        threading.Thread(target=self._dispatch, daemon=True).start()

    def _broken(self) -> bool:
        ex = self.executor
        return ex is None or getattr(ex, "_broken", False)

    def cancel(self, job: Job) -> bool:
        """Cancels a queued job at once and asks a running one to stop: True. A job that has
        already ended is left as it is, record and outputs: False. A client's list is a poll
        behind, so its cancel can cross the job's end; that is not an error."""
        with self.lock:
            if job.status in FINAL:
                return False
            if job.status == "queued":
                if job.key in self.queue:
                    self.queue.remove(job.key)
                job.record.update(
                    status="cancelled",
                    finished=iso(self.clock()),
                    error={"code": "cancelled", "message": "The job was cancelled.", "param": None},
                )
                self._save(job)
                return True
            job.cancel_requested_at = self.clock()
            job.path(".cancel").touch(exist_ok=True)
            return True

    def check_timeouts(self) -> None:
        """Asks an over-time job to stop, and kills the pool when it has not after a grace."""
        limit = self.settings.caps.job_timeout_s
        if limit is None:
            return
        kill = False
        with self.lock:
            now = self.clock()
            for job in self.jobs.values():
                if job.status != "running" or job.started_at is None:
                    continue
                if now - job.started_at > limit:
                    if not job.timed_out:
                        job.timed_out = True
                        job.cancel_requested_at = now
                        job.path(".cancel").touch(exist_ok=True)
                    elif now - job.cancel_requested_at > CANCEL_GRACE_S:
                        kill = True
            if kill:
                log.warning(
                    "a job passed its time limit and ignored the stop request; killing the pool"
                )
                self._kill_pool()

    # ---- views ----

    def _progress(self, job: Job) -> dict:
        try:
            lines = job.path(".progress").read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # a line being written
            p = max(float(rec.get("p", 0.0)), float(job.record.get("progress") or 0.0))
            return {
                "progress": min(p, 0.99),
                "stage": rec.get("stage"),
                "message": rec.get("message"),
            }
        return {}

    def _tail(self, job: Job) -> list[str]:
        try:
            text = job.path(".log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return text.splitlines()[-LOG_TAIL:]

    def view(self, job: Job) -> dict:
        with self.lock:
            rec = dict(job.record)
            if job.status == "running":
                rec.update(self._progress(job))
                job.record["progress"] = rec.get("progress", rec["progress"])
            if job.status != "queued":
                rec["log_tail"] = self._tail(job)
        return {k: rec[k] for k in PUBLIC_JOB}
