"""Smoke-test a running datanuggets app (the Docker image in CI, or a local uvicorn).

Checks, against the contract in docs/app/contract.md: health, config (mode, caps and ttl null in
local mode and set in trial mode), the page's security headers, the workspace cookie (trial),
the PBMC demo, a gate of its files and a small flow run from it to done, the run's plot and
cells payloads, its files list, one of its files and its zip.

Standard library only, so the CI runner needs no install. Every request has a timeout.

    python app/scripts/smoke.py --base-url http://127.0.0.1:8000 --mode local
    python app/scripts/smoke.py --base-url http://127.0.0.1:8001 --mode trial
"""

from __future__ import annotations

import argparse
import http.cookiejar
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SmokeConfig:
    request_timeout_s: float = 30.0
    health_wait_s: float = 180.0  # container start, first import of numba and pandas
    job_timeout_s: float = 600.0
    poll_s: float = 1.0
    api: str = "/api/v1"
    cookie_name: str = "dn_ws"
    demo_id: str = "pbmc"
    # the flow run: few nuggets and cells, so it stays quick on a CI runner and inside the trial
    # caps (dn_num2 per file x 4 files under pooled_nuggets_max)
    k: int = 8
    dn_num1: int = 1_500
    dn_num2: int = 150
    cells_per_file: int = 100
    k_max: int = 100
    csp: str = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    storage_notes: dict[str, str] = field(
        default_factory=lambda: {
            "trial": "Files stay in a temporary workspace and are deleted within 24 hours. "
            "Do not upload identifiable patient data.",
            "local": "Files stay on this computer.",
        }
    )
    trial_caps_keys: tuple[str, ...] = ("k_max", "fcs_events", "upload_fcs_bytes", "job_timeout_s")


CONFIG = SmokeConfig()
HEX = re.compile(r"^#[0-9a-f]{6}$")


class SmokeFail(Exception):
    pass


def check(cond: bool, what: str) -> None:
    if not cond:
        raise SmokeFail(what)


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    set_cookies: list[str]
    body: bytes

    def json(self):
        try:
            return json.loads(self.body)
        except ValueError:
            raise SmokeFail(f"body is not JSON: {self.body[:200]!r}") from None


class Client:
    def __init__(self, base: str, cfg: SmokeConfig = CONFIG):
        self.base = base.rstrip("/")
        self.cfg = cfg
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body: dict | None = None) -> Reply:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            resp = self.opener.open(req, timeout=self.cfg.request_timeout_s)
        except urllib.error.HTTPError as e:  # non-2xx: keep status and body for the checks
            resp = e
        with resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return Reply(
                resp.status, headers, resp.headers.get_all("Set-Cookie") or [], resp.read()
            )

    def api(self, method: str, path: str, body: dict | None = None, expect: int = 200):
        r = self.call(method, self.cfg.api + path, body)
        if r.status != expect:
            raise SmokeFail(
                f"{method} {path}: HTTP {r.status}, expected {expect}: {r.body[:300]!r}"
            )
        return r.json() if r.body else None


def has_keys(obj: dict, keys: set[str], what: str) -> None:
    check(isinstance(obj, dict), f"{what} is not an object")
    missing = keys - obj.keys()
    check(not missing, f"{what} lacks {sorted(missing)}")


def wait_for_health(c: Client, mode: str) -> dict:
    deadline = time.monotonic() + c.cfg.health_wait_s
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            r = c.call("GET", c.cfg.api + "/health")
            if r.status == 200:
                h = r.json()
                has_keys(h, {"status", "mode", "version", "jobs"}, "health")
                check(h["status"] == "ok", f"health status {h['status']!r}")
                check(h["mode"] == mode, f"health mode {h['mode']!r}, expected {mode!r}")
                has_keys(h["jobs"], {"running", "queued"}, "health.jobs")
                return h
            last = f"HTTP {r.status}"
        except OSError as e:  # refused while the server starts
            last = type(e).__name__
        time.sleep(c.cfg.poll_s)
    raise SmokeFail(f"/health not ok after {c.cfg.health_wait_s:.0f} s ({last})")


def check_config(c: Client, mode: str) -> dict:
    cfg = c.api("GET", "/config")
    has_keys(
        cfg,
        {
            "mode",
            "version",
            "package_version",
            "caps",
            "ttl",
            "defaults",
            "limits",
            "docker_command",
            "build_command",
            "build_run_command",
            "storage_note",
        },
        "config",
    )
    check(cfg["mode"] == mode, f"config mode {cfg['mode']!r}")
    check(cfg["limits"].get("k_max") == c.cfg.k_max, f"limits.k_max {cfg['limits'].get('k_max')!r}")
    check(cfg["storage_note"] == c.cfg.storage_notes[mode], f"storage_note {cfg['storage_note']!r}")
    has_keys(cfg["defaults"], {"gate", "cluster"}, "config.defaults")
    check("docker run" in cfg["docker_command"], "docker_command lacks 'docker run'")
    # both commands name the running version, so a copied command starts this same app
    pinned = f"#v{cfg['package_version']}"
    check(cfg["build_command"].endswith(pinned), f"build_command is not pinned to {pinned}")
    if mode == "local":
        check(cfg["caps"] is None, "local caps should be null")
        check(cfg["ttl"] is None, "local ttl should be null")
    else:
        has_keys(cfg["caps"], set(c.cfg.trial_caps_keys), "trial caps")
        has_keys(cfg["ttl"], {"idle_s", "max_s"}, "trial ttl")
    return cfg


def check_page(c: Client) -> None:
    r = c.call("GET", "/")
    check(r.status == 200, f"GET /: HTTP {r.status}")
    check(r.headers.get("content-type", "").startswith("text/html"), "GET / is not text/html")
    check(
        r.headers.get("content-security-policy") == c.cfg.csp,
        f"CSP differs: {r.headers.get('content-security-policy')!r}",
    )
    check(r.headers.get("x-content-type-options") == "nosniff", "page lacks nosniff")
    check(r.headers.get("referrer-policy") == "no-referrer", "page lacks Referrer-Policy")
    check(b"unsafe-eval" not in r.body, "page mentions unsafe-eval")


def check_workspace(c: Client, mode: str) -> None:
    if mode == "trial":
        bare = Client(c.base, c.cfg)  # no cookie: a workspace route must refuse
        r = bare.call("GET", c.cfg.api + "/uploads")
        check(r.status == 401, f"GET /uploads without a cookie: HTTP {r.status}, expected 401")
        err = r.json().get("error", {})
        check(err.get("code") == "no_workspace", f"error code {err.get('code')!r}")
    r = c.call("GET", c.cfg.api + "/workspace")
    check(r.status == 200, f"GET /workspace: HTTP {r.status}")
    ws = r.json()
    has_keys(ws, {"mode", "created", "uploads", "gates", "runs", "jobs"}, "workspace")
    check(ws["mode"] == mode, f"workspace mode {ws['mode']!r}")
    if mode == "trial":
        cookie = next((s for s in r.set_cookies if s.startswith(c.cfg.cookie_name + "=")), None)
        check(cookie is not None, f"trial workspace set no {c.cfg.cookie_name} cookie")
        attrs = {a.strip().split("=")[0].lower(): a.strip() for a in cookie.split(";")[1:]}
        check("httponly" in attrs, "cookie lacks HttpOnly")
        check(
            attrs.get("samesite", "").lower() == "samesite=strict", "cookie lacks SameSite=Strict"
        )
        check(attrs.get("path", "").lower() == "path=/api", "cookie Path is not /api")
        check(any(k.name == c.cfg.cookie_name for k in c.jar), "cookie jar did not keep the cookie")
        # the same cookie must reach the workspace routes now
        c.api("GET", "/uploads")


def load_demo(c: Client) -> list[dict]:
    demos = c.api("GET", "/demos")["demos"]
    demo = next((d for d in demos if d["id"] == c.cfg.demo_id), None)
    check(demo is not None, f"demo {c.cfg.demo_id!r} not listed")
    has_keys(
        demo,
        {
            "id",
            "title",
            "kind",
            "files",
            "license",
            "source_url",
            "rows",
            "description",
            "available",
        },
        "demo",
    )
    check(demo["kind"] == "fcs", f"demo kind {demo['kind']!r}")
    check(demo["available"] is True, f"demo {c.cfg.demo_id!r} is not available")
    loaded = c.api("POST", f"/demos/{c.cfg.demo_id}/load", expect=201)
    ups = loaded["uploads"]
    check(
        len(ups) == len(demo["files"]),
        f"demo load gave {len(ups)} uploads for {len(demo['files'])} files",
    )
    for up in ups:
        has_keys(
            up, {"id", "name", "kind", "bytes", "rows", "columns", "created", "demo"}, "upload"
        )
        check(up["kind"] == "fcs", f"upload kind {up['kind']!r}")
        check(up["demo"] == c.cfg.demo_id, f"upload.demo {up['demo']!r}")
    events = sum(up["rows"] for up in ups)
    check(events == demo["rows"], f"uploads hold {events} events, demo lists {demo['rows']}")
    return ups


def wait_job(c: Client, jid: str) -> None:
    deadline = time.monotonic() + c.cfg.job_timeout_s
    last_progress = 0.0
    while True:
        job = c.api("GET", f"/jobs/{jid}")
        p = job["progress"]
        check(0.0 <= p <= 1.0, f"progress {p} outside [0, 1]")
        check(p >= last_progress, f"progress went back from {last_progress} to {p}")
        last_progress = p
        if job["status"] == "done":
            check(p == 1.0, f"done job has progress {p}")
            return
        if job["status"] in ("failed", "cancelled"):
            tail = "\n    ".join(job.get("log_tail") or [])
            raise SmokeFail(f"job {jid} {job['status']}: {job.get('error')}\n    {tail}")
        if time.monotonic() > deadline:
            raise SmokeFail(
                f"job {jid} not done after {c.cfg.job_timeout_s:.0f} s ({job['status']})"
            )
        time.sleep(c.cfg.poll_s)


def gate(c: Client, uploads: list[dict]) -> dict:
    """Every demo file gated with the default settings, to done; the Gate."""
    ids = [up["id"] for up in uploads]
    started = c.api("POST", "/flow/gates", {"uploads": ids, "settings": {}}, expect=202)
    has_keys(started, {"job", "gate_id"}, "gate start")
    wait_job(c, started["job"]["id"])
    g = c.api("GET", f"/flow/gates/{started['gate_id']}")
    has_keys(g, {"id", "status", "created", "settings", "files", "figures"}, "gate")
    check(g["status"] == "done", f"gate status {g['status']!r}")
    check([f["upload"] for f in g["files"]] == ids, "the gate's files are not the uploads")
    for f in g["files"]:
        has_keys(
            f, {"number", "upload", "name", "n_events", "channels", "populations"}, "gate file"
        )
        check(len(f["populations"]) > 0, f"no population in file {f['number']}")
    return g


def run_flow(c: Client, g: dict) -> str:
    """A small flow run of each file's first population, to done; its run id."""
    started = c.api(
        "POST",
        "/flow/runs",
        {
            "gate_id": g["id"],
            "pops": [[f["populations"][0]["pop"]] for f in g["files"]],
            "k": c.cfg.k,
            "dn_num1": c.cfg.dn_num1,
            "dn_num2": c.cfg.dn_num2,
            "cells_per_file": c.cfg.cells_per_file,
        },
        expect=202,
    )
    has_keys(started, {"job", "run_id"}, "run start")
    wait_job(c, started["job"]["id"])
    return started["run_id"]


def check_run(c: Client, rid: str) -> dict:
    """The run's plot and cells payloads; its manifest."""
    man = c.api("GET", f"/runs/{rid}")
    has_keys(
        man,
        {
            "id",
            "kind",
            "status",
            "created",
            "title",
            "settings",
            "record",
            "k",
            "clusters",
            "files",
            "warnings",
        },
        "run",
    )
    check(man["status"] == "done", f"run status {man['status']!r}")
    check(man["kind"] == "flow", f"run kind {man['kind']!r}")
    plot = c.api("GET", f"/runs/{rid}/plot")
    has_keys(
        plot,
        {
            "run_id",
            "kind",
            "columns",
            "short_columns",
            "transform",
            "k",
            "clusters",
            "nuggets",
            "pca",
            "tsne",
            "files",
            "groups",
            "warnings",
        },
        "plot",
    )
    check(plot["kind"] == "flow", f"plot kind {plot['kind']!r}")
    k = plot["k"]
    check(k == c.cfg.k, f"plot k {k}, expected {c.cfg.k}")
    check([cl["cluster"] for cl in plot["clusters"]] == list(range(1, k + 1)), "clusters not 1..k")
    colors = [cl["color"] for cl in plot["clusters"]]
    check(all(HEX.match(x) for x in colors) and len(set(colors)) == k, f"cluster colours {colors}")
    numbers = [f["number"] for f in plot["files"]]
    check(len(numbers) > 0, "the plot has no files")
    nug = plot["nuggets"]
    n = nug["n"]
    check(n > 0, "no nuggets")
    for key in ("nugget0", "file", "weight", "cluster", "centers"):
        check(len(nug[key]) == n, f"nuggets.{key} has {len(nug[key])} entries, n = {n}")
    check(set(nug["cluster"]) <= set(range(1, k + 1)), "nugget cluster outside 1..k")
    check(set(nug["file"]) <= set(numbers), "nugget file outside the plot's files")
    check(
        all(len(row) == len(plot["columns"]) for row in nug["centers"]), "center width != columns"
    )
    if plot["pca"] is not None:
        q = len(plot["pca"]["components"])
        check(
            len(plot["pca"]["scores"]) == n and all(len(s) == q for s in plot["pca"]["scores"]),
            "pca scores are not n x q",
        )
    cells = c.api("GET", f"/runs/{rid}/cells")
    has_keys(
        cells,
        {
            "run_id",
            "n",
            "cap_per_file",
            "columns",
            "file",
            "row0",
            "nugget0",
            "cluster",
            "pca",
            "values",
        },
        "cells",
    )
    most = c.cfg.cells_per_file * len(numbers)
    check(
        0 < cells["n"] <= most and len(cells["row0"]) == len(cells["file"]) == cells["n"],
        f"cells n {cells['n']}",
    )
    return man


def check_files(c: Client, man: dict) -> None:
    """The run's files list, one of its CSVs and the zip of them all."""
    rid = man["id"]
    for f in man["files"]:
        has_keys(f, {"name", "bytes", "kind"}, "run file")
    names = {f["name"] for f in man["files"]}
    check({"run.json", "cluster_summary.csv"} <= names, f"run files {sorted(names)}")
    r = c.call("GET", f"{c.cfg.api}/runs/{rid}/files/cluster_summary.csv")
    check(r.status == 200, f"GET cluster_summary.csv: HTTP {r.status}")
    check(r.headers.get("content-type", "").startswith("text/csv"), "the CSV is not text/csv")
    check("attachment" in r.headers.get("content-disposition", ""), "the CSV is not an attachment")
    check(b"cluster" in r.body.split(b"\n", 1)[0], f"CSV header {r.body[:100]!r}")
    r = c.call("GET", f"{c.cfg.api}/runs/{rid}/download.zip")
    check(r.status == 200, f"GET download.zip: HTTP {r.status}")
    check(r.headers.get("content-type") == "application/zip", "the zip is not application/zip")
    try:
        zipped = set(zipfile.ZipFile(io.BytesIO(r.body)).namelist())
    except zipfile.BadZipFile as e:
        raise SmokeFail(f"download.zip: {e}") from None
    check(zipped == names, f"the zip holds {sorted(zipped ^ names)} apart from the files list")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument(
        "--mode",
        choices=("local", "trial"),
        required=True,
        help="the mode the server should report",
    )
    a = p.parse_args(argv)
    c = Client(a.base_url)
    steps = [
        ("health", lambda: wait_for_health(c, a.mode)),
        ("config", lambda: check_config(c, a.mode)),
        ("page headers", lambda: check_page(c)),
        ("workspace", lambda: check_workspace(c, a.mode)),
    ]
    state: dict = {}
    steps += [
        ("demo load", lambda: state.update(uploads=load_demo(c))),
        ("gate", lambda: state.update(gate=gate(c, state["uploads"]))),
        ("flow run", lambda: state.update(run=run_flow(c, state["gate"]))),
        ("plot and cells", lambda: state.update(manifest=check_run(c, state["run"]))),
        ("files and zip", lambda: check_files(c, state["manifest"])),
    ]
    for name, step in steps:
        t0 = time.monotonic()
        try:
            step()
        except (SmokeFail, OSError, KeyError, TypeError, ValueError) as e:
            print(f"FAIL  {name}: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        print(f"ok    {name} ({time.monotonic() - t0:.1f} s)")
    print(f"smoke passed ({a.mode} mode, {a.base_url})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
