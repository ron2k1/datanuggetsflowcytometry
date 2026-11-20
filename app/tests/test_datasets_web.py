"""Datasets on the page, run in Node: app/web/shared/datasets.js groups FCS uploads by their colour
channels, by the package's own rule, names each one, and words how datasets and stains differ; a
file read in the tab (fixture mode) has the channel names and stains the server gives it. The
uploads are the recorded workspace's PBMC demo files (one panel) and copies of them with a channel
dropped or a stain renamed; the FCS files are rebuilt from the repository's recorded 202 events,
as testkit.py's fcs_202 builds them. The shared modules are copied beside a package.json that
marks them as ES modules, so any Node from 18 on runs them; the tests skip where Node isn't
installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from testkit import API, FLOW, channel_list, upload

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")

# Reads an FCS file through the in-tab reader, local-upload.js, with a FileReader that hands it
# the file's bytes.
READ = """
globalThis.FileReader = class {
  readAsArrayBuffer(f) { this.result = f.buf; queueMicrotask(() => this.onload()); }
};
const { readFile } = await import('node:fs/promises');
const { readLocalUpload } = await import('./shared/api/local-upload.js');
const readFcs = async (path, name) => {
  const b = await readFile(path);
  return readLocalUpload({ name, size: b.length, buf: b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) });
};
"""


# The fixture transport (?fixtures=1), with a fetch that reads app/web's recorded fixtures.
FIXTURES = f"""
globalThis.location = {{ search: '?fixtures=1' }};
const {{ readFile: readText }} = await import('node:fs/promises');
const {{ join }} = await import('node:path');
globalThis.fetch = async url => ({{ json: async () => JSON.parse(await readText(join({json.dumps(str(WEB))}, url), 'utf8')) }});
const t = await import('./shared/api/fixtures.js');
"""
# half a UTF-16 surrogate pair, which a JSON escape can carry and UTF-8 cannot encode
LONE = [chr(0xD800), chr(0xDFFF)]
JSON = {"content-type": "application/json"}


def fcs_202(
    path: Path,
    names: list[str] | None = None,
    labels: list[str] | None = None,
    columns: list[int] | None = None,
) -> Path:
    """202's recorded events as an FCS 3.1 file, with its own $PnN and $PnS when given. columns
    picks the recorded columns (FSC-A, SSC-A and three fluorescence channels, by index) to write,
    so a column can be left out or written twice; names and labels then give one per column."""
    import flowio

    with np.load(FLOW / "202.npz") as gate, np.load(FLOW / "202_fluor.npz") as fluor:
        events = np.column_stack((gate["fsc"], gate["ssc"], fluor["fluor"]))
        names = names or ["FSC-A", "SSC-A", *fluor["pnn"].tolist()]
        labels = labels or ["", "", *fluor["pns"].tolist()]
    if columns is not None:
        events = events[:, columns]
    with path.open("wb") as handle:
        flowio.create_fcs(handle, events.ravel(), names, opt_channel_names=labels)
    return path


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """js(body) runs body as an async function in Node with `config` (shared/config.js) and `ds`
    (shared/datasets.js) imported, and returns what it returns, through JSON. brief(d) gives a
    dataset with upload ids for its uploads."""
    return node(tmp_path_factory.mktemp("web"))


def node(root: Path, datasets_max: int | None = None):
    """The js runner on a copy of shared/ in root, with config.js's DATASETS_MAX set to
    datasets_max when it is given, as a server test sets the server's."""
    from dnapp.core.config import DATASETS_MAX

    shutil.copytree(WEB / "shared", root / "shared")
    if datasets_max is not None:
        path = root / "shared" / "config.js"
        text, line = path.read_text(encoding="utf-8"), "export const DATASETS_MAX = {};"
        assert line.format(DATASETS_MAX) in text
        text = text.replace(line.format(DATASETS_MAX), line.format(datasets_max))
        path.write_text(text, encoding="utf-8")
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"

    def run(body: str):
        script.write_text(
            "import * as config from './shared/config.js';\n"
            "import * as ds from './shared/datasets.js';\n"
            "const ids = us => us.map(u => u.id);\n"
            "const brief = d => ({ ...d, files: ids(d.files), stains: d.stains.map(s =>"
            " ({ channel: s.channel, labels: s.labels.map(l => ({ label: l.label, files: ids(l.files) })) })) });\n"
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


@pytest.fixture(scope="module")
def pbmc():
    """The recorded workspace's four FCS uploads, the PBMC demo's 190, 193, 199 and 223.fcs: one
    panel of 39 channels."""
    ws = json.loads((WEB / "fixtures" / "GET__workspace.json").read_text(encoding="utf-8"))
    return [u for u in ws["uploads"] if u["kind"] == "fcs"]


def colour(u: dict) -> list[str]:
    """u's colour channels by the package's own constants, sorted."""
    from datanuggets_flow._defaults import FLOW_CHANNEL_SUFFIX, FLOW_SCATTER_PREFIXES

    names = (c["name"] for c in u["columns"] if c["name"].endswith(FLOW_CHANNEL_SUFFIX))
    return sorted({n for n in names if not n.startswith(FLOW_SCATTER_PREFIXES)})


def variant(u: dict, uid: str, drop=(), labels=None) -> dict:
    """A copy of upload u as uid (named uid.fcs), without the channels in drop and with the stains
    in labels."""
    cols = [{**c, "label": (labels or {}).get(c["name"], c["label"])} for c in u["columns"]]
    cols = [c for c in cols if c["name"] not in drop]
    return {**u, "id": uid, "name": f"{uid}.fcs", "columns": cols}


def test_the_colour_channel_rule_is_the_packages(js):
    from datanuggets_flow._defaults import FLOW_CHANNEL_SUFFIX, FLOW_SCATTER_PREFIXES

    got = js("return [config.FLOW_CHANNEL_SUFFIX, config.LIVECELLS_SCATTER_PREFIXES];")
    assert got == [FLOW_CHANNEL_SUFFIX, list(FLOW_SCATTER_PREFIXES)]


def test_a_file_read_in_the_tab_has_the_servers_names_and_stains(js, make_client, tmp_path):
    """The server keeps each $PnN as stored, padding and all, as the package reads it (so a
    padded "-A " name is no colour channel to either), and trims each $PnS with Python's
    str.strip(), which trims \\x1c to \\x1f too. A file read in the tab gets the same names and
    stains, so the two group it alike."""
    path = fcs_202(
        tmp_path / "202-padded.fcs",
        ["FSC-A", "SSC-A", " FJComp-Alexa Fluor 700-A ", "FJComp-BV510-A ", "FJComp-Spark Blue-A"],
        ["", "", " CD8 ", "\x1fCD3 \x1c", "CD4"],
    )
    r = upload(make_client(), path)
    assert r.status_code == 201, r.text
    server = [[c["name"], c["label"]] for c in r.json()["columns"]]
    got = js(
        READ + f"const u = await readFcs({json.dumps(str(path))}, '202-padded.fcs');"
        " return [u.columns.map(c => [c.name, c.label]), ds.colourChannels(u)];"
    )
    assert got[0] == server
    assert server[2:4] == [[" FJComp-Alexa Fluor 700-A ", "CD8"], ["FJComp-BV510-A ", "CD3"]]
    assert got[1] == ["FJComp-Spark Blue-A"]


def test_a_file_read_in_the_tab_reads_its_text_as_flowio_does(js, make_client, tmp_path):
    """flowio decodes the TEXT segment as UTF-8, or as ISO-8859-1 when it is not UTF-8, drops
    every $, and splits it at each delimiter that is not doubled, then halves the doubled ones,
    which is how a value holds one. The tab reads a file so too: a / in a $PnN or a $PnS (which
    flowio writes doubled), a $ in a stain, a stain in UTF-8, and a $PnN in Windows-1252 with an
    en dash (0x96), which reads as U+0096."""
    pnn = ["FSC-A", "SSC-A", "FJComp-Alexa Fluor 700-A", "FJComp-BV510/x-A", "FJComp-Spark Blue-A"]
    slashed = fcs_202(tmp_path / "slashed.fcs", pnn, ["", "", "CD8/a", "CD3 $1", "CD4 \u00b5"])
    raw = fcs_202(tmp_path / "dash.fcs").read_bytes()
    assert raw.count(b"FJComp-BV510-A") == 1
    dash = tmp_path / "dash.fcs"
    dash.write_bytes(raw.replace(b"FJComp-BV510-A", b"FJComp\x96BV510-A"))
    c, server = make_client(), []
    for path in (slashed, dash):
        r = upload(c, path)
        assert r.status_code == 201, r.text
        server.append([[col["name"], col["label"]] for col in r.json()["columns"]])
    got = js(
        READ + f"const paths = {json.dumps([str(slashed), str(dash)])}, out = [];"
        " for (const p of paths) out.push((await readFcs(p, 'x.fcs')).columns.map(c => [c.name, c.label]));"
        " return out;"
    )
    assert got == server
    assert server[0][2:] == [
        ["FJComp-Alexa Fluor 700-A", "CD8/a"],
        ["FJComp-BV510/x-A", "CD3 1"],
        ["FJComp-Spark Blue-A", "CD4 \u00b5"],
    ]
    assert server[1][3][0] == "FJComp\x96BV510-A"


def test_a_file_read_in_the_tab_halves_a_doubled_delimiter_as_flowio_does(
    js, make_client, tmp_path
):
    """With |, \\ or * as the delimiter, flowio splits as at any other but halves only that
    delimiter's regex-escaped pair: a stain's || stays as written, and four backslashes read as
    two. The tab reads both files so too. Each is 202.fcs with every / in its TEXT segment
    rewritten, so CD8/a, written CD8//a, holds the doubled delimiter."""
    base = fcs_202(tmp_path / "slashed.fcs", None, ["", "", "CD8/a", "CD3//b", "CD4"])
    raw = base.read_bytes()
    t0, t1 = int(raw[10:18]), int(raw[18:26])
    text = raw[t0 : t1 + 1]
    assert b"|" not in text and b"\\" not in text and text.count(b"/") > 10
    paths = []
    for d, name in ((b"|", "pipe.fcs"), (b"\\", "backslash.fcs")):
        paths.append(tmp_path / name)
        paths[-1].write_bytes(raw[:t0] + text.replace(b"/", d) + raw[t1 + 1 :])
    c, server = make_client(), []
    for path in paths:
        r = upload(c, path)
        assert r.status_code == 201, r.text
        server.append([[col["name"], col["label"]] for col in r.json()["columns"]])
    got = js(
        READ + f"const paths = {json.dumps([str(p) for p in paths])}, out = [];"
        " for (const p of paths) out.push((await readFcs(p, 'x.fcs')).columns.map(c => [c.name, c.label]));"
        " return out;"
    )
    assert got == server
    assert [s[2][1] for s in server] == ["CD8||a", "CD8\\\\a"]
    assert [s[3][1] for s in server] == ["CD3||||b", "CD3\\\\b"]


def test_a_file_the_tab_cannot_read_gets_the_servers_words(js, make_client, tmp_path):
    """A file with no FCS 2.0, 3.0 or 3.1 header, and one the reader cannot follow (202.fcs cut
    to its first 64 bytes), are refused in the tab with the server's code and words; the error
    the second names is JavaScript's, where the server names Python's."""
    raw = fcs_202(tmp_path / "202.fcs").read_bytes()
    fake, cut = tmp_path / "fake.fcs", tmp_path / "cut.fcs"
    fake.write_bytes(b"NOTFCS" + b"\0" * 100)
    cut.write_bytes(raw[:64])
    c = make_client()
    server = [upload(c, p).json()["error"] for p in (fake, cut)]
    got = js(
        READ + f"const paths = {json.dumps([str(fake), str(cut)])}, out = [];"
        " for (const p of paths) {"
        "   try { await readFcs(p, 'x.fcs'); out.push(null); } catch (e) { out.push([e.code, e.message]); }"
        " }"
        " return out;"
    )
    assert got[0] == [server[0]["code"], server[0]["message"]]
    assert server[0]["message"] == "This is not an FCS 2.0, 3.0 or 3.1 file."
    read = "The FCS file could not be read: "
    assert got[1][0] == server[1]["code"] == "unreadable_file"
    assert server[1]["message"].startswith(read) and got[1][1] == f"{read}RangeError."


def test_colour_channels_follow_the_packages_rule(js, pbmc):
    """Every -A channel but forward and side scatter (SSC-B-A too), sorted: not Time, not -H.
    A colour channel an upload lists twice is listed once."""
    u = pbmc[0]
    twice = {
        **u,
        "columns": [*u["columns"], next(c for c in u["columns"] if c["name"] in colour(u))],
    }
    got, again = js(f"return [{json.dumps(u)}, {json.dumps(twice)}].map(ds.colourChannels);")
    assert got == again == colour(u) and len(got) == 32
    assert not {"FSC-A", "SSC-A", "SSC-B-A", "FSC-H", "Time"} & set(got)


def test_grouping_ignores_channel_order_stains_scatter_and_time(js, pbmc):
    """Uploads are in one dataset when their colour channels are the same set, in the order of
    their first upload; one colour channel fewer is another dataset."""
    u3, u4, u5, u6 = pbmc
    turned = variant(u4, "x1", labels={"FJComp-BV510-A": "CD3 BV510"})
    turned["columns"].reverse()
    bare = variant(u5, "x2", drop=("FSC-H", "SSC-H", "SSC-B-H", "Time"))
    fewer = variant(u6, "x3", drop=("FJComp-BV510-A",))
    got = js(
        f"const us = {json.dumps([fewer, u3, turned, bare])};"
        " return [ds.groupDatasets(us).map(brief), us.map(ds.datasetKey)];"
    )
    groups, keys = got
    assert [d["files"] for d in groups] == [["x3"], ["u3", "x1", "x2"]]
    assert [d["channels"] for d in groups] == [colour(fewer), colour(u3)]
    assert [d["key"] for d in groups] == [keys[0], keys[1]] and keys[1] == keys[2] == keys[3]
    assert keys[0] != keys[1]


def test_the_diff_wording(js, pbmc):
    """diff(a -> b): what b lacks and adds, each sorted, three names at most and then how many
    more, joined by '; '."""
    p = colour(pbmc[0])
    pairs = [
        (p[:3], p[:2]), (p[:2], p[:3]), (p[:3], p[1:4]), (p[:2], p[2:4]), (p[:3], []),
        (p[:7], p[:1]), (p[:3], p), (p[4::-1], p[:1]), (p, p[::-1]),
    ]  # fmt: skip
    got = js(f"return {json.dumps(pairs)}.map(([a, b]) => ds.diffText(a, b));")
    assert got == [
        f"lacks {p[2]}",
        f"adds {p[2]}",
        f"lacks {p[0]}; adds {p[3]}",
        f"lacks {p[0]}, {p[1]}; adds {p[2]}, {p[3]}",
        f"lacks {p[0]}, {p[1]}, {p[2]}",
        f"lacks {p[1]}, {p[2]}, {p[3]} and 3 more",
        f"adds {p[3]}, {p[4]}, {p[5]} and 26 more",
        f"lacks {p[1]}, {p[2]}, {p[3]} and 1 more",
        "",
    ]


def test_each_dataset_differs_from_the_one_with_most_files(js, pbmc):
    """The dataset with the most files, the earliest on a tie, has no diff; every other one says
    what it lacks and adds against it."""
    u3, u4, u5, u6 = pbmc
    p = colour(u3)
    fewer = [variant(u, f"x{i}", drop=(p[0],)) for i, u in enumerate((u4, u5), 1)]
    least = variant(u6, "x3", drop=(p[0], p[1]))
    got = js(
        f"const [u3, a, b, c] = {json.dumps([u3, *fewer, least])};"
        " return [ds.groupDatasets([u3, a, b, c]), ds.groupDatasets([u3, a])]"
        ".map(g => g.map(d => [d.name, ids(d.files), d.diff]));"
    )
    assert got == [
        [
            ["Dataset 1", ["u3"], f"adds {p[0]}"],
            ["Dataset 2", ["x1", "x2"], ""],
            ["Dataset 3", ["x3"], f"lacks {p[1]}"],
        ],
        [["Dataset 1", ["u3"], ""], ["Dataset 2", ["x1"], f"lacks {p[0]}"]],
    ]


def test_names_are_matched_by_channel_set_and_others_numbered(js, pbmc):
    """A dataset shows the name given to its channel set, listed in any order; every other one is
    "Dataset N" by the order of first uploads, named ones counted. A name for a set no upload has
    shows nowhere."""
    u3, u4, u5, _ = pbmc
    p = colour(u3)
    a, b = variant(u4, "x1", drop=(p[0],)), variant(u5, "x2", drop=(p[1],))
    named = [
        {"id": "d1", "channels": colour(a)[::-1], "name": "Panel less one"},
        {"id": "d2", "channels": p[:2], "name": "Nobody's"},
    ]
    got = js(
        f"return ds.groupDatasets({json.dumps([u3, a, u4, b])}, {json.dumps(named)})"
        ".map(d => [d.name, ids(d.files)]);"
    )
    assert got == [
        ["Dataset 1", ["u3", "u4"]],
        ["Panel less one", ["x1"]],
        ["Dataset 3", ["x2"]],
    ]


def test_a_file_with_under_two_colour_channels_groups_by_its_set(js, pbmc):
    """It is never left out or merged into a larger dataset: it groups by its own set, like any
    file, so two files with no colour channel at all share one."""
    u3, u4, u5, u6 = pbmc
    p = colour(u3)
    one = variant(u6, "x1", drop=p[1:])
    none = [variant(u, f"x{i}", drop=p) for i, u in enumerate((u3, u4), 2)]
    got = js(
        f"return ds.groupDatasets({json.dumps([u3, u4, u5, one, *none])})"
        ".map(d => [ids(d.files), d.channels, d.diff]);"
    )
    assert got == [
        [["u3", "u4", "u5"], p, ""],
        [["x1"], [p[0]], f"lacks {p[1]}, {p[2]}, {p[3]} and 28 more"],
        [["x2", "x3"], [], f"lacks {p[0]}, {p[1]}, {p[2]} and 29 more"],
    ]


def test_stains_differ_by_trimmed_labels_and_never_by_an_empty_one(js, pbmc):
    """A colour channel whose stains differ between a dataset's files is listed with each stain,
    in the order the files first use them, and the files that use it. A stain is trimmed as the
    server trims it, a file with none never differs, and scatter stains never count."""
    u3, u4, u5, u6 = pbmc
    files = [
        u3,
        variant(u4, "x1", labels={"FJComp-BV510-A": "\x1c CD3 \x85"}),
        variant(u5, "x2", labels={"FJComp-BV510-A": "", "FSC-A": "Forward"}),
        variant(u6, "x3", labels={"FJComp-BV510-A": "CD3 BV510", "FJComp-PerCP-A": "CD45 PerCP"}),
    ]
    got = js(
        f"const us = {json.dumps(files)};"
        " const st = ds.groupDatasets(us)[0].stains;"
        " return [brief({ files: [], stains: st }).stains, ds.stainText(st),"
        " ds.stainDiffs(us.slice(0, 3)), ds.stainText(st, '\\n')];"
    )
    stains, text, alike, lines = got
    assert stains == [
        {"channel": "FJComp-BV510-A", "labels": [
            {"label": "CD3", "files": ["u3", "x1"]}, {"label": "CD3 BV510", "files": ["x3"]}]},
        {"channel": "FJComp-PerCP-A", "labels": [
            {"label": "CD45", "files": ["u3", "x1", "x2"]}, {"label": "CD45 PerCP", "files": ["x3"]}]},
    ]  # fmt: skip
    assert text == (
        "FJComp-BV510-A: CD3 (190.fcs, x1.fcs) or CD3 BV510 (x3.fcs); "
        "FJComp-PerCP-A: CD45 (190.fcs, x1.fcs, x2.fcs) or CD45 PerCP (x3.fcs)"
    )
    assert lines == text.replace("; ", "\n")
    assert alike == []


def test_stain_text_names_three_files_and_channels_at_most(js, pbmc):
    p = colour(pbmc[0])
    files = [*pbmc, *(variant(pbmc[0], f"x{i}", labels={c: "other" for c in p}) for i in (1, 2))]
    got = js(f"return ds.stainText(ds.stainDiffs({json.dumps(files)}));")
    stain = {c["name"]: c["label"] for c in pbmc[0]["columns"]}[p[0]]
    assert got.startswith(
        f"{p[0]}: {stain} (190.fcs, 193.fcs, 199.fcs and 1 more) or other (x1.fcs, x2.fcs); "
    )
    assert got.endswith(" and 29 more channels")
    assert got.count(" or other ") == 3


def test_the_client_names_a_dataset_with_post_datasets(js):
    got = js(
        "const { makeClient } = await import('./shared/api/client.js');"
        " const api = makeClient({ request: async (m, p, b) => [m, p, b] });"
        " return api.nameDataset({ channels: ['B-A', 'A-A'], name: 'Panel' });"
    )
    assert got == ["POST", "/datasets", {"channels": ["B-A", "A-A"], "name": "Panel"}]


def test_the_client_deletes_an_upload_and_a_gate_by_their_routes(js):
    got = js(
        "const { makeClient } = await import('./shared/api/client.js');"
        " const api = makeClient({ request: async (m, p, b) => [m, p, b === undefined] });"
        " return [await api.deleteUpload('u3'), await api.deleteGate('g1')];"
    )
    assert got == [["DELETE", "/uploads/u3", True], ["DELETE", "/flow/gates/g1", True]]


def test_the_store_groups_the_workspaces_uploads_with_its_names(js, pbmc):
    """S.ws.datasets is GET /workspace's names, [] when a server sends none; datasets() groups the
    FCS uploads, read-in-the-tab ones too, and datasetOf(uid) finds an upload's dataset."""
    u3, u4, *_ = pbmc
    p = colour(u3)
    fewer = variant(u4, "x1", drop=(p[0],))
    local = {**variant(u4, "local1"), "local": True}
    named = [{"id": "d1", "channels": colour(fewer), "name": "Less one"}]
    got = js(
        "globalThis.location = { search: '' }; globalThis.window = { innerWidth: 1440 };"
        " globalThis.localStorage = { getItem: () => null };"
        " const store = await import('./shared/store.js');"
        " const { api } = await import('./shared/api/index.js');"
        f" const ws = {{ uploads: {json.dumps([u3, fewer])}, gates: [], runs: [], jobs: [] }};"
        " const seen = [];"
        " for (const datasets of [undefined, " + json.dumps(named) + "]) {"
        "   api.workspace = async () => (datasets ? { ...ws, datasets } : { ...ws });"
        "   await store.loadWorkspace();"
        f"   store.S.localUploads = [{json.dumps(local)}];"
        "   seen.push([store.S.ws.datasets, store.datasets().map(d => [d.name, ids(d.files)]),"
        "     ['x1', 'local1', 'u9'].map(id => (store.datasetOf(id) || {}).name || null)]);"
        " }"
        " return seen;"
    )
    assert got == [
        [
            [],
            [["Dataset 1", ["u3", "local1"]], ["Dataset 2", ["x1"]]],
            ["Dataset 2", "Dataset 1", None],
        ],
        [
            named,
            [["Dataset 1", ["u3", "local1"]], ["Less one", ["x1"]]],
            ["Less one", "Dataset 1", None],
        ],
    ]


def test_fixture_mode_keeps_dataset_names_in_the_tab(js, pbmc):
    """In fixture mode the transport answers POST /datasets itself, as the server does: one record
    per channel set, matched in any order and stored sorted; a trimmed name; a blank name removes
    the record. GET /workspace lists them beside the recorded workspace. A name over 60
    characters or with a control character is refused, and so is a channel list that is empty or
    has a blank or a repeated name."""
    p = colour(pbmc[0])
    fixture = json.loads((WEB / "fixtures" / "GET__workspace.json").read_text(encoding="utf-8"))
    got = js(
        FIXTURES + f"const p = {json.dumps(p)};"
        " const post = body => t.request('POST', '/datasets', body);"
        " const before = await t.request('GET', '/workspace');"
        " const steps = [await post({ channels: [...p].reverse(), name: '  PBMC panel ' }),"
        "   await post({ channels: p.slice(1), name: 'Less one' }),"
        "   await post({ channels: p, name: 'P'.repeat(60) }),"
        "   await post({ channels: p.slice(1), name: ' ' })];"
        " const after = await t.request('GET', '/workspace');"
        " const refused = [];"
        " for (const body of [{ channels: p, name: 'x'.repeat(61) }, { channels: p, name: 'a\\tb' },"
        "   { channels: [], name: 'x' }, { channels: [p[0], p[0]], name: 'x' }, { channels: [p[0], ''], name: 'x' }]) {"
        "   try { await post(body); refused.push(null); } catch (e) { refused.push([e.status, e.code, e.param]); }"
        " }"
        " return [before.datasets, steps, after, refused, (await t.request('GET', '/workspace')).datasets];"
    )
    before, steps, after, refused, last = got
    d1 = {"id": "d1", "channels": p, "name": "PBMC panel"}
    d2 = {"id": "d2", "channels": p[1:], "name": "Less one"}
    long = {**d1, "name": "P" * 60}
    assert before == []
    assert steps == [
        {"datasets": [d1]},
        {"datasets": [d1, d2]},
        {"datasets": [long, d2]},
        {"datasets": [long]},
    ]
    assert after == {**fixture, "datasets": [long]}
    refusal = [422, "invalid_setting"]
    assert refused == [[*refusal, "name"]] * 2 + [[*refusal, "channels"]] * 3
    assert last == [long]


def test_fixture_mode_checks_and_trims_a_name_as_the_server_does(js):
    """The server's checks, params and words (features/datasets/router.py and service.py), its
    limits (DATASET_* in core/config.py) and its counting: a length is in code points, and a name
    is trimmed of what Python's str.strip() trims, which is not what JS's trim() trims."""
    spaced = ["\x1c Panel \x85", "﻿Panel ", " Panel　"]
    smile = "\U0001f600"
    got = js(
        FIXTURES + " const post = body => t.request('POST', '/datasets', body);"
        " const answer = async body => { try { return (await post(body)).datasets; }"
        " catch (e) { return [e.status, e.code, e.param, e.message]; } };"
        f" const spaced = {json.dumps(spaced)}, smile = {json.dumps(smile)};"
        " const out = [];"
        " for (const [i, name] of spaced.entries()) out.push((await answer({ channels: [`C${i}-A`], name })).at(-1).name);"
        " out.push((await answer({ channels: ['S-A'], name: smile.repeat(60) })).at(-1).name.length);"
        " out.push(await answer({ channels: ['S-A'], name: smile.repeat(61) }));"
        " out.push(await answer({ channels: ['S-A'], name: 'a\\u0085b' }));"
        " out.push((await answer({ channels: [smile.repeat(100)], name: 'x' })).length);"
        " for (const channels of [[], ['A-A', ''], ['A-A', 'A-A'], ['x'.repeat(101)],"
        "   Array.from({ length: 513 }, (_, i) => `C${i}-A`)]) out.push(await answer({ channels, name: 'x' }));"
        " for (let i = 0; i < 95; i++) await post({ channels: [`N${i}-A`], name: 'n' });"
        " out.push((await answer({ channels: ['N0-A'], name: 'renamed' })).length);"
        " out.push(await answer({ channels: ['New-A'], name: 'one more' }));"
        " return out;"
    )
    ref = [422, "invalid_setting"]
    assert got == [
        *(s.strip() for s in spaced),
        120,
        [*ref, "name", "The name is 61 characters long; a dataset name is at most 60."],
        [
            *ref,
            "name",
            (
                "The name has a control character, such as a tab, a line break or a text "
                "direction mark."
            ),
        ],
        5,
        [*ref, "channels", "List at least one channel."],
        [*ref, "channels", "A channel name cannot be empty."],
        [*ref, "channels", "List each channel once."],
        [
            *ref,
            "channels",
            "A channel name is 101 characters long; this server allows at most 100.",
        ],
        [*ref, "channels", "channels is 513; this server allows at most 512."],
        100,
        # at the cap, with none of the 100 an upload's set, they all go
        [{"id": "d101", "channels": ["New-A"], "name": "one more"}],
    ]
    assert got[:3] == ["Panel", "﻿Panel", "Panel"]


def answers(js, make_client, bodies: list[dict]) -> tuple[list, list]:
    """What the server and the fixture transport each answer to the POST /datasets bodies in
    turn: the datasets, or [status, code, param, message]."""
    c, server = make_client(), []
    for body in bodies:
        r = c.post(f"{API}/datasets", content=json.dumps(body), headers=JSON)
        err = r.json().get("error")
        server.append(
            [r.status_code, *(err[k] for k in ("code", "param", "message"))]
            if err
            else r.json()["datasets"]
        )
    tab = js(
        FIXTURES + f" const bodies = {json.dumps(bodies)}, out = [];"
        " for (const body of bodies) {"
        "   try { out.push((await t.request('POST', '/datasets', body)).datasets); }"
        "   catch (e) { out.push([e.status, e.code, e.param, e.message]); }"
        " }"
        " return out;"
    )
    return server, tab


def test_fixture_mode_refuses_the_bodies_the_server_refuses(js, make_client):
    """A body that is not {channels, name}, a list of strings and a string, is refused with
    pydantic's param and words, in fixture mode as by the server: a body that is not an object,
    then the fields in order, then the first field the model does not have, all before any check
    of the names themselves."""
    bodies = [
        *(None, ["A-A"], "x", 7, {}, {"name": "x"}, {"channels": ["A-A"]}),
        {"channels": "A-A", "name": "x"},
        {"channels": ["A-A", 7], "name": "x"},
        {"channels": ["A-A"], "name": None},
        {"channels": [], "name": 7},
        {"channels": ["A-A"], "name": "x", "colour": "red", "body": 1},
        {"colour": "red", "channels": "A-A", "name": "x"},
    ]
    server, tab = answers(js, make_client, bodies)
    assert tab == server
    assert [a[:2] for a in server] == [[422, "invalid_setting"]] * len(bodies)


def test_fixture_mode_refuses_the_names_the_server_refuses(js, make_client):
    """A trimmed name with a control character, a line or paragraph separator or a bidi control
    is refused, in fixture mode as by the server; a separator at an end is trimmed, and a
    zero-width joiner or a narrow no-break space inside is kept."""
    chars = [*"\t\x1f\x85\x9f\u2028\u2029\u061c\u200e\u200f\u202a\u202e\u2066\u2069", *LONE]
    names = [f"P{ch}B" for ch in chars] + ["\u200eP", "\u2028P\u2029", "P\u200dB", "P\u202fB"]
    server, tab = answers(
        js, make_client, [{"channels": [f"C{i}-A"], "name": n} for i, n in enumerate(names)]
    )
    assert tab == server
    refused = len(chars) + 1
    assert [a[:3] for a in server[:refused]] == [[422, "invalid_setting", "name"]] * refused
    assert [a[-1]["name"] for a in server[refused:]] == ["P", "P\u200dB", "P\u202fB"]


def test_fixture_mode_refuses_the_channel_lists_the_server_refuses(js, make_client):
    """A channel name with a lone surrogate is refused, and so is a list of more than
    DATASET_CHANNELS_MAX names or longer than DATASET_CHANNELS_BYTES as json.dumps writes it, in
    fixture mode as by the server; a list of just that many names or that length is kept, and so
    is a channel name with a control character, a line or paragraph separator or a bidi control,
    which an upload's $PnN can hold."""
    from dnapp.core.config import DATASET_CHANNELS_BYTES, DATASET_CHANNELS_MAX

    chars = [*"\t\x1f\x85\x9f\u2028\u2029\u061c\u200e\u200f\u202a\u202e\u2066\u2069"]

    def wide(size: int) -> list[str]:  # with a name past U+FFFF: two escapes, 18 bytes in all
        return [*channel_list(size - 18, n=199), chr(0x1F600) + "-A"]

    def quoted(size: int) -> list[str]:  # with a name of ", \ and ", each escaped: 12 bytes
        return [*channel_list(size - 12, n=199), '"\\"-A']

    def many(n: int) -> list[str]:
        return [f"C{i}-A" for i in range(n)]

    over, cap = DATASET_CHANNELS_BYTES + 1, DATASET_CHANNELS_BYTES
    lists = [*(["A-A", f"B{ch}-A"] for ch in LONE), channel_list(over), wide(over), quoted(over)]
    lists.append(many(DATASET_CHANNELS_MAX + 1))
    refused = len(lists)
    lists += [channel_list(cap), wide(cap), quoted(cap), many(DATASET_CHANNELS_MAX)]
    lists += [["A-A", f"B{ch}-A"] for ch in chars]
    server, tab = answers(js, make_client, [{"channels": ch, "name": "x"} for ch in lists])
    assert tab == server
    assert [a[:3] for a in server[:refused]] == [[422, "invalid_setting", "channels"]] * refused
    assert [a[-1]["channels"] for a in server[refused:]] == [sorted(ch) for ch in lists[refused:]]


def test_fixture_mode_makes_room_at_the_cap_as_the_server_does(make_client, tmp_path, monkeypatch):
    """With DATASETS_MAX at 2 in both, a new name at the cap removes the names of sets no upload
    has, and is refused when every name is an upload's set. The server has 202.fcs and a copy
    without its last channel; the tab has read the same two files, beside the recorded
    workspace's PBMC uploads, which no name here is for."""
    monkeypatch.setattr("dnapp.features.datasets.service.DATASETS_MAX", 2)
    files = [fcs_202(tmp_path / "202.fcs")]
    names = ["FSC-A", "SSC-A", "FJComp-Alexa Fluor 700-A", "FJComp-BV510-A"]
    files.append(fcs_202(tmp_path / "less.fcs", names, [""] * 4, [0, 1, 2, 3]))
    panel = [*names[2:], "FJComp-Spark Blue-A"]
    bodies = [
        {"channels": ["FJComp-BV421-A"], "name": "Nobody's"},
        {"channels": panel, "name": "202"},
        {"channels": names[2:], "name": "Less"},
        {"channels": ["FJComp-BV421-A", *panel], "name": "More"},
    ]
    c, server = make_client(), []
    for path in files:
        assert upload(c, path).status_code == 201
    for body in bodies:
        r = c.post(f"{API}/datasets", json=body)
        err = r.json().get("error")
        server.append(
            [r.status_code, err["param"], err["message"]] if err else r.json()["datasets"]
        )
    tab = node(tmp_path / "web", datasets_max=2)(
        READ + FIXTURES + f" for (const path of {json.dumps([str(p) for p in files])}) {{"
        "   const b = await readFile(path);"
        "   await t.upload({ name: path, size: b.length, buf: b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) });"
        " }"
        " const out = [];"
        f" for (const body of {json.dumps(bodies)}) {{"
        "   try { out.push((await t.request('POST', '/datasets', body)).datasets); }"
        "   catch (e) { out.push([e.status, e.param, e.message]); }"
        " }"
        " return out;"
    )
    assert tab == server
    kept = [[d["name"] for d in a] for a in server[:3]]
    assert kept == [["Nobody's"], ["Nobody's", "202"], ["202", "Less"]]  # Nobody's went
    message = "This workspace holds 2 dataset names, the most it can; remove one first."
    assert server[3] == [422, "name", message]


def test_fixture_mode_counts_the_recorded_uploads_at_the_cap(pbmc, tmp_path):
    """The recorded workspace's PBMC uploads are the tab's uploads too: with DATASETS_MAX at 2, a
    name for their set and one for a file read in the tab are both an upload's set, so a third
    set's name is refused and neither goes."""
    path = fcs_202(tmp_path / "202.fcs")
    bodies = [
        {"channels": colour(pbmc[0]), "name": "PBMC"},
        {
            "channels": ["FJComp-Alexa Fluor 700-A", "FJComp-BV510-A", "FJComp-Spark Blue-A"],
            "name": "202",
        },
        {"channels": ["FJComp-BV421-A"], "name": "Third"},
    ]
    got = node(tmp_path / "web", datasets_max=2)(
        READ + FIXTURES + f" const b = await readFile({json.dumps(str(path))});"
        " await t.upload({ name: '202.fcs', size: b.length, buf: b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) });"
        " const out = [];"
        f" for (const body of {json.dumps(bodies)}) {{"
        "   try { out.push((await t.request('POST', '/datasets', body)).datasets.map(d => d.name)); }"
        "   catch (e) { out.push([e.status, e.param, e.message]); }"
        " }"
        " out.push((await t.request('GET', '/workspace')).datasets.map(d => d.name));"
        " return out;"
    )
    message = "This workspace holds 2 dataset names, the most it can; remove one first."
    assert got == [["PBMC"], ["PBMC", "202"], [422, "name", message], ["PBMC", "202"]]


def test_the_dataset_limits_are_the_servers(js):
    from dnapp.core import config

    names = [
        "DATASET_NAME_MAX",
        "DATASET_CHANNELS_MAX",
        "DATASET_CHANNEL_CHARS",
        "DATASET_CHANNELS_BYTES",
        "DATASETS_MAX",
    ]
    assert js(f"return {json.dumps(names)}.map(n => config[n]);") == [
        getattr(config, n) for n in names
    ]


def test_a_batch_names_each_new_dataset_once_another_was_there(js, pbmc):
    """After a batch, each dataset it made while another dataset was already there gets a line
    naming it and what it lacks or adds against the largest other dataset (the earliest on a tie),
    which may be one the batch made. In a workspace with no dataset before, the batch's first
    dataset was made with no other there, so it gets none, and every later one gets its line."""
    u3, u4, u5, _ = pbmc
    p = colour(u3)
    a, b = variant(u4, "x1", drop=(p[0],)), variant(u5, "x2", drop=(p[0],))
    c = variant(u5, "x3", drop=(p[1],))
    got = js(
        f"const [u3, u4, a, b, c] = {json.dumps([u3, u4, a, b, c])};"
        " const known = new Set(ds.groupDatasets([u3]).map(d => d.key)), none = new Set();"
        " return [ds.newDatasetNotes(known, ds.groupDatasets([u3, u4, a])),"
        " ds.newDatasetNotes(known, ds.groupDatasets([u3, a, b])),"
        " ds.newDatasetNotes(known, ds.groupDatasets([u3, u4])),"
        " ds.newDatasetNotes(none, ds.groupDatasets([u3, a])),"
        " ds.newDatasetNotes(none, ds.groupDatasets([a, b, u3, c])),"
        " ds.newDatasetNotes(none, ds.groupDatasets([u3, u4]))];"
    )
    note = "Dataset {} is a new dataset: compared with Dataset {}, it {}."
    assert got == [
        [note.format(2, 1, f"lacks {p[0]}")],
        [note.format(2, 1, f"lacks {p[0]}")],
        [],
        [note.format(2, 1, f"lacks {p[0]}")],
        [note.format(2, 1, f"adds {p[0]}"), note.format(3, 1, f"lacks {p[1]}; adds {p[0]}")],
        [],
    ]


def test_a_new_dataset_with_no_other_left_gets_no_note(js, pbmc):
    """When the workspace is cleared during a batch, the keys from before name datasets that are
    gone, and the batch's dataset may be the only one: it has nothing to be compared with."""
    u3, u4, *_ = pbmc
    a = variant(u4, "x1", drop=(colour(u3)[0],))
    got = js(
        f"const [u3, a] = {json.dumps([u3, a])};"
        " const known = new Set(ds.groupDatasets([u3]).map(d => d.key));"
        " return ds.newDatasetNotes(known, ds.groupDatasets([a]));"
    )
    assert got == []
