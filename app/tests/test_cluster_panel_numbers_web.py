"""The cluster panel's numbers as text, app/web/features/cluster-panel/numbers.js, run in Node: the
label beside each box (median and quartiles), the hover label over it, the points along it that
carry that hover, and the rows of the tables under the charts. The last test feeds it the boxes
stats.js makes from the public PBMC fixtures (run r7). The tests skip where Node isn't installed."""

from __future__ import annotations

import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
FIX = WEB / "fixtures"
NODE = shutil.which("node")
MODULES = (
    "shared/config.js",
    "shared/format.js",
    "features/cluster-panel/stats.js",
    "features/cluster-panel/numbers.js",
)
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")

BOX = {"q1": 0.8123, "median": 1.23456, "q3": 1.6, "lo": -0.5, "hi": 2.75, "n": 1234}


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """js(body) runs body as a function in Node with `num` (numbers.js), `stats` and `config`
    imported and r7's plot and cells payloads as P7 and X7, and returns what it returns."""
    root = tmp_path_factory.mktemp("web")
    for rel in MODULES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEB / rel, root / rel)
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"
    head = "import { readFileSync } from 'node:fs';\n" + "".join(
        f"const {k} = JSON.parse(readFileSync({json.dumps(str(FIX / f))}, 'utf8'));\n"
        for k, f in (("P7", "GET__runs__r7__plot.json"), ("X7", "GET__runs__r7__cells.json"))
    )

    def run(body: str):
        script.write_text(
            "import * as num from './features/cluster-panel/numbers.js';\n"
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


def test_the_label_beside_a_box_is_its_median_then_quartiles_to_three_digits(js):
    assert js(f"return num.boxLabel({json.dumps(BOX)});") == "1.23 [0.812, 1.6]"
    neg = {**BOX, "q1": -1.2345, "median": -0.04567, "q3": 12345.6}
    assert js(f"return num.boxLabel({json.dumps(neg)});") == "-0.0457 [-1.23, 12,346]"


def test_the_hover_label_names_the_box_and_gives_all_five_numbers_and_n(js):
    got = js(f"return num.boxHover('CD3 <BV421>', {json.dumps(BOX)}, 1234);")
    assert got == (
        "<b>CD3 &lt;BV421&gt;</b><br>median 1.235<br>quartiles 0.8123 to 1.6"
        "<br>whiskers -0.5 to 2.75<br>1,234 sampled cells"
    )


def test_hover_points_run_evenly_along_each_box_from_whisker_to_whisker(js):
    k = js("return config.BOX_HOVER_POINTS;")
    assert k == 24
    other = {**BOX, "lo": 3, "hi": 3}  # a box with no spread still gets its points
    got = js(
        f"return num.hoverPoints([{{ y: 0.81, s: {json.dumps(BOX)}, hover: 'a' }},"
        f" {{ y: 2, s: {json.dumps(other)}, hover: 'b' }}]);"
    )
    assert len(got["x"]) == len(got["y"]) == len(got["text"]) == 2 * k
    first = got["x"][:k]
    assert first[0] == BOX["lo"] and first[-1] == pytest.approx(BOX["hi"], rel=1e-12)
    steps = [b - a for a, b in itertools.pairwise(first)]
    assert steps == pytest.approx([(BOX["hi"] - BOX["lo"]) / (k - 1)] * (k - 1), rel=1e-9)
    assert got["x"][k:] == [3] * k
    assert got["y"] == [0.81] * k + [2] * k and got["text"] == ["a"] * k + ["b"] * k


def test_the_marker_table_puts_the_cluster_beside_the_rest(js):
    rest = {**BOX, "median": 0.5, "q1": 0.1, "q3": 0.9}
    b = [{"all": BOX, "rest": rest}, {"all": BOX, "rest": None}]
    got = js(f"return [num.MARKER_HEAD, num.markerRows(['CD3 ↑', 'CD4'], {json.dumps(b)})];")
    assert got[0] == [
        "Marker",
        "Cluster median",
        "Cluster Q1 to Q3",
        "Rest median",
        "Rest Q1 to Q3",
    ]
    assert got[1] == [
        ["CD3 ↑", "1.235", "0.8123 to 1.6", "0.5", "0.1 to 0.9"],
        ["CD4", "1.235", "0.8123 to 1.6", "–", "–"],
    ]


def test_the_one_marker_table_counts_each_row_and_marks_a_row_with_no_box(js):
    rows = [
        {"label": "Cluster 2", "s": BOX, "n": 1234},
        {"label": "Group A", "s": None, "n": 3},
    ]
    got = js(f"return [num.PART_HEAD, num.partRows({json.dumps(rows)})];")
    assert got[0] == ["", "Cells", "Median", "Q1 to Q3", "Whiskers"]
    assert got[1] == [
        ["Cluster 2", "1,234", "1.235", "0.8123 to 1.6", "-0.5 to 2.75"],
        ["Group A", "3", "–", "–", "–"],
    ]


def test_the_tables_carry_the_boxes_stats_js_makes_from_r7(js):
    """Every marker of r7's cluster 2: one table row each, whose numbers are the boxes' own."""
    got = js(
        "const w = stats.cellWeights(P7, X7);"
        "const B = P7.columns.map((_, j) => stats.boxes(P7, X7, X7.values.map(r => r[j]), 2, w));"
        "return { B, rows: num.markerRows(P7.columns.map(c => c.name || String(c)), B),"
        " fmt: B.map(b => [b.all.median, b.rest.median].map(v => String(Number(v.toPrecision(4))))) };"
    )
    assert len(got["rows"]) == len(got["B"]) > 1
    for row, (med, rest_med) in zip(got["rows"], got["fmt"], strict=True):
        assert row[1] == med and row[3] == rest_med
