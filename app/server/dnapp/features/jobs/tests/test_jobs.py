"""Jobs and the trial's job limits, on real gate jobs in the worker pool (a gate on one FCS file
is the cheapest job the app runs): cancelling a queued and a running job and one that has
already ended, the timeout, a server restart, the busy queue, and the per-IP and daily limits.
What a running job holds across features is tested in app/tests/test_job_claims_and_caps.py.

A worker is a spawned process, so a job submitted here takes well over a second to reach its
first step; a cancel or a timeout sent right after the submit therefore lands before the job
can finish, which is what makes these tests deterministic without a slow fixture."""

from __future__ import annotations

import json

import pytest

from dnapp.core.config import BUSY_RETRY_S, RESTART_MESSAGE, TIMEOUT_MESSAGE
from dnapp.core.limits import HOUR_S, Limits
from testkit import API, assert_error, make_settings, new_client, upload, wait_job


def plenty(path) -> int:
    return 10**13


def _gate(c):
    return c.post(f"{API}/flow/gates", json={"uploads": ["u1"], "settings": {}})


def _fcs_client(make_client, fcs_202, mode="local", **over):
    c = make_client(mode, free_bytes=plenty, **over)
    if mode == "trial":
        assert c.get(f"{API}/workspace").status_code == 200
    assert upload(c, fcs_202).status_code == 201
    return c


def _jobs(c):
    return c.app.state.dn.jobs


# ---- cancel ---------------------------------------------------------------------------------


def test_cancel_queued_then_running(make_client, fcs_202):
    c = _fcs_client(make_client, fcs_202)  # one worker
    first, second = _gate(c).json(), _gate(c).json()
    assert first["job"]["status"] == "running" and second["job"]["status"] == "queued"
    j1, j2 = first["job"]["id"], second["job"]["id"]

    r = c.post(f"{API}/jobs/{j2}/cancel")
    assert r.status_code == 202 and r.json()["status"] == "cancelled"  # at once: never started
    assert r.json()["error"]["code"] == "cancelled"

    assert c.post(f"{API}/jobs/{j1}/cancel").status_code == 202
    job = wait_job(c, j1)
    assert job["status"] == "cancelled" and job["error"]["code"] == "cancelled"
    gid = first["gate_id"]
    out = c.app.state.dn.settings.data_dir / "ws" / "local" / "gates"
    assert not (out / gid).exists()  # a cancelled gate leaves no output
    assert c.get(f"{API}/flow/gates/{gid}").json()["status"] == "cancelled"
    again = c.post(f"{API}/jobs/{j1}/cancel")  # already cancelled: left as it is
    assert again.status_code == 200 and again.json() == job
    assert_error(c.get(f"{API}/flow/gates/{gid}/figures/gates.png"), 409, "wrong_state")


def test_cancel_after_the_job_ended_leaves_it(make_client, fcs_202):
    """A client's job list is a poll behind the server, so a cancel can arrive after its job
    ended. It answers 200 with the job as it was: a done job stays done, its record on disk is
    not rewritten, and its gate's outputs stay."""
    c = _fcs_client(make_client, fcs_202)
    started = _gate(c).json()
    jid, gid = started["job"]["id"], started["gate_id"]
    job = wait_job(c, jid)
    assert job["status"] == "done" and job["error"] is None
    ws = c.app.state.dn.settings.data_dir / "ws" / "local"
    on_disk = (ws / "jobs" / f"{jid}.json").read_bytes()
    outputs = sorted(p.name for p in (ws / "gates" / gid).iterdir())

    r = c.post(f"{API}/jobs/{jid}/cancel")
    assert r.status_code == 200, r.text
    assert r.json() == job
    assert c.get(f"{API}/jobs/{jid}").json() == job
    assert (ws / "jobs" / f"{jid}.json").read_bytes() == on_disk
    assert not (ws / "jobs" / f"{jid}.cancel").exists()
    assert sorted(p.name for p in (ws / "gates" / gid).iterdir()) == outputs
    assert c.get(f"{API}/flow/gates/{gid}").json()["status"] == "done"
    assert c.get(f"{API}/flow/gates/{gid}/figures/gates.png").status_code == 200


# ---- timeout and restart ----------------------------------------------------------------------


def test_timeout_stops_the_job(make_client, fcs_202, clock):
    c = _fcs_client(make_client, fcs_202, clock=clock, caps={"job_timeout_s": 60})
    started = _gate(c).json()
    clock.advance(61)
    _jobs(c).check_timeouts()  # what the watchdog does every couple of seconds
    job = wait_job(c, started["job"]["id"])
    assert job["status"] == "failed"
    assert job["error"] == {
        "code": "timeout",
        "message": TIMEOUT_MESSAGE.format(s=60),
        "param": None,
    }
    assert c.get(f"{API}/flow/gates/{started['gate_id']}").json()["status"] == "failed"
    r = c.post(f"{API}/jobs/{started['job']['id']}/cancel")  # a failed job is left as it is
    assert r.status_code == 200 and r.json() == job


def test_restart_fails_the_jobs_it_interrupted(tmp_path, fcs_202):
    """S8: stopping the server with one job running and one queued, then starting it again on
    the same data folder, leaves both jobs failed with the restart message."""
    settings = make_settings(tmp_path, "local")
    c = new_client(settings)
    c.__enter__()
    assert upload(c, fcs_202).status_code == 201
    running, queued = _gate(c).json(), _gate(c).json()
    assert running["job"]["status"] == "running" and queued["job"]["status"] == "queued"
    c.__exit__(None, None, None)  # the server stops mid-job

    jobs = tmp_path / "data" / "ws" / "local" / "jobs"
    on_disk = json.loads((jobs / f"{queued['job']['id']}.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "queued"  # still queued when it stopped

    c2 = new_client(settings)
    with c2:
        for started in (running, queued):
            job = c2.get(f"{API}/jobs/{started['job']['id']}").json()
            assert job["status"] == "failed", job
            assert job["error"] == {"code": "internal", "message": RESTART_MESSAGE, "param": None}
            gate = c2.get(f"{API}/flow/gates/{started['gate_id']}").json()
            assert gate["status"] == "failed"
        assert c2.get(f"{API}/health").json()["jobs"] == {"running": 0, "queued": 0}
        # and the restarted server runs new jobs
        assert wait_job(c2, _gate(c2).json()["job"]["id"])["status"] == "done"


# ---- the queue and the per-IP limits ------------------------------------------------------


def test_full_queue_is_busy(make_client, fcs_202):
    c = _fcs_client(make_client, fcs_202, caps={"queue_max": 1})
    a, b = _gate(c).json(), _gate(c).json()
    assert a["job"]["status"] == "running" and b["job"]["status"] == "queued"
    r = _gate(c)
    err = assert_error(r, 503, "busy")
    assert r.headers["retry-after"] == str(BUSY_RETRY_S) and "queue" in err["message"]
    for started in (b, a):
        c.post(f"{API}/jobs/{started['job']['id']}/cancel")
    wait_job(c, a["job"]["id"])


def test_trial_pending_jobs_per_ip(make_client, fcs_202):
    c = _fcs_client(make_client, fcs_202, "trial")  # 2 pending jobs per address
    a, b = _gate(c).json(), _gate(c).json()
    r = _gate(c)
    assert_error(r, 429, "rate_limited")
    assert r.headers["retry-after"] == str(BUSY_RETRY_S)
    assert _jobs(c).pending_for_ip("testclient") == 2
    for started in (b, a):
        c.post(f"{API}/jobs/{started['job']['id']}/cancel")
    wait_job(c, a["job"]["id"])
    assert _jobs(c).pending_for_ip("testclient") == 0
    started = _gate(c).json()  # room again
    c.post(f"{API}/jobs/{started['job']['id']}/cancel")
    wait_job(c, started["job"]["id"])


def test_trial_jobs_per_hour(make_client, fcs_202, clock):
    c = _fcs_client(make_client, fcs_202, "trial", clock=clock, caps={"jobs_per_ip_hour": 1})
    first = _gate(c).json()
    assert wait_job(c, first["job"]["id"])["status"] == "done"
    clock.advance(600)
    r = _gate(c)
    assert_error(r, 429, "rate_limited")
    assert r.headers["retry-after"] == str(HOUR_S - 600)
    clock.advance(HOUR_S - 600)  # the first job leaves the hour's window
    second = _gate(c)
    assert second.status_code == 202, second.text
    wait_job(c, second.json()["job"]["id"])


def test_trial_daily_budget(make_client, fcs_202, clock):
    # the workspace lives past the day here, so the new day is not hidden behind its expiry
    caps = {"heavy_budget_s_per_day": 5, "ttl_idle_s": 10 * 86_400, "ttl_max_s": 10 * 86_400}
    c = _fcs_client(make_client, fcs_202, "trial", clock=clock, caps=caps)
    started = _gate(c).json()
    clock.advance(10)  # the job is billed by the server's clock: start to finish
    wait_job(c, started["job"]["id"])
    r = _gate(c)
    err = assert_error(r, 503, "busy")
    assert "today" in err["message"]
    wait = int(r.headers["retry-after"])
    assert wait == 86_400 - int(clock.t % 86_400)
    clock.advance(wait)  # midnight UTC: a new day's budget
    again = _gate(c)
    assert again.status_code == 202, again.text
    wait_job(c, again.json()["job"]["id"])


def test_limits_window_and_budget_arithmetic(clock):
    from dnapp.core.config import TRIAL_CAPS
    from dnapp.core.errors import ApiError

    lim = Limits(TRIAL_CAPS, clock)
    for _ in range(TRIAL_CAPS.workspaces_per_ip_hour):
        lim.check_workspace("1.2.3.4")
        lim.note_workspace("1.2.3.4")
        clock.advance(60)
    with pytest.raises(ApiError) as e:
        lim.check_workspace("1.2.3.4")
    assert e.value.status == 429
    assert e.value.headers["Retry-After"] == str(HOUR_S - 5 * 60)
    lim.check_workspace("5.6.7.8")  # per address
    lim.spend(TRIAL_CAPS.heavy_budget_s_per_day)
    with pytest.raises(ApiError) as e:
        lim.check_job("5.6.7.8", 0)
    assert e.value.status == 503 and e.value.code == "busy"
