"""The Live cells step's row logic, app/web/features/live-cells/rows.js, run in Node: the channels
its dropdowns offer, the rows it starts with and adds, and the filters it hands on. The channel
list is the PBMC demo's, from the step's GET fixture. The module and the shared ones it imports
are copied beside a package.json that marks them as ES modules, so any Node from 18 on runs them;
the tests skip where Node isn't installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
MODULES = ("shared/config.js", "shared/channels.js", "features/live-cells/rows.js")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """js(body) runs body as a function in Node with `rows` (rows.js) and `config` (config.js)
    imported, and returns what it returns, through JSON."""
    root = tmp_path_factory.mktemp("web")
    for rel in MODULES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEB / rel, root / rel)
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"

    def run(body: str):
        script.write_text(
            "import * as rows from './features/live-cells/rows.js';\n"
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


@pytest.fixture(scope="module")
def step():
    """The step's GET fixture: the PBMC demo's file 1 channels and the package's suggestion."""
    path = WEB / "fixtures" / "GET__flow__gates__g1__livecells.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_dropdowns_offer_every_channel_but_time(js, step):
    """Every channel of the file is offered in the file's order, forward and side scatter too, so
    a file from any instrument can be filtered on any of its channels; only Time is not."""
    channels = step["channels"]
    got = js(f"return rows.filterChannels({json.dumps(channels)}).map(c => c.pnn);")
    pnn = [c["pnn"] for c in channels]
    assert [c for c in pnn if c not in got] == ["Time"]
    assert got == [c for c in pnn if c != "Time"] and len(got) == 38
    assert {"FSC-A", "SSC-B-H"} <= set(got)
    names = [
        "FSC-A",
        "SSC-W",
        "TIME",
        "time",
        "HDR-T",
        "Time (s)",
        "FJComp-PerCP-A",
        "Zombie NIR-A",
        "CD3-FSC",
        "Timestamp",
    ]
    assert js(f"return {json.dumps(names)}.map(rows.canFilter);") == [
        True, True, False, False, False, False, True, True, True, True
    ]  # fmt: skip


def test_the_first_rows_are_the_two_roles_on_the_suggestion(js, step):
    got = js(f"return rows.startRows({json.dumps(step['suggested'])});")
    assert got == [
        {"role": "viability", "channel": "FJComp-LIVE DEAD Blue-A", "keep": "<"},
        {"role": "cd45", "channel": "FJComp-PerCP-A", "keep": ">"},
    ]
    # a suggestion that is the time channel, or none, leaves its row on None; scatter is taken
    odd = {"viability": "Time", "cd45": None, "candidates": {"viability": [], "cd45": []}}
    got = js(f"return rows.startRows({json.dumps(odd)}).map(r => r.channel);")
    assert got == [None, None]
    odd["viability"] = "SSC-A"
    got = js(f"return rows.startRows({json.dumps(odd)}).map(r => r.channel);")
    assert got == ["SSC-A", None]


def test_rows_add_up_to_the_channels_and_only_added_ones_go(js, step):
    """Added rows start on None, keeping above; as many rows as channels offered, fewer under a
    server's cap; the two role rows stay. Added rows are numbered among themselves, from 1."""
    sug = json.dumps(step["suggested"])
    got = js(
        f"let r = rows.startRows({sug}); r = rows.addRow(rows.addRow(r));"
        "const kept = rows.removeRow(r, 2), roleKept = rows.removeRow(r, 0);"
        "return {r, kept, roleKept, names: r.map(rows.rowName), keptNames: kept.map(rows.rowName),"
        " max: [rows.maxRows(32, null), rows.maxRows(32, 8), rows.maxRows(3, 8),"
        " rows.maxRows(0, null)]};"
    )
    added = {"role": None, "channel": None, "keep": ">"}
    assert got["r"][2:] == [added, added] and len(got["r"]) == 4
    assert got["kept"] == got["r"][:2] + [added]
    assert got["roleKept"] == got["r"]  # a role row is set to None, never removed
    assert got["names"] == ["Viability dye", "CD45", "Channel 1", "Channel 2"]
    assert got["keptNames"] == ["Viability dye", "CD45", "Channel 1"]
    assert got["max"] == [32, 8, 3, 0]


def test_a_channel_in_one_row_is_taken_in_the_others(js):
    got = js(
        "const r = [{role: 'viability', channel: 'A', keep: '<'}, {role: 'cd45', channel: 'B', keep: '>'},"
        " {role: null, channel: 'A', keep: '>'}, {role: null, channel: null, keep: '>'}];"
        "return {taken: [0, 1, 3].map(i => [...rows.taken(r, i)].sort()), chosen: rows.chosen(r),"
        " clashes: rows.clashes(r), none: rows.clashes(r.slice(0, 2))};"
    )
    assert got["taken"] == [["A", "B"], ["A"], ["A", "B"]]
    assert got["chosen"] == ["A", "B", "A"]
    assert got["clashes"] == ["A"] and got["none"] == []


def test_the_filters_are_one_per_row_with_a_line_in_row_order(js):
    """Every row with a channel, a histogram and a line gives one filter with that row's side;
    a row on None, without a line, or whose channel the set has no histogram for gives none."""
    got = js(
        "const r = [{role: 'viability', channel: 'A', keep: '<'}, {role: 'cd45', channel: 'B', keep: '>'},"
        " {role: null, channel: 'C', keep: '>'}, {role: null, channel: null, keep: '>'},"
        " {role: null, channel: 'D', keep: '<'}, {role: null, channel: 'E', keep: '<'}];"
        "const lines = {A: 1.5, C: 300, D: 4, E: -2, F: 9};"
        "return rows.rowFilters(r, lines, c => c !== 'D');"
    )
    assert got == [
        {"column": "A", "op": "<", "value": 1.5},
        {"column": "C", "op": ">", "value": 300},
        {"column": "E", "op": "<", "value": -2},
    ]
