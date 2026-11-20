"""The live-cells routes' refusals, cache, caps and claims on their gate (contract-livecells.md
S13, S15, S16, S17), through HTTP on real flow events, with the job hour, the loads the counts
cache allows at once, and the boot's cleanup of sets a restart cut off. A module fixture gates
202's recorded events (uploaded twice) and makes one set, l1, on a server it then stops; each
test starts its own server on a copy of that data folder, with the caps it tests. A copy run with
no job workers keeps every new job queued, which is how a test holds a set active for as long as
it needs."""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections import Counter

import pytest

from dnapp.core.config import LOCAL_CAPS, TRIAL_CAPS
from testkit import API, assert_error, make_settings, new_client, upload, wait_job, watch

SETS = f"{API}/flow/gates/g1/livecells"


@pytest.fixture(scope="module")
def base(tmp_path_factory, fcs_202):
    settings = make_settings(tmp_path_factory.mktemp("livecells-base"))
    with new_client(settings) as c:
        for _ in range(2):
            assert upload(c, fcs_202).status_code == 201
        r = c.post(f"{API}/flow/gates", json={"uploads": ["u1", "u2"], "settings": {}})
        assert wait_job(c, r.json()["job"]["id"])["status"] == "done"
        gate = c.get(f"{API}/flow/gates/g1").json()
        channels = [ch["pnn"] for ch in gate["files"][0]["channels"]]
        body = {"pops": [[1], [1]], "channels": channels[2:4]}
        r = c.post(SETS, json=body)
        assert r.status_code == 202, r.text
        assert wait_job(c, r.json()["job"]["id"])["status"] == "done"
        first = c.get(f"{SETS}/l1").json()
    return {
        "data": settings.data_dir,
        "gate": gate,
        "channels": channels,
        "body": body,
        "l1": first,
    }


@pytest.fixture
def on_copy(base, tmp_path):
    """on_copy(workers=1, **caps) -> a started client on a copy of base's data folder."""
    clients = []

    def start(workers: int = 1, **caps):
        settings = make_settings(tmp_path, workers=workers, caps=caps)
        shutil.copytree(base["data"], settings.data_dir)
        client = new_client(settings)
        client.__enter__()
        clients.append(client)
        return client

    yield start
    for c in clients:
        c.__exit__(None, None, None)


def folder(c, lid: str, gid: str = "g1"):
    return c.app.state.dn.settings.data_dir / "ws" / "local" / "gates" / gid / "livecells" / lid


def jobs(c) -> list[dict]:
    return c.get(f"{API}/jobs").json()["jobs"]


def test_refusals_name_their_field(base, on_copy):
    """S13: 404 for an unknown gate or set, 422 with param for each field, and no job started."""
    c = on_copy(livecells_channels_max=2, livecells_filters_max=4)
    caps = c.app.state.dn.settings.caps
    body, channels = base["body"], base["channels"]
    before = len(jobs(c))
    assert_error(c.get(f"{API}/flow/gates/g9/livecells"), 404, "not_found")
    assert_error(c.post(f"{API}/flow/gates/g9/livecells", json=body), 404, "not_found")
    n_pops = len(base["gate"]["files"][0]["populations"])
    for pops in ([[1]], [[n_pops + 1], [1]], [[], []], [[0], [1]]):
        assert_error(c.post(SETS, json=body | {"pops": pops}), 422, "invalid_setting", "pops")
    for chosen in ([], channels[2:5], [channels[2], channels[2]], [1]):
        r = c.post(SETS, json=body | {"channels": chosen})
        assert_error(r, 422, "invalid_setting", "channels")
    for bins in (caps.livecells_bins_min - 1, caps.livecells_bins_max + 1, 12.5):
        assert_error(c.post(SETS, json=body | {"bins": bins}), 422, "invalid_setting", "bins")
    # "auto", spelt so, or a number from 0; true and false are not 1 and 0, and a list of
    # cofactors per channel isn't taken
    for cofactor in (-1, "x", "Auto", "150", [150], [150, 6000], True, False):
        r = c.post(SETS, json=body | {"cofactor": cofactor})
        assert_error(r, 422, "invalid_setting", "cofactor")
    assert_error(c.post(SETS, json=body | {"extra": 1}), 422, "invalid_setting")
    assert_error(c.get(f"{SETS}/l9"), 404, "not_found")
    counts = f"{SETS}/l1/counts"
    assert_error(c.post(f"{SETS}/l9/counts", json={"row_filters": []}), 404, "not_found")
    held = base["l1"]["request"]["channels"]
    edge = base["l1"]["histograms"]["channels"][0]["edges"][0]  # a value from the data
    one = {"column": held[0], "op": ">", "value": edge}
    too_many = [one] * (caps.livecells_filters_max + 1)
    for filters in (too_many, [one | {"column": channels[0]}], [one | {"op": "~"}]):
        r = c.post(counts, json={"row_filters": filters})
        assert_error(r, 422, "invalid_setting", "row_filters")
    assert len(jobs(c)) == before


def test_a_channel_with_a_lone_surrogate_is_refused(base, on_copy):
    """Half a UTF-16 surrogate pair, which a JSON escape can carry and UTF-8 cannot encode, is
    refused before a set is kept, whatever the rest of the name: a set that held one failed every
    answer that lists it, and a refusal naming it failed too. The body goes as json.dumps writes
    it."""
    c = on_copy()
    before = len(jobs(c))
    for bad in ("\ud800-A", "FSC\udfff-A"):
        body = base["body"] | {"channels": [base["channels"][2], bad]}
        r = c.post(SETS, content=json.dumps(body), headers={"content-type": "application/json"})
        err = assert_error(r, 422, "invalid_setting", "channels")
        assert err["message"] == (
            "A channel name has a lone surrogate (U+D800 to U+DFFF), which is not a character."
        )
    assert c.get(SETS).status_code == 200
    assert len(jobs(c)) == before


def test_a_refusal_that_names_a_lone_surrogate_still_answers(base, on_copy):
    """The package's cofactor check and the counts' channel check name the value they refuse; one
    that held half a surrogate pair could not be encoded, so the refusal answered 500. An error
    message holds U+FFFD in its place, and the 422 keeps its param."""
    c = on_copy()
    sent = {"content-type": "application/json"}
    body = base["body"] | {"cofactor": "\ud800"}
    r = c.post(SETS, content=json.dumps(body), headers=sent)
    assert "�" in assert_error(r, 422, "invalid_setting", "cofactor")["message"]
    row = {"column": "\ud800-A", "op": ">", "value": 0}
    r = c.post(f"{SETS}/l1/counts", content=json.dumps({"row_filters": [row]}), headers=sent)
    err = assert_error(r, 422, "invalid_setting", "row_filters")
    assert err["message"].startswith("�-A is not one of this set's channels")


def test_every_channel_scatter_included(base, on_copy):
    """At the trial caps a set takes every channel of the file, forward and side scatter too
    (no channel name is assumed, so a file from any instrument can be filtered on any of its
    channels), past the viability dye and CD45, and counts take a filter on each and more. (The
    channel cap's own refusal is in test_refusals_name_their_field.)"""
    c = on_copy(
        livecells_channels_max=TRIAL_CAPS.livecells_channels_max,
        livecells_filters_max=TRIAL_CAPS.livecells_filters_max,
    )
    assert TRIAL_CAPS.livecells_channels_max > 4 and TRIAL_CAPS.livecells_filters_max > 4
    channels = base["channels"]
    assert channels[:2] == ["FSC-A", "SSC-A"] and len(channels) == 5  # 202's recorded channels
    r = c.post(SETS, json=base["body"] | {"channels": channels})
    assert r.status_code == 202, r.text
    assert wait_job(c, r.json()["job"]["id"])["status"] == "done"
    lid = r.json()["livecells_id"]
    hist = c.get(f"{SETS}/{lid}").json()["histograms"]
    assert [h["channel"] for h in hist["channels"]] == channels
    # a line on each channel at its middle edge, plus two more: five filters, past the old four
    filters = [
        {"column": h["channel"], "op": ">", "value": h["edges"][len(h["edges"]) // 2]}
        for h in hist["channels"]
    ]
    filters += [f | {"op": "<", "value": 2 * h["hi"]} for f, h in zip(filters, hist["channels"])]
    filters = filters[:5]
    r = c.post(f"{SETS}/{lid}/counts", json={"row_filters": filters})
    assert r.status_code == 200, r.text
    assert len(r.json()["row_filters"]) == 5
    too_many = [filters[0]] * (TRIAL_CAPS.livecells_filters_max + 1)
    r = c.post(f"{SETS}/{lid}/counts", json={"row_filters": too_many})
    assert_error(r, 422, "invalid_setting", "row_filters")


def test_local_mode_caps_neither_channels_nor_filters():
    """Local mode takes any number of channels and of counts filters; trial mode caps both."""
    assert LOCAL_CAPS.livecells_channels_max is None
    assert LOCAL_CAPS.livecells_filters_max is None


def test_a_repeated_request_reuses_its_set(base, on_copy):
    """S15: an equal request (pops in another order) returns l1 and its job, starting none; a
    different one starts a new set."""
    c = on_copy()
    before = len(jobs(c))
    again = base["body"] | {"pops": [list(reversed(p)) for p in base["body"]["pops"]]}
    r = c.post(SETS, json=again)
    assert r.status_code == 202, r.text
    assert r.json()["livecells_id"] == "l1"
    assert r.json()["job"]["id"] == base["l1"]["job"]
    assert len(jobs(c)) == before
    other = c.post(SETS, json=base["body"] | {"bins": base["l1"]["request"]["bins"] // 2})
    assert other.json()["livecells_id"] == "l2" and len(jobs(c)) == before + 1
    assert wait_job(c, other.json()["job"]["id"])["status"] == "done"


def test_the_list_and_the_cache_read_the_sets_under_the_workspace_lock(base, on_copy):
    """The gate's list and a POST the cache answers run in the threadpool, beside a request that
    adds a set or a gate delete that drops them, so each goes over the sets only while it holds
    the workspace's lock."""
    c = on_copy()
    sets = watch(c.app.state.dn.workspaces.local(), "livecells")
    assert [s["id"] for s in c.get(SETS).json()["livecells"]] == ["l1"]
    assert c.post(SETS, json=base["body"]).json()["livecells_id"] == "l1"
    assert sets.free and not any(sets.free), sets.free


# a set's histograms, in order: drawn on each channel's own auto cofactor, or on one number
AUTO_KEYS = [
    "cofactor_from", "bins", "kept", "files", "channels", "cofactors", "negative_fraction",
    "negative_sd",
]  # fmt: skip
ONE_KEYS = ["cofactor", "cofactor_from", "range", "bins", "kept", "files", "channels"]


def test_the_cofactor_is_auto_unless_a_number_is_sent(base, on_copy):
    """A request without a cofactor asks for "auto": each channel's histogram is drawn on the
    cofactor a run clustering the kept cells would pick for it, from their spread below 0, and
    the histograms say so, with no single cofactor and no range. "auto" sent is the same
    request, so the cache answers it; a number is used as set for every channel."""
    c = on_copy()
    l1 = base["l1"]
    assert l1["request"]["cofactor"] == "auto"
    hist = l1["histograms"]
    assert list(hist) == AUTO_KEYS and hist["cofactor_from"] == "auto"
    n = len(base["body"]["channels"])
    assert len(hist["cofactors"]) == len(hist["negative_fraction"]) == len(hist["negative_sd"]) == n
    assert all(cof >= 150.0 for cof in hist["cofactors"])  # the rule's floor
    # the log gives the span of the cofactors, one number when they are all the same
    lo, hi = (f"{v:,.0f}" for v in (min(hist["cofactors"]), max(hist["cofactors"])))
    span = lo if lo == hi else f"{lo}-{hi}"
    log = c.get(f"{API}/jobs/{l1['job']}").json()["log_tail"]
    assert [line for line in log if line.startswith("Histogram cofactor")] == [
        f"Histogram cofactor per channel (auto): {span}"
    ]
    before = len(jobs(c))
    again = c.post(SETS, json=base["body"] | {"cofactor": "auto"}).json()
    assert again["livecells_id"] == "l1" and len(jobs(c)) == before

    r = c.post(SETS, json=base["body"] | {"cofactor": 6000})
    assert r.status_code == 202, r.text
    job = wait_job(c, r.json()["job"]["id"])
    assert job["status"] == "done"
    assert "Histogram cofactor 6000 (set)" in job["log_tail"]
    got = c.get(f"{SETS}/{r.json()['livecells_id']}").json()
    assert got["request"]["cofactor"] == 6000.0
    set_hist = got["histograms"]
    assert list(set_hist) == ONE_KEYS
    assert (set_hist["cofactor"], set_hist["cofactor_from"], set_hist["range"]) == (
        6000.0,
        "set",
        None,
    )
    assert set_hist["channels"][0]["edges"] != hist["channels"][0]["edges"]  # another scale


def test_sets_made_under_earlier_rules_still_load(base, on_copy):
    """A set's histograms.json from before keeps reading as it was drawn: one of the header
    rule, one auto cofactor with the range it was picked by, as auto with its range; one from
    before the cofactor could be auto, which was asked for a number, as set with no range.
    Neither gains per-channel cofactors, and their bins are served as written."""
    c = on_copy()
    hist = base["l1"]["histograms"]
    path = folder(c, "l1") / "histograms.json"
    now = json.loads(path.read_text(encoding="utf-8"))
    drawn = {k: now[k] for k in ("bins", "kept", "files", "channels")}

    header_rule = {"cofactor": 150.0, "cofactor_from": "auto", "range": 262144.0, **drawn}
    path.write_text(json.dumps(header_rule), encoding="utf-8")
    was = c.get(f"{SETS}/l1").json()["histograms"]
    assert list(was) == ONE_KEYS
    assert (was["cofactor"], was["cofactor_from"], was["range"]) == (150.0, "auto", 262144.0)
    assert was["channels"] == hist["channels"]

    before_auto = {"cofactor": 6000.0, **drawn}
    path.write_text(json.dumps(before_auto), encoding="utf-8")
    was = c.get(f"{SETS}/l1").json()["histograms"]
    assert list(was) == ONE_KEYS
    assert (was["cofactor"], was["cofactor_from"], was["range"]) == (6000.0, "set", None)
    assert was["channels"] == hist["channels"]


def test_an_auto_set_of_the_header_rule_no_longer_answers_auto(base, on_copy):
    """A set asked for "auto" while auto picked one number from the headers is drawn on that
    number, where auto now gives each channel its own: the same request starts a new set, drawn
    per channel, which then answers it, so the step never shows the old axes as auto's."""
    c = on_copy()
    path = folder(c, "l1") / "histograms.json"
    now = json.loads(path.read_text(encoding="utf-8"))
    drawn = {k: now[k] for k in ("bins", "kept", "files", "channels")}
    header_rule = {"cofactor": 6000.0, "cofactor_from": "auto", "range": 3162277.0, **drawn}
    path.write_text(json.dumps(header_rule), encoding="utf-8")
    assert base["l1"]["request"]["cofactor"] == "auto"
    before = len(jobs(c))
    r = c.post(SETS, json=base["body"])
    assert r.status_code == 202, r.text
    lid = r.json()["livecells_id"]
    assert lid != "l1" and len(jobs(c)) == before + 1
    assert wait_job(c, r.json()["job"]["id"])["status"] == "done"
    assert list(c.get(f"{SETS}/{lid}").json()["histograms"]) == AUTO_KEYS
    again = c.post(SETS, json=base["body"] | {"cofactor": "auto"}).json()
    assert again["livecells_id"] == lid and len(jobs(c)) == before + 1


def test_active_sets_hold_their_gate_and_the_per_gate_cap(base, on_copy):
    """S16 and S17 with every new job held in the queue: a gate that is not done refuses the
    step, a set not done refuses counts, an active set refuses its gate's delete, a new set past
    the cap evicts the oldest finished one and is refused when none is finished, a cancelled set
    leaves no folder, and the gate's delete takes its sets with it."""
    c = on_copy(workers=0, livecells_per_gate=2)
    body = base["body"]
    r = c.post(f"{API}/flow/gates", json={"uploads": ["u1"], "settings": {}})
    assert r.json()["gate_id"] == "g2" and r.json()["job"]["status"] == "queued"
    assert_error(c.get(f"{API}/flow/gates/g2/livecells"), 409, "wrong_state")
    assert_error(c.post(f"{API}/flow/gates/g2/livecells", json=body), 409, "wrong_state")
    assert_error(c.get(f"{API}/flow/gates/g2/livecells/l1"), 404, "not_found")  # g1's set

    bins = base["l1"]["request"]["bins"]
    a = c.post(SETS, json=body | {"bins": bins // 2}).json()
    assert a["livecells_id"] == "l2" and a["job"]["status"] == "queued"
    assert (a["job"]["kind"], a["job"]["gate_id"], a["job"]["run_id"]) == ("livecells", "g1", None)
    assert c.post(SETS, json=body | {"bins": bins // 2}).json()["livecells_id"] == "l2"
    queued = c.get(f"{SETS}/l2").json()
    assert queued["status"] == "queued" and queued["histograms"] is None
    assert_error(c.post(f"{SETS}/l2/counts", json={"row_filters": []}), 409, "wrong_state")
    r = c.delete(f"{API}/flow/gates/g1")
    assert_error(r, 409, "wrong_state")
    assert "l2" in r.json()["error"]["message"]

    assert folder(c, "l1").is_dir()
    b = c.post(SETS, json=body | {"bins": bins // 4}).json()  # the cap is 2: l1 goes
    assert b["livecells_id"] == "l3"
    assert_error(c.get(f"{SETS}/l1"), 404, "not_found")
    assert not folder(c, "l1").exists()
    listed = c.get(SETS).json()["livecells"]
    assert [s["id"] for s in listed] == ["l2", "l3"]
    assert_error(c.post(SETS, json=body | {"bins": bins // 8}), 409, "wrong_state")

    for s in (a, b):
        r = c.post(f"{API}/jobs/{s['job']['id']}/cancel")
        assert r.status_code in (200, 202), r.text
        assert c.get(f"{SETS}/{s['livecells_id']}").json()["status"] == "cancelled"
        assert not folder(c, s["livecells_id"]).exists()
    assert c.delete(f"{API}/flow/gates/g1").status_code == 204
    assert_error(c.get(SETS), 404, "not_found")
    assert not folder(c, "l2").parent.parent.exists()
    meta = c.app.state.dn.settings.data_dir / "ws" / "local" / "meta.json"
    assert json.loads(meta.read_text(encoding="utf-8"))["livecells"] == {}


def test_the_cells_cap_and_the_counts_rate(base, on_copy):
    """S16: a set whose populations keep more cells than livecells_cells_max fails naming pops,
    and a failed set never answers a request again; counts past the minute's cap get 429 with
    Retry-After. The cap is l1's own kept cells, read from its histograms."""
    kept = base["l1"]["histograms"]["kept"]
    c = on_copy(livecells_cells_max=kept, livecells_counts_per_ip_minute=3)
    body = base["body"]
    n_pops = len(base["gate"]["files"][0]["populations"])
    assert n_pops >= 2
    at_cap = c.post(SETS, json=body | {"bins": base["l1"]["request"]["bins"] // 2}).json()
    assert wait_job(c, at_cap["job"]["id"])["status"] == "done"  # exactly the cap is allowed
    more = body | {"pops": [list(range(1, n_pops + 1))] * 2}
    r = c.post(SETS, json=more).json()
    job = wait_job(c, r["job"]["id"])
    assert job["status"] == "failed"
    assert (job["error"]["code"], job["error"]["param"]) == ("invalid_setting", "pops")
    assert not folder(c, r["livecells_id"]).exists()
    assert c.post(SETS, json=more).json()["livecells_id"] != r["livecells_id"]

    url = f"{SETS}/l1/counts"
    for _ in range(3):
        assert c.post(url, json={"row_filters": []}).status_code == 200
    limited = c.post(url, json={"row_filters": []})
    assert_error(limited, 429, "rate_limited")
    assert int(limited.headers["retry-after"]) >= 1


def test_new_sets_count_toward_the_hourly_job_cap(base, on_copy):
    """S15 and section 2.2: a new set is one of its address's jobs in the hour, like a gate or a
    run, and the cache's answer, which starts no job, counts nothing."""
    c = on_copy(workers=0, jobs_per_ip_hour=2)
    body, bins = base["body"], base["l1"]["request"]["bins"]
    for _ in range(3):  # l1 is done: the cache answers
        assert c.post(SETS, json=body).json()["livecells_id"] == "l1"
    a = c.post(SETS, json=body | {"bins": bins // 2})
    assert a.status_code == 202, a.text
    again = c.post(SETS, json=body | {"bins": bins // 2})  # the queued set answers
    assert again.json()["livecells_id"] == a.json()["livecells_id"]
    b = c.post(SETS, json=body | {"bins": bins // 4})
    assert b.status_code == 202, b.text
    assert_error(c.post(SETS, json=body | {"bins": bins // 8}), 429, "rate_limited")
    gate = c.post(f"{API}/flow/gates", json={"uploads": ["u1"], "settings": {}})
    assert_error(gate, 429, "rate_limited")
    assert c.post(SETS, json=body).json()["livecells_id"] == "l1"  # a hit is still answered


def test_concurrent_loads_stay_within_the_memory_sets(base):
    """Section 2.4's livecells_memory_sets bounds the sets loaded for counts at once, not only
    the sets kept: twelve threads ask for six sets not loaded yet, each set twice, and each load
    reads l1's real values.npz and holds its slot for a moment. At most 2 loads run at once, each
    set is loaded once (its second asker waits for the first load), and every asker gets the
    values."""
    from dnapp.core.package import livecells
    from dnapp.features.livecells.service import LoadedSets

    path = base["data"] / "ws" / "local" / "gates" / "g1" / "livecells" / "l1" / "values.npz"
    size, keys = 2, [("local", f"l{i}") for i in range(1, 7)]
    sets = LoadedSets(size)
    lock = threading.Lock()
    running, peak, loads = 0, 0, Counter()
    start = threading.Barrier(2 * len(keys))
    got: dict[int, object] = {}

    def loader(key):
        def load():
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
                loads[key] += 1
            try:
                time.sleep(0.2)  # every asker arrives while the first loads are running
                return livecells.load(path)
            finally:
                with lock:
                    running -= 1

        return load

    def ask(i: int, key) -> None:
        start.wait()
        got[i] = sets.get(key, loader(key))

    threads = [threading.Thread(target=ask, args=(i, key)) for i, key in enumerate(keys + keys)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)
    assert peak <= size, peak
    assert loads == Counter(dict.fromkeys(keys, 1)), loads
    want = livecells.load(path)
    assert len(got) == 2 * len(keys)
    for v in got.values():
        assert livecells.count(v, []) == livecells.count(want, [])


def test_a_set_cut_off_by_a_restart_leaves_no_folder(base, tmp_path):
    """A set whose job the server's stop cut off (here held in the queue, its folder then half
    written the way a killed worker leaves it: request.json and the first half of values.npz,
    both from l1) is failed after the restart and its folder is gone, as is a set folder with
    no record (the server stopped between starting the job and saving the set). l1 is kept and
    still counts, and the same request starts a new set instead of reading the old folder."""
    settings = make_settings(tmp_path, workers=0)
    shutil.copytree(base["data"], settings.data_dir)
    body = base["body"] | {"bins": base["l1"]["request"]["bins"] // 2}
    with new_client(settings) as c:
        r = c.post(SETS, json=body)
        assert r.status_code == 202 and r.json()["job"]["status"] == "queued"
        lid = r.json()["livecells_id"]
        cut, l1 = folder(c, lid), folder(c, "l1")
        orphan = folder(c, "l99")
        request = c.get(f"{SETS}/{lid}").json()["request"]
    values = (l1 / "values.npz").read_bytes()
    for half in (cut, orphan):
        half.mkdir(parents=True)
        (half / "request.json").write_text(json.dumps(request), encoding="utf-8")
        (half / "values.npz").write_bytes(values[: len(values) // 2])

    with new_client(make_settings(tmp_path)) as c:
        s = c.get(f"{SETS}/{lid}").json()
        assert s["status"] == "failed" and s["histograms"] is None
        assert not cut.exists() and not orphan.exists()
        assert l1.is_dir() and c.get(f"{SETS}/l1").json()["status"] == "done"
        assert c.post(f"{SETS}/l1/counts", json={"row_filters": []}).status_code == 200
        assert_error(c.post(f"{SETS}/{lid}/counts", json={"row_filters": []}), 409, "wrong_state")
        new = c.post(SETS, json=body).json()
        assert new["livecells_id"] not in (lid, "l1")
        assert wait_job(c, new["job"]["id"])["status"] == "done"
        assert c.get(f"{SETS}/{new['livecells_id']}").json()["histograms"]["kept"] > 0
