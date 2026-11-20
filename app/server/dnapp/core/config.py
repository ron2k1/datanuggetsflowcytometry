"""Every cap, default, path and environment name the app uses, in one place. Settings.from_env()
reads the environment once; nothing else reads os.environ."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]  # app/server/dnapp/core/config.py -> the repository

MODES = ("local", "trial")
API_PREFIX = "/api/v1"
LOCAL_WORKSPACE = "local"
# under DATA_DIR: local mode's one workspace is ws/local and survives restarts, while trial mode
# keeps its workspaces in trial/ and empties that folder at every start, so a trial start on the
# same volume never touches local mode's files
LOCAL_DIR = "ws"
TRIAL_DIR = "trial"
COOKIE_NAME = "dn_ws"
COOKIE_PATH = "/api"
COOKIE_TOKEN_BYTES = 16  # secrets.token_urlsafe(16)

# environment names
ENV_MODE = "DN_MODE"
ENV_DATA_DIR = "DN_DATA_DIR"
ENV_WEB_DIR = "DN_WEB_DIR"
ENV_DEMO_DIR = "DN_DEMO_DIR"
ENV_HOST = "HOST"
ENV_PORT = "PORT"
ENV_WORKERS = "DN_WORKERS"
ENV_JOBS = "DN_JOBS"
ENV_COOKIE_SECURE = "DN_COOKIE_SECURE"
ENV_TRUST_PROXY = "DN_TRUST_PROXY"
ENV_DOCKER_COMMAND = "DN_DOCKER_COMMAND"
ENV_ALLOWED_HOSTS = "DN_ALLOWED_HOSTS"

# the Host names the app answers. Local mode has no login, so it answers the loopback names and
# what DN_ALLOWED_HOSTS lists, and a page on another site that points its own name at this
# computer (DNS rebinding) gets a 400. Trial mode answers any name until the list names some.
# The loopback names stay allowed in both modes, so the image's health check keeps passing
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]")
ANY_HOST = "*"
INVALID_HOST_MESSAGE = (
    "This server does not answer for the name in the Host header. Open it at 127.0.0.1 or "
    f"localhost, or add the name to {ENV_ALLOWED_HOSTS}."
)

# defaults
DEFAULT_MODE = "local"
DEFAULT_DATA_DIR = REPO / "tmp" / "appdata"
DEFAULT_WEB_DIR = REPO / "app" / "web"
DEFAULT_DEMO_DIR = REPO / "app" / "demo"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
LOCAL_WORKERS_MAX = 2  # local: min(2, cpu count)
TRIAL_WORKERS = 1
TRIAL_JOBS = 1  # create_dn n_jobs / --jobs in trial
LOCAL_JOBS = -1
# the published image, and the repository whose v<version> tag each image is built from. "Run it
# locally" names the running build's version in both commands, so either one starts this app
IMAGE = "ghcr.io/ron2k1/datanuggets-flow"
SOURCE_REPO = "https://github.com/ron2k1/datanuggetsflowcytometry.git"
SOURCE_IMAGE = "datanuggets-flow"  # the name a build from the source gives its image
RUN_COMMAND = "docker run --rm -p 127.0.0.1:8000:8000 -v datanuggets-data:/data {image}"
BUILD_COMMAND = "docker build -t {image} {repo}#v{version}"
STORAGE_NOTE = {
    "trial": "Files stay in a temporary workspace and are deleted within 24 hours. "
    "Do not upload identifiable patient data.",
    "local": "Files stay on this computer.",
}
REAL_IP_HEADER = "x-real-ip"

# payloads
SIG_DIGITS = 4  # floats in payloads are rounded to 4 significant digits
MAX_PCS = 5  # plot payload PCs: min(5, p)
LOG_TAIL = 50  # Job.log_tail lines
SAFE_NAME_MAX = 100
FCS_MAGIC = (b"FCS2.0", b"FCS3.0", b"FCS3.1")
# every upload's kind: an FCS file, known by its header (FCS_MAGIC) whatever its name, since some
# instruments name theirs otherwise (a FACSCalibur's .B08, a .LMD)
UPLOAD_KIND = "fcs"
CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
GATE_FIGURES = ("local_maxima.png", "gates.png")

# dataset names (POST /datasets), in both modes. Each record holds its channel list, and meta.json
# is written whole, with \u escapes, on every change. Without DATASET_CHANNELS_BYTES, 100 records
# of 512 channels of 100 characters past U+FFFF came to 60 MB; with it, the datasets reach 1.9 MB
# of meta.json at most. Fifty channels named like 202's take under 2,000 bytes.
DATASET_NAME_MAX = 60
DATASET_CHANNELS_MAX = 512
DATASET_CHANNEL_CHARS = 100  # one channel name
DATASET_CHANNELS_BYTES = 16_000  # one channel list, as json.dumps writes it
DATASETS_MAX = 100  # name records per workspace; at the cap, those of sets no upload has go

# job bookkeeping
WATCHDOG_S = 2.0  # how often the timeout and sweep task wakes
CANCEL_GRACE_S = 5.0  # after a cooperative cancel request, before a timeout kills the pool
BUSY_RETRY_S = 30  # Retry-After when the queue is full or an address has too many jobs pending
RESTART_MESSAGE = "The server restarted during this job."
WORKER_DIED_MESSAGE = (
    "The worker process stopped unexpectedly, usually because it ran out of memory."
)
TIMEOUT_MESSAGE = "The job ran longer than the {s} second limit and was stopped."

# a job's progress bar: where each kind's steps put it (the worker never reports 1.0; done does)
PROGRESS_START = 0.02
GATE_SHARE = 0.9  # the gate files' part of a gate job's bar; its figures take the rest
# the default channels' check for values that aren't numbers moves the bar from PROGRESS_START to
# "select", a step per file read (channels sent by name make no such pass); the auto cofactor's
# pass over the files moves it from "select" to "cofactor", a step per file read (a set cofactor
# makes no such pass), then the Scale stage's pass from "transform" to
# "scale", and the nuggets start from there. The cofactor's pass reads the same files and does
# less with them (about 40% of the Scale pass's time on four FlowCAP files), so its band is the
# narrower one
FLOW_STEPS = {"select": 0.05, "cofactor": 0.08, "transform": 0.08, "scale": 0.15,
              "nuggets_from": 0.15, "nuggets_to": 0.65, "cluster": 0.75}  # fmt: skip
FLOW_FIGURES = 0.95
FLOW_RECORD = 0.98
LIVECELLS_SHARE = 0.8  # a live-cells job's bar once the kept cells' values are saved

# a live-cells set's folder, gates/<gid>/livecells/<lid>, and the files its job writes there
LIVECELLS_DIR = "livecells"
LIVECELLS_REQUEST = "request.json"
LIVECELLS_VALUES = "values.npz"
LIVECELLS_HISTOGRAMS = "histograms.json"

KB = 1_000
MB = 1_000_000
GB = 1_000_000_000


@dataclass(frozen=True)
class Caps:
    """The trial caps (section 4 of the contract, and section 2.4 of its live-cells amendment).
    The local values switch most of them off."""

    upload_fcs_bytes: int | None = 200 * MB
    workspace_bytes: int | None = 1 * GB
    fcs_events: int | None = 3_000_000
    fcs_files_per_gate: int | None = 8
    k_max: int = 100
    dn_num1_max: int | None = 10_000
    dn_num2_max: int | None = 2_000
    pooled_nuggets_max: int | None = 8_000
    cells_per_file_max: int = 2_000
    cells_max_total: int = 50_000
    runs_per_workspace: int | None = 10
    jobs_pending_per_ip: int | None = 2
    jobs_per_ip_hour: int | None = 20
    workspaces_per_ip_hour: int | None = 5
    heavy_budget_s_per_day: int | None = 14_400
    job_timeout_s: int | None = 900
    queue_max: int | None = 8
    ttl_idle_s: int | None = 21_600
    ttl_max_s: int | None = 86_400
    sweep_s: int = 600
    min_free_bytes: int | None = 1 * GB
    # marker channels per live-cells set: a set's values are kept cells x channels, so the trial
    # cap keeps a set at most livecells_cells_max x 8 float64 values (about 384 MB), and the
    # livecells_memory_sets sets the server keeps loaded for counts about 768 MB in all
    livecells_channels_max: int | None = 8
    livecells_bins_min: int = 8
    livecells_bins_max: int = 512
    livecells_per_gate: int = 8
    livecells_cells_max: int | None = 6_000_000  # kept cells, summed over a gate's files
    livecells_filters_max: int | None = 16  # per counts request: two per channel at the trial cap
    livecells_counts_per_ip_minute: int | None = 120
    livecells_memory_sets: int = 2  # loaded sets the server keeps for counts

    def public(self) -> dict[str, int | None]:
        """The caps as /config sends them, by their lower-case names."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


TRIAL_CAPS = Caps()
# local: no caps but the k limit and the cells sampling bounds
LOCAL_CAPS = Caps(
    **{f.name: None for f in fields(Caps) if f.default is not None and f.type == "int | None"},
    cells_per_file_max=5_000,
    cells_max_total=200_000,
)


def _flag(value: str | None) -> bool:
    return (value or "0").strip() == "1"


@dataclass(frozen=True)
class Settings:
    mode: str = DEFAULT_MODE
    data_dir: Path = DEFAULT_DATA_DIR
    web_dir: Path = DEFAULT_WEB_DIR
    demo_dir: Path = DEFAULT_DEMO_DIR
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    workers: int = 1
    jobs: int = LOCAL_JOBS
    cookie_secure: bool = False
    trust_proxy: bool = False
    docker_command: str | None = None  # DN_DOCKER_COMMAND, else the published image's command
    allowed_hosts: tuple[str, ...] = ()  # DN_ALLOWED_HOSTS, lower case
    caps: Caps = field(default_factory=lambda: LOCAL_CAPS)

    @property
    def trial(self) -> bool:
        return self.mode == "trial"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, **overrides) -> Settings:
        """The settings from env (os.environ by default), then overrides by field name."""
        env = os.environ if env is None else env
        mode = env.get(ENV_MODE, DEFAULT_MODE).strip().lower()
        if mode not in MODES:
            raise SystemExit(f"{ENV_MODE} must be local or trial, not {mode!r}")
        trial = mode == "trial"
        default_workers = TRIAL_WORKERS if trial else min(LOCAL_WORKERS_MAX, os.cpu_count() or 1)
        hosts = (h.strip().lower() for h in env.get(ENV_ALLOWED_HOSTS, "").split(","))
        values = {
            "mode": mode,
            "data_dir": Path(env.get(ENV_DATA_DIR) or DEFAULT_DATA_DIR),
            "web_dir": Path(env.get(ENV_WEB_DIR) or DEFAULT_WEB_DIR),
            "demo_dir": Path(env.get(ENV_DEMO_DIR) or DEFAULT_DEMO_DIR),
            "host": env.get(ENV_HOST) or DEFAULT_HOST,
            "port": int(env.get(ENV_PORT) or DEFAULT_PORT),
            "workers": int(env.get(ENV_WORKERS) or default_workers),
            "jobs": int(env.get(ENV_JOBS) or (TRIAL_JOBS if trial else LOCAL_JOBS)),
            "cookie_secure": _flag(env.get(ENV_COOKIE_SECURE)),
            "trust_proxy": _flag(env.get(ENV_TRUST_PROXY)),
            "docker_command": env.get(ENV_DOCKER_COMMAND) or None,
            "allowed_hosts": tuple(filter(None, hosts)),
            "caps": TRIAL_CAPS if trial else LOCAL_CAPS,
        }
        values.update(overrides)
        if values["workers"] < 1:
            raise SystemExit(f"{ENV_WORKERS} must be 1 or more")
        return cls(**values)

    @property
    def storage_note(self) -> str:
        return STORAGE_NOTE[self.mode]
