"""Live cells end to end on real flow events (contract-livecells.md S14, S15, S17): 202's recorded
events uploaded twice, gated, and a live-cells set made from them. Its histograms are checked
against the package run on the same gate folder, and its counts against the package and against
the filtered column of a flow run sent the same filters. The thresholds sit at each histogram's
middle edge, as the web fixtures place them: derived from the data, never typed, and never
offered to a user. The refusals, the cache and the caps are tested in features/livecells."""

from __future__ import annotations

import json
import threading
import time

import numpy as np
import pandas as pd
import pytest

from testkit import API, assert_no_paths, make_settings, new_client, upload, wait_job

JOB_KEYS = {
    "id", "kind", "status", "progress", "stage", "message", "log_tail", "created", "started",
    "finished", "run_id", "gate_id", "error",
}  # fmt: skip
SET_KEYS = {"id", "gate_id", "status", "created", "job", "request", "histograms"}
COUNTS_KEYS = {"row_filters", "kept", "passed", "files"}
COUNT_FILE_KEYS = {"number", "name", "events", "kept", "passed", "left_out"}
# the histograms of an auto set, in order: drawn on each channel's own cofactor, so no single
# cofactor and no header range, and each channel's cofactor and how it was picked after the bins
AUTO_HISTOGRAM_KEYS = [
    "cofactor_from", "bins", "kept", "files", "channels", "cofactors", "negative_fraction",
    "negative_sd",
]  # fmt: skip


@pytest.fixture(scope="module")
def lc(tmp_path_factory, fcs_202):
    settings = make_settings(tmp_path_factory.mktemp("livecells"))
    client = new_client(settings)
    client.__enter__()
    for _ in range(2):
        assert upload(client, fcs_202).status_code == 201
    r = client.post(f"{API}/flow/gates", json={"uploads": ["u1", "u2"], "settings": {}})
    assert wait_job(client, r.json()["job"]["id"])["status"] == "done"
    gate = client.get(f"{API}/flow/gates/g1").json()
    # every channel after FSC-A and SSC-A: three markers, more than the viability dye and CD45
    channels = [c["pnn"] for c in gate["files"][0]["channels"]][2:]
    assert len(channels) == 3 and not any(c.startswith(("FSC", "SSC")) for c in channels)
    pops = [[2, 1], [1]]  # sent unsorted: the record keeps them sorted
    r = client.post(f"{API}/flow/gates/g1/livecells", json={"pops": pops, "channels": channels})
    assert r.status_code == 202, r.text
    started = r.json()
    job = wait_job(client, started["job"]["id"])
    yield {
        "client": client,
        "settings": settings,
        "gate": gate,
        "channels": channels,
        "started": started,
        "job": job,
        "set": client.get(f"{API}/flow/gates/g1/livecells/l1").json(),
    }
    client.__exit__(None, None, None)


def gate_folder(lc):
    return lc["settings"].data_dir / "ws" / "local" / "gates" / "g1"


def middle_filters(hist) -> list[dict]:
    """One filter per channel at its histogram's middle edge, turned back to a raw value with
    that channel's cofactor (the one cofactor of a set drawn on a number) and rounded to 4
    significant digits as the web's line writes it: the first channel keeping below, the others
    above."""
    out = []
    for j, ch in enumerate(hist["channels"]):
        t = ch["edges"][len(ch["edges"]) // 2]
        c = hist["cofactors"][j] if "cofactors" in hist else hist["cofactor"]
        raw = float(f"{c * np.sinh(t):.4g}")
        out.append({"column": ch["channel"], "op": "<" if j == 0 else ">", "value": raw})
    return out


def package_auto(lc, pops, channels, settings: dict | None = None) -> dict:
    """The Transform stage the package's own rule gives a run of gate g1 with settings (a
    run.json's, or the defaults) clustering channels of the cells pops keep."""
    from datanuggets_flow.pipeline import auto_cofactor, negative_tally
    from datanuggets_flow.settings import ClusterSettings
    from datanuggets_flow.state import load_gates

    samples = load_gates(gate_folder(lc)).samples
    checked = ClusterSettings.from_dict(settings or {})
    return auto_cofactor(negative_tally(samples, pops, channels, checked)).transform()


def test_the_job_and_the_record(lc):
    started, job, rec = lc["started"], lc["job"], lc["set"]
    assert set(started) == {"job", "livecells_id"} and started["livecells_id"] == "l1"
    assert job["status"] == "done", job
    assert set(job) == JOB_KEYS  # S17: the key set is unchanged
    assert (job["kind"], job["gate_id"], job["run_id"]) == ("livecells", "g1", None)
    assert job["progress"] == 1.0
    assert set(rec) == SET_KEYS and rec["status"] == "done" and rec["job"] == job["id"]
    assert rec["request"]["pops"] == [[1, 2], [1]]
    assert rec["request"]["channels"] == lc["channels"]
    config = lc["client"].get(f"{API}/config").json()["defaults"]["cluster"]
    assert rec["request"]["bins"] == 128 and rec["request"]["cofactor"] == config["cofactor"]
    assert config["cofactor"] == "auto"
    # the log gives the span of the channels' cofactors, rounded as the run's Transform lines are
    cofactors = rec["histograms"]["cofactors"]
    span = [f"{c:,.0f}" for c in (min(cofactors), max(cofactors))]
    assert span[0] != span[1]  # 202's CD8 is picked above the floor, its CD3 and CD4 at it
    line = f"Histogram cofactor per channel (auto): {span[0]}-{span[1]}"
    assert line in job["log_tail"]
    folder = gate_folder(lc) / "livecells" / "l1"
    assert sorted(p.name for p in folder.iterdir()) == [
        "histograms.json", "request.json", "values.npz"
    ]  # fmt: skip
    assert json.loads((folder / "request.json").read_text()) == rec["request"]
    assert_no_paths(lc["client"].get(f"{API}/flow/gates/g1/livecells/l1").text, folder.parent)


def test_the_step_lists_file_1s_channels_and_the_package_suggestion(lc):
    from datanuggets_flow.livecells import suggest_channels

    body = lc["client"].get(f"{API}/flow/gates/g1/livecells").json()
    assert set(body) == {"gate_id", "channels", "suggested", "livecells"}
    channels = lc["gate"]["files"][0]["channels"]
    assert body["gate_id"] == "g1" and body["channels"] == channels
    pnn, pns = [c["pnn"] for c in channels], [c["pns"] for c in channels]
    assert body["suggested"] == suggest_channels(pnn, pns)  # names only, never a value
    assert body["livecells"] == [{k: lc["set"][k] for k in ("id", "status", "created", "request")}]


def test_histograms_equal_the_package_on_the_same_gate(lc):
    """S14: the payload's histograms are channel_histograms(kept_values(...)), unrounded, with
    how the cofactors were chosen first: auto, each channel drawn on the cofactor kept_values
    picked from the kept cells, the one a run clustering them with no row filters picks."""
    from datanuggets_flow.livecells import channel_histograms, kept_values
    from datanuggets_flow.state import load_gates

    req = lc["set"]["request"]
    samples = load_gates(gate_folder(lc)).samples
    kept = kept_values(samples, req["pops"], req["channels"])
    assert req["cofactor"] == "auto" and kept.cofactor.source == "auto"
    want = channel_histograms(kept, bins=req["bins"], cofactor=req["cofactor"])
    want = {"cofactor_from": want.pop("cofactor_from"), **want}
    got = lc["set"]["histograms"]
    assert json.loads(json.dumps(want)) == got
    assert list(got) == AUTO_HISTOGRAM_KEYS and got["cofactor_from"] == "auto"
    run = package_auto(lc, req["pops"], req["channels"])
    for key in ("cofactors", "negative_fraction", "negative_sd"):
        assert got[key] == run[key] and len(got[key]) == len(req["channels"]), key
    assert got["kept"] == sum(f["kept"] for f in got["files"]) > 0
    for ch in got["channels"]:
        assert len(ch["edges"]) == req["bins"] + 1 and len(ch["counts"]) == req["bins"]


def test_counts_equal_the_package_and_the_flow_runs_filtered(lc):
    """S14: the counts response is count_kept on the saved values, and a flow run sent the same
    row_filters writes the same passing cells into selection.csv's filtered. The run, sent no
    cofactor, picks each channel's cofactor by the rule the histograms' were picked by, from the
    cells it clusters: the ones that pass the filters, where the histograms' come from every
    kept cell."""
    from datanuggets_flow.livecells import count_kept, load_kept_values

    client = lc["client"]
    filters = middle_filters(lc["set"]["histograms"])
    r = client.post(f"{API}/flow/gates/g1/livecells/l1/counts", json={"row_filters": filters})
    assert r.status_code == 200, r.text
    got = r.json()
    assert set(got) == COUNTS_KEYS and all(set(f) == COUNT_FILE_KEYS for f in got["files"])
    values = load_kept_values(gate_folder(lc) / "livecells" / "l1" / "values.npz")
    assert got == count_kept(values, got["row_filters"])
    assert len(got["row_filters"]) == len(lc["channels"]) == 3
    assert 0 < got["passed"] < got["kept"]  # the middle edges keep some cells, not all
    every = client.post(f"{API}/flow/gates/g1/livecells/l1/counts", json={"row_filters": []})
    assert [f["passed"] for f in every.json()["files"]] == [f["kept"] for f in got["files"]]

    body = {
        "gate_id": "g1",
        "pops": lc["set"]["request"]["pops"],
        "row_filters": filters,
        "dn_num1": 500,
        "dn_num2": 50,
        "k": 3,
        "tsne": False,
    }
    run = client.post(f"{API}/flow/runs", json=body)
    assert run.status_code == 202, run.text
    assert wait_job(client, run.json()["job"]["id"])["status"] == "done"
    rid = run.json()["run_id"]
    selection = pd.read_csv(
        lc["settings"].data_dir / "ws" / "local" / "runs" / rid / "selection.csv"
    )
    assert selection["kept"].tolist() == [f["kept"] for f in got["files"]]
    assert selection["filtered"].tolist() == [f["passed"] for f in got["files"]]
    record = client.get(f"{API}/runs/{rid}").json()["record"]
    assert record["channels"] == lc["set"]["request"]["channels"]
    want = package_auto(lc, body["pops"], record["channels"], record["settings"])
    assert record["transform"] == want and record["transform"]["cofactor_from"] == "auto"
    # the cells the filters drop count for nothing, so the shares below 0 move off the histograms'
    hist = lc["set"]["histograms"]
    assert record["transform"]["negative_fraction"] != hist["negative_fraction"]


def test_counts_read_no_fcs_and_leave_the_loop_free(lc):
    """S15: with the gated FCS uploads gone from disk, counts still answer, from values.npz;
    and /health answers within 200 ms while counts run in the threadpool."""
    client = lc["client"]
    filters = middle_filters(lc["set"]["histograms"])
    url = f"{API}/flow/gates/g1/livecells/l1/counts"
    want = client.post(url, json={"row_filters": filters}).json()
    uploads = lc["settings"].data_dir / "ws" / "local" / "uploads"
    fcs = sorted(uploads.rglob("*.fcs"))
    assert len(fcs) == 2
    moved = [p.rename(p.with_name(p.name + ".away")) for p in fcs]
    try:
        assert not list(uploads.rglob("*.fcs"))
        lc["client"].app.state.dn.features["livecells"].loaded.sets.clear()  # force a re-read
        assert client.post(url, json={"row_filters": filters}).json() == want
        stop, worst, errors = threading.Event(), [0.0], []

        def hammer():
            while not stop.is_set():
                if client.post(url, json={"row_filters": filters}).status_code != 200:
                    errors.append(1)

        threads = [threading.Thread(target=hammer) for _ in range(2)]
        for t in threads:
            t.start()
        try:
            for _ in range(20):
                t0 = time.perf_counter()
                assert client.get(f"{API}/health").status_code == 200
                worst[0] = max(worst[0], time.perf_counter() - t0)
                time.sleep(0.02)
        finally:
            stop.set()
            for t in threads:
                t.join()
        assert not errors and worst[0] < 0.2, (errors, worst)
    finally:
        for p, back in zip(moved, fcs):
            p.rename(back)
