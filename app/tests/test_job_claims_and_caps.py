"""What a job holds, and the caps on run settings, across features: the 409s for deleting a
run or a gate whose own job is running, a gate that a running or queued flow run reads, and an
upload that a gate uses; and the trial caps on flow settings that local mode lifts. Real jobs in
the worker pool."""

from __future__ import annotations

import pytest

from testkit import API, assert_error, upload, wait_job


def plenty(path) -> int:
    return 10**13


def _gate(c):
    return c.post(f"{API}/flow/gates", json={"uploads": ["u1", "u2"], "settings": {}})


def _flow_run(c, gid):
    return c.post(f"{API}/flow/runs", json={"gate_id": gid, "pops": [[1], [1]], "k": 5})


@pytest.fixture
def gated(make_client, fcs_202):
    """make(mode, **caps) -> a client with two FCS uploads and their finished gate g1."""

    def make(mode, **caps):
        c = make_client(mode, free_bytes=plenty, sub=mode, caps=caps or None)
        if mode == "trial":
            c.get(f"{API}/workspace")
        for _ in range(2):
            assert upload(c, fcs_202).status_code == 201
        assert wait_job(c, _gate(c).json()["job"]["id"])["status"] == "done"
        return c

    return make


# ---- what a job holds -----------------------------------------------------------------------


def test_a_running_or_queued_run_holds_its_gate(gated):
    """A flow run takes what it needs from its gate's folder when it runs, so a gate cannot go
    while one of its runs is running or still queued; the 409 names the run and says which. Each
    run here has its own gate, so each gate's refusal shows which run holds it."""
    c = gated("local")
    second = _gate(c).json()
    g2 = second["gate_id"]
    assert wait_job(c, second["job"]["id"])["status"] == "done"
    running, queued = _flow_run(c, g2).json(), _flow_run(c, "g1").json()  # one worker
    assert running["job"]["status"] == "running" and queued["job"]["status"] == "queued"

    for started in (running, queued):
        assert_error(c.delete(f"{API}/runs/{started['run_id']}"), 409, "wrong_state")
    for gid, started, state in ((g2, running, "still running"), ("g1", queued, "queued")):
        err = assert_error(c.delete(f"{API}/flow/gates/{gid}"), 409, "wrong_state")
        assert err["message"] == f"Run {started['run_id']} from this gate is {state}."

    r = c.post(f"{API}/jobs/{queued['job']['id']}/cancel")  # at once: it never started
    assert r.json()["status"] == "cancelled"
    assert c.delete(f"{API}/flow/gates/g1").status_code == 204
    assert_error(c.delete(f"{API}/flow/gates/{g2}"), 409, "wrong_state")  # still running
    c.post(f"{API}/jobs/{running['job']['id']}/cancel")
    assert wait_job(c, running["job"]["id"])["status"] == "cancelled"
    assert c.delete(f"{API}/flow/gates/{g2}").status_code == 204
    for started in (running, queued):
        assert c.delete(f"{API}/runs/{started['run_id']}").status_code == 204
    for uid in ("u1", "u2"):  # no gate left to use them
        assert c.delete(f"{API}/uploads/{uid}").status_code == 204


def test_running_gate_cannot_be_deleted(make_client, fcs_202):
    """Nor can a file its gate uses, while the gate runs or after: the gate's record names the
    file whatever its state, so the gate goes first."""
    c = make_client()
    assert upload(c, fcs_202).status_code == 201
    started = c.post(f"{API}/flow/gates", json={"uploads": ["u1"], "settings": {}}).json()
    gid = started["gate_id"]
    assert_error(c.delete(f"{API}/flow/gates/{gid}"), 409, "wrong_state")
    held = f"Gate {gid} uses this file; delete it first."
    assert assert_error(c.delete(f"{API}/uploads/u1"), 409, "wrong_state")["message"] == held
    c.post(f"{API}/jobs/{started['job']['id']}/cancel")
    assert wait_job(c, started["job"]["id"])["status"] == "cancelled"
    assert assert_error(c.delete(f"{API}/uploads/u1"), 409, "wrong_state")["message"] == held
    assert c.delete(f"{API}/flow/gates/{gid}").status_code == 204
    assert c.delete(f"{API}/uploads/u1").status_code == 204


# ---- the trial caps, and local mode without them ----------------------------------------------


def test_trial_caps_refuse_big_settings(gated):
    c = gated("trial", pooled_nuggets_max=1_000)
    flow = {"gate_id": "g1", "pops": [[1], [1]], "k": 5}
    for over, param in (
        ({"dn_num2": 2_001}, "dn_num2"),
        ({"dn_num1": 10_001}, "dn_num1"),
        ({"k": 101}, "k"),
        ({"dn_num2": 600}, "dn_num2"),  # 2 files x 600 pooled nuggets > 1,000
    ):
        assert_error(
            c.post(f"{API}/flow/runs", json={**flow, **over}), 422, "invalid_setting", param
        )
    assert [j["kind"] for j in c.get(f"{API}/jobs").json()["jobs"]] == ["gate"]  # none started


def test_local_mode_accepts_what_the_trial_refuses(gated):
    c = gated("local")
    r = c.post(
        f"{API}/flow/runs",
        json={"gate_id": "g1", "pops": [[1], [1]], "k": 5, "dn_num1": 10_001, "dn_num2": 2_001},
    )
    assert r.status_code == 202, r.text
    started = r.json()
    c.post(f"{API}/jobs/{started['job']['id']}/cancel")
    assert wait_job(c, started["job"]["id"])["status"] == "cancelled"
