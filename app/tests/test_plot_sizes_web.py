"""The plot's marker sizes, app/web/features/plot/sizes.js, run in Node: a run of up to 2,000
nuggets draws at MARKER's sizes, a larger one at sqrt(2,000 / n) of them down to each view's
floor, with the Point size factor on top; and figure.js, which hands those sizes to each view's
traces. The modules and what they import are copied beside a package.json that marks them as ES
modules, so any Node from 18 on runs them; the tests skip where Node isn't installed."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
MODULES = ("shared/config.js", "features/plot/sizes.js")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")

# MARKER's sizes in px, pinned here so a change to config.js has to change this file too.
BASE = {"2d": 12, "3d": 7, "pairs": 7}
FLOOR = {"2d": 4, "3d": 2.5, "pairs": 4 * 7 / 12}
# The weights of a four-nugget run, and ln(1 + w) / ln(1 + wmax) for each.
WEIGHTS = [1, 4, 0, 2.25]
LOGS = [math.log(2) / math.log(5), 1, 0, math.log(3.25) / math.log(5)]
# The weight sizes in px before the shrink: min + span x that log, per view.
WEIGHT = {"2d": (3, 21), "3d": (2, 12)}


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """js(body) runs body as a function in Node with `sizes` (sizes.js) and `config` (config.js)
    imported, and returns what it returns, through JSON."""
    root = tmp_path_factory.mktemp("web")
    for rel in MODULES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEB / rel, root / rel)
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"

    def run(body: str):
        script.write_text(
            "import * as sizes from './features/plot/sizes.js';\n"
            "import * as config from './shared/config.js';\n"
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


def per_view(js, model: dict, st: dict, idx: list[int]) -> dict:
    """markerSizes for each view, keyed '2d', '3d' and 'pairs'."""
    args = f"{json.dumps(model)}, {json.dumps(st)}, {json.dumps(idx)}"
    views = "['2d', '3d', 'pairs']"
    return js(f"return Object.fromEntries({views}.map(v => [v, sizes.markerSizes({args}, v)]));")


def uniform(js, n, scale=1.0, src="nuggets"):
    """The one size each view gives every point of a run of n, at Point size `scale`."""
    model = {"src": src, "n": n, "weight": None}
    return per_view(js, model, {"pointScale": scale, "sizeW": False}, [0, 1])


def weighted(js, n, idx, scale=1.0):
    """Each view's sizes by weight for the points idx of a run of n nuggets."""
    model = {"src": "nuggets", "n": n, "weight": WEIGHTS}
    return per_view(js, model, {"pointScale": scale, "sizeW": True}, idx)


def times(sizes: dict, factor: dict) -> dict:
    return {v: [s * factor[v] for s in sizes[v]] for v in sizes}


def assert_close(got: dict, want: dict):
    """Per-view lists of sizes equal to 12 significant digits (approx takes no nested dicts)."""
    assert got.keys() == want.keys()
    for v, sizes in want.items():
        assert got[v] == pytest.approx(sizes, rel=1e-12), v


def test_the_reference_and_floors_are_in_marker(js):
    got = js("const m = config.MARKER; return [m.refNuggets, m.floor2d, m.floor3d];")
    assert got == [2000, FLOOR["2d"], FLOOR["3d"]]
    got = js("const m = config.MARKER; return [m.size2d, m.size3d, m.pairs];")
    assert got == [BASE["2d"], BASE["3d"], BASE["pairs"]]


@pytest.mark.parametrize("n", [0, 1, 500, 2000])
def test_a_run_of_up_to_2000_nuggets_draws_as_before(js, n):
    assert uniform(js, n) == BASE


# Each view's sizes with no shrink, written out from config.js's MARKER, for the test below.
BEFORE = """
const K = config.MARKER;
const old = (M, st, idx, three) => {
  const f = st.pointScale;
  if (st.sizeW && M.weight) {
    let wmax = 0;
    for (const w of M.weight) if (w > wmax) wmax = w;
    const lo = three ? K.weightMin3d : K.weightMin2d, sp = three ? K.weightSpan3d : K.weightSpan2d;
    return idx.map(i => f * (lo + sp * (Math.log1p(M.weight[i]) / (Math.log1p(wmax) || 1))));
  }
  if (M.src === 'cells') return f * (three ? K.cells3d : K.cells2d);
  return f * (three ? K.size3d : K.size2d);
};
const oldPairs = (M, st, idx) => (st.sizeW && M.weight
  ? old(M, st, idx, false).map(v => v * (K.pairs / K.size2d))
  : st.pointScale * (M.src === 'cells' ? K.cells2d : K.pairs));
"""


def test_up_to_2000_nuggets_every_size_is_bit_for_bit_the_unshrunk_one(js):
    got = js(
        BEFORE + "const bad = [], idx = [0, 1, 2, 3];"
        "for (const n of [0, 1, 500, 1999, 2000]) for (const src of ['nuggets', 'cells'])"
        " for (const p of [0.5, 1, 1.3, 1.7, 3]) for (const sizeW of [false, true]) {"
        "  const M = {src, n, weight: src === 'cells' ? null : [1, 4, 0, 2.25, 0.3]};"
        "  const st = {pointScale: p, sizeW};"
        "  const want = {'2d': old(M, st, idx, false), '3d': old(M, st, idx, true),"
        "    pairs: oldPairs(M, st, idx)};"
        "  for (const v of ['2d', '3d', 'pairs']) {"
        "    const a = JSON.stringify(sizes.markerSizes(M, st, idx, v));"
        "    if (a !== JSON.stringify(want[v])) bad.push([n, src, p, sizeW, v, a]);"
        "  }"
        "}"
        "return bad;"
    )
    assert got == []


@pytest.mark.parametrize(
    ("n", "factor"), [(2001, math.sqrt(2000 / 2001)), (8000, 0.5), (13000, math.sqrt(2 / 13))]
)
def test_a_larger_run_shrinks_by_the_square_root(js, n, factor):
    got = uniform(js, n)
    assert got == pytest.approx({v: BASE[v] * factor for v in BASE}, rel=1e-12)
    if n == 13000:  # 13 files x 1,000 nuggets
        assert factor == pytest.approx(0.392, abs=1e-3)
        assert got == pytest.approx({"2d": 4.707, "3d": 2.746, "pairs": 2.746}, abs=1e-3)


@pytest.mark.parametrize("n", [100_000, 10**7])
def test_a_huge_run_stops_at_the_floor(js, n):
    assert uniform(js, n) == pytest.approx(FLOOR, rel=1e-12)


def test_the_floor_is_reached_where_the_square_root_meets_it(js):
    """2D reaches 4 px at 2,000 x (12 / 4)^2 = 18,000 nuggets, 3D 2.5 px at 2,000 x (7 / 2.5)^2
    = 15,680; Pairs keeps the 2D ratio, so it reaches its floor with 2D."""
    got = js(
        "return [15680, 18000, 30000].map(n =>"
        " ['2d', '3d', 'pairs'].map(v => sizes.crowdFactor(n, v)));"
    )
    early = math.sqrt(2000 / 15680)
    assert got[0] == pytest.approx([early, 2.5 / 7, early], rel=1e-12)
    assert got[1] == pytest.approx([1 / 3, 2.5 / 7, 1 / 3], rel=1e-12)
    assert got[2] == pytest.approx([1 / 3, 2.5 / 7, 1 / 3], rel=1e-12)


@pytest.mark.parametrize(
    ("n", "scale"), [(2000, 2.0), (8000, 2.0), (8000, 0.5), (100_000, 3.0), (100_000, 0.5)]
)
def test_point_size_multiplies_after_the_shrink_and_floor(js, n, scale):
    one = uniform(js, n)
    assert uniform(js, n, scale) == pytest.approx({v: one[v] * scale for v in one}, rel=1e-12)


def test_cells_keep_their_sizes_whatever_the_count(js):
    for n in (500, 13000, 10**6):
        assert uniform(js, n, src="cells") == {"2d": 4, "3d": 2.6, "pairs": 4}
    assert uniform(js, 10**6, 2.0, src="cells") == {"2d": 8, "3d": 5.2, "pairs": 8}


def test_weight_sizes_shrink_by_the_same_factor(js):
    """lo + span x ln(1 + w) / ln(1 + wmax) per point (2D 3 + 21, 3D 2 + 12, Pairs the 2D ones x
    7 / 12), times the run's factor and then the Point size."""
    (lo2, sp2), (lo3, sp3) = WEIGHT["2d"], WEIGHT["3d"]
    as_before = {
        "2d": [lo2 + sp2 * t for t in LOGS],
        "3d": [lo3 + sp3 * t for t in LOGS],
        "pairs": [(lo2 + sp2 * t) * 7 / 12 for t in LOGS],
    }
    all4 = [0, 1, 2, 3]
    assert_close(weighted(js, 2000, all4), as_before)
    assert_close(weighted(js, 500, all4), as_before)
    assert_close(weighted(js, 8000, all4), times(as_before, {"2d": 0.5, "3d": 0.5, "pairs": 0.5}))
    assert_close(weighted(js, 8000, all4, 2.0), as_before)
    floor = times(as_before, {"2d": 1 / 3, "3d": 2.5 / 7, "pairs": 1 / 3})
    assert_close(weighted(js, 10**6, all4), floor)
    assert_close(weighted(js, 10**6, all4, 1.5), times(floor, {"2d": 1.5, "3d": 1.5, "pairs": 1.5}))


def test_heavy_tailed_weights_get_distinct_sizes(js):
    """The r3 fixture's 4,000 nuggets (four public PBMC files): median weight 3, 95th percentile
    106, largest 3,970. sqrt(w / wmax) drew the median and the 95th percentile at 7.0 and 9.4 px
    in 2D; the log puts them at 6.5 and 14.8 before the run's shrink, and the largest at 24."""
    fix = WEB / "fixtures" / "GET__runs__r3__plot.json"
    w = json.loads(fix.read_text(encoding="utf-8"))["nuggets"]["weight"]
    assert (np.median(w), np.percentile(w, 95), max(w)) == (3, 106, 3970)
    at = [w.index(3), w.index(106), w.index(3970)]
    model = {"src": "nuggets", "n": 2000, "weight": w}
    got = per_view(js, model, {"pointScale": 1, "sizeW": True}, at)["2d"]
    assert got == pytest.approx([6.512, 14.84, 24], abs=5e-3)
    assert got[1] - got[0] > 8


@pytest.mark.parametrize(
    ("wmax", "keys"),
    [(3970, [1, 10, 100, 1000, 3970]), (1000, [1, 10, 100, 1000]), (12, [1, 12]), (1, [1])],
)
def test_the_size_key_has_powers_of_ten_then_the_largest_weight(js, wmax, keys):
    """Powers of ten up to half the largest weight, then the largest, each at the size a nugget
    of that weight draws in the view (here a run of 8,000, so half size, at Point size 2)."""
    model = {"src": "nuggets", "n": 8000, "weight": [wmax, 1]}
    st = {"pointScale": 2, "sizeW": True}
    for view in ("2d", "3d", "pairs"):
        got = js(
            f"return sizes.weightKey({json.dumps(model)}, {json.dumps(st)}, {json.dumps(view)});"
        )
        lo, span = WEIGHT["3d" if view == "3d" else "2d"]
        pairs = 7 / 12 if view == "pairs" else 1
        assert [k["w"] for k in got] == keys
        want = [(lo + span * math.log1p(k) / math.log1p(wmax)) * pairs * 0.5 * 2 for k in keys]
        assert [k["size"] for k in got] == pytest.approx(want, rel=1e-12), view


def test_the_points_drawn_never_change_a_size(js):
    """The factor comes from the model's n, not from how many points a view draws, so hiding or
    picking clusters leaves every point its size."""
    every = weighted(js, 13000, [0, 1, 2, 3])
    assert weighted(js, 13000, [1, 3]) == {v: [every[v][1], every[v][3]] for v in every}
    model = {"src": "nuggets", "n": 13000, "weight": None}
    assert per_view(js, model, {"pointScale": 1, "sizeW": False}, []) == uniform(js, 13000)


# figure.js, the Plotly traces, run with the stubs its imports read at load and draw time (the
# theme's colours, the fixture flag, stored settings). The run has N nuggets in clusters 1, 2 and
# 3 (point i in cluster 1 + i % 3, weight i % 4) and cluster 1 picked, so clusters 2 and 3 are
# the other clusters' points. N = 8,000 halves every nugget size.
N = 8000
HALF = 0.5
FIGURE = """
const stub = (k, v) => Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
stub('window', { innerWidth: 1600 });
stub('location', { search: '' });
stub('localStorage', { getItem: () => null, setItem() {} });
stub('document', { documentElement: { getAttribute: () => null } });
stub('getComputedStyle', () => ({ getPropertyValue: () => '#888888' }));
const { figure } = await import('./features/plot/figure.js');
const model = (n, src, weighted) => {
  const col = a => Array.from({ length: n }, (_, i) => i * a);
  const cols = { v1: col(1), v2: col(2), v3: col(3) };
  return { n, src, cluster: Array.from({ length: n }, (_, i) => 1 + (i % 3)),
    index: Array.from({ length: n }, (_, i) => i), file: null,
    weight: weighted ? Array.from({ length: n }, (_, i) => i % 4) : null,
    colors: new Map([[1, '#d55e00'], [2, '#0072b2'], [3, '#009e73']]), vars: ['v1', 'v2', 'v3'], pcs: [],
    column: k => cols[k], label: k => k };
};
const draw = (view, o) => {
  const M = model(o.n, o.src, o.sizeW);
  const st = { view, axes: ['v1', 'v2', 'v3'], units: 'raw', hidden: new Set(o.hidden), sel: new Set(o.sel),
    hover: null, others: o.others, colorBy: 'cluster', pointScale: o.scale, sizeW: o.sizeW, camera: null,
    drag3d: 'orbit', boxArmed: false };
  if (o.zoom != null) st.zoomGrow = o.zoom;
  if (o.box3) st.box3 = o.box3;
  if (o.point) st.point = o.point;
  const f = figure(M, st, [], 'r1');
  if (view === 'pairs') {
    const t = f.data[0];
    return { type: [t.type], idx: [...f.parts.dim, ...f.parts.on], size: t.marker.size };
  }
  const sc = f.layout.scene;
  return { type: f.data.map(t => t.type), dim: f.parts.dim, on: f.parts.on,
    size: f.data.map(t => t.marker.size),
    scene: sc && { xaxis: sc.xaxis, yaxis: sc.yaxis, zaxis: sc.zaxis },
    onText: f.data[1].text,
    ring: f.data[2] ? (r => ({ type: r.type, symbol: r.marker.symbol, hoverinfo: r.hoverinfo ?? null,
      hovertemplate: r.hovertemplate ?? null, text: r.text ?? null }))(f.data[2]) : null };
};
"""


@pytest.fixture(scope="module")
def fig(tmp_path_factory):
    """fig(view, ...) draws the run in figure.js and returns its trace types and marker sizes:
    for 2D and 3D the dim trace's then the "on" trace's, for Pairs the splom's, over the points
    idx (other clusters' points first)."""
    root = tmp_path_factory.mktemp("web")
    shutil.copytree(WEB / "shared", root / "shared")
    for rel in ("figure.js", "history.js", "sizes.js", "zoom3.js"):
        rel = f"features/plot/{rel}"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEB / rel, root / rel)
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"

    def run(
        view,
        *,
        n=N,
        src="nuggets",
        size_w=False,
        sel=(1,),
        hidden=(),
        others="grey",
        scale=1,
        zoom=None,
        box3=None,
        point=None,
    ):
        opts = {"n": n, "src": src, "sizeW": size_w, "sel": list(sel), "hidden": list(hidden)}
        opts |= {"others": others, "scale": scale, "zoom": zoom, "box3": box3, "point": point}
        call = f"draw({json.dumps(view)}, {json.dumps(opts)})"
        script.write_text(
            f"{FIGURE}process.stdout.write(JSON.stringify({call}));\n", encoding="utf-8"
        )
        done = subprocess.run(
            [NODE, str(script)], capture_output=True, text=True, timeout=60, check=False
        )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    return run


def weight_size(i: int, lo: float, span: float) -> float:
    """lo + span x ln(1 + w) / ln(1 + wmax) for point i of the figure's run (w = i % 4, wmax =
    3)."""
    return lo + span * math.log1p(i % 4) / math.log1p(3)


def test_figure_draws_each_view_at_its_size_and_other_clusters_smaller(fig):
    """2D draws scattergl at 12 px and 3D scatter3d at 7, Pairs a splom at 7, each times the
    run's factor, with the other clusters' nuggets at 0.6x of that (DIM.scale)."""
    for view, kind, base in (("2d", "scattergl", 12), ("3d", "scatter3d", 7)):
        got = fig(view)
        assert got["type"] == [kind, kind]
        assert len(got["dim"]) == 2 * N // 3 and len(got["on"]) == N - 2 * N // 3
        assert got["size"] == pytest.approx([base * HALF * 0.6, base * HALF], rel=1e-12), view
    got = fig("pairs")
    assert got["type"] == ["splom"] and len(got["idx"]) == N
    want = [7 * HALF * (1 if i % 3 == 0 else 0.6) for i in got["idx"]]
    assert got["size"] == pytest.approx(want, rel=1e-12)


def test_figure_draws_weight_sizes_per_point(fig):
    """By weight, each point's size from its own weight: 2D 3 + 21 x ln(1 + w) / ln(1 + wmax), 3D
    2 + 12 x the same, Pairs the 2D ones x 7 / 12, all times the run's factor and, for the other
    clusters' nuggets, 0.6."""
    for view in ("2d", "3d"):
        lo, span = WEIGHT[view]
        got = fig(view, size_w=True)
        dim, on = got["size"]
        assert dim == pytest.approx([weight_size(i, lo, span) * HALF * 0.6 for i in got["dim"]])
        assert on == pytest.approx([weight_size(i, lo, span) * HALF for i in got["on"]])
    got = fig("pairs", size_w=True)
    fade = {i: 1 if i % 3 == 0 else 0.6 for i in got["idx"]}
    want = [weight_size(i, *WEIGHT["2d"]) * 7 / 12 * HALF * fade[i] for i in got["idx"]]
    assert got["size"] == pytest.approx(want, rel=1e-12)


def test_figure_keeps_the_cells_sizes(fig):
    """Cells draw at 4 px in 2D and Pairs and 2.6 in 3D whatever the count, the other clusters'
    cells too."""
    assert fig("2d", src="cells")["size"] == [4, 4]
    assert fig("3d", src="cells")["size"] == [2.6, 2.6]
    assert fig("pairs", src="cells")["size"] == 4


def test_figure_sizes_do_not_follow_what_is_drawn(fig):
    """No pick, a hidden cluster, the other clusters hidden or in their own colour: every point
    keeps its size. Point size 2 doubles them."""
    none = fig("2d", sel=())
    assert none["dim"] == [] and len(none["on"]) == N and none["size"][1] == 12 * HALF
    assert fig("3d", hidden=(2,))["size"] == pytest.approx([7 * HALF * 0.6, 7 * HALF])
    hidden = fig("3d", others="hide")
    assert hidden["dim"] == [] and hidden["size"][1] == pytest.approx(7 * HALF)
    assert fig("2d", others="own")["size"] == pytest.approx([12 * HALF * 0.6, 12 * HALF])
    assert fig("pairs", sel=())["size"] == pytest.approx(7 * HALF)
    pairs = fig("pairs", others="hide")
    assert len(pairs["idx"]) == N - 2 * N // 3 and pairs["size"] == pytest.approx(7 * HALF)
    assert fig("2d", scale=2)["size"] == pytest.approx([12 * HALF * 0.6 * 2, 12 * HALF * 2])


# Zoom: 2D nuggets grow as the view zooms in from Fit. The factor is the smaller of the two axes'
# span ratios (Fit's span over the view's), to the power ZOOM_GROW.power, held in [1, max].
HOME = {"xaxis": [-200, 200], "yaxis": [-80, 80]}


def view_at(zx: float, zy: float, cx: float = 0, cy: float = 0) -> dict:
    """HOME zoomed in zx times on x and zy on y, centred on (cx, cy)."""
    hx, hy = 200 / zx, 80 / zy
    return {"xaxis": [cx - hx, cx + hx], "yaxis": [cy - hy, cy + hy]}


def grow(js, home, now):
    return js(f"return sizes.zoomGrow({json.dumps(home)}, {json.dumps(now)});")


def test_zoom_grow_is_pinned_in_config(js):
    assert js("return config.ZOOM_GROW;") == {"power": 0.5, "max": 4}


def test_zoom_grow_is_one_at_fit_and_without_a_view(js):
    assert grow(js, HOME, HOME) == 1
    assert grow(js, None, HOME) == 1 and grow(js, HOME, None) == 1
    assert grow(js, HOME, {"xaxis": [0, 1]}) == 1  # an axis missing


@pytest.mark.parametrize("z", [1.5, 4, 9, 16])
def test_zoom_grow_is_the_square_root_of_the_zoom(js, z):
    assert grow(js, HOME, view_at(z, z, cx=37, cy=-12)) == pytest.approx(math.sqrt(z), rel=1e-12)


def test_zoom_grow_follows_the_less_zoomed_axis(js):
    """A box drawn tall and thin zooms one axis far more than the other; the points grow with
    the other, so they never outgrow the room the view gives them across."""
    assert grow(js, HOME, view_at(9, 1)) == 1
    assert grow(js, HOME, view_at(9, 4)) == pytest.approx(2, rel=1e-12)


def test_zoom_grow_never_shrinks_and_stops_at_max(js):
    assert grow(js, HOME, view_at(0.25, 0.25)) == 1  # zoomed out past Fit
    assert grow(js, HOME, view_at(16, 16)) == pytest.approx(4)
    assert grow(js, HOME, view_at(400, 400)) == 4
    # A reversed axis (range high to low) has a negative span; a 4x zoom on one still grows 2x.
    reversed_zoom = {"xaxis": [50, -50], "yaxis": [20, -20]}
    assert grow(js, HOME, reversed_zoom) == pytest.approx(2, rel=1e-12)


def zoomed(js, model: dict, st: dict, idx: list[int], g: float) -> dict:
    return per_view(js, model, {**st, "zoomGrow": g}, idx)


def test_zoom_grows_2d_and_3d_nuggets(js):
    """2D and 3D nugget sizes, uniform or by weight, take the zoom factor on top of everything
    else; Pairs keeps its sizes (its subplots don't zoom with the view), and cells keep theirs."""
    plain = {"src": "nuggets", "n": 8000, "weight": None}
    st = {"pointScale": 1.5, "sizeW": False}
    one = per_view(js, plain, st, [0, 1])
    got = zoomed(js, plain, st, [0, 1], 2.5)
    assert got == pytest.approx(
        {"2d": one["2d"] * 2.5, "3d": one["3d"] * 2.5, "pairs": one["pairs"]}
    )
    heavy = {"src": "nuggets", "n": 8000, "weight": WEIGHTS}
    stw = {"pointScale": 1, "sizeW": True}
    one = per_view(js, heavy, stw, [0, 1, 2, 3])
    assert_close(
        zoomed(js, heavy, stw, [0, 1, 2, 3], 3), times(one, {"2d": 3, "3d": 3, "pairs": 1})
    )
    cells = {"src": "cells", "n": 10**6, "weight": None}
    assert zoomed(js, cells, st, [0], 4) == per_view(js, cells, st, [0])


def test_the_size_key_shows_the_zoomed_sizes(js):
    model = {"src": "nuggets", "n": 2000, "weight": [3970, 1]}
    st = {"pointScale": 1, "sizeW": True}
    for view, g in (("2d", 2), ("3d", 2), ("pairs", 1)):
        call = f"{json.dumps(model)}, {{...{json.dumps(st)}, zoomGrow: 2}}, {json.dumps(view)}"
        at = js(f"return sizes.weightKey({call});")
        base = js(
            f"return sizes.weightKey({json.dumps(model)}, {json.dumps(st)}, {json.dumps(view)});"
        )
        assert [k["size"] for k in at] == pytest.approx([k["size"] * g for k in base]), view


def test_figure_draws_2d_and_3d_nuggets_zoomed(fig):
    assert fig("2d", zoom=2)["size"] == pytest.approx([12 * HALF * 0.6 * 2, 12 * HALF * 2])
    assert fig("3d", zoom=2)["size"] == pytest.approx([7 * HALF * 0.6 * 2, 7 * HALF * 2])
    assert fig("2d", src="cells", zoom=2)["size"] == [4, 4]


# 3D zoom: the wheel narrows the box (zoom3.js, its own tests in test_plot_zoom3_web.py) and the
# camera can close in on the point it looks at. Plotly draws a 3D marker at a fixed size in px, so
# either spreads the points and leaves the dots as they were; grow3 grows them by 2D's rule on the
# product of the two zooms: the box's (boxZoom) times Fit's camera distance (DEFAULT_CAMERA) over
# the camera's, to ZOOM_GROW.power, held in [1, max].
DEFAULT = {
    "eye": {"x": 1.5, "y": 1.4, "z": 0.95},
    "center": {"x": 0, "y": 0, "z": -0.08},
    "up": {"x": 0, "y": 0, "z": 1},
}


def camera(z: float = 1, turn: float = 0, shift=(0.0, 0.0, 0.0)) -> dict:
    """DEFAULT moved z times closer to its center, turned `turn` radians about the vertical
    through the center, then the eye and the center both moved by shift (a pan)."""
    c, e = DEFAULT["center"], DEFAULT["eye"]
    d = [(e[k] - c[k]) / z for k in "xyz"]
    d = [
        d[0] * math.cos(turn) - d[1] * math.sin(turn),
        d[0] * math.sin(turn) + d[1] * math.cos(turn),
        d[2],
    ]
    center = {k: c[k] + s for k, s in zip("xyz", shift, strict=True)}
    eye = {k: center[k] + v for k, v in zip("xyz", d, strict=True)}
    return {"eye": eye, "center": center, "up": DEFAULT["up"]}


def grow3(js, cam, box_zoom=None):
    args = json.dumps(cam) + ("" if box_zoom is None else f", {box_zoom}")
    return js(f"return sizes.grow3({args});")


def test_the_3d_zoom_is_pinned_in_config(js):
    assert js("return config.ZOOM_3D;") == {"wheelMax": 20, "wheelScale": 200, "maxZoom": 1e4}
    assert js("return config.DEFAULT_CAMERA;") == DEFAULT
    assert js("return 'ZOOM_GROW_3D' in config;") is False


def test_grow3_is_one_at_fit_and_without_a_camera(js):
    assert grow3(js, DEFAULT) == 1
    assert grow3(js, DEFAULT, 1) == 1
    assert grow3(js, None) == 1
    assert grow3(js, {"eye": {"x": 1, "y": 1, "z": 1}}) == 1  # no center


@pytest.mark.parametrize("z", [1.5, 4, 9, 16])
def test_grow3_takes_the_box_zoom_as_2d_takes_its_zoom(js, z):
    """A box narrowed z times grows a dot sqrt(z) times, as a 2D view zoomed z times does: its
    area grows with the zoom while the gaps grow with its square."""
    assert grow3(js, DEFAULT, z) == pytest.approx(math.sqrt(z), rel=1e-12)
    assert grow3(js, None, z) == pytest.approx(math.sqrt(z), rel=1e-12)


@pytest.mark.parametrize("z", [1.2, 1.5, 1.8])
def test_grow3_takes_the_camera_zoom_too(js, z):
    assert grow3(js, camera(z)) == pytest.approx(math.sqrt(z), rel=1e-12)
    # The two zooms multiply: a camera 1.5 times closer on a box narrowed 6 times is 9 times in.
    assert grow3(js, camera(1.5), 6) == pytest.approx(3, rel=1e-12)


def test_grow3_ignores_turns_and_pans(js):
    assert grow3(js, camera(1, turn=2.1)) == pytest.approx(1, rel=1e-12)
    assert grow3(js, camera(1, shift=(0.4, -0.3, 0.2))) == pytest.approx(1, rel=1e-12)
    got = grow3(js, camera(1.5, turn=-0.7, shift=(0.1, 0.2, 0)), 6)
    assert got == pytest.approx(3, rel=1e-12)


def test_grow3_never_shrinks_and_stops_at_max(js):
    assert grow3(js, camera(0.5)) == 1  # further than Fit
    assert grow3(js, camera(0.5), 4) == pytest.approx(math.sqrt(2), rel=1e-12)
    assert grow3(js, DEFAULT, 16) == pytest.approx(4)
    assert grow3(js, DEFAULT, 400) == 4
    assert grow3(js, camera(40), 40) == 4


def test_figure_draws_the_wheels_box_else_fit(fig):
    """With a box (st.box3) every scene axis is fixed to it; without one Plotly autoranges, so a
    box the last draw had never stays."""
    box = {"xaxis": [1, 2], "yaxis": [-3, 5], "zaxis": [0.25, 0.5]}
    got = fig("3d", box3=box)["scene"]
    for k, r in box.items():
        assert got[k]["range"] == r and got[k]["autorange"] is False, k
    for k, ax in fig("3d")["scene"].items():
        assert ax["autorange"] is True and "range" not in ax, k


def test_the_3d_ring_carries_its_points_hover_and_the_2d_ring_takes_none(fig):
    """Plotly's 3D scene hovers whatever its pick buffer finds nearest the pointer, the ring
    included, and drops a pick whose trace skips hovers: a 3D ring that skipped them left its
    point and the points around it with no hover, so no click. The 3D ring carries its point's
    label (view.js takes a pick of it as the point). 2D hovers by distance per trace, so its ring
    still takes none."""
    for i, cluster in ((3, 1), (4, 2)):  # picked cluster 1: point 3 in view, point 4 greyed
        d = fig("3d", point={"src": "nuggets", "i": i})
        ring = d["ring"]
        assert ring["type"] == "scatter3d" and ring["symbol"] == "circle-open"
        assert ring["hoverinfo"] is None and ring["hovertemplate"] == "%{text}<extra></extra>"
        assert len(ring["text"]) == 1 and ring["text"][0].startswith(f"<b>Cluster {cluster}</b>")
        assert f"Nugget {i + 1}" in ring["text"][0]
        if i in d["on"]:
            assert ring["text"] == [d["onText"][d["on"].index(i)]]
        flat = fig("2d", point={"src": "nuggets", "i": i})["ring"]
        assert flat["symbol"] == "circle-open" and flat["hoverinfo"] == "skip"
        assert flat["text"] is None and flat["hovertemplate"] is None
    assert fig("3d")["ring"] is None
