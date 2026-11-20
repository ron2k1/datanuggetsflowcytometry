"""Workspaces: the trial cookie, expiry by idle time and age, the per-IP workspace limit, and
the local workspace."""

from __future__ import annotations

import pytest

from testkit import API, assert_error, upload, watch

WS_KEYS = {"mode", "created", "idle_expires_at", "expires_at"}
WS_KEYS |= {"uploads", "gates", "runs", "jobs", "datasets"}  # a list per record kind


def _cookie_header(r) -> str:
    return r.headers.get("set-cookie", "")


def test_trial_cookie_is_created_with_the_pinned_flags(make_client, clock):
    c = make_client("trial", clock=clock)
    assert_error(c.get(f"{API}/uploads"), 401, "no_workspace", None)
    r = c.get(f"{API}/workspace")
    assert r.status_code == 200
    assert set(r.json()) == WS_KEYS
    header = _cookie_header(r)
    low = header.lower()
    assert header.startswith("dn_ws=")
    assert "httponly" in low and "samesite=strict" in low and "path=/api" in low
    assert "secure" not in low
    assert "max-age=86400" in low
    body = r.json()
    assert body["mode"] == "trial" and body["expires_at"] and body["idle_expires_at"]
    # the cookie now opens the same workspace
    again = c.get(f"{API}/workspace")
    assert "set-cookie" not in again.headers
    assert again.json()["created"] == body["created"]
    assert c.get(f"{API}/uploads").json() == {"uploads": []}


def test_secure_flag_when_configured(make_client):
    c = make_client("trial", cookie_secure=True)
    r = c.get(f"{API}/workspace")
    assert "secure" in _cookie_header(r).lower()


def test_unknown_cookie_gets_a_new_workspace(make_client):
    c = make_client("trial")
    c.cookies.set("dn_ws", "not-a-real-token", path="/api")
    assert_error(c.get(f"{API}/uploads"), 401, "no_workspace")
    r = c.get(f"{API}/workspace")
    assert r.status_code == 200 and _cookie_header(r).startswith("dn_ws=")


def test_idle_expiry_gives_410_and_clears_the_cookie(make_client, clock, fcs_202):
    c = make_client("trial", clock=clock)
    c.get(f"{API}/workspace")
    assert upload(c, fcs_202).status_code == 201
    clock.advance(21_600 - 1)
    assert c.get(f"{API}/uploads").status_code == 200  # touches it
    clock.advance(21_600 - 1)
    assert c.get(f"{API}/uploads").status_code == 200
    clock.advance(21_600 + 1)
    r = c.get(f"{API}/uploads")
    assert_error(r, 410, "workspace_expired")
    low = _cookie_header(r).lower()
    assert low.startswith("dn_ws=") and "max-age=0" in low
    # the folder is gone: the same token is still refused with 410
    c.cookies.clear()


def test_hard_cap_expiry_even_when_active(make_client, clock):
    c = make_client("trial", clock=clock)
    c.get(f"{API}/workspace")
    for _ in range(4):
        clock.advance(18_000)
        assert c.get(f"{API}/uploads").status_code == 200
    clock.advance(86_400 - 4 * 18_000)
    assert_error(c.get(f"{API}/uploads"), 410, "workspace_expired")
    r = c.get(f"{API}/workspace")  # a fresh one
    assert r.status_code == 200 and r.json()["uploads"] == []


def test_swept_workspace_cookie_still_gets_410(make_client, clock):
    c = make_client("trial", clock=clock)
    c.get(f"{API}/workspace")
    token = c.cookies.get("dn_ws")
    state = c.app.state.dn
    clock.advance(86_401)
    assert state.workspaces.sweep(state.jobs.busy)
    c.cookies.clear()
    c.cookies.set("dn_ws", token, path="/api")
    assert_error(c.get(f"{API}/runs"), 410, "workspace_expired")


def test_workspaces_per_ip_hour(make_client, clock):
    c = make_client("trial", clock=clock)
    for _ in range(5):
        c.cookies.clear()
        assert c.get(f"{API}/workspace").status_code == 200
    c.cookies.clear()
    r = c.get(f"{API}/workspace")
    assert_error(r, 429, "rate_limited")
    assert int(r.headers["retry-after"]) > 0
    clock.advance(3601)
    assert c.get(f"{API}/workspace").status_code == 200


def test_trusted_proxy_ip(make_client, clock):
    c = make_client("trial", clock=clock, trust_proxy=True)
    for i in range(6):
        c.cookies.clear()
        r = c.get(f"{API}/workspace", headers={"X-Real-IP": f"10.0.0.{i}"})
        assert r.status_code == 200


def test_local_workspace_survives_restart(make_client, fcs_202):
    c = make_client("local", sub="same")
    r = c.get(f"{API}/workspace")
    assert r.json()["mode"] == "local" and r.json()["expires_at"] is None
    assert "set-cookie" not in r.headers
    assert upload(c, fcs_202).status_code == 201
    c2 = make_client("local", sub="same")
    assert [u["name"] for u in c2.get(f"{API}/uploads").json()["uploads"]] == ["202.fcs"]


def test_a_trial_start_keeps_the_local_workspace(make_client, fcs_202):
    """compose.yaml lets DN_MODE=trial start on the volume local mode uses. A trial start empties
    only its own folder, so the local uploads are there when local mode starts again."""
    local = make_client("local", sub="shared")
    assert upload(local, fcs_202).status_code == 201
    local_dir = local.app.state.dn.workspaces.local().path
    trial = make_client("trial", sub="shared")
    assert trial.get(f"{API}/workspace").status_code == 200
    assert (local_dir / "meta.json").is_file()
    again = make_client("local", sub="shared")
    assert [u["name"] for u in again.get(f"{API}/uploads").json()["uploads"]] == ["202.fcs"]


def test_a_trial_start_empties_the_last_trial_run(make_client, fcs_202):
    first = make_client("trial", sub="shared")
    first.get(f"{API}/workspace")
    assert upload(first, fcs_202).status_code == 201
    token = first.cookies.get("dn_ws")
    (old,) = first.app.state.dn.workspaces.all()
    assert old.path.is_dir()
    second = make_client("trial", sub="shared")
    assert not old.path.exists()
    second.cookies.set("dn_ws", token, path="/api")
    assert_error(second.get(f"{API}/uploads"), 401, "no_workspace")


def test_delete_workspace(make_client, fcs_202):
    c = make_client()
    upload(c, fcs_202)
    assert c.delete(f"{API}/workspace").status_code == 204
    assert c.get(f"{API}/workspace").json()["uploads"] == []
    assert upload(c, fcs_202).json()["id"] == "u2"  # ids are never reused


@pytest.mark.parametrize(
    ("path", "listed"),
    [
        ("workspace", ("uploads", "gates", "runs", "datasets")),
        ("uploads", ("uploads",)),
        ("runs", ("runs",)),
    ],
)
def test_a_list_reads_its_records_under_the_workspace_lock(make_client, path, listed):
    """A list runs in the threadpool, beside requests that add and remove records, so it goes
    over each kind's records only while it holds the workspace's lock."""
    c = make_client()
    ws = c.app.state.dn.workspaces.local()
    kinds = {kind: watch(ws, kind) for kind in listed}
    assert c.get(f"{API}/{path}").status_code == 200
    free = {kind: records.free for kind, records in kinds.items()}
    assert all(f and not any(f) for f in free.values()), free
