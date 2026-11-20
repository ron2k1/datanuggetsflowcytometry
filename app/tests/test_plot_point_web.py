"""The point card's numbers, app/web/features/plot/point.js, run in Node on the r7 fixtures (four
public PBMC files, auto cofactors per channel): a clicked nugget or sampled cell gives each
marker's value as plotted, in the Transform stage's units, and back in the file's units,
c x sinh(v) with c that channel's cofactor, which is the value the run read from the .fcs file
for a cell and the nugget's center on that scale for a nugget. The modules are copied beside a
package.json that marks them as ES modules; the tests skip where Node isn't installed."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
MODULES = (
    "shared/config.js",
    "shared/format.js",
    "shared/cofactor.js",
    "features/plot/model.js",
    "features/plot/point.js",
)
FIXTURES = WEB / "fixtures"
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def payloads():
    return load("GET__runs__r7__plot.json"), load("GET__runs__r7__cells.json")


@pytest.fixture(scope="module")
def js(tmp_path_factory, payloads):
    """js(body) runs body in Node with `point` (point.js), `makeModel` (model.js) and the r7
    payloads `P` and `cells` in scope, and returns what it returns, through JSON."""
    root = tmp_path_factory.mktemp("web")
    for rel in MODULES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEB / rel, root / rel)
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    P, cells = payloads
    (root / "P.json").write_text(json.dumps(P), encoding="utf-8")
    (root / "cells.json").write_text(json.dumps(cells), encoding="utf-8")
    script = root / "run.js"

    def run(body: str):
        script.write_text(
            "import { readFileSync } from 'node:fs';\n"
            "import * as point from './features/plot/point.js';\n"
            "import * as config from './shared/config.js';\n"
            "import { makeModel } from './features/plot/model.js';\n"
            "const P = JSON.parse(readFileSync(new URL('./P.json', import.meta.url)));\n"
            "const cells = JSON.parse(readFileSync(new URL('./cells.json', import.meta.url)));\n"
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


# Rows spread over the four files: the first and last nugget, two in the middle.
NUGGETS = [0, 251, 637, 999]
CELLS = [0, 777, 1999]


@pytest.mark.parametrize("i", NUGGETS)
def test_a_nugget_gives_its_center_and_the_center_in_file_units(js, payloads, i):
    P, _ = payloads
    out = js(f"return point.pointNumbers(P, makeModel(P, null, 'nuggets'), {i});")
    t = P["transform"][0]
    centers = P["nuggets"]["centers"][i]
    assert [r["name"] for r in out["rows"]] == P["columns"]
    assert [r["short"] for r in out["rows"]] == P["short_columns"]
    for j, r in enumerate(out["rows"]):
        c = t["cofactors"][j]
        assert r["plotted"] == centers[j]
        assert r["cofactor"] == c
        assert r["file"] == pytest.approx(c * math.sinh(centers[j]), rel=1e-12)
        # The way back: the run's own transform of the file value gives the plotted one.
        assert math.asinh(r["file"] / c) == pytest.approx(centers[j], abs=1e-12)


@pytest.mark.parametrize("i", NUGGETS)
def test_a_nugget_names_its_file_number_weight_and_cluster(js, payloads, i):
    P, _ = payloads
    out = js(f"return point.pointNumbers(P, makeModel(P, null, 'nuggets'), {i});")
    nug = P["nuggets"]
    f = next(x for x in P["files"] if x["number"] == nug["file"][i])
    assert out["src"] == "nuggets"
    assert out["cluster"] == nug["cluster"][i]
    # Nuggets are numbered within their file, from 1 on screen.
    assert out["nugget"] == nug["nugget0"][i] + 1
    assert out["event"] is None
    assert out["weight"] == nug["weight"][i]
    assert out["file"] == f


@pytest.mark.parametrize("i", CELLS)
def test_a_cell_gives_the_value_the_run_read_from_its_file(js, payloads, i):
    P, cells = payloads
    out = js(f"return point.pointNumbers(P, makeModel(P, cells, 'cells'), {i});")
    t = P["transform"][0]
    assert out["src"] == "cells"
    assert out["cluster"] == cells["cluster"][i]
    assert out["event"] == cells["row0"][i] + 1
    assert out["nugget"] == cells["nugget0"][i] + 1
    assert out["weight"] is None
    assert out["file"]["number"] == cells["file"][i]
    for j, r in enumerate(out["rows"]):
        v = cells["values"][i][j]
        assert r["plotted"] == v
        assert r["file"] == pytest.approx(t["cofactors"][j] * math.sinh(v), rel=1e-12)


def test_a_cell_sits_in_a_nugget_of_its_own_file_and_cluster(js, payloads):
    """The card names a cell's nugget by its number within the cell's file: every sampled cell's
    nugget is one of that file's, in the cell's cluster."""
    P, _ = payloads
    nug = P["nuggets"]
    owner = {(f, k): c for f, k, c in zip(nug["file"], nug["nugget0"], nug["cluster"], strict=True)}
    got = js(
        "const M = makeModel(P, cells, 'cells');"
        "return [0, 500, 1000, 1500, 1999].map(i => point.pointNumbers(P, M, i))"
        ".map(o => [o.file.number, o.nugget - 1, o.cluster]);"
    )
    for f, k, c in got:
        assert owner[(f, k)] == c


def test_one_cofactor_for_every_channel(js):
    """A run with one cofactor set converts every channel by it."""
    out = js(
        "const Q = { ...P, transform: [{ name: 'arcsinh', cofactor: 150, cofactor_from: 'set' }] };"
        "return point.pointNumbers(Q, makeModel(Q, null, 'nuggets'), 3);"
    )
    assert out["transform"] == "arcsinh"
    assert out["perChannel"] is False
    for r in out["rows"]:
        assert r["cofactor"] == 150
        assert r["file"] == pytest.approx(150 * math.sinh(r["plotted"]), rel=1e-12)


def test_a_run_on_raw_values_plots_the_file_values(js):
    """With a cofactor of 0 the run clusters the values as stored: plotted and file agree."""
    out = js(
        "const Q = { ...P, transform: [{ name: 'none' }] };"
        "return point.pointNumbers(Q, makeModel(Q, null, 'nuggets'), 3);"
    )
    assert out["transform"] == "none"
    for r in out["rows"]:
        assert r["file"] == r["plotted"]
        assert r["cofactor"] is None


def test_the_drawn_markers_are_marked_by_axis(js):
    """Rows for the channels on the axes say which axis; PCs and t-SNE axes mark none."""
    out = js(
        "const M = makeModel(P, null, 'nuggets');"
        "return [point.pointNumbers(P, M, 0, ['v4', 'v0', 'p1']).rows.map(r => r.axis),"
        " point.pointNumbers(P, M, 0, ['t0', 't1']).rows.map(r => r.axis)];"
    )
    with_vars, tsne = out
    assert with_vars[4] == "x"
    assert with_vars[0] == "y"
    assert [a for a in with_vars if a] == ["y", "x"]
    assert not any(tsne)


def test_from_plotted_inverts_the_transform(js):
    out = js(
        "const t = { name: 'arcsinh', cofactors: [150, 300] };"
        "return [point.fromPlotted(t, 0, Math.asinh(1234.5 / 150)),"
        " point.fromPlotted(t, 1, Math.asinh(-87 / 300)),"
        " point.fromPlotted({ name: 'none' }, 0, 2.5)];"
    )
    assert out[0] == pytest.approx(1234.5, rel=1e-12)
    assert out[1] == pytest.approx(-87, rel=1e-12)
    assert out[2] == 2.5


# In the file: the payload rounds a plotted value v to four significant digits, so v is known to
# half a unit in its last digit, u / 2, and c sinh(v) to about c cosh(v) u / 2. The card shows it
# to the power of ten at or above that, the step, and no finer.
def step_of(c: float, v: float) -> float:
    e = int(f"{v:e}".split("e")[1])
    h = c * math.cosh(v) * 10 ** (e - 3) / 2
    return 10 ** math.ceil(math.log10(h))


T2 = {"name": "arcsinh", "cofactor_from": "auto", "cofactors": [310.29, 150]}


def test_the_payload_digits_are_the_servers(js):
    from dnapp.core.config import SIG_DIGITS

    assert js("return config.PAYLOAD_SIG_DIGITS;") == SIG_DIGITS == 4


def test_a_file_value_stops_at_the_place_the_plotted_digits_fix(js):
    """At v = 5.715 a unit in the last digit is 0.001, so c sinh(v) = 47,069 is known to about
    310.29 x cosh(5.715) x 0.0005 = 24: the card shows 47,100. A small v pins its file value to
    the hundredth."""
    t = json.dumps(T2)
    got = js(
        f"const t = {t}, x = 310.29 * Math.sinh(5.715), y = 150 * Math.sinh(0.1234);"
        "return { s: point.fileStep(t, 0, 5.715), card: point.fmtFile(x, 100),"
        " plain: point.fmtFile(x, 100, true), neg: point.fmtFile(-x, point.fileStep(t, 0, -5.715)),"
        " s2: point.fileStep(t, 1, 0.1234), card2: point.fmtFile(y, 0.01),"
        " plain2: point.fmtFile(y, 0.01, true) };"
    )
    assert got == {
        "s": 100,
        "card": "47,100",
        "plain": "47100",
        "neg": "-47,100",
        "s2": 0.01,
        "card2": "18.56",
        "plain2": "18.56",
    }


def test_a_file_value_without_a_step(js):
    """0 is exact, and so is a value no arcsinh moved: those show as fmtNum does. A value that
    rounds to 0 never shows a minus sign."""
    t = json.dumps(T2)
    got = js(
        f"const t = {t};"
        "return [point.fileStep(t, 0, 0), point.fileStep({ name: 'none' }, 0, 5),"
        " point.fmtFile(1234.5, null), point.fmtFile(1234.5, null, true),"
        " point.fmtFile(-0.004, 0.01), point.fmtFile(-0.004, 0.01, true), point.fmtFile(-40, 100)];"
    )
    assert got == [None, None, "1235", "1234.5", "0.00", "0.00", "0"]


def test_every_r7_nugget_shows_only_digits_its_center_fixes(js, payloads):
    """Over every nugget and marker of the r7 run: the step covers the file value's uncertainty
    and is the smallest power of ten that does, and the value shown is within 1.5 steps of
    c sinh(v) at either end of v's rounding (half a step from rounding, a step of uncertainty)."""
    P, _ = payloads
    rows = js(
        "const M = makeModel(P, null, 'nuggets'), out = [];"
        "for (let i = 0; i < M.n; i++) for (const r of point.pointNumbers(P, M, i).rows)"
        " out.push([r.plotted, r.cofactor, r.step, point.fmtFile(r.file, r.step, true)]);"
        "return out;"
    )
    assert len(rows) == len(P["nuggets"]["centers"]) * len(P["columns"])
    for v, c, step, shown in rows:
        if v == 0:
            assert step is None and float(shown) == 0
            continue
        assert step == pytest.approx(step_of(c, v), rel=1e-12)
        e = int(f"{v:e}".split("e")[1])
        u = 10 ** (e - 3)
        h = c * math.cosh(v) * u / 2
        assert h <= step < 10 * h * (1 + 1e-9)
        for end in (v - u / 2, v + u / 2):
            assert abs(float(shown) - c * math.sinh(end)) <= 1.5 * step * (1 + 1e-9)
