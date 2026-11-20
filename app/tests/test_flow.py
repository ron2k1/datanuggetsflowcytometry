"""End to end on real flow events: 202's recorded events (FSC-A, SSC-A and three fluorescence
channels, 50,000 events) uploaded twice as two samples, gated, clustered with groups, and the
plot, cells and comparison payloads checked against the run's own CSVs. Also: the run's
downloads, no server path in any payload, and /health answering within 200 ms while the flow
job runs in the worker pool."""

from __future__ import annotations

import io
import sys
import time
import zipfile

import numpy as np
import pandas as pd
import pytest

from testkit import (
    API,
    JOB_KEYS,
    MANIFEST_KEYS,
    PLOT_KEYS,
    assert_error,
    assert_no_paths,
    upload,
    wait_job,
)

GATE_KEYS = {"id", "status", "created", "settings", "files", "figures"}
GATE_FILE_KEYS = {
    "number", "upload", "name", "n_events", "channels", "default_channels", "local_maxima",
    "populations",
}  # fmt: skip
POP_KEYS = {"pop", "events", "percent", "median_fsc", "median_ssc", "peak", "color"}
COMPARE_KEYS = {
    "run_id", "k", "clusters", "files", "counts", "percent", "groups", "group_files", "reference",
    "log2fc_pseudocount", "group_summary", "channels", "cluster_markers", "group_markers",
}  # fmt: skip
SMALL = {"dn_num1": 1500, "dn_num2": 150, "k": 12, "tsne": True}
# The keys of the Transform stage a run gets by default, in order: auto picks each clustered
# channel's cofactor from the cells the run clusters, so the record holds one per channel and no
# single cofactor, nor the range the earlier header rule picked by
AUTO_KEYS = [
    "name", "cofactor_from", "cofactors", "negative_fraction", "negative_sd", "floor",
    "min_negative_fraction",
]  # fmt: skip
# a run.json of the earlier rule, which picked one auto number from the files' headers
HEADER_RULE = {"name": "arcsinh", "cofactor": 150.0, "cofactor_from": "auto", "range": 262144.0}


def package_auto(settings, pops, channels, **over) -> dict:
    """The Transform stage the package's own rule gives a run of gate g1 clustering channels of
    the cells pops keep (after over's row filters, if any): auto_cofactor of their tally."""
    from datanuggets_flow.pipeline import auto_cofactor, negative_tally
    from datanuggets_flow.settings import ClusterSettings
    from datanuggets_flow.state import load_gates

    samples = load_gates(settings.data_dir / "ws" / "local" / "gates" / "g1").samples
    tally = negative_tally(samples, pops, channels, ClusterSettings(**over))
    return auto_cofactor(tally).transform()


@pytest.fixture(scope="module")
def flow(tmp_path_factory, fcs_202):
    from fastapi.testclient import TestClient

    from dnapp.main import create_app
    from testkit import make_settings

    settings = make_settings(tmp_path_factory.mktemp("flow"), "local")
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    client.__enter__()
    for _ in range(2):
        assert upload(client, fcs_202).status_code == 201
    r = client.post(f"{API}/flow/gates", json={"uploads": ["u1", "u2"], "settings": {}})
    assert r.status_code == 202, r.text
    gate_job = wait_job(client, r.json()["job"]["id"])
    yield client, settings, r.json(), gate_job
    client.__exit__(None, None, None)


def test_gate_payload(flow):
    client, settings, started, job = flow
    assert set(started) == {"job", "gate_id"} and started["gate_id"] == "g1"
    assert set(started["job"]) == JOB_KEYS and started["job"]["kind"] == "gate"
    assert job["status"] == "done", job
    g = client.get(f"{API}/flow/gates/g1").json()
    assert set(g) == GATE_KEYS and g["status"] == "done"
    assert g["settings"]["fsc"] == "FSC-A"
    assert g["figures"] == {
        "local_maxima": f"{API}/flow/gates/g1/figures/local_maxima.png",
        "gates": f"{API}/flow/gates/g1/figures/gates.png",
    }
    assert [f["upload"] for f in g["files"]] == ["u1", "u2"]
    assert [f["name"] for f in g["files"]] == ["202.fcs", "202-2.fcs"]
    import json

    gates = json.loads(
        (settings.data_dir / "ws" / "local" / "gates" / "g1" / "gates.json").read_text()
    )
    for f, rec in zip(g["files"], gates["files"]):
        assert set(f) == GATE_FILE_KEYS
        assert f["n_events"] == 50_000 and f["local_maxima"] == rec["local_maxima"]
        assert [c["pnn"] for c in f["channels"]] == rec["pnn"]
        assert f["default_channels"] == [c for c in rec["pnn"][2:]]
        assert len(f["populations"]) == len(rec["populations"]) >= 1
        for p, q in zip(f["populations"], rec["populations"]):
            assert set(p) == POP_KEYS and p["events"] == q["events"] and p["peak"] == q["peak"]
    for name in ("local_maxima.png", "gates.png"):
        r = client.get(f"{API}/flow/gates/g1/figures/{name}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get(f"{API}/flow/gates/g1/figures/gates.json").status_code == 404
    assert_error(client.delete(f"{API}/uploads/u1"), 409, "wrong_state")
    assert_no_paths(client.get(f"{API}/flow/gates/g1").text, settings.data_dir)


@pytest.fixture(scope="module")
def flow_run(flow):
    client, settings, _, _ = flow
    body = {
        "gate_id": "g1",
        "pops": [[1], [1, 2]],
        "groups": ["ctrl", "case"],
        "cells_per_file": 300,
        **SMALL,
    }
    r = client.post(f"{API}/flow/runs", json=body)
    assert r.status_code == 202, r.text
    started = r.json()
    # the event loop stays free while the worker runs (S5)
    worst = 0.0
    while True:
        t0 = time.perf_counter()
        h = client.get(f"{API}/health")
        worst = max(worst, time.perf_counter() - t0)
        assert h.status_code == 200
        job = client.get(f"{API}/jobs/{started['job']['id']}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.1)
    return client, settings, started, job, worst


def test_health_stays_fast_while_a_flow_job_runs(flow_run):
    *_, job, worst = flow_run
    assert job["status"] == "done", job
    assert worst < 0.2, worst


def test_flow_manifest(flow_run):
    client, settings, started, job, _ = flow_run
    assert set(started) == {"job", "run_id"} and started["run_id"] == "r1"
    assert set(started["job"]) == JOB_KEYS and started["job"]["kind"] == "flow"
    m = client.get(f"{API}/runs/r1").json()
    assert set(m) == MANIFEST_KEYS
    assert m["status"] == "done" and m["kind"] == "flow"
    assert m["k"] == 12 and len(m["clusters"]) == 12
    names = {f["name"] for f in m["files"]}
    assert {"selection.csv", "cluster_summary.csv", "nuggets_1.csv", "events_2.csv", "run.json",
            "local_maxima.png", "gates.png", "clusters_pca.png"} <= names  # fmt: skip
    assert "INCOMPLETE.txt" not in names
    assert m["record"]["gates"] == "g1"  # scrubbed to the folder's name
    assert job["progress"] == 1.0
    assert_no_paths(client.get(f"{API}/runs/r1").text, settings.data_dir)


def test_flow_plot_equals_the_run_csvs(flow_run):
    client, settings, *_ = flow_run
    out = settings.data_dir / "ws" / "local" / "runs" / "r1"
    p = client.get(f"{API}/runs/r1/plot").json()
    assert set(p) == PLOT_KEYS
    assert p["kind"] == "flow" and p["method"] is None and p["k"] == 12
    import json

    rec = json.loads((out / "run.json").read_text())
    st = rec["standardize"]
    # the per-channel Transform stage reaches the plot as run.json records it, unrounded, its
    # cofactors in the order of columns
    assert p["transform"] == [
        rec["transform"],
        {"name": "scale", "mean": [float(f"{v:.4g}") for v in st["mean"]],
         "sd": [float(f"{v:.4g}") for v in st["sd"]]},
    ]  # fmt: skip
    assert list(p["transform"][0]) == AUTO_KEYS
    assert len(p["transform"][0]["cofactors"]) == len(p["columns"]) == 3
    center = pd.read_csv(out / "pca_center.csv")
    np.testing.assert_allclose(p["pca"]["scale"], center["scale"], rtol=1e-3)
    np.testing.assert_allclose(p["pca"]["center"], center["center"], rtol=1e-3)
    labels = pd.read_csv(out / "cluster_centers.csv").columns[1:].tolist()
    assert p["columns"] == labels
    assert p["short_columns"] == [c.split(" (")[0] for c in labels]
    parts = []
    for n in (1, 2):
        df = pd.read_csv(out / f"nuggets_{n}.csv")
        df.insert(0, "file", n)
        parts.append(df[df.weight > 0])
    nug = pd.concat(parts, ignore_index=True)
    assert p["nuggets"]["n"] == len(nug)
    assert p["nuggets"]["file"] == nug.file.tolist()
    assert p["nuggets"]["nugget0"] == nug.nugget0.tolist()
    assert p["nuggets"]["cluster"] == nug.cluster.tolist()
    np.testing.assert_allclose(p["nuggets"]["centers"], nug[labels], rtol=1e-3, atol=1e-9)
    assert [f["number"] for f in p["files"]] == [1, 2]
    assert_no_paths(client.get(f"{API}/runs/r1/plot").text, settings.data_dir)


def test_flow_plot_sends_nugget_weights_exact(flow_run, tmp_path):
    """A nugget's weight is its count of cells, which the point card and the box plots' counts
    show as it is: the payload sends it exact, not to 4 significant digits like the other floats.
    r1's nuggets hold fewer than 10,000 cells, which 4 digits keep, so a copy of the run gets one
    of 12,347."""
    import json
    import shutil

    from dnapp.features.plot.service import flow_plot

    _, settings, *_ = flow_run
    out = tmp_path / "r1"
    shutil.copytree(settings.data_dir / "ws" / "local" / "runs" / "r1", out)
    path = out / "nuggets_1.csv"
    df = pd.read_csv(path)
    df.loc[df.weight.idxmax(), "weight"] = 12_347
    df.to_csv(path, index=False)
    p = flow_plot("r1", out, json.loads((out / "run.json").read_text()), {})
    parts = [pd.read_csv(out / f"nuggets_{n}.csv") for n in (1, 2)]
    want = pd.concat([d[d.weight > 0] for d in parts]).weight.astype(float).tolist()
    assert p["nuggets"]["weight"] == want and 12_347.0 in want


def test_compare_counts_equal_cluster_summary(flow_run):
    client, settings, *_ = flow_run
    out = settings.data_dir / "ws" / "local" / "runs" / "r1"
    c = client.get(f"{API}/runs/r1/compare").json()
    assert set(c) == COMPARE_KEYS
    s = pd.read_csv(out / "cluster_summary.csv")
    for i, n in enumerate((1, 2)):
        rows = s[s.file_number == n].sort_values("cluster")
        assert c["counts"][i] == rows.cells.tolist()
        assert c["percent"][i] == [float(f"{v:.4g}") for v in rows.percent]
        assert c["files"][i]["cells"] == int(rows.cells.sum())
    sel = pd.read_csv(out / "selection.csv")
    assert [f["cells"] for f in c["files"]] == sel.kept.tolist()
    gs = pd.read_csv(out / "group_summary.csv")
    want = gs.log2fc_pseudocount.iloc[0] if "log2fc_pseudocount" in gs else None
    assert c["log2fc_pseudocount"] == (None if want is None else float(f"{want:.4g}"))
    assert c["k"] == 12


def test_phase2_outputs_reach_the_payloads(flow_run):
    client, settings, *_ = flow_run
    out = settings.data_dir / "ws" / "local" / "runs" / "r1"
    p = client.get(f"{API}/runs/r1/plot").json()
    colors = pd.read_csv(out / "cluster_colors.csv")
    assert [c["color"] for c in p["clusters"]] == colors.color.tolist()
    assert [c["cluster"] for c in p["clusters"]] == colors.cluster.tolist() == list(range(1, 13))
    assert [c["parent"] for c in p["clusters"]] == colors.parent.tolist()
    assert len(set(colors.color)) == 12
    assert client.get(f"{API}/runs/r1").json()["clusters"] == p["clusters"]
    assert p["groups"] == ["ctrl", "case"]
    assert [f["group"] for f in p["files"]] == ["ctrl", "case"]
    sc = pd.read_csv(out / "pca_scores.csv")
    np.testing.assert_allclose(p["pca"]["scores"], sc[p["pca"]["components"]], rtol=1e-3, atol=1e-6)
    tsne = pd.read_csv(out / "tsne.csv")
    np.testing.assert_allclose(p["tsne"]["d2"], tsne[["tsne1", "tsne2"]], rtol=1e-3, atol=1e-6)
    tsne3d = pd.read_csv(out / "tsne3d.csv")
    want = tsne3d[["tsne1", "tsne2", "tsne3"]]
    np.testing.assert_allclose(p["tsne"]["d3"], want, rtol=1e-3, atol=1e-6)
    cells = client.get(f"{API}/runs/r1/cells").json()
    csv = pd.read_csv(out / "cells.csv")
    assert cells["n"] == len(csv) == 600 and cells["cap_per_file"] == 300
    assert cells["file"] == csv.file_number.tolist() and cells["row0"] == csv.event0.tolist()
    assert cells["cluster"] == csv.cluster.tolist()
    c = client.get(f"{API}/runs/r1/compare").json()
    assert c["groups"] == ["ctrl", "case"] and c["reference"] == "ctrl"
    assert c["group_files"] == [1, 1]
    gs = pd.read_csv(out / "group_summary.csv")
    assert len(c["group_summary"]) == len(gs)
    assert [r["diff_vs_ref"] for r in c["group_summary"] if r["group"] == "ctrl"] == [0.0] * 12
    for r, (_, row) in zip(c["group_summary"], gs.iterrows()):
        assert (r["group"], r["cluster"], r["samples"]) == (row.group, row.cluster, row.samples)
        for key in ("mean_percent", "sd_percent", "diff_vs_ref", "log2fc_vs_ref"):
            want = None if pd.isna(row[key]) else float(f"{row[key]:.4g}")
            assert r[key] == want, (key, r, row)
    cm = pd.read_csv(out / "cluster_markers.csv")
    assert len(c["cluster_markers"]) == len(cm)
    labels = c["channels"]
    for r, (_, row) in zip(c["cluster_markers"], cm.iterrows()):
        assert (r["file_number"], r["cluster"], r["cells"]) == (
            row.file_number,
            row.cluster,
            row.cells,
        )
        want = [None if pd.isna(row[lab]) else float(f"{row[lab]:.4g}") for lab in labels]
        assert r["means"] == want
    gm = pd.read_csv(out / "group_markers.csv")
    assert len(c["group_markers"]) == len(gm)
    for r, (_, row) in zip(c["group_markers"], gm.iterrows()):
        assert (r["group"], r["cluster"], r["channel"]) == (row.group, row.cluster, row.label)
        assert r["mean"] == (None if pd.isna(row["mean"]) else float(f"{row['mean']:.4g}"))


def test_a_run_made_before_the_3d_tsne_plots_without_it(flow_run):
    """A run from before tsne3d.csv existed still plots, its t-SNE block with d3 None."""
    client, settings, *_ = flow_run
    path = settings.data_dir / "ws" / "local" / "runs" / "r1" / "tsne3d.csv"
    aside = path.with_name("tsne3d.csv.aside")
    path.rename(aside)
    try:
        p = client.get(f"{API}/runs/r1/plot").json()
    finally:
        aside.rename(path)
    assert p["tsne"]["d3"] is None and len(p["tsne"]["d2"]) == p["nuggets"]["n"]


def test_downloads(flow_run):
    client, settings, *_ = flow_run
    out = settings.data_dir / "ws" / "local" / "runs" / "r1"
    r = client.get(f"{API}/runs/r1/files/nuggets_1.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert pd.read_csv(io.BytesIO(r.content)).shape == pd.read_csv(out / "nuggets_1.csv").shape
    png = client.get(f"{API}/runs/r1/files/clusters_pca.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    # a name is one of the run's own files, never a path, even one that leads back to its folder
    for bad in ("../meta.json", "..%2Fmeta.json", "..%2Fr1%2Frun.json", "INCOMPLETE.txt",
                "nope.csv"):  # fmt: skip
        assert client.get(f"{API}/runs/r1/files/{bad}").status_code == 404, bad
    z = zipfile.ZipFile(io.BytesIO(client.get(f"{API}/runs/r1/download.zip").content))
    manifest = {f["name"] for f in client.get(f"{API}/runs/r1").json()["files"]}
    assert set(z.namelist()) == manifest


def test_the_run_json_download_names_its_gate_without_a_path(flow_run):
    """run.json records the gate folder the run read; alone or zipped, it goes out as the gate's
    name, as the manifest's record does."""
    import json

    client, settings, *_ = flow_run
    r = client.get(f"{API}/runs/r1/files/run.json")
    assert r.status_code == 200
    assert_no_paths(r.text, settings.data_dir)
    assert json.loads(r.text)["gates"] == "g1"
    # byte for byte the package's file but for that value, which it writes with ensure_ascii off
    path = settings.data_dir / "ws" / "local" / "runs" / "r1" / "run.json"
    on_disk = path.read_text(encoding="utf-8")
    gates = json.dumps(json.loads(on_disk)["gates"], ensure_ascii=False)
    assert gates in on_disk
    assert r.text == on_disk.replace(gates, '"g1"')
    z = zipfile.ZipFile(io.BytesIO(client.get(f"{API}/runs/r1/download.zip").content))
    assert z.read("run.json").decode() == r.text


def test_csv_injection_prefix(flow_run):
    client, settings, *_ = flow_run
    out = settings.data_dir / "ws" / "local" / "runs" / "r1"
    (out / "evil.csv").write_text("a,b\n=HYPERLINK(1),-2.5\n", encoding="utf-8")
    try:
        r = client.get(f"{API}/runs/r1/files/evil.csv")
        assert r.text == "a,b\n'=HYPERLINK(1),-2.5\n"
        z = zipfile.ZipFile(io.BytesIO(client.get(f"{API}/runs/r1/download.zip").content))
        assert z.read("evil.csv").decode() == "a,b\n'=HYPERLINK(1),-2.5\n"
    finally:
        (out / "evil.csv").unlink()


def test_no_absolute_path_in_any_payload(flow_run):
    client, settings, _, job, _ = flow_run
    urls = [
        "/workspace", "/uploads", "/uploads/u1", "/flow/gates/g1", "/runs", "/runs/r1",
        "/runs/r1/plot", "/runs/r1/cells", "/runs/r1/compare", "/jobs", "/jobs/j1",
        f"/jobs/{job['id']}", "/config", "/health", "/runs/r1/files/cluster_summary.csv",
    ]  # fmt: skip
    for u in urls:
        r = client.get(API + u)
        assert r.status_code == 200, (u, r.text)
        assert_no_paths(r.text, settings.data_dir)
    # every CSV in the zip; its run.json has the test above
    z = zipfile.ZipFile(io.BytesIO(client.get(f"{API}/runs/r1/download.zip").content))
    for name in z.namelist():
        if name.endswith(".csv"):
            assert_no_paths(z.read(name).decode(), settings.data_dir)
    assert "matplotlib.pyplot" not in sys.modules


def test_a_flow_run_records_the_transform_and_scale_stages(flow_run):
    import json

    client, settings, started, job, _ = flow_run
    rid = started["run_id"]
    out = settings.data_dir / "ws" / "local" / "runs" / rid
    rec = json.loads((out / "run.json").read_text())
    # nothing sent: the cofactor is auto, picked per channel from the cells the run clusters by
    # the package's own rule; the settings keep "auto" as asked and the transform the cofactors
    # used, each channel's share of cells below 0 and their SD, and the rule's floor and guard
    assert rec["transform"] == package_auto(settings, [[1], [1, 2]], rec["channels"])
    assert list(rec["transform"]) == AUTO_KEYS and rec["transform"]["cofactor_from"] == "auto"
    assert len(rec["transform"]["cofactors"]) == len(rec["labels"]) == 3
    assert all(c >= rec["transform"]["floor"] == 150.0 for c in rec["transform"]["cofactors"])
    assert rec["settings"]["cofactor"] == "auto"
    assert client.get(f"{API}/runs/{rid}").json()["settings"]["cofactor"] == "auto"
    assert rec["settings"]["standardize"] is True  # the default, nothing sent
    st = rec["standardize"]
    assert set(st) == {"mean", "sd", "ddof", "cells", "skew"} and st["ddof"] == 0
    assert len(st["mean"]) == len(st["sd"]) == len(st["skew"]) == len(rec["labels"]) == 3
    assert all(sd > 0 for sd in st["sd"])
    assert st["cells"] == int(pd.read_csv(out / "selection.csv").kept.sum())
    m = client.get(f"{API}/runs/{rid}").json()
    assert m["record"]["transform"] == rec["transform"]
    assert m["record"]["standardize"] == st
    # the Transform stage's lines: the rule, then a line per channel with its cofactor
    log = job["log_tail"]
    head = log.index(
        "Transform: arcsinh(x / c) of every clustered channel, c per channel (auto: the SD of the "
        "cells below 0 where at least 1% of the kept cells are below 0, at least 150; else 150)"
    )
    t = rec["transform"]
    for j, label in enumerate(rec["labels"]):
        line = log[head + 1 + j]
        assert line.startswith(f"  {label}: {t['cofactors'][j]:,.0f}  ("), line
        assert f"{100 * t['negative_fraction'][j]:.1f}% below 0" in line
    assert "Scale: every channel to mean 0 and SD 1, pooled over 2 files'" in "\n".join(log)
    # auto's pass over the files moves the bar a step per file read, between select and
    # transform, before the Scale stage's pass moves it on to scale; the bar never goes back
    steps = progress_steps(settings, job)
    assert [s for s in steps if s[1] == "cofactor"] == [
        (0.065, "cofactor", "Cofactor: read file 1 of 2"),
        (0.08, "cofactor", "Cofactor: read file 2 of 2"),
    ]
    assert [s for s in steps if s[1] == "transform"] == [
        (0.08, "transform", "Transformed the channels")
    ]
    assert [s for s in steps if s[1] == "scale"] == [
        (0.115, "scale", "Scaling: read file 1 of 2"),
        (0.15, "scale", "Scaling: read file 2 of 2"),
        (0.15, "scale", "Scaled the channels"),
    ]
    stages = [s[1] for s in steps]
    assert stages.index("select") < stages.index("cofactor") < stages.index("transform")
    assert stages.index("transform") < stages.index("scale") < stages.index("nuggets")
    assert [s[0] for s in steps] == sorted(s[0] for s in steps)


def progress_steps(settings, job) -> list[tuple]:
    """A job's progress lines as (p, stage, message), in the order the worker wrote them."""
    import json

    progress = next(settings.data_dir.rglob(f"jobs/{job['id']}.progress"))
    lines = progress.read_text(encoding="utf-8").splitlines()
    return [(r["p"], r["stage"], r["message"]) for r in map(json.loads, lines)]


def test_standardize_false_runs_without_the_scale_stage(flow):
    """Also a cofactor sent as a number: it overrides auto and is recorded as set."""
    import json

    client, settings, _, _ = flow
    body = {"gate_id": "g1", "pops": [[1], [1]], **SMALL, "tsne": False, "standardize": False,
            "cofactor": 6000}  # fmt: skip
    r = client.post(f"{API}/flow/runs", json=body)
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    job = wait_job(client, r.json()["job"]["id"])
    assert job["status"] == "done", job
    out = settings.data_dir / "ws" / "local" / "runs" / rid
    rec = json.loads((out / "run.json").read_text())
    assert rec["settings"]["standardize"] is False and rec["standardize"] is False
    assert rec["settings"]["cofactor"] == 6000
    assert rec["transform"] == {"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}
    log = "\n".join(job["log_tail"])
    assert "Transform: arcsinh(x / 6000) of every clustered channel; cofactor 6000 as set" in log
    assert "Scale: none; the channels keep the transform's units" in log
    # a number set needs no pass over the cells for it, so the bar takes no cofactor step
    steps = progress_steps(settings, job)
    assert "cofactor" not in {s[1] for s in steps}
    assert [s for s in steps if s[1] == "transform"] == [
        (0.08, "transform", "Transformed the channels")
    ]
    assert [s[0] for s in steps] == sorted(s[0] for s in steps)
    assert list(pd.read_csv(out / "pca_center.csv").columns) == ["channel", "label", "center"]
    p = client.get(f"{API}/runs/{rid}/plot").json()
    assert p["transform"] == [{"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}]
    assert p["pca"]["scale"] is None


def test_a_run_json_from_before_the_two_stages_still_loads(flow_run):
    import json

    client, settings, started, *_ = flow_run
    rid = started["run_id"]
    path = settings.data_dir / "ws" / "local" / "runs" / rid / "run.json"
    now = path.read_text()
    old = json.loads(now)
    del old["transform"], old["standardize"], old["settings"]["standardize"]
    old["settings"]["cofactor"] = 6000.0  # a number then, never "auto"
    try:
        path.write_text(json.dumps(old))
        m = client.get(f"{API}/runs/{rid}")
        assert m.status_code == 200, m.text
        assert "standardize" not in m.json()["record"]
        for part in ("plot", "compare", "cells"):
            assert client.get(f"{API}/runs/{rid}/{part}").status_code == 200, part
        # the settings' cofactor stands for the Transform stage, read as set
        p = client.get(f"{API}/runs/{rid}/plot").json()
        assert p["transform"] == [{"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}]
    finally:
        path.write_text(now)


def test_a_run_json_from_before_cofactor_from_reads_as_set(flow_run):
    """A run.json whose transform predates cofactor_from (and range) still loads; its arcsinh
    held a number set or defaulted, so the plot reads it as set and the record stays as written."""
    import json

    client, settings, started, *_ = flow_run
    rid = started["run_id"]
    path = settings.data_dir / "ws" / "local" / "runs" / rid / "run.json"
    now = path.read_text()
    old = json.loads(now)
    old["transform"] = {"name": "arcsinh", "cofactor": 6000.0}
    old["settings"]["cofactor"] = 6000.0
    try:
        path.write_text(json.dumps(old))
        m = client.get(f"{API}/runs/{rid}")
        assert m.status_code == 200, m.text
        assert m.json()["record"]["transform"] == {"name": "arcsinh", "cofactor": 6000.0}
        p = client.get(f"{API}/runs/{rid}/plot")
        assert p.status_code == 200, p.text
        assert p.json()["transform"][0] == {"name": "arcsinh", "cofactor": 6000.0,
                                            "cofactor_from": "set"}  # fmt: skip
        for part in ("compare", "cells"):
            assert client.get(f"{API}/runs/{rid}/{part}").status_code == 200, part
    finally:
        path.write_text(now)


def test_a_run_json_of_the_header_rule_still_loads(flow_run):
    """A run.json the earlier auto rule wrote, one cofactor picked from the files' headers with
    the range it was picked by, is served as written: the record and the plot keep its number,
    auto and its range, with no per-channel cofactors."""
    import json

    client, settings, started, *_ = flow_run
    rid = started["run_id"]
    path = settings.data_dir / "ws" / "local" / "runs" / rid / "run.json"
    now = path.read_text()
    old = json.loads(now)
    old["transform"] = dict(HEADER_RULE)
    try:
        path.write_text(json.dumps(old))
        m = client.get(f"{API}/runs/{rid}")
        assert m.status_code == 200, m.text
        assert m.json()["record"]["transform"] == HEADER_RULE
        assert m.json()["settings"]["cofactor"] == "auto"
        p = client.get(f"{API}/runs/{rid}/plot")
        assert p.status_code == 200, p.text
        assert p.json()["transform"][0] == HEADER_RULE
        for part in ("compare", "cells"):
            assert client.get(f"{API}/runs/{rid}/{part}").status_code == 200, part
    finally:
        path.write_text(now)


def test_flow_refusals(flow):
    client, *_ = flow
    base = {"gate_id": "g1", "pops": [[1], [1]], **SMALL}
    for bad in ("yes", 1):  # true or false only
        assert_error(
            client.post(f"{API}/flow/runs", json={**base, "standardize": bad}),
            422,
            "invalid_setting",
            "standardize",
        )
    # "auto", spelt so, or a finite number from 0; the package's message names the choices. true
    # and false are not 1 and 0, and auto's cofactors per channel can't be sent as a list
    for bad in ("x", "Auto", "150", -1, [150], [150, 6000], {"auto": True}, True, False):
        err = assert_error(
            client.post(f"{API}/flow/runs", json={**base, "cofactor": bad}),
            422,
            "invalid_setting",
            "cofactor",
        )
        if isinstance(bad, str | int) and not isinstance(bad, bool):
            assert "auto, 0 (linear) or a positive number" in err["message"], err
    assert_error(
        client.post(f"{API}/flow/runs", json={**base, "pops": [[1]]}),
        422,
        "invalid_setting",
        "pops",
    )
    assert_error(
        client.post(f"{API}/flow/runs", json={**base, "pops": [[99], [1]]}),
        422,
        "invalid_setting",
        "pops",
    )
    assert_error(
        client.post(f"{API}/flow/runs", json={**base, "pops": [[], []]}),
        422,
        "invalid_setting",
        "pops",
    )
    assert_error(
        client.post(f"{API}/flow/runs", json={**base, "k": 101}), 422, "invalid_setting", "k"
    )
    assert_error(
        client.post(f"{API}/flow/runs", json={**base, "k": 0}), 422, "invalid_setting", "k"
    )
    assert_error(
        client.post(f"{API}/flow/runs", json={**base, "dn_num2": 1}),
        422,
        "invalid_setting",
        "dn_num2",
    )
    assert_error(
        client.post(f"{API}/flow/runs", json={**base, "groups": ["a"]}),
        422,
        "invalid_setting",
        "groups",
    )
    assert_error(
        client.post(f"{API}/flow/runs", json={**base, "gate_id": "g9"}),
        422,
        "invalid_setting",
        "gate_id",
    )
    assert_error(
        client.post(f"{API}/flow/gates", json={"uploads": []}), 422, "invalid_setting", "uploads"
    )
    assert_error(
        client.post(f"{API}/flow/gates", json={"uploads": ["u1"], "settings": {"disc": "x"}}),
        422,
        "invalid_setting",
        "disc",
    )
    assert_error(
        client.post(f"{API}/flow/gates", json={"uploads": ["u1"], "settings": {"bogus": 1}}),
        422,
        "invalid_setting",
        "bogus",
    )


def run_record(settings, rid: str) -> dict:
    import json

    path = settings.data_dir / "ws" / "local" / "runs" / rid / "run.json"
    return json.loads(path.read_text(encoding="utf-8"))


def nugget_rows(settings, rid: str) -> tuple[int, int]:
    """(nuggets with weight > 0, all nuggets) over the run's nuggets_N.csv files."""
    out = settings.data_dir / "ws" / "local" / "runs" / rid
    frames = [pd.read_csv(p) for p in sorted(out.glob("nuggets_*.csv"))]
    return sum(int((f.weight > 0).sum()) for f in frames), sum(len(f) for f in frames)


def test_a_default_flow_run_is_weighted_kmeans_on_original_centers(flow_run):
    """flow_run sends neither method nor center_method. The server fills them from the package's
    defaults, so the run clusters with weighted k-means on the original center points, its
    nuggets drawn with R's set.seed draws, and never as the hierarchical tree on mean centers,
    which only a record written before method existed loads as. run.json's clustering block says
    what ran, over which nuggets, and the R calls that rebuild it."""
    client, settings, started, job, _ = flow_run
    assert job["status"] == "done", job
    rid = started["run_id"]
    rec = run_record(settings, rid)
    s = rec["settings"]
    assert (s["method"], s["center_method"], s["draws"]) == ("wkmeans", "original", "r")
    assert (s["num_init"], s["max_iter"]) == (10, 100)
    m = client.get(f"{API}/runs/{rid}").json()
    sent = m["settings"]
    assert (sent["method"], sent["center_method"], sent["draws"]) == ("wkmeans", "original", "r")
    c = rec["clustering"]
    assert (c["method"], c["k"], c["k_used"]) == ("wkmeans", 12, 12)
    used, every = nugget_rows(settings, rid)  # 150 nuggets kept per file, two files
    assert (c["nuggets_clustered"], c["nuggets_dropped"]) == (used, every - used)
    assert every == 300 and c["total_wwcss"] > 0
    assert 'center.method = "original"' in c["r"]["create.DN"]
    assert "seed = 291102" in c["r"]["create.DN"]
    for part in ("Wkmeans(", "k = 12,", "num.init = 10", "max.iterations = 100", "seed = 291102"):
        assert part in c["r"]["cluster"], (part, c["r"])
    assert m["record"]["clustering"] == c
    # what ran, not what was asked: c["method"] echoes the settings, but only a pool with no
    # tree (weighted k-means) leaves dendrogram.png out
    names = {f["name"] for f in m["files"]}
    assert "dendrogram.png" not in names and "clusters_pca.png" in names, names


def test_a_flow_run_takes_the_tree_and_mean_centers(flow):
    """The two choices the page offers reach the package as sent. The draws stay R's, which the
    app never sends, so create.DN rebuilds these nuggets too."""
    client, settings, _, _ = flow
    body = {"gate_id": "g1", "pops": [[1], [1]], **SMALL, "tsne": False, "method": "tree",
            "center_method": "mean"}  # fmt: skip
    r = client.post(f"{API}/flow/runs", json=body)
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    job = wait_job(client, r.json()["job"]["id"])
    assert job["status"] == "done", job
    rec = run_record(settings, rid)
    s = rec["settings"]
    assert (s["method"], s["center_method"], s["draws"]) == ("tree", "mean", "r")
    manifest = client.get(f"{API}/runs/{rid}").json()
    sent = manifest["settings"]
    assert (sent["method"], sent["center_method"]) == ("tree", "mean")
    assert "dendrogram.png" in {f["name"] for f in manifest["files"]}  # the pool has a tree
    c = rec["clustering"]
    assert (c["method"], c["k"], c["k_used"]) == ("tree", 12, 12)
    assert 'center.method = "mean"' in c["r"]["create.DN"]
    assert "Whclust(" in c["r"]["cluster"] and "k = 12)" in c["r"]["cluster"], c["r"]
    assert client.get(f"{API}/runs/{rid}/plot").json()["k"] == 12


def test_an_unknown_method_is_refused_naming_method(flow):
    """The package's check refuses a method or centers it doesn't know, naming the field, before
    a job is queued. The draws and the weighted k-means starts and rounds aren't request fields:
    the app never sends them, and a request that does is refused naming the field."""
    client, *_ = flow
    base = {"gate_id": "g1", "pops": [[1], [1]], **SMALL}
    jobs = len(client.get(f"{API}/jobs").json()["jobs"])
    for bad in ("kmeans", "Tree", "hclust", "", 1):
        r = client.post(f"{API}/flow/runs", json={**base, "method": bad})
        err = assert_error(r, 422, "invalid_setting", "method")
        if isinstance(bad, str):
            assert "wkmeans or tree" in err["message"], err
    for bad in ("medoid", "Mean", ""):
        r = client.post(f"{API}/flow/runs", json={**base, "center_method": bad})
        assert_error(r, 422, "invalid_setting", "center_method")
    for key, value in (("draws", "numpy"), ("num_init", 1), ("max_iter", 5)):
        r = client.post(f"{API}/flow/runs", json={**base, key: value})
        assert_error(r, 422, "invalid_setting", key)
    assert len(client.get(f"{API}/jobs").json()["jobs"]) == jobs


def test_too_few_nuggets_for_k_fails_the_job_naming_dn_num2(flow):
    """Weighted k-means needs two nuggets in use per cluster and never clusters into fewer than
    k: 2 files of 10 nuggets can't make k = 12, so the job fails as the package refuses it, with
    param dn_num2 and the field's own name in the message."""
    client, *_ = flow
    body = {"gate_id": "g1", "pops": [[1], [1]], **SMALL, "dn_num2": 10, "tsne": False}
    r = client.post(f"{API}/flow/runs", json=body)
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"]["id"])
    assert job["status"] == "failed", job
    err = job["error"]
    assert (err["code"], err["param"]) == ("invalid_setting", "dn_num2"), err
    assert "lower k or increase dn_num2" in err["message"], err
    need = "two nuggets in use per cluster: k = 12 needs 24, and the kept cells fill 20"
    assert need in err["message"], err
