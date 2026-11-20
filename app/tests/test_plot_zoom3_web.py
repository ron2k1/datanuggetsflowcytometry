"""The 3D wheel's zoom, app/web/features/plot/zoom3.js, and how history.js records it, run in
Node: the wheel narrows the three axis ranges about the point under the cursor, as Plotly's 2D
wheel narrows two, instead of moving the camera, which EYE.minR stops about 1.8 times closer than
Fit. The modules and what they import are copied beside a package.json that marks them as ES
modules; the tests skip where Node isn't installed."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")

AXES = ("xaxis", "yaxis", "zaxis")
# Fit's box of three axes of different spans and signs.
FIT = {"xaxis": [-10.0, 30.0], "yaxis": [2.0, 3.0], "zaxis": [-400.0, -100.0]}
CAMERA = {
    "eye": {"x": 1.5, "y": 1.4, "z": 0.95},
    "center": {"x": 0, "y": 0, "z": -0.08},
    "up": {"x": 0, "y": 0, "z": 1},
}


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """js(body) runs body as an async function in Node with `zoom3`, `history` and `config`
    imported, and returns what it returns, through JSON."""
    root = tmp_path_factory.mktemp("web")
    shutil.copytree(WEB / "shared", root / "shared")
    (root / "features/plot").mkdir(parents=True)
    for rel in ("zoom3.js", "history.js"):
        shutil.copyfile(WEB / "features/plot" / rel, root / "features/plot" / rel)
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"

    def run(body: str):
        script.write_text(
            "import * as zoom3 from './features/plot/zoom3.js';\n"
            "import * as history from './features/plot/history.js';\n"
            "import * as config from './shared/config.js';\n"
            f"const out = await (async () => {{ {body} }})();\n"
            "process.stdout.write(JSON.stringify(out === undefined ? null : out));\n",
            encoding="utf-8",
        )
        done = subprocess.run(
            [NODE, str(script)], capture_output=True, text=True, timeout=60, check=False
        )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    return run


def zoom_box(js, box, p, f, fit=FIT):
    return js(f"return zoom3.zoomBox({json.dumps(fit)}, {json.dumps(box)}, {p}, {f});")


def place(box, p):
    """Where p sits in box on each axis, 0 at its low end and 1 at its high end."""
    return [(p[a] - box[k][0]) / (box[k][1] - box[k][0]) for a, k in enumerate(AXES)]


def test_fit_box_is_plotlys_3d_autorange(js):
    """Each axis from the lowest to the highest value of the rows drawn, padded by 1/32 of that
    span either side; rows not drawn don't count."""
    cols = [[0, 4, 100, 2], [-1, 1, 50, 0], [7, 7, 7, 9]]
    got = js(f"return zoom3.fitBox({json.dumps(cols)}, [0, 1, 3]);")
    assert got["xaxis"] == pytest.approx([0 - 4 / 32, 4 + 4 / 32])
    assert got["yaxis"] == pytest.approx([-1 - 2 / 32, 1 + 2 / 32])
    assert got["zaxis"] == pytest.approx([7 - 2 / 32, 9 + 2 / 32])


def test_fit_box_without_a_span(js):
    """-1 to 1 with no rows; the value plus or minus 1 when every row has the same one."""
    cols = [[5, 5], [0, 0], [-2, -2]]
    assert js(f"return zoom3.fitBox({json.dumps(cols)}, []);") == {k: [-1, 1] for k in AXES}
    got = js(f"return zoom3.fitBox({json.dumps(cols)}, [0, 1]);")
    assert got == {"xaxis": [4, 6], "yaxis": [-1, 1], "zaxis": [-3, -1]}


@pytest.mark.parametrize("dy", [100, -100, 5, -3, 20, 1000, -1000])
def test_wheel_factor_is_plotlys_2d_wheel(js, dy):
    """Plotly's 2D wheel scales an axis by exp(-clamp(-deltaY, -20, 20) / 200): a mouse notch
    (deltaY 100) zooms in or out by exp(0.1)."""
    plotly = math.exp(-min(max(-dy, -20), 20) / 200)
    assert js(f"return zoom3.wheelFactor({dy});") == pytest.approx(plotly, rel=1e-15)


def test_zoom_box_keeps_the_point_in_place(js):
    """Zooming in by f about p scales every span by f and leaves p where it was in the box on
    each axis, so it stays under the cursor; the point need not be the middle."""
    p = [20.0, 2.25, -350.0]
    got = zoom_box(js, None, p, 0.5)
    for k in AXES:
        assert got[k][1] - got[k][0] == pytest.approx((FIT[k][1] - FIT[k][0]) / 2, rel=1e-12)
    assert place(got, p) == pytest.approx(place(FIT, p), rel=1e-12)
    again = zoom_box(js, got, p, 0.2)
    assert place(again, p) == pytest.approx(place(FIT, p), rel=1e-12)
    assert js(f"return zoom3.boxZoom({json.dumps(FIT)}, {json.dumps(again)});") == pytest.approx(
        10, rel=1e-12
    )


def test_zoom_box_snaps_back_to_fit(js):
    """A spin in and back out ends at Fit (null) though its steps multiply back to 1 only to
    rounding; zooming out from Fit stays at Fit."""
    p = [0.0, 2.9, -120.0]
    steps = ", ".join(["0.9"] * 7 + [str(1 / 0.9)] * 7)
    body = (
        f"let b = null; for (const f of [{steps}]) b = zoom3.zoomBox({json.dumps(FIT)}, b, {p}, f);"
        " return b;"
    )
    assert js(body) is None
    assert zoom_box(js, None, p, 1.3) is None
    # Halfway back out is still zoomed in.
    half = zoom_box(js, zoom_box(js, None, p, 0.25), p, 2)
    assert js(f"return zoom3.boxZoom({json.dumps(FIT)}, {json.dumps(half)});") == pytest.approx(
        2, rel=1e-12
    )


def test_zoom_box_stops_at_max_zoom(js):
    """No span goes under Fit's / maxZoom, however far the wheel turns."""
    max_zoom = js("return config.ZOOM_3D.maxZoom;")
    p = [10.0, 2.5, -250.0]
    got = zoom_box(js, None, p, 1e-9)
    for k in AXES:
        want = (FIT[k][1] - FIT[k][0]) / max_zoom
        assert got[k][1] - got[k][0] == pytest.approx(want, rel=1e-9), k
    assert js(f"return zoom3.boxZoom({json.dumps(FIT)}, {json.dumps(got)});") == pytest.approx(
        max_zoom, rel=1e-9
    )


def test_box_zoom_is_the_least_zoomed_axis(js):
    assert js(f"return zoom3.boxZoom({json.dumps(FIT)}, null);") == 1
    assert js(f"return zoom3.boxZoom(null, {json.dumps(FIT)});") == 1
    box = {"xaxis": [0, 10], "yaxis": [2, 2.5], "zaxis": [-400, -100]}  # 4x, 2x and 1x
    assert js(f"return zoom3.boxZoom({json.dumps(FIT)}, {json.dumps(box)});") == 1
    box["zaxis"] = [-300, -150]
    assert js(f"return zoom3.boxZoom({json.dumps(FIT)}, {json.dumps(box)});") == 2


def test_middle(js):
    assert js(f"return zoom3.middle({json.dumps(FIT)});") == [10, 2.5, -250]


# history.js: a wheel step relayouts the scene axes and is one Back step; Back restores the box
# with the camera, and Fit drops the box. Plotly is a stub that records each relayout.
STUB = f"""
globalThis.window = {{ Plotly: {{ calls: [], relayout(div, upd) {{ this.calls.push(upd); return Promise.resolve(); }} }} }};
const cam = {json.dumps(CAMERA)};
const div = {{ _fullLayout: {{ scene: {{ _scene: {{ getCamera: () => JSON.parse(JSON.stringify(cam)) }} }} }} }};
const st = {{ view: '3d', camera: null, box3: null, hist: history.newHist() }};
st.hist.now = history.view3(st, cam);
// Node's clock starts with the process, a page's long before a wheel turn: the last gesture
// ended long ago.
st.hist.last = -Infinity;
const fit = {json.dumps(FIT)};
const calls = window.Plotly.calls;
"""


def test_a_wheel_step_relayouts_the_box_and_is_one_back_step(js):
    got = js(
        STUB
        + "await history.zoomView3(div, st, fit, [20, 2.25, -350], 0.5);"
        + "const first = { box: st.box3, stack: st.hist.stack, now: st.hist.now, calls: [...calls] };"
        + "await history.zoomView3(div, st, fit, [20, 2.25, -350], 0.5);"
        + "return { first, stack: st.hist.stack.length, box: st.box3 };"
    )
    first = got["first"]
    assert first["calls"] == [{f"scene.{k}.range": first["box"][k] for k in AXES}]
    # The view before the spin, Fit's box and the camera, is the one Back step; now is the box.
    assert first["stack"] == [{"camera": CAMERA, "box": None}]
    assert first["now"] == {"camera": CAMERA, "box": first["box"]}
    # A second step of the same spin (under HISTORY.gapMs later) adds no Back step.
    assert got["stack"] == 1
    for k in AXES:
        assert got["box"][k][1] - got["box"][k][0] == pytest.approx(
            (FIT[k][1] - FIT[k][0]) / 4, rel=1e-12
        )


def test_back_restores_the_box_and_fit_drops_it(js):
    got = js(
        STUB
        + "await history.zoomView3(div, st, fit, [20, 2.25, -350], 0.5);"
        + "const zoomed = st.box3; calls.length = 0;"
        + "history.backView(div, st, () => {}); await Promise.resolve();"
        + "const back = { box: st.box3, call: calls[calls.length - 1], stack: st.hist.stack.length };"
        + "st.box3 = zoomed; calls.length = 0;"
        + "history.fitView(div, st, () => {}); await Promise.resolve();"
        + "return { back, fit: { box: st.box3, call: calls[calls.length - 1], camera: st.camera } };"
    )
    back, fit = got["back"], got["fit"]
    autorange = {f"scene.{k}.autorange": True for k in AXES}
    assert back["box"] is None and back["stack"] == 0
    assert back["call"] == {"scene.camera": CAMERA, **autorange}
    assert fit["box"] is None and fit["camera"] == CAMERA
    assert fit["call"] == {"scene.camera": CAMERA, **autorange}


def test_box_layout(js):
    box = {"xaxis": [1, 2], "yaxis": [3, 4], "zaxis": [5, 6]}
    assert js(f"return history.boxLayout({json.dumps(box)});") == {
        f"scene.{k}.range": box[k] for k in AXES
    }
    assert js("return history.boxLayout(null);") == {f"scene.{k}.autorange": True for k in AXES}
