"""The cluster panel's numbers, app/web/features/cluster-panel/stats.js, run in Node against the
public PBMC fixtures (app/web/fixtures, run r7): the cluster's cells per group or file, exact from
the nugget weights, and its boxes from the sampled cells, each cell weighted by its file's kept /
sampled cells (docs/app/cluster-panel.md). The references here are numpy. The tests skip where
Node isn't installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
FIX = WEB / "fixtures"
NODE = shutil.which("node")
MODULES = ("shared/config.js", "features/cluster-panel/stats.js")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")

QS = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]
BOX_MIN_CELLS = 5


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """js(body) runs body as a function in Node with `stats` (stats.js) and `config` imported and
    the fixtures' payloads as P7, X7, C7 (r7: plot, cells, compare), and returns what it returns,
    through JSON."""
    root = tmp_path_factory.mktemp("web")
    for rel in MODULES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEB / rel, root / rel)
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"
    load = {
        "P7": "GET__runs__r7__plot.json",
        "X7": "GET__runs__r7__cells.json",
        "C7": "GET__runs__r7__compare.json",
    }
    head = "import { readFileSync } from 'node:fs';\n" + "".join(
        f"const {k} = JSON.parse(readFileSync({json.dumps(str(FIX / f))}, 'utf8'));\n"
        for k, f in load.items()
    )

    def run(body: str):
        script.write_text(
            "import * as stats from './features/cluster-panel/stats.js';\n"
            "import * as config from './shared/config.js';\n"
            f"{head}"
            f"const out = (() => {{ {body} }})();\n"
            "process.stdout.write(JSON.stringify(out === undefined ? null : out));\n",
            encoding="utf-8",
        )
        done = subprocess.run(
            [NODE, str(script)], capture_output=True, text=True, timeout=60, check=False
        )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    return run


def fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def ref_quantile(x, w, q: float) -> float:
    """The weighted midpoint quantile of docs/app/cluster-panel.md, written out in numpy."""
    order = np.argsort(x, kind="stable")
    x, w = np.asarray(x, float)[order], np.asarray(w, float)[order]
    p = (np.cumsum(w) - w / 2) / w.sum()
    return float(np.interp(q, p, x))  # np.interp holds the end values outside [p_1, p_n]


def ref_box(x, w) -> dict | None:
    if len(x) < BOX_MIN_CELLS:
        return None
    x = np.asarray(x, float)
    q1, med, q3 = (ref_quantile(x, w, q) for q in (0.25, 0.5, 0.75))
    iqr = q3 - q1
    inside = x[(x >= q1 - 1.5 * iqr) & (x <= q3 + 1.5 * iqr)]
    return {"n": len(x), "q1": q1, "median": med, "q3": q3, "lo": inside.min(), "hi": inside.max()}


def assert_box(got: dict | None, want: dict | None):
    if want is None:
        assert got is None
        return
    assert got is not None
    assert got["n"] == want["n"]
    for k in ("q1", "median", "q3", "lo", "hi"):
        assert got[k] == pytest.approx(want[k], rel=1e-12, abs=1e-12), k


def test_box_min_cells_is_in_config(js):
    assert js("return config.BOX_MIN_CELLS;") == BOX_MIN_CELLS


@pytest.mark.parametrize("n", [1, 2, 7, 50, 1001])
def test_equal_weights_give_the_hazen_quantiles(js, n):
    x = np.random.default_rng(n).normal(size=n).round(6).tolist()
    got = js(
        f"const x = {json.dumps(x)}.slice().sort((a, b) => a - b);"
        f"return {json.dumps(QS)}.map(q => stats.quantile(x, x.map(() => 1), q));"
    )
    want = [float(np.percentile(x, q * 100, method="hazen")) for q in QS]
    assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_weighted_quantiles_follow_the_midpoint_rule(js, seed):
    rng = np.random.default_rng(seed)
    x = rng.gamma(2.0, size=40).round(6)
    w = rng.integers(1, 30, size=40).astype(float)
    order = np.argsort(x, kind="stable")
    xs, ws = x[order].tolist(), w[order].tolist()
    got = js(f"return {json.dumps(QS)}.map(q => stats.quantile({xs}, {ws}, q));")
    want = [ref_quantile(x, w, q) for q in QS]
    assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


def test_a_heavier_value_pulls_the_median_towards_it(js):
    """Three values: equal weights give the middle one. A weight of 10 on the largest puts the
    midpoints at 0.5 / 12, 1.5 / 12 and (2 + 5) / 12, so the median is 9 / 11 of the way from 2
    to 3."""
    got = js(
        "return [stats.quantile([1, 2, 3], [1, 1, 1], 0.5), stats.quantile([1, 2, 3], [1, 1, 10], 0.5)];"
    )
    assert got[0] == 2
    assert got[1] == pytest.approx(2 + 9 / 11, rel=1e-12)


def test_box_whiskers_stop_at_the_last_value_inside_the_fences(js):
    x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]
    got = js(f"return stats.boxStats({x}, {[1] * len(x)});")
    want = ref_box(x, [1] * len(x))
    assert_box(got, want)
    assert got["hi"] == 9 and got["lo"] == 1


def test_a_whisker_with_no_value_between_its_fence_and_the_box_stays_at_the_box(js):
    # Hazen q1 of [0, 10, 10, 10, 10] is 7.5 and the lower fence 3.75: the first value inside
    # the fence is 10, above q1, so the whisker would point into the box.
    got = js("return stats.boxStats([0, 10, 10, 10, 10], [1, 1, 1, 1, 1]);")
    assert got["q1"] == pytest.approx(7.5) and got["q3"] == 10
    assert got["lo"] == got["q1"] and got["hi"] == 10


def test_a_box_needs_box_min_cells(js):
    got = js(
        "return [stats.boxStats([3, 1, 2, 5], [1, 1, 1, 1]), stats.boxStats([3, 1, 2, 5, 4], [1, 1, 1, 1, 1])];"
    )
    assert got[0] is None
    assert_box(got[1], ref_box([3, 1, 2, 5, 4], [1] * 5))


def test_counts_per_group_match_compare():
    """Run in Python against Compare's counts: the sum of the cluster's nugget weights per file,
    which test_cluster_counts_* below check stats.js against."""
    p = fixture("GET__runs__r7__plot.json")
    c = fixture("GET__runs__r7__compare.json")
    w = np.array(p["nuggets"]["weight"], float)
    f = np.array(p["nuggets"]["file"])
    cl = np.array(p["nuggets"]["cluster"])
    for i, row in enumerate(c["counts"]):
        n = c["files"][i]["number"]
        assert [w[(f == n) & (cl == k)].sum() for k in range(1, c["k"] + 1)] == row


def test_cluster_counts_per_group(js):
    c = fixture("GET__runs__r7__compare.json")
    got = js("return Array.from({ length: P7.k }, (_, i) => stats.counts(P7, i + 1));")
    total = sum(f["cells"] for f in c["files"])
    for k, g in enumerate(got, start=1):
        rows = {
            grp: [i for i, f in enumerate(c["files"]) if f["group"] == grp] for grp in c["groups"]
        }
        cells = sum(row[k - 1] for row in c["counts"])
        assert g["cells"] == cells and g["total"] == total
        assert g["nuggets"] == sum(
            1 for x in fixture("GET__runs__r7__plot.json")["nuggets"]["cluster"] if x == k
        )
        assert [p["label"] for p in g["parts"]] == c["groups"]
        assert [p["count"] for p in g["parts"]] == [
            sum(c["counts"][i][k - 1] for i in rows[grp]) for grp in c["groups"]
        ]
        assert [p["of"] for p in g["parts"]] == [
            sum(c["files"][i]["cells"] for i in rows[grp]) for grp in c["groups"]
        ]


def test_cluster_counts_per_file_without_groups(js):
    c = fixture("GET__runs__r7__compare.json")
    got = js(
        "const P = { ...P7, groups: null, files: P7.files.map(f => ({ ...f, group: null })) };"
        "return stats.counts(P, 2);"
    )
    assert [p["label"] for p in got["parts"]] == [f"F{f['number']} {f['name']}" for f in c["files"]]
    assert [p["count"] for p in got["parts"]] == [row[1] for row in c["counts"]]
    assert [p["of"] for p in got["parts"]] == [f["cells"] for f in c["files"]]


def test_each_sampled_cell_stands_for_its_files_kept_over_sampled(js):
    p = fixture("GET__runs__r7__plot.json")
    x = fixture("GET__runs__r7__cells.json")
    got = js("return Array.from(stats.cellWeights(P7, X7));")
    kept = {
        n: float(np.array(p["nuggets"]["weight"])[np.array(p["nuggets"]["file"]) == n].sum())
        for n in {f["number"] for f in p["files"]}
    }
    files = np.array(x["file"])
    sampled = {n: int((files == n).sum()) for n in kept}
    assert got == pytest.approx([kept[n] / sampled[n] for n in x["file"]], rel=1e-12)
    for n, cells in kept.items():
        assert np.array(got)[files == n].sum() == pytest.approx(cells, rel=1e-12)


@pytest.mark.parametrize(("cluster", "j"), [(1, 0), (4, 3), (8, 31)])
def test_boxes_for_all_cells_and_per_group(js, cluster, j):
    p = fixture("GET__runs__r7__plot.json")
    x = fixture("GET__runs__r7__cells.json")
    got = js(
        f"const col = X7.values.map(r => r[{j}]), w = stats.cellWeights(P7, X7);"
        f"return stats.boxes(P7, X7, col, {cluster}, w);"
    )
    w = np.array(js("return Array.from(stats.cellWeights(P7, X7));"))
    v = np.array([r[j] for r in x["values"]], float)
    cl = np.array(x["cluster"])
    fl = np.array(x["file"])
    inc = cl == cluster
    assert_box(got["all"], ref_box(v[inc], w[inc]))
    groups = {f["number"]: f["group"] for f in p["files"]}
    assert [g["label"] for g in got["parts"]] == p["groups"]
    for part, grp in zip(got["parts"], p["groups"], strict=True):
        m = inc & np.array([groups[n] == grp for n in fl])
        assert part["n"] == int(m.sum())
        assert_box(part["stats"], ref_box(v[m], w[m]))


@pytest.mark.parametrize(("cluster", "j"), [(1, 0), (4, 3), (8, 31)])
def test_the_rest_box_pools_every_other_clusters_sampled_cells(js, cluster, j):
    """The rest is the run's other clusters, all groups together, weighted like the cluster's cells,
    so the two boxes of a marker sit on one scale."""
    x = fixture("GET__runs__r7__cells.json")
    got = js(
        f"const col = X7.values.map(r => r[{j}]), w = stats.cellWeights(P7, X7);"
        f"return stats.boxes(P7, X7, col, {cluster}, w);"
    )
    w = np.array(js("return Array.from(stats.cellWeights(P7, X7));"))
    v = np.array([r[j] for r in x["values"]], float)
    out = np.array(x["cluster"]) != cluster
    assert got["restN"] == int(out.sum()) > 0
    assert got["n"] + got["restN"] == len(v)
    assert_box(got["rest"], ref_box(v[out], w[out]))


def test_a_cluster_is_high_or_low_when_its_median_leaves_the_rests_middle_half(js):
    rest = {"q1": 1, "median": 2, "q3": 3}
    got = js(
        f"const rest = {json.dumps(rest)};"
        "return [0.5, 1, 2.5, 3, 3.5].map(m => stats.level({ median: m }, rest))"
        ".concat([stats.level(null, rest), stats.level({ median: 2 }, null)]);"
    )
    assert got == ["low", "mid", "mid", "mid", "high", None, None]
