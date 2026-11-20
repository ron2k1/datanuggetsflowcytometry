"""An older workspace on the flow-only page, run in Node. A workspace made before the app was flow
only can still hold CSV uploads and general runs and jobs, and the server lists them so they can
be deleted; the page counts only the FCS uploads and flow runs it lists. main.js boots in fixture
mode on the recorded workspace with the General items it held before put back, the real shell,
tabs and explorer drawn into a small stand-in for the DOM and every other feature a stub. The
modules are copied beside a package.json that marks them as ES modules, so any Node from 18 on
runs them; the tests skip where Node isn't installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
REAL = ("explorer", "shell", "tabs")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")

# The General items the recorded workspace held before General mode left: the iris and California
# housing demo uploads, their three k-means and hclust runs, and those runs' jobs.
DONE = {"status": "done", "progress": 1.0, "stage": "done", "message": None, "log_tail": []}
CSV_UPLOADS = [
    {"id": "u1", "name": "iris.csv", "kind": "csv", "bytes": 4009, "rows": 150, "columns": [],
     "created": "2026-10-27T20:37:30Z", "demo": "iris"},
    {"id": "u2", "name": "california_housing.csv", "kind": "csv", "bytes": 1915795, "rows": 20640,
     "columns": [], "created": "2026-10-27T20:37:30Z", "demo": "housing"},
]  # fmt: skip
GENERAL_RUNS = [
    {"id": "r1", "kind": "general", "status": "done", "created": "2026-10-27T20:37:19Z",
     "title": "iris.csv · k-means K=3", "source": "u1", "k": 3},
    {"id": "r2", "kind": "general", "status": "done", "created": "2026-10-27T20:37:17Z",
     "title": "california_housing.csv · k-means K=4", "source": "u2", "k": 4},
    {"id": "r4", "kind": "general", "status": "done", "created": "2026-10-28T01:17:11Z",
     "title": "california_housing.csv · hclust K=100", "source": "u2", "k": 100},
]  # fmt: skip
GENERAL_JOBS = [
    {"id": jid, "kind": "general", **DONE, "created": at, "started": at, "finished": at,
     "run_id": rid, "gate_id": None, "error": None}
    for jid, rid, at in (("j2", "r1", "2026-10-27T20:37:19Z"), ("j3", "r2", "2026-10-27T20:37:17Z"),
                         ("j5", "r4", "2026-10-28T01:17:11Z"))
]  # fmt: skip
# Tab keys for the General items, one for each kind of tab that shows one (a plot's clone too),
# then keys for flow items and for items the workspace does not hold.
GENERAL_KEYS = [
    "upload:u1", "upload:u2", "plot:r1", "plot:r2~2", "compare:r4", "files:r1", "record:r2",
    "job:j2",
]  # fmt: skip
FLOW_KEYS = [
    "upload:u3", "plot:r3", "plot:r3~2", "compare:r7", "files:r3", "record:r7", "job:j1", "job:j4",
    "gate:g1",
]  # fmt: skip
MISSING_KEYS = ["upload:u9", "plot:r9", "job:j9"]

# A stand-in for the few DOM calls the shell, tabs, explorer and menus make: elements keep their
# children, attributes, listeners and text; document.querySelector('#id') gives one per id.
PRELUDE = """
import { readFile } from 'node:fs/promises';
const stub = (k, v) => Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
class Fake {
  constructor(tag) {
    this.tag = tag; this.kids = []; this.attrs = {}; this.on = {}; this.style = {};
    this.own = ''; this.innerHTML = ''; this.className = ''; this.scrollTop = 0;
    const cls = new Set();
    this.classList = { add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c),
      toggle: (c, on = !cls.has(c)) => (on ? cls.add(c) : cls.delete(c)) };
  }
  get nodeType() { return this.tag === '#text' ? 3 : 1; }
  get textContent() { return this.own + this.kids.map(k => k.textContent).join(''); }
  set textContent(v) { this.own = String(v); this.kids = []; }
  append(...ns) { this.kids.push(...ns.map(node)); }
  replaceChildren(...ns) { this.own = ''; this.kids = ns.map(node); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(type, f) { (this.on[type] ||= []).push(f); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, right: 0 }; }
  scrollIntoView() {}
  focus() {}
  remove() {}
  // The first node below this one with class cls.
  find(cls) {
    for (const k of this.kids) { if (k.className.split(' ').includes(cls)) return k; const f = k.find(cls); if (f) return f; }
    return null;
  }
}
const text = s => Object.assign(new Fake('#text'), { own: String(s) });
const node = n => (typeof n === 'string' ? text(n) : n);
const ids = new Map();
stub('document', {
  querySelector: s => ids.get(s) || ids.set(s, new Fake(s)).get(s),
  createElement: tag => new Fake(tag), createTextNode: text, addEventListener() {},
  body: new Fake('body'), documentElement: new Fake('html'), activeElement: null,
});
stub('window', { innerWidth: 1440, addEventListener() {} });
stub('location', { search: '?fixtures=1' });
stub('localStorage', { getItem: () => null, setItem() {} });
stub('fetch', async url => {
  const t = await readFile(new URL(url, import.meta.url), 'utf8');
  return { json: async () => JSON.parse(t) };
});
const $ = s => document.querySelector(s);
const { S, emit, subscribe } = await import('./shared/store.js');
const { EV } = await import('./shared/events.js');
const booted = new Promise((ok, bad) => { subscribe(EV.ready, ok); subscribe(EV.bootFailed, e => bad(e.error)); });
await import('./main.js');
await booted;
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    """page(body) boots the page, runs body as an async function with S, emit, EV and $ in
    scope, and returns what it returns, through JSON."""
    root = tmp_path_factory.mktemp("web")
    shutil.copytree(WEB / "shared", root / "shared")
    shutil.copyfile(WEB / "main.js", root / "main.js")
    for feature in (WEB / "features").iterdir():
        if feature.name in REAL:
            shutil.copytree(feature, root / "features" / feature.name)
        elif feature.is_dir():
            (root / "features" / feature.name).mkdir(parents=True)
            (root / "features" / feature.name / "index.js").write_text(
                "export function mount() {}\n", encoding="utf-8"
            )
    # The upload view beside its feature's stub, unmounted: the test that draws it registers it.
    view = Path("features", "upload", "view.js")
    shutil.copyfile(WEB / view, root / view)
    (root / "fixtures").mkdir()
    for name in ("index.json", "GET__config.json"):
        shutil.copyfile(WEB / "fixtures" / name, root / "fixtures" / name)
    ws = json.loads((WEB / "fixtures" / "GET__workspace.json").read_text(encoding="utf-8"))
    ws["uploads"][:0] = CSV_UPLOADS
    ws["runs"] += GENERAL_RUNS
    ws["jobs"] += GENERAL_JOBS
    (root / "fixtures" / "GET__workspace.json").write_text(json.dumps(ws), encoding="utf-8")
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"

    def run(body: str):
        # The toast's timer would hold Node open for seconds, so the script exits once written.
        script.write_text(
            PRELUDE + f"const out = await (async () => {{ {body} }})();\n"
            "process.stdout.write(JSON.stringify(out === undefined ? null : out),"
            " () => process.exit(0));\n",
            encoding="utf-8",
        )
        done = subprocess.run(
            [NODE, str(script)], capture_output=True, text=True, timeout=60, check=False
        )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    return run


def test_boot_counts_what_the_explorer_lists(page):
    """The workspace holds the CSV uploads and general runs, and the boot line and the explorer's
    foot count neither."""
    got = page(
        "return { held: [S.ws.uploads.length, S.ws.runs.length, S.ws.jobs.length],"
        " boot: S.activity[0].msg, foot: $('#ex-foot').textContent };"
    )
    assert got == {
        "held": [6, 5, 6],
        "boot": "Workspace ready (fixture mode): 4 uploads, 2 runs",
        "foot": "4 uploads · 2 runs · 30.2 MB",
    }


def test_the_workspace_menu_counts_what_the_explorer_lists(page):
    """The FCS uploads' 30.2 MB, not 32.1 MB with the CSV uploads, and the two flow runs."""
    got = page(
        "const btn = $('#btn-ws'); btn.on.click[0]({ currentTarget: btn });"
        " return document.body.find('menu').find('meter-row').textContent;"
    )
    assert got == "30.2 MB of uploads · limit 1.00 GB · 2 runs"


def test_no_tab_opens_for_a_general_item(page):
    """Every tab opens through EV.openTab, so whoever sends a key for a CSV upload or a general
    run or job, it is refused with a toast and a line in the activity log, in front of the
    current tab or behind it."""
    got = page(
        f"return {json.dumps(GENERAL_KEYS)}.flatMap(key => [false, true].map(background => {{"
        " emit(EV.openTab, { key, background });"
        " return [[...S.tabs.open], S.tabs.active, $('#toast').textContent,"
        " S.activity.at(-1).msg]; }));"
    )
    want = []
    for key in GENERAL_KEYS:
        item = key.split(":")[1].split("~")[0]
        msg = f"{item} is from General mode, which this app no longer has."
        want += [[["start"], "start", msg, f"Open {key}: {msg}"]] * 2
    assert got == want


def test_flow_items_and_missing_ones_still_open(page):
    """A key for a flow item, or for an item the workspace does not hold, opens as before."""
    keys = FLOW_KEYS + MISSING_KEYS
    got = page(
        f"const keys = {json.dumps(keys)}; keys.forEach(key => emit(EV.openTab, {{ key }}));"
        " return [S.tabs.open, S.tabs.active, $('#toast').textContent, $('#tabs').kids.length];"
    )
    assert got == [["start", *keys], keys[-1], "", len(keys) + 1]


def test_the_upload_view_refuses_a_csv_upload_it_fetches(page):
    """An upload tab for an upload the page has not listed fetches it: a CSV upload is refused in
    the words the tabs refuse it in and not kept, and an FCS upload is kept and drawn."""
    fetched = {
        "u8": {**CSV_UPLOADS[0], "id": "u8", "name": "old.csv"},
        "u7": {"id": "u7", "name": "new.fcs", "kind": "fcs", "bytes": 100, "rows": 10,
               "columns": [], "created": "2026-10-28T01:17:11Z", "demo": None},
    }  # fmt: skip
    got = page(
        "const { registerUploadView } = await import('./features/upload/view.js');"
        " const { viewFor } = await import('./shared/views.js');"
        " const { api } = await import('./shared/api/index.js');"
        f" const fetched = {json.dumps(fetched)}; api.uploadInfo = async id => fetched[id];"
        " registerUploadView();"
        " const draw = async key => { const body = document.createElement('div');"
        " viewFor('upload').render(body, key); await new Promise(ok => setTimeout(ok));"
        " return [body.find('empty')?.textContent ?? null, body.find('doc-title')?.textContent ?? null]; };"
        " return [await draw('upload:u8'), await draw('upload:u7'),"
        " S.ws.uploads.map(u => u.id).filter(id => id in fetched)];"
    )
    assert got == [
        ["u8 is from General mode, which this app no longer has.", None],
        [None, "new.fcs"],
        ["u7"],
    ]
