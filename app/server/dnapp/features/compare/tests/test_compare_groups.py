"""The comparison payload's groups (contract section 3.5) on real flow events: 202's recorded
events uploaded five times, gated, and clustered with one group per file, named None, 01, 1, NA
and nan, and no population chosen in file 1. Every one of those names is a valid group, and
pandas' defaults would read None, NA and nan as missing and 01 and 1 as the same number; the
payloads keep each as the text the user gave. The group of file 1 has no kept file but has rows in
group_summary.csv, so it stays in groups with 0 kept files. log2fc_pseudocount is the
group_summary.csv column of that name, or null without it."""

from __future__ import annotations

import shutil

import pandas as pd
import pytest

from testkit import API, make_settings, new_client, upload, wait_job

GROUPS = ["None", "01", "1", "NA", "nan"]
POPS = [[], [1], [1], [1], [1]]
SMALL = {"dn_num1": 1500, "dn_num2": 150, "k": 6, "tsne": False}
TEXT = {"keep_default_na": False, "na_values": [""]}


def as_written(path, *columns):
    """A run CSV with the named columns as the text in the file (an empty cell is missing)."""
    return pd.read_csv(path, dtype={c: str for c in columns}, **TEXT)


@pytest.fixture(scope="module")
def base(tmp_path_factory, fcs_202):
    settings = make_settings(tmp_path_factory.mktemp("compare-groups"))
    with new_client(settings) as c:
        for _ in GROUPS:
            assert upload(c, fcs_202).status_code == 201
        uploads = [f"u{i}" for i in range(1, len(GROUPS) + 1)]
        r = c.post(f"{API}/flow/gates", json={"uploads": uploads, "settings": {}})
        assert wait_job(c, r.json()["job"]["id"])["status"] == "done"
        body = {"gate_id": "g1", "pops": POPS, "groups": GROUPS, **SMALL}
        r = c.post(f"{API}/flow/runs", json=body)
        assert r.status_code == 202, r.text
        assert wait_job(c, r.json()["job"]["id"])["status"] == "done"
    return settings.data_dir


@pytest.fixture
def on_copy(base, tmp_path):
    """on_copy(edit=None) -> (client, run folder) on a copy of base's data folder; edit(out) runs
    on the copy's run folder before the server starts."""
    clients = []

    def start(edit=None):
        settings = make_settings(tmp_path / f"copy{len(clients)}")
        shutil.copytree(base, settings.data_dir)
        out = settings.data_dir / "ws" / "local" / "runs" / "r1"
        if edit:
            edit(out)
        client = new_client(settings)
        client.__enter__()
        clients.append(client)
        return client, out

    yield start
    for c in clients:
        c.__exit__(None, None, None)


def test_group_names_stay_the_text_given(on_copy):
    c, out = on_copy()
    cmp = c.get(f"{API}/runs/r1/compare").json()
    assert cmp["groups"] == GROUPS
    assert [f["group"] for f in cmp["files"]] == GROUPS[1:]
    assert cmp["reference"] == "01"
    gs = as_written(out / "group_summary.csv", "group")
    assert [r["group"] for r in cmp["group_summary"]] == gs.group.tolist()
    assert list(dict.fromkeys(gs.group)) == GROUPS
    gm = as_written(out / "group_markers.csv", "group", "label")
    assert [r["group"] for r in cmp["group_markers"]] == gm.group.tolist()
    assert [r["channel"] for r in cmp["group_markers"]] == gm.label.tolist()
    plot = c.get(f"{API}/runs/r1/plot").json()
    assert plot["groups"] == GROUPS[1:]
    assert [f["group"] for f in plot["files"]] == GROUPS[1:]


def test_a_group_with_no_kept_file_stays_with_zero_files(on_copy):
    c, out = on_copy()
    cmp = c.get(f"{API}/runs/r1/compare").json()
    groups = as_written(out / "groups.csv", "group", "file")
    kept = groups[groups.kept.astype(str).str.lower() == "true"]
    assert cmp["group_files"] == [int((kept.group == g).sum()) for g in cmp["groups"]]
    assert cmp["group_files"] == [0, 1, 1, 1, 1]
    rows = [r for r in cmp["group_summary"] if r["group"] == "None"]
    assert len(rows) == cmp["k"] and {r["samples"] for r in rows} == {0}
    assert {r["mean_percent"] for r in rows} == {None}


def _pseudocount(out) -> float:
    """D2's pseudocount from the run's own cluster_summary.csv: the mean over kept files of 50
    over the file's cells, in percentage points (half a cell per file)."""
    s = pd.read_csv(out / "cluster_summary.csv")
    return float((50 / s.groupby("file_number")["cells"].sum()).mean())


def _with_pseudocount(out):
    gs = as_written(out / "group_summary.csv", "group")
    gs["log2fc_pseudocount"] = _pseudocount(out)
    gs.to_csv(out / "group_summary.csv", index=False)


def _without_pseudocount(out):
    gs = as_written(out / "group_summary.csv", "group")
    gs.drop(columns=["log2fc_pseudocount"], errors="ignore").to_csv(
        out / "group_summary.csv", index=False
    )


def test_log2fc_pseudocount_comes_from_group_summary(on_copy):
    c, out = on_copy(_with_pseudocount)
    cmp = c.get(f"{API}/runs/r1/compare").json()
    assert "pseudocount" not in cmp
    assert cmp["log2fc_pseudocount"] == float(f"{_pseudocount(out):.4g}")
    assert cmp["groups"] == GROUPS
    c, _ = on_copy(_without_pseudocount)
    assert c.get(f"{API}/runs/r1/compare").json()["log2fc_pseudocount"] is None
