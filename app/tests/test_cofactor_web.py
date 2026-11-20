"""The Transform stage's cofactor in the web, run in Node: app/web/shared/cofactor.js reads a run's
transform as the package reads it (run_transform), old run.json files included, and puts it in
words for the record, Compare, the plot and its inspector; the Live cells step's histogram.js draws
each channel on its own cofactor. Auto picks one cofactor per channel from the cells a run
clusters, so the cluster form can't preview it and says so. The modules are copied beside a
package.json that marks them as ES modules (plot-base.js, which reads the page's theme, as a stub),
so any Node from 18 on runs them; the tests skip where Node isn't installed."""

from __future__ import annotations

import json
import math
import re
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
    "features/live-cells/histogram.js",
)
# histogram.js takes only these from plot-base.js, which reads the page's theme tokens.
PLOT_BASE_STUB = (
    "export const PLOT_MONO = 'mono';\n"
    "export const baseLayout = () => ({});\n"
    "export const fileColor = () => '#000000';\n"
)
RULE = {"rule": "per_channel", "floor": 150.0, "min_negative_fraction": 0.01}
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """js(body) runs body as a function in Node with `cof` (cofactor.js), `config` (config.js)
    and `hist` (live-cells/histogram.js) imported, and returns what it returns, through JSON."""
    root = tmp_path_factory.mktemp("web")
    for rel in MODULES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEB / rel, root / rel)
    (root / "shared" / "plot-base.js").write_text(PLOT_BASE_STUB, encoding="utf-8")
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"

    def run(body: str):
        script.write_text(
            "import * as cof from './shared/cofactor.js';\n"
            "import * as config from './shared/config.js';\n"
            "import * as hist from './features/live-cells/histogram.js';\n"
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


def per_channel():
    """A per-channel auto transform as the package records it, for four channels of the Aurora
    demo files with the negative fractions, SDs and cofactors the package measured on them
    (rounded): CD8 and CD19 raised to their SD, CCR7's wide SD from 0.1% of the cells kept at the
    floor by the 1% guard, CD45 with no cell below 0."""
    from datanuggets_flow.pipeline import Cofactor

    return Cofactor(
        150.0,
        "auto",
        None,
        (337.95, 150.0, 150.0, 203.88),
        (0.021, 0.0012, 0.0, 0.1008),
        (337.95, 698.46, None, 203.88),
    ).transform()


LABELS = [
    "CD8 (FJComp-Alexa Fluor 700-A)",
    "CCR7 (FJComp-BV785-A)",
    "CD45 (FJComp-PerCP-A)",
    "CD19 (FJComp-PE-Cy5.5-A)",
]
# The records the web reads besides the per-channel one: a number as set, the header rule's auto
# (written before auto went per channel, with or without a usable range) and an arcsinh written
# before cofactor_from was recorded.
SET = {"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}
LEGACY = {"name": "arcsinh", "cofactor": 150.0, "cofactor_from": "auto", "range": 262144.0}
LEGACY_NONE = {"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "auto", "range": None}
OLD = {"name": "arcsinh", "cofactor": 5.0}


def test_the_time_pattern_is_the_packages(js):
    from datanuggets_flow._defaults import FLOW_TIME_PATTERN

    got = js("const r = config.LIVECELLS_TIME_RE; return [r.source, r.flags];")
    assert got == [FLOW_TIME_PATTERN, "i"]


def test_the_rule_is_the_packages():
    """The rule GET /config serves as defaults.cofactor_auto, which the cluster form reads."""
    from datanuggets_flow._defaults import FLOW_COFACTOR_FLOOR, FLOW_COFACTOR_MIN_NEGATIVE

    assert RULE == {
        "rule": "per_channel",
        "floor": FLOW_COFACTOR_FLOOR,
        "min_negative_fraction": FLOW_COFACTOR_MIN_NEGATIVE,
    }


def test_the_rule_from_config_is_the_packages():
    from dnapp.core.package import flow

    assert flow.cofactor_rule() == RULE


def test_the_auto_line_previews_no_number(js):
    """Auto is picked per channel from the cells the run clusters, so the form names the rule and
    its floor (when /config gives one) instead of a number; the header-range preview is gone."""
    old_rule = {"range_max": 262144, "narrow": 150.0, "wide": 6000.0}
    got = js(
        f"return [cof.autoText({json.dumps(RULE)}), cof.autoText(undefined),"
        f" cof.autoText({json.dumps(old_rule)}), typeof cof.autoCofactor];"
    )
    line = "Auto: picked per channel when the run starts, from the spread of the values below 0"
    assert got == [f"{line}, at least 150", line, line, "undefined"]


def test_a_run_transform_reads_as_the_packages(js):
    """run.json's transform as the package's run_transform reads it: the per-channel record as
    written, and the old shapes."""
    from datanuggets_flow.state import run_transform

    records = [
        {"transform": per_channel(), "settings": {"cofactor": "auto"}},
        {"transform": LEGACY},
        {"transform": SET},
        {"transform": OLD, "settings": {"cofactor": 5.0}},
        {"transform": {"name": "none"}},
        {"settings": {"cofactor": 6000.0}},
        {"settings": {"cofactor": 0.0}},
        {"settings": {}},
    ]
    got = js(f"return {json.dumps(records)}.map(cof.runTransform);")
    assert got == [run_transform(r) for r in records]
    assert got[0] == per_channel()


def test_each_channel_has_its_cofactor(js):
    """cofactorFor(t, j): channel j's own in a per-channel record or histograms, else the one
    number every channel shares."""
    hists = {"cofactor_from": "auto", "cofactors": [150.0, 337.95], "channels": []}
    legacy = {"cofactor": 6000.0, "cofactor_from": "auto", "range": 3162277.0, "channels": []}
    got = js(
        f"const per = {json.dumps(per_channel())}, set = {json.dumps(SET)};"
        f"const hists = {json.dumps(hists)}, legacy = {json.dumps(legacy)};"
        "return [[0, 1, 2, 3].map(j => cof.cofactorFor(per, j)), [0, 5].map(j => cof.cofactorFor(set, j)),"
        " [0, 1].map(j => cof.cofactorFor(hists, j)), [0, 1].map(j => cof.cofactorFor(legacy, j)),"
        " [per, set, hists, legacy].map(cof.perChannel)];"
    )
    assert got == [
        [337.95, 150.0, 150.0, 203.88],
        [6000.0, 6000.0],
        [150.0, 337.95],
        [6000.0, 6000.0],
        [True, False, True, False],
    ]


def test_the_cofactor_in_words(js):
    """The units every view prints (cofactorTag, then transformText with how it was chosen) and
    the record's reason (cofactorWhy), for each kind of record."""
    same = {**per_channel(), "cofactors": [150.0] * 4}
    kinds = [per_channel(), same, LEGACY, LEGACY_NONE, SET, OLD]
    got = js(
        f"const ts = {json.dumps(kinds)};"
        "return [ts.map(t => cof.cofactorTag(t)), ts.map(t => cof.transformText(t)), ts.map(cof.cofactorWhy),"
        " cof.transformText({name: 'none'})];"
    )
    tags, texts, whys, none = got
    assert tags == [
        # an auto cofactor is a whole number, as the run's log prints it: its median is read to
        # about 0.6%, so 337.95 is 338
        "arcsinh(x / c), c per channel (150–338)",
        # every channel picked the same, so one number says it
        "arcsinh(x / 150)",
        "arcsinh(x / 150)",
        "arcsinh(x / 6,000)",
        "arcsinh(x / 6,000)",
        "arcsinh(x / 5)",
    ]
    assert texts == [
        "arcsinh(x / c), c per channel (150–338), cofactor auto",
        "arcsinh(x / 150), cofactor auto",
        "arcsinh(x / 150), cofactor auto",
        "arcsinh(x / 6,000), cofactor auto",
        "arcsinh(x / 6,000), cofactor set",
        # written before cofactor_from: read as set
        "arcsinh(x / 5), cofactor set",
    ]
    rule = (
        "auto (each channel: the SD of the cells below 0 where at least 1% of the kept cells"
        " are below 0, at least 150; else 150)"
    )
    assert whys == [
        rule,
        rule,
        # beside "arcsinh(x / 150)", so without the number again; range null is either fallback
        # of the header rule (a marker channel with no usable range, or no marker channel)
        "auto (channels up to 262,144)",
        "auto (no usable range in the headers)",
        "set",
        "set",
    ]
    assert none == "raw values"


def test_the_units_of_the_channels_in_view(js):
    """The plot names the cofactor of the channels it draws: one number when they share it, the
    range of theirs when not; a run with one cofactor is the same whatever is drawn."""
    got = js(
        f"const per = {json.dumps(per_channel())}, set = {json.dumps(SET)};"
        "return [[[0], [1, 2], [0, 3], [1, 0]].map(js => cof.transformText(per, js)),"
        " cof.transformText(set, [0, 1])];"
    )
    assert got == [
        [
            "arcsinh(x / 338), cofactor auto",
            "arcsinh(x / 150), cofactor auto",
            "arcsinh(x / c), c per channel (204–338), cofactor auto",
            "arcsinh(x / c), c per channel (150–338), cofactor auto",
        ],
        "arcsinh(x / 6,000), cofactor set",
    ]


def test_the_record_lists_each_channels_cofactor(js):
    """The run record's table: each channel's cofactor, the share of its kept cells below 0 and
    their SD, by the run's labels, as the run's Transform lines give them: whole numbers, and the
    SD only where the rule used it, so none where no cell is below 0 or fewer than 1% are (the
    guard). Nothing for one number."""
    # either side of the guard: 0.97% below 0 prints as 1.0% but its SD was not used; at 1% an
    # SD under the floor was, and the floor won
    guard = {
        **per_channel(),
        "cofactors": [150.0, 150.0],
        "negative_fraction": [0.0097, 0.01],
        "negative_sd": [420.0, 135.4],
    }
    got = js(
        f"const per = {json.dumps(per_channel())}, labels = {json.dumps(LABELS)};"
        f"return [cof.cofactorRows(per, labels), cof.cofactorRows({json.dumps(guard)}, labels),"
        f" cof.cofactorRows({json.dumps(SET)}, labels), cof.cofactorRows({json.dumps(LEGACY)}, labels)];"
    )
    assert got == [
        [
            {"channel": LABELS[0], "cofactor": "338", "below": "2.1%", "sd": "338"},
            {"channel": LABELS[1], "cofactor": "150", "below": "0.1%", "sd": "–"},
            {"channel": LABELS[2], "cofactor": "150", "below": "0.0%", "sd": "–"},
            {"channel": LABELS[3], "cofactor": "204", "below": "10.1%", "sd": "204"},
        ],
        [
            {"channel": LABELS[0], "cofactor": "150", "below": "1.0%", "sd": "–"},
            {"channel": LABELS[1], "cofactor": "150", "below": "1.0%", "sd": "135"},
        ],
        None,
        None,
    ]


def test_live_cells_draw_each_channel_on_its_own_cofactor(js):
    """The Live cells step's axes: channel j of a per-channel set on t = asinh(raw / c_j), turned
    back as c_j * sinh(t), with c_j in its axis title, a whole number as the job's log gives it;
    an older set (one cofactor, the header rule's) and a number sent (0 keeps the axis linear)
    draw every channel on that one, a number sent as typed."""
    chans = [
        {"channel": "FJComp-BV510-A", "label": "CD3"},
        {"channel": "FJComp-Alexa Fluor 700-A", "label": "CD8"},
    ]
    sets = [
        {"cofactor_from": "auto", "cofactors": [150.0, 337.95], "channels": chans},
        {"cofactor": 6000.0, "cofactor_from": "auto", "range": 3162277.0, "channels": chans},
        {"cofactor": 0.0, "cofactor_from": "set", "channels": chans},
        {"cofactor": 2.5, "cofactor_from": "set", "channels": chans},
    ]
    got = js(
        f"return {json.dumps(sets)}.map(H => H.channels.map(h => {{"
        " const s = hist.channelScale(H, h);"
        " return [s.cof, s.from, s.toT(1000), s.toRaw(s.toT(-250)), hist.axisTitle(s.cof, s.from)]; }));"
    )
    want = [
        [(150.0, "auto", math.asinh(1000 / 150), "raw value, arcsinh axis (cofactor 150, auto)"),
         (337.95, "auto", math.asinh(1000 / 337.95), "raw value, arcsinh axis (cofactor 338, auto)")],
        [(6000.0, "auto", math.asinh(1000 / 6000), "raw value, arcsinh axis (cofactor 6,000, auto)")] * 2,
        [(0.0, "set", 1000.0, "raw value")] * 2,
        [(2.5, "set", math.asinh(1000 / 2.5), "raw value, arcsinh axis (cofactor 2.5, set)")] * 2,
    ]  # fmt: skip
    for got_set, want_set in zip(got, want, strict=True):
        for (cof, frm, t, back, title), (w_cof, w_from, w_t, w_title) in zip(
            got_set, want_set, strict=True
        ):
            assert (cof, frm, title) == (w_cof, w_from, w_title)
            assert t == pytest.approx(w_t, rel=1e-12)
            assert back == pytest.approx(-250, rel=1e-12)


def test_the_marker_channels_are_the_packages(js):
    """Scatter (FSC or SSC at the start) and Time, by the package's own constants, are the
    channels the upload view shows no header range for."""
    from datanuggets_flow._defaults import FLOW_SCATTER_PREFIXES, FLOW_TIME_PATTERN

    names = [
        "FSC-A",
        "SSC-B-H",
        "Time",
        "TIME",
        "HDR-T",
        "Time (s)",
        "CD3-A",
        "Timestamp",
        "CD3-FSC",
    ]
    time = re.compile(FLOW_TIME_PATTERN, re.IGNORECASE)
    want = [not n.startswith(FLOW_SCATTER_PREFIXES) and not time.match(n) for n in names]
    assert want == [False, False, False, False, False, False, True, True, True]
    assert js(f"return {json.dumps(names)}.map(cof.isMarkerChannel);") == want
