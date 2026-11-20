"""create_app: the FastAPI app with the API under /api/v1, the page from DN_WEB_DIR at /, the
security headers on every response, and the pinned error shape for every failure."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, FastAPI

from dnapp.core.config import API_PREFIX, WATCHDOG_S, Settings
from dnapp.core.errors import ApiError, Scrubber, install_errors, log
from dnapp.core.http import HostCheck, SecurityHeaders, WebFiles, allowed_names
from dnapp.core.limits import Limits
from dnapp.core.state import State, disk_free
from dnapp.core.workspace import Workspaces
from dnapp.features.compare import router as compare_router
from dnapp.features.datasets import router as datasets_router
from dnapp.features.datasets.service import Datasets
from dnapp.features.demos import router as demos_router
from dnapp.features.downloads import router as downloads_router
from dnapp.features.flow import router as flow_router
from dnapp.features.flow.worker import flow_work
from dnapp.features.gates import router as gates_router
from dnapp.features.gates.service import Gates
from dnapp.features.gates.worker import gate_work
from dnapp.features.jobs import router as jobs_router
from dnapp.features.jobs.service import JobManager
from dnapp.features.livecells import router as livecells_router
from dnapp.features.livecells.service import LiveCells
from dnapp.features.livecells.worker import livecells_work
from dnapp.features.meta import router as meta_router
from dnapp.features.meta.service import app_version
from dnapp.features.plot import router as plot_router
from dnapp.features.runs import router as runs_router
from dnapp.features.runs.service import Runs
from dnapp.features.uploads import router as uploads_router
from dnapp.features.uploads.service import Uploads
from dnapp.features.workspaces import router as workspaces_router

# Each job kind and the work its worker runs (a module-level function, sent to the worker by name).
JOB_KINDS = {
    "gate": gate_work,
    "flow": flow_work,
    "livecells": livecells_work,
}


def build_state(settings: Settings, clock: Callable[[], float], free_bytes) -> State:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    roots = sorted({str(settings.data_dir), str(settings.data_dir.resolve())})
    workspaces = Workspaces(settings, clock)
    limits = Limits(settings.caps, clock)
    jobs = JobManager(settings, limits, clock, roots, JOB_KINDS)
    for ws in workspaces.all():  # local: the jobs of the last run of the server
        jobs.load(ws)
    scrub = Scrubber(roots)
    uploads = Uploads(settings, clock)
    gates = Gates(jobs, scrub)
    runs = Runs(settings, jobs, limits, scrub)
    live = LiveCells(settings, jobs, gates, scrub)
    for ws in workspaces.all():  # the sets the last run of the server cut off
        live.recover(ws)
    return State(
        settings=settings,
        clock=clock,
        free_bytes=free_bytes or disk_free,
        workspaces=workspaces,
        limits=limits,
        scrub=scrub,
        jobs=jobs,
        uploads=uploads,
        gates=gates,
        runs=runs,
        sections={
            "uploads": uploads,
            "gates": gates,
            "runs": runs,
            "jobs": jobs,
            "datasets": Datasets(),
        },
        upload_users=[gates],  # a run holds its files through its gate, which holds them
        gate_users=[runs, live],
        features={"livecells": live},
    )


async def _watchdog(state: State) -> None:
    last_sweep = time.monotonic()
    while True:
        await asyncio.sleep(WATCHDOG_S)
        try:
            state.jobs.check_timeouts()
            if time.monotonic() - last_sweep >= state.settings.caps.sweep_s:
                last_sweep = time.monotonic()
                gone = state.workspaces.sweep(state.jobs.busy)
                if gone:
                    log.info("swept %d expired workspaces", len(gone))
        except Exception:  # noqa: BLE001 - the watchdog must outlive any one bad step
            log.exception("watchdog step failed")


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], float] | None = None,
    free_bytes: Callable[[Path], int] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    hosts = allowed_names(settings)  # before any folder is made, so a bad entry changes nothing
    state = build_state(settings, clock or time.time, free_bytes)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_watchdog(state))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await asyncio.to_thread(state.jobs.shutdown)

    app = FastAPI(
        title="datanuggets app",
        version=app_version(),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.dn = state
    install_errors(app)
    for feature in (
        meta_router,
        workspaces_router,
        uploads_router,
        datasets_router,
        demos_router,
        jobs_router,
        gates_router,
        flow_router,
        livecells_router,
        runs_router,
        plot_router,
        compare_router,
        downloads_router,
    ):
        app.include_router(feature.router, prefix=API_PREFIX)

    fallback = APIRouter()

    @fallback.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def unknown(rest: str):
        raise ApiError("not_found", "No such API route.")

    app.include_router(fallback, prefix=API_PREFIX)
    app.mount("/", WebFiles(directory=settings.web_dir, html=True, check_dir=False), name="web")
    app.add_middleware(HostCheck, names=hosts)
    app.add_middleware(SecurityHeaders)  # the last one added runs first, so it heads every answer
    logging.getLogger("dnapp").setLevel(logging.INFO)
    return app
