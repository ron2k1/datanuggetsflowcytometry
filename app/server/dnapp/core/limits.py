"""The trial's limits: per-IP jobs pending and per hour, workspaces per hour, a kind of request
per minute (live-cells counts), the server's daily budget of job run seconds, a request's settings
against their caps, and the disk-space floor. Local mode's caps are None, which switches each one
off."""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path

from starlette.requests import Request

from dnapp.core.config import BUSY_RETRY_S, REAL_IP_HEADER, Caps, Settings
from dnapp.core.errors import ApiError

MINUTE_S = 60
HOUR_S = 3600
DAY_S = 86_400


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy:
        real = request.headers.get(REAL_IP_HEADER)
        if real:
            return real.strip()
    return request.client.host if request.client else "unknown"


def check_max(name: str, value, cap) -> None:
    """422 on name when value passes cap; a None cap or value checks nothing."""
    if cap is not None and value is not None and value > cap:
        raise ApiError(
            "invalid_setting", f"{name} is {value}; this server allows at most {cap}.", name
        )


def check_space(settings: Settings, free_bytes: Callable[[Path], int]) -> None:
    """507 when the data folder's disk is below the free-space floor."""
    floor = settings.caps.min_free_bytes
    if floor is not None and free_bytes(settings.data_dir) < floor:
        raise ApiError("out_of_space", "The server is low on disk space; try again later.")


def _retry(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, math.ceil(seconds)))}


class Limits:
    def __init__(self, caps: Caps, clock: Callable[[], float]):
        self.caps, self.clock = caps, clock
        self.lock = threading.Lock()
        self.jobs: dict[str, deque[float]] = defaultdict(deque)
        self.workspaces: dict[str, deque[float]] = defaultdict(deque)
        self.requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.budget_day = -1
        self.budget_used = 0.0

    def _window(
        self,
        log: deque[float],
        limit: int | None,
        what: str,
        span: int = HOUR_S,
        per: str = "hour",
    ) -> None:
        if limit is None:
            return
        now = self.clock()
        while log and log[0] <= now - span:
            log.popleft()
        if len(log) >= limit:
            raise ApiError(
                "rate_limited",
                f"Too many {what} from this address in the last {per}; try again later.",
                headers=_retry(log[0] + span - now),
            )

    def take_per_minute(self, key: str, ip: str, limit: int | None, what: str) -> None:
        """Counts one request of kind key from ip, or refuses it with 429 when ip sent limit of
        them in the last minute. A None limit counts nothing."""
        if limit is None:
            return
        with self.lock:
            log = self.requests[(key, ip)]
            self._window(log, limit, what, MINUTE_S, "minute")
            log.append(self.clock())

    def check_workspace(self, ip: str) -> None:
        with self.lock:
            self._window(self.workspaces[ip], self.caps.workspaces_per_ip_hour, "new workspaces")

    def note_workspace(self, ip: str) -> None:
        with self.lock:
            self.workspaces[ip].append(self.clock())

    def check_job(self, ip: str, pending: int) -> None:
        """Refuses a new job for ip with 429, or with 503 when the day's budget is spent."""
        with self.lock:
            limit = self.caps.jobs_pending_per_ip
            if limit is not None and pending >= limit:
                raise ApiError(
                    "rate_limited",
                    f"This address already has {pending} jobs queued or running; wait for one "
                    "to finish.",
                    headers=_retry(BUSY_RETRY_S),
                )
            self._window(self.jobs[ip], self.caps.jobs_per_ip_hour, "jobs")
            budget = self.caps.heavy_budget_s_per_day
            if budget is not None:
                self._roll_day()
                if self.budget_used >= budget:
                    now = self.clock()
                    raise ApiError(
                        "busy",
                        "The trial server has used its compute time for today; try again "
                        "tomorrow (UTC) or run the app locally.",
                        headers=_retry(DAY_S - now % DAY_S),
                    )

    def note_job(self, ip: str) -> None:
        with self.lock:
            self.jobs[ip].append(self.clock())

    def _roll_day(self) -> None:
        day = int(self.clock() // DAY_S)
        if day != self.budget_day:
            self.budget_day, self.budget_used = day, 0.0

    def spend(self, seconds: float) -> None:
        with self.lock:
            self._roll_day()
            self.budget_used += max(0.0, seconds)
