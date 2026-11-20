"""The app tests' shared kit, for app/tests and every feature's tests/ alike (app/conftest.py
registers its fixtures): apps on temporary data folders, an injectable clock, request helpers,
and real public data: FCS files rebuilt from the repository's recorded 202 events (Zenodo
22079206, CC BY 4.0)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dnapp.core.config import LOCAL_CAPS, REPO, TRIAL_CAPS, Settings
from dnapp.main import create_app

FLOW = REPO / "tests" / "fixtures" / "flow"
API = "/api/v1"
INDEX = "<!doctype html><title>datanuggets</title><p>app</p>"
# the keys of a Job, of a run's manifest (GET /runs/{rid}) and of its plot payload
JOB_KEYS = {
    "id", "kind", "status", "progress", "stage", "message", "log_tail", "created", "started",
    "finished", "run_id", "gate_id", "error",
}  # fmt: skip
MANIFEST_KEYS = {
    "id", "kind", "status", "created", "title", "settings", "record", "k", "clusters", "files",
    "warnings",
}  # fmt: skip
PLOT_KEYS = {
    "run_id", "kind", "method", "columns", "short_columns", "transform", "k", "clusters",
    "nuggets", "pca", "tsne", "files", "groups", "warnings",
}  # fmt: skip


class Clock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def make_settings(tmp: Path, mode: str = "local", **over) -> Settings:
    web = tmp / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "index.html").write_text(INDEX, encoding="utf-8")
    base = {
        "mode": mode,
        "data_dir": tmp / "data",
        "web_dir": web,
        "demo_dir": tmp / "demo",
        "workers": 1,
        "jobs": 1,
        "caps": TRIAL_CAPS if mode == "trial" else LOCAL_CAPS,
        # TestClient sends Host: testserver, which the Host check allows only when it is listed,
        # as DN_ALLOWED_HOSTS would list it
        "allowed_hosts": ("testserver",),
    }
    caps = over.pop("caps", None)
    base.update(over)
    if caps:
        base["caps"] = replace(base["caps"], **caps)
    return Settings(**base)


def new_client(settings: Settings) -> TestClient:
    """A client on a new app for settings, not started yet: for a test that stops a server and
    starts another on the same data folder. make_client covers every other test."""
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_client(tmp_path):
    """make_client(mode, clock=None, free_bytes=None, **settings) -> a started TestClient."""
    clients = []

    def make(mode="local", *, clock=None, free_bytes=None, sub="a", **over):
        settings = make_settings(tmp_path / sub, mode, **over)
        app = create_app(settings, clock=clock, free_bytes=free_bytes)
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture(scope="session")
def fcs_202(tmp_path_factory) -> Path:
    """202's recorded events (FSC-A, SSC-A and three fluorescence channels, 50,000 events) as
    an FCS 3.1 file, as tests/flow/test_flow_fcs_integration.py builds it."""
    import flowio

    path = tmp_path_factory.mktemp("fcs") / "202.fcs"
    with np.load(FLOW / "202.npz") as gate, np.load(FLOW / "202_fluor.npz") as fluor:
        events = np.column_stack((gate["fsc"], gate["ssc"], fluor["fluor"]))
        names = ["FSC-A", "SSC-A", *fluor["pnn"].tolist()]
        labels = ["", "", *fluor["pns"].tolist()]
    with path.open("wb") as handle:
        flowio.create_fcs(handle, events.ravel(), names, opt_channel_names=labels)
    return path


def upload(
    client, path: Path, name: str | None = None, content_type="application/octet-stream", **kw
):
    with path.open("rb") as f:
        files = {"file": (name or path.name, f, content_type)}
        return client.post(f"{API}/uploads", files=files, **kw)


def wait_job(client, jid: str, timeout: float = 240.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"{API}/jobs/{jid}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {jid} did not finish in {timeout}s: {job}")


def assert_no_paths(text: str, *roots: Path) -> None:
    for root in roots:
        for v in {
            str(root),
            str(root.resolve()),
            str(root).replace("\\", "/"),
            str(root).replace("\\", "\\\\"),
        }:
            assert v not in text, f"{v} leaked"


class LockWatch(dict):
    """A workspace's records of one kind that note, each time they are gone over, whether
    another thread could take ws.lock then (free): watch(ws, kind) puts one in place. A request
    that goes over them unlocked can meet another request's thread adding or removing a record,
    which raises "dictionary changed size during iteration"."""

    def __init__(self, ws, records: dict):
        super().__init__(records)
        self.ws, self.free = ws, []

    def note(self) -> None:
        got = []

        def probe():
            taken = self.ws.lock.acquire(blocking=False)
            if taken:
                self.ws.lock.release()
            got.append(taken)

        t = threading.Thread(target=probe)
        t.start()
        t.join()
        self.free.append(got[0])

    def __iter__(self):
        self.note()
        return super().__iter__()

    def keys(self):
        self.note()
        return super().keys()

    def values(self):
        self.note()
        return super().values()

    def items(self):
        self.note()
        return super().items()


def watch(ws, kind: str) -> LockWatch:
    ws.meta[kind] = LockWatch(ws, ws.meta[kind])
    return ws.meta[kind]


def channel_list(size: int, n: int = 200) -> list[str]:
    """n distinct channel names whose list json.dumps writes in size bytes, as POST /datasets
    measures one against DATASET_CHANNELS_BYTES. Each holds a µ, which json.dumps escapes in
    six bytes."""
    names = [f"µ{i:03d}-A" for i in range(n)]
    per, extra = divmod(size - len(json.dumps(names)), n)
    names = [f"{s[:-2]}{'x' * (per + (i < extra))}-A" for i, s in enumerate(names)]
    assert len(json.dumps(names)) == size
    return names


ERROR_KEYS = {"code", "message", "param"}


def assert_error(r, status: int, code: str, param="__any__"):
    assert r.status_code == status, (r.status_code, r.text)
    body = r.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == ERROR_KEYS
    assert body["error"]["code"] == code
    if param != "__any__":
        assert body["error"]["param"] == param
    return body["error"]
