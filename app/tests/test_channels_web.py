"""The page's channel rules, app/web/shared/channels.js, run in Node against the package's own: the
time channel, the default clustering channels (default_channels) and the two channels a gate
takes when none are set (gate_channels), for the PBMC demo's channels and for files from
instruments that name scatter otherwise or record none. The modules are copied beside a
package.json that marks them as ES modules, so any Node from 18 on runs them; the tests skip where
Node isn't installed."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
MODULES = ("shared/config.js", "shared/channels.js")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")

# The PBMC demo's file 1 channels, from the Live cells step's GET fixture.
PBMC = [
    c["pnn"]
    for c in json.loads(
        (WEB / "fixtures" / "GET__flow__gates__g1__livecells.json").read_text(encoding="utf-8")
    )["channels"]
]
FILES = {
    "pbmc": PBMC,
    "spectral": ["Time", "SSC-H", "SSC-A", "FSC-H", "FSC-A", "SSC-B-H", "SSC-B-A", "UV1-A", "V1-A"],
    "heights only": ["FSC-H", "SSC-H", "FL1-H", "FL2-H", "FL3-H", "FL2-A", "FL4-H", "Time"],
    "side scatter only": ["SSC-A", "FL1-H", "FL2-H", "Time"],
    "forward scatter only": ["FSC-H", "FL1-H", "Time"],
    "mass cytometer": ["Time", "Event_length", "Ce140Di", "Ir191Di", "Ir193Di"],
    "beckman navios": ["FS INT", "FS PEAK", "SS INT", "FL1 INT", "FL2 INT", "TIME"],
    "lower case": ["Time", "fsc-a", "ssc-a", "cd3-a", "cd4-a"],
    "ssea marker": ["FSC-A", "SSC-A", "SSEA4-A", "CD3-A"],
    "long s": ["\N{LATIN SMALL LETTER LONG S}SC-A", "CD3-A"],
    "newline": ["FS\n", "SS\n", "FL1", "FL2"],
    "one name twice": ["FSC-A", "FSC-A", "SSC-A", "CD3-A", "CD4-A"],
    "one area twice": ["FSC-A", "CD3-A", "CD3-A", "CD4-H"],
    "time only": ["Time"],
    "none": [],
}


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """js(body) runs body as a function in Node with `ch` (channels.js) and `config` (config.js)
    imported, and returns what it returns, through JSON."""
    root = tmp_path_factory.mktemp("web")
    for rel in MODULES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEB / rel, root / rel)
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"

    def run(body: str):
        script.write_text(
            "import * as ch from './shared/channels.js';\n"
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


def test_the_constants_are_the_packages(js):
    from datanuggets_flow._defaults import (
        FLOW_CHANNEL_SUFFIX,
        FLOW_SCATTER_PATTERNS,
        FLOW_TIME_PATTERN,
    )

    got = js(
        "return [config.FLOW_SCATTER_RES.map(r => [r.source, r.flags]), config.FLOW_CHANNEL_SUFFIX,"
        " config.FLOW_TIME_RE.source, config.FLOW_TIME_RE.flags];"
    )
    scatter = [[p, "i"] for p in FLOW_SCATTER_PATTERNS]
    assert got == [scatter, FLOW_CHANNEL_SUFFIX, FLOW_TIME_PATTERN, "i"]


def test_time_is_the_packages(js):
    """Time, Time (s) and HDR-T in any case, never Timestamp; matched as the package matches."""
    from datanuggets_flow._defaults import FLOW_TIME_PATTERN

    names = ["Time", "TIME", "time", "HDR-T", "Time (s)", "Timestamp", "CD3-FSC", "FSC-A"]
    names += ["t\N{LATIN SMALL LETTER DOTLESS I}me", "T\N{LATIN CAPITAL LETTER I WITH DOT ABOVE}ME"]
    names += ["Time\N{LATIN SMALL LETTER E WITH ACUTE}"]
    time = re.compile(FLOW_TIME_PATTERN, re.IGNORECASE | re.ASCII)
    want = [bool(time.match(n)) for n in names]
    assert want == [True, True, True, True, True, False, False, False, False, False, True]
    assert js(f"return {json.dumps(names)}.map(ch.isTime);") == want


def test_default_channels_are_the_packages(js):
    """Every -A channel but scatter, or every channel but scatter and Time with fewer than two,
    in the file's order, on each instrument's channels."""
    from datanuggets_flow._pipeline.clustering import default_channels

    got = dict(
        zip(FILES, js(f"return Object.values({json.dumps(FILES)}).map(ch.defaultChannels);"))
    )
    assert got == {name: default_channels(names) for name, names in FILES.items()}
    assert len(got["pbmc"]) == 32  # the demo's colour channels
    assert got["mass cytometer"] == ["Event_length", "Ce140Di", "Ir191Di", "Ir193Di"]
    assert got["lower case"] == ["cd3-a", "cd4-a"]
    assert got["ssea marker"] == ["SSEA4-A", "CD3-A"]
    assert got["spectral"] == ["UV1-A", "V1-A"]  # the violet side scatter SSC-B-A left out
    assert got["long s"] == FILES["long s"]  # matched in ASCII, so no scatter
    assert got["newline"] == FILES["newline"]  # a name's end is its last character, in both


@pytest.mark.parametrize(
    ("name", "fsc", "ssc", "want"),
    [
        ("pbmc", None, None, ["FSC-A", "SSC-A"]),
        ("spectral", None, None, ["FSC-A", "SSC-A"]),
        ("heights only", None, None, ["FSC-H", "SSC-H"]),
        ("side scatter only", None, None, ["FL1-H", "SSC-A"]),
        ("forward scatter only", None, None, ["FSC-H", "FL1-H"]),
        ("mass cytometer", None, None, ["Event_length", "Ce140Di"]),
        ("mass cytometer", "Ir191Di", "Ir193Di", ["Ir191Di", "Ir193Di"]),
        ("mass cytometer", None, "Event_length", ["Ce140Di", "Event_length"]),
        ("pbmc", "SSC-A", None, ["SSC-A", "SSC-B-A"]),
        ("pbmc", None, "FSC-A", ["FSC-H", "FSC-A"]),
        ("beckman navios", None, None, ["FS INT", "SS INT"]),
        ("beckman navios", "FL1 INT", None, ["FL1 INT", "SS INT"]),
        ("lower case", None, None, ["fsc-a", "ssc-a"]),
        ("ssea marker", None, None, ["FSC-A", "SSC-A"]),
        ("long s", None, None, ["\N{LATIN SMALL LETTER LONG S}SC-A", "CD3-A"]),
        ("one name twice", None, None, ["FSC-A", "SSC-A"]),
        ("one name twice", None, "FSC-A", ["CD3-A", "FSC-A"]),
        ("pbmc", "", "", ["FSC-A", "SSC-A"]),
        ("time only", None, None, [None, None]),
        ("none", None, None, [None, None]),
    ],
)
def test_the_gate_channels_are_the_packages(js, name, fsc, ssc, want):
    """A channel given stands; one not given is the file's forward (or side) scatter, an -A one
    first, else a marker channel, never the other's channel, and null when none is left."""
    from datanuggets_flow.pipeline import gate_channels

    names = FILES[name]
    got = js(f"return ch.gateChannels({json.dumps(names)}, {json.dumps(fsc)}, {json.dumps(ssc)});")
    assert got == list(gate_channels(names, fsc, ssc)) == want
