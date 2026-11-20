"""Datasets on the page, run in Node: the explorer lists the FCS uploads by dataset and renames
one. main.js boots in fixture mode on the recorded workspace, with copies of its PBMC uploads
added: one without a colour channel (another dataset), one with a stain renamed (the same
dataset) and one without any colour channel. The explorer, shell, tabs, upload and gate features
are real, drawn into a small stand-in for the DOM, and every other feature is a stub. The modules
are copied beside a package.json that marks them as ES modules, so any Node from 18 on runs them;
the tests skip where Node isn't installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_datasets_web import colour, fcs_202, variant

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
REAL = ("explorer", "shell", "tabs", "upload", "gate")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")

# A stand-in for the DOM calls these features make: elements keep their parent, children,
# attributes, listeners, text and value; events bubble up to document unless stopped; focus moves
# document.activeElement and blurs the element it leaves. A click is a press, which focuses its
# element, a release and then the click, which a press that took the element out of the page
# loses; disabling the focused element blurs it, as a browser may. document.querySelector('#id')
# gives one connected element per id.
PRELUDE = """
import { readFile } from 'node:fs/promises';
const stub = (k, v) => Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
const docOn = {};
class Fake {
  constructor(tag) {
    Object.assign(this, { tag, kids: [], attrs: {}, on: {}, style: {}, parent: null, root: false, own: '',
      innerHTML: '', className: '', scrollTop: 0, value: '', disabled: false, checked: false, hidden: false });
    const has = () => new Set(this.className.split(' ').filter(Boolean));
    const put = s => { this.className = [...s].join(' '); };
    this.classList = {
      add: c => { const s = has(); s.add(c); put(s); }, remove: c => { const s = has(); s.delete(c); put(s); },
      contains: c => has().has(c), toggle: (c, on = !has().has(c)) => { const s = has(); on ? s.add(c) : s.delete(c); put(s); return on; },
    };
  }
  get nodeType() { return this.tag === '#text' ? 3 : 1; }
  get textContent() { return this.own + this.kids.map(k => k.textContent).join(''); }
  set textContent(v) { this.own = String(v); this.drop(); this.kids = []; }
  get isConnected() { let n = this; while (n.parent) n = n.parent; return n.root; }
  drop() { this.kids.forEach(k => { k.parent = null; }); }
  adopt(n) { n = node(n); if (n.parent) n.remove(); n.parent = this; return n; }
  append(...ns) { this.kids.push(...ns.map(n => this.adopt(n))); }
  replaceChildren(...ns) { this.own = ''; this.drop(); this.kids = []; this.append(...ns); }
  replaceWith(n) { const p = this.parent, i = p.kids.indexOf(this); n = p.adopt(n); p.kids[p.kids.indexOf(this)] = n; this.parent = null; return i; }
  remove() { if (this.parent) { this.parent.kids.splice(this.parent.kids.indexOf(this), 1); this.parent = null; } }
  // A boolean attribute (el() sets one only when true) sets its property, as a page's would.
  setAttribute(k, v) { this.attrs[k] = String(v); if (['checked', 'disabled', 'hidden'].includes(k)) this[k] = true; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, f) { (this.on[type] ||= []).push(f); }
  // Calls the listeners of this element, then of each parent and of document, until one stops it.
  dispatch(type, init = {}, bubbles = true) {
    const e = { type, target: this, defaultPrevented: false, stopped: false, ...init,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; } };
    for (let n = this; n && !e.stopped; n = bubbles ? n.parent : null) { e.currentTarget = n; (n.on[type] || []).forEach(f => f(e)); }
    if (bubbles && !e.stopped) (docOn[type] || []).forEach(f => f(e));
    return e;
  }
  click() { this.dispatch('mousedown'); this.focus(); this.dispatch('mouseup'); return this.isConnected ? this.dispatch('click') : null; }
  get disabled() { return this.off; }
  set disabled(v) { this.off = Boolean(v); if (this.off && document.activeElement === this) this.blur(); }
  focus() {
    const was = document.activeElement;
    if (was === this) return;
    document.activeElement = this;
    if (was && was.dispatch) was.dispatch('blur', {}, false);
  }
  blur() { if (document.activeElement === this) { document.activeElement = document.body; this.dispatch('blur', {}, false); } }
  select() {}
  // A dialog: showModal opens it; close(value) shuts it, keeps the value as its returnValue and
  // fires close, as a browser's does.
  showModal() { this.open = true; this.returnValue = this.returnValue || ''; }
  close(v) { if (!this.open) return; this.open = false; if (v !== undefined) this.returnValue = v; this.dispatch('close', {}, false); }
  closest(sel) {
    const tags = sel.split(',').map(s => s.trim());
    for (let n = this; n; n = n.parent) if (tags.includes(n.tag)) return n;
    return null;
  }
  contains(n) { for (; n; n = n.parent) if (n === this) return true; return false; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, right: 0 }; }
  scrollIntoView() {}
  // The first node below this one with class cls, and every one.
  find(cls) { return this.findAll(cls)[0] || null; }
  findAll(cls) { return this.kids.flatMap(k => [...(k.classList.contains(cls) ? [k] : []), ...k.findAll(cls)]); }
}
const text = s => Object.assign(new Fake('#text'), { own: String(s) });
const node = n => (typeof n === 'string' ? text(n) : n);
const ids = new Map();
const body = Object.assign(new Fake('body'), { root: true });
stub('Element', Fake);
stub('document', {
  querySelector: s => ids.get(s) || ids.set(s, Object.assign(new Fake(s), { root: true })).get(s),
  createElement: tag => new Fake(tag), createTextNode: text,
  addEventListener: (type, f) => { (docOn[type] ||= []).push(f); },
  body, documentElement: new Fake('html'), activeElement: body,
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
const { api } = await import('./shared/api/index.js');
const booted = new Promise((ok, bad) => { subscribe(EV.ready, ok); subscribe(EV.bootFailed, e => bad(e.error)); });
await import('./main.js');
await booted;
const tick = () => new Promise(ok => setTimeout(ok));
const press = (n, key) => n.dispatch('keydown', { key });
// The explorer's rows: [depth, name, meta, the warning mark's title, the rename button's label].
const rows = () => $('#tree').kids.filter(k => !k.classList.contains('tree-empty')).map(k => {
  const r = k.classList.contains('tree-row') ? k : k.find('tree-row'), warn = r.find('tree-warn'), act = k.find('tree-act');
  const name = r.find('tree-name'), meta = r.find('tree-meta');
  return [Number(r.attrs.style.split(':')[1]), name ? name.textContent : null, meta ? meta.textContent : null,
    warn ? warn.attrs.title : null, act ? act.attrs['aria-label'] : null];
});
const item = name => $('#tree').findAll('tree-item').find(k => k.find('tree-name').textContent === name);
// The datasets' names: the rows with an action that are folders (a file's and a gate's are not).
const names = () => $('#tree').findAll('tree-item').filter(k => k.find('k-folder')).map(k => k.find('tree-name').textContent);
const field = () => $('#tree').find('tree-input');
// POST /datasets's names, as the explorer sends them.
const sent = [];
const nameDataset = api.nameDataset;
api.nameDataset = body => { sent.push(body.name); return nameDataset(body); };
"""


def mb(u: dict) -> str:
    """u's size as fmtBytes writes one of a megabyte or more."""
    return f"{u['bytes'] / 1e6:.1f} MB"


WS = json.loads((WEB / "fixtures" / "GET__workspace.json").read_text(encoding="utf-8"))
PBMC = [u for u in WS["uploads"] if u["kind"] == "fcs"]
P = colour(PBMC[0])
# x1 lacks the first colour channel, x2 spells one stain another way, x3 has no colour channel.
EXTRA = [
    variant(PBMC[1], "x1", drop=(P[0],)),
    variant(PBMC[2], "x2", labels={"FJComp-BV510-A": "CD3 BV510"}),
    variant(PBMC[3], "x3", drop=P),
]


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    """page(body) boots the page, runs body as an async function with S, emit, EV, api, $ and the
    helpers above in scope, and returns what it returns, through JSON."""
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
    (root / "fixtures").mkdir()
    for name in ("index.json", "GET__config.json"):
        shutil.copyfile(WEB / "fixtures" / name, root / "fixtures" / name)
    ws = {**WS, "uploads": WS["uploads"] + EXTRA}
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


def test_the_explorer_lists_the_uploads_by_dataset(page):
    """Datasets holds a folder for each dataset, named, with its file count and its files; its
    tooltip gives its colour channels and what it lacks or adds against the largest dataset, and
    a mark warns when stains differ between its files. A dataset with no colour channel has no
    channels to name it by, so it has no rename button. Each file has a delete button. The foot
    still counts uploads."""
    got = page(
        "const ds = rows(), titles = $('#tree').findAll('tree-item').filter(k => k.find('k-folder'))"
        ".map(k => k.find('tree-row').attrs.title);"
        " item('Dataset 1').find('tree-row').click();"
        " return [ds, titles, rows().map(r => r[1]), $('#ex-foot').textContent];"
    )
    shown, titles, folded, foot = got
    stains = (
        "Stains differ between its files:\n"
        "FJComp-BV510-A: CD3 (190.fcs, 193.fcs, 199.fcs and 1 more) or CD3 BV510 (x2.fcs)"
    )
    x1, x2, x3 = EXTRA
    assert shown[: shown.index([0, "Gates", "1", None, None])] == [
        [0, "Start", None, None, None],
        [0, "Datasets", "3", None, None],
        [1, "Dataset 1", "5 files", stains, "Rename Dataset 1"],
        *([2, u["name"], mb(u), None, f"Delete {u['name']}"] for u in [*PBMC, x2]),
        [1, "Dataset 2", "1 file", None, "Rename Dataset 2"],
        [2, "x1.fcs", mb(x1), None, "Delete x1.fcs"],
        [1, "Dataset 3", "1 file", None, None],
        [2, "x3.fcs", mb(x3), None, "Delete x3.fcs"],
    ]
    assert titles == [
        f"Dataset 1 · 32 colour channels\n{stains}",
        f"Dataset 2 · 31 colour channels\nCompared with Dataset 1, it lacks {P[0]}.",
        (
            f"Dataset 3 · 0 colour channels\nCompared with Dataset 1, it lacks {P[0]}, {P[1]},"
            f" {P[2]} and 29 more."
        ),
    ]
    assert folded[1:6] == ["Datasets", "Dataset 1", "Dataset 2", "x1.fcs", "Dataset 3"]
    assert foot.startswith("7 uploads · 2 runs · ")


def test_collapse_folders_shuts_the_dataset_folders_too(page):
    """Collapse folders closes the explorer's folders and every dataset's, so Datasets opened
    again lists the datasets shut."""
    got = page(
        "$('#ex-actions').kids.find(b => b.attrs['aria-label'] === 'Collapse folders').click();"
        " const shut = rows().map(r => r[1]);"
        " $('#tree').findAll('tree-row').find(r => r.find('tree-name').textContent === 'Datasets').click();"
        " return [shut, rows().map(r => r[1])];"
    )
    roots = ["Datasets", "Gates", "Runs", "Jobs", "Run it locally"]
    assert got == [
        ["Start", *roots],
        ["Start", "Datasets", "Dataset 1", "Dataset 2", "Dataset 3", *roots[1:]],
    ]


def test_enter_saves_a_name_and_a_blank_one_gives_the_number_back(page):
    """The rename button turns the name into a field holding it. Enter sends the name and the
    explorer shows the name the server answers with, trimmed, with the focus back on the rename
    button; an empty name removes it, so the dataset is numbered again. Enter on the name as it
    was sends nothing."""
    got = page(
        "item('Dataset 2').find('tree-act').click();"
        " const f = field(), opened = [f.value, document.activeElement === f, names()];"
        " f.value = '  Less one '; press(f, 'Enter'); await tick();"
        " const saved = [names(), S.ws.datasets, S.activity.at(-1).msg, field(),"
        " document.activeElement === item('Less one').find('tree-act')];"
        " item('Less one').find('tree-act').click(); press(field(), 'Enter'); await tick();"
        " const same = [names(), field()];"
        " item('Less one').find('tree-act').click(); field().value = ''; press(field(), 'Enter'); await tick();"
        " return [opened, saved, same, [names(), S.ws.datasets, S.activity.at(-1).msg], sent];"
    )
    opened, saved, same, cleared, posted = got
    assert opened == ["Dataset 2", True, ["Dataset 1", "Dataset 3"]]
    record = {"id": "d1", "channels": colour(EXTRA[0]), "name": "Less one"}
    assert saved == [
        ["Dataset 1", "Less one", "Dataset 3"],
        [record],
        "Renamed Dataset 2 to Less one",
        None,
        True,
    ]
    assert same == [["Dataset 1", "Less one", "Dataset 3"], None]
    assert cleared == [["Dataset 1", "Dataset 2", "Dataset 3"], [], "Renamed Less one to Dataset 2"]
    assert posted == ["  Less one ", ""]


def test_enter_while_composing_sends_nothing(page):
    """An Enter that ends a composition (an input method's) is the input method's, so it saves
    nothing and the field stays open with what is typed."""
    got = page(
        "item('Dataset 2').find('tree-act').click(); const f = field(); f.value = 'Less one';"
        " const e = f.dispatch('keydown', { key: 'Enter', isComposing: true }); await tick();"
        " return [e.defaultPrevented, field() === f, f.value, sent, names()];"
    )
    assert got == [False, True, "Less one", [], ["Dataset 1", "Dataset 3"]]


def test_a_refused_name_keeps_the_field_open_with_the_servers_words(page):
    got = page(
        "item('Dataset 1').find('tree-act').click(); const f = field();"
        " f.value = 'x'.repeat(61); press(f, 'Enter'); await tick();"
        " return [$('#toast').textContent, $('#toast').classList.contains('err'), field() === f, f.value.length,"
        " f.disabled, document.activeElement === f, S.activity.at(-1).msg, names()];"
    )
    words = "The name is 61 characters long; a dataset name is at most 60."
    assert got == [
        words, True, True, 61, False, True, f"Rename Dataset 1: {words}", ["Dataset 2", "Dataset 3"],
    ]  # fmt: skip


def test_a_name_saved_while_the_workspace_reloads_is_kept(page):
    """A job that ends reloads the workspace. A name saved meanwhile still shows, whichever
    answer comes last: the reload's, sent before the name was saved (the server kept the name
    all the same), or the save's, which lands in the reloaded workspace."""
    got = page(
        "const { loadWorkspace } = await import('./shared/store.js');"
        " const hold = () => { let go; return [new Promise(ok => { go = ok; }), () => go()]; };"
        " const post = api.nameDataset, get = api.workspace;"
        " let [held, go] = hold(); api.nameDataset = async body => { await held; return post(body); };"
        " item('Dataset 2').find('tree-act').click(); field().value = 'Less one'; press(field(), 'Enter');"
        " await loadWorkspace(); go(); await tick(); await tick();"
        " const saveLast = [names(), S.ws.datasets.map(d => d.name)];"
        " api.nameDataset = post; [held, go] = hold(); let answered;"
        " const onItsWay = new Promise(ok => { answered = ok; });"
        " api.workspace = async () => { const ws = await get(); answered(); await held; return ws; };"
        " const reload = loadWorkspace(); await onItsWay;"
        " item('Dataset 1').find('tree-act').click(); field().value = 'Full'; press(field(), 'Enter');"
        " await tick(); go(); await reload; emit(EV.render);"
        " return [saveLast, [names(), S.ws.datasets.map(d => d.name)]];"
    )
    assert got == [
        [["Dataset 1", "Less one", "Dataset 3"], ["Less one"]],
        [["Full", "Less one", "Dataset 3"], ["Less one", "Full"]],
    ]


def test_no_second_rename_opens_while_a_name_is_on_its_way(page):
    """While a name is being saved, another rename button opens nothing, so the answer finds its
    own field: a saved name closes it, and a refused one leaves it open, focused, where Escape
    still cancels it."""
    got = page(
        "const post = api.nameDataset; let go;"
        " api.nameDataset = async body => { await new Promise(ok => { go = ok; }); return post(body); };"
        " const fields = () => $('#tree').findAll('tree-input').length;"
        " const tryBoth = async value => { item(names()[1]).find('tree-act').click(); const f = field();"
        "   f.value = value; press(f, 'Enter'); item('Dataset 1').find('tree-act').click();"
        "   const during = fields(); await tick(); go(); await tick(); await tick(); return [f, during]; };"
        " const [, during] = await tryBoth('Less one'); const saved = [during, fields(), names()];"
        " const [f, again] = await tryBoth('x'.repeat(61));"
        " const refused = [again, fields(), field() === f, document.activeElement === f, f.disabled];"
        " press(f, 'Escape');"
        " return [saved, refused, [fields(), names(), sent]];"
    )
    assert got == [
        [1, 0, ["Dataset 1", "Less one", "Dataset 3"]],
        [1, 1, True, True, False],
        [0, ["Dataset 1", "Less one", "Dataset 3"], ["Less one", "x" * 61]],
    ]


def test_a_click_that_leaves_the_field_lands_on_its_row(page):
    """A redraw asked for while the field is open waits for the press that leaves the field to
    end, so its click still opens the row it was aimed at; the gate that came meanwhile shows
    then."""
    u = PBMC[1]
    got = page(
        "item('Dataset 2').find('tree-act').click(); field().value = 'Typed';"
        " S.ws.gates.push({ id: 'g9', status: 'done', files: [] }); emit(EV.jobsChange, { changed: true });"
        f" const file = $('#tree').findAll('tree-row').find(r => r.find('tree-name').textContent === {json.dumps(u['name'])});"
        " file.click(); await tick();"
        " return [S.tabs.active, field(), rows().some(r => r[1] === 'Gate g9'), sent];"
    )
    assert got == [f"upload:{u['id']}", None, True, []]


def test_a_press_that_leaves_the_field_elsewhere_still_redraws(page):
    """A press that leaves the field on something that does not redraw the explorer, the editor
    here, still ends with the redraw that was put off, a tick after its release."""
    got = page(
        "item('Dataset 2').find('tree-act').click(); field().value = 'Typed';"
        " S.ws.gates.push({ id: 'g9', status: 'done', files: [] }); emit(EV.jobsChange, { changed: true });"
        " $('#editor').click(); const before = rows().some(r => r[1] === 'Gate g9'); await tick();"
        " return [field(), before, rows().some(r => r[1] === 'Gate g9'), sent];"
    )
    assert got == [None, False, True, []]


def test_a_name_saved_after_its_upload_went_still_redraws(page):
    """The upload a dataset was found by can go while its name is on its way: the rename is
    logged without the name it came to, and the explorer redraws."""
    got = page(
        "const post = api.nameDataset; let go;"
        " api.nameDataset = async body => { await new Promise(ok => { go = ok; }); return post(body); };"
        " item('Dataset 2').find('tree-act').click(); field().value = 'Less one'; press(field(), 'Enter');"
        " S.ws.uploads = S.ws.uploads.filter(u => u.id !== 'x1'); go(); await tick(); await tick();"
        " return [S.activity.at(-1).msg, names(), field(), S.ws.datasets.map(d => d.name)];"
    )
    assert got == ["Renamed Dataset 2", ["Dataset 1", "Dataset 2"], None, ["Less one"]]


def test_the_upload_tab_names_its_dataset(page):
    """The tab says which dataset the upload is in, with its files and colour channels, what it
    lacks or adds against the dataset with the most files, and a warning when stains differ
    between the dataset's files. The crumbs go through the dataset, and a new name shows at once."""
    got = page(
        "const tab = async key => { emit(EV.openTab, { key }); await tick(); const b = $('#editor');"
        " return [b.find('ds-line').textContent, b.findAll('ds-note').map(n => [n.className, n.textContent]),"
        " $('#crumbs').kids.map(k => k.textContent).filter(Boolean)]; };"
        " const shown = [await tab('upload:u3'), await tab('upload:x1')];"
        " item('Dataset 2').find('tree-act').click(); field().value = 'Less one'; press(field(), 'Enter');"
        " await tick(); const b = $('#editor');"
        " return [...shown, [b.find('ds-line').textContent, $('#crumbs').kids.map(k => k.textContent).filter(Boolean)]];"
    )
    stains = (
        "Stains differ between this dataset's files: FJComp-BV510-A: CD3 (190.fcs, 193.fcs,"
        " 199.fcs and 1 more) or CD3 BV510 (x2.fcs). One stain can be spelled two ways; check"
        " these name the same markers."
    )
    lacks = f"Compared with Dataset 1, the dataset with the most files, it lacks {P[0]}."
    assert got == [
        [
            "Dataset: Dataset 1 · 5 files · 32 colour channels",
            [["note warn ds-note", stains]],
            ["Datasets", "Dataset 1", "190.fcs"],
        ],
        [
            "Dataset: Dataset 2 · 1 file · 31 colour channels",
            [["note ds-note", lacks]],
            ["Datasets", "Dataset 2", "x1.fcs"],
        ],
        ["Dataset: Less one · 1 file · 31 colour channels", ["Datasets", "Less one", "x1.fcs"]],
    ]


def test_the_gate_form_takes_files_from_the_opened_files_dataset(page):
    """The form lists only the files of the opened file's dataset, ticks the last batch's files
    only within it, and counts the files it leaves out. A warning shows while the ticked files'
    stains differ. A refusal from the server still shows in its words."""
    refusal = (
        f"x1.fcs has different colour channels from 190.fcs (it lacks {P[0]})."
        " A gate takes files from one dataset."
    )
    got = page(
        "const { ApiError } = await import('./shared/api/errors.js');"
        " const form = () => { const b = $('#editor').find('gate-files');"
        "   return [b.findAll('check').map(c => [c.textContent, c.kids[0].checked]),"
        "     b.find('gate-files-head').kids[1].textContent,"
        "     b.findAll('note').filter(n => !n.hidden).map(n => n.textContent)]; };"
        " const box = name => $('#editor').find('gate-files').findAll('check').find(c => c.textContent.startsWith(name)).kids[0];"
        " S.lastBatch = ['x1', 'u3', 'x2']; emit(EV.openTab, { key: 'upload:u3' }); await tick();"
        " const opened = form();"
        " const x2 = box('x2.fcs'); x2.checked = false; x2.dispatch('change'); const unticked = form();"
        " $('#editor').find('gate-files').findAll('linkbtn').find(b => b.textContent === 'Select all').click();"
        " const all = form();"
        " const asked = []; api.startGate = async body => { asked.push(body.uploads);"
        "   throw new ApiError(422, { error: { code: 'invalid_setting', param: 'uploads',"
        f"   message: {json.dumps(refusal)} }} }}); }};"
        " $('#editor').findAll('primary').at(-1).click(); await tick();"
        " const msg = $('#editor').findAll('form-actions').at(-1).kids.find(k => k.classList.contains('grow'));"
        " const refused = [asked, msg.className, msg.textContent];"
        " emit(EV.openTab, { key: 'upload:x1' }); await tick();"
        " return [opened, unticked, all, refused, form()];"
    )
    opened, unticked, all_, refused, alone = got
    files = [f"{u['name']} ({u['rows']:,} events)" for u in [*PBMC, EXTRA[1]]]
    hidden = "2 files in other datasets are not shown: a gate takes files from one dataset."
    differ = (
        "Stains differ between the ticked files: FJComp-BV510-A: CD3 ({}) or CD3 BV510 (x2.fcs)."
    )
    spelled = " One stain can be spelled two ways; check these name the same markers."
    more = "Add more with the button or by dropping files on this box."
    assert opened[0] == [[f, f.startswith(("190.fcs", "x2.fcs"))] for f in files]
    assert opened[1:] == [
        "2 of 5 selected, up to 8 per gate",
        [hidden, differ.format("190.fcs") + spelled, opened[2][2]],
    ]
    assert opened[2][2].startswith(more)
    assert unticked[1:] == ["1 of 5 selected, up to 8 per gate", [hidden, opened[2][2]]]
    assert all_[1:] == [
        "5 of 5 selected, up to 8 per gate",
        [hidden, differ.format("190.fcs, 193.fcs, 199.fcs and 1 more") + spelled, opened[2][2]],
    ]
    assert refused == [[["u3", "u4", "u5", "u6", "x2"]], "grow note err", f"uploads: {refusal}"]
    assert alone[0] == [[f"x1.fcs ({EXTRA[0]['rows']:,} events)", True]]
    assert alone[1:] == [
        "1 of 1 selected, up to 8 per gate",
        ["6 files in other datasets are not shown: a gate takes files from one dataset."],
    ]


def test_a_mixed_batch_spends_the_cap_only_on_the_opened_files_dataset(page):
    """The last batch's files of other datasets take none of the files-per-gate cap (8): a batch
    of six files of Dataset 2, then nine of Dataset 1, ticks the opened file and the batch's first
    seven other files of Dataset 1."""
    ones = [variant(PBMC[i % 4], f"a{i}") for i in range(1, 5)]
    twos = [variant(PBMC[i % 4], f"b{i}", drop=(P[0],)) for i in range(1, 7)]
    batch = [u["id"] for u in [*twos, *PBMC, EXTRA[1], *ones]]
    got = page(
        f"S.localUploads.push(...{json.dumps([*ones, *twos])}); S.lastBatch = {json.dumps(batch)};"
        " emit(EV.openTab, { key: 'upload:u4' }); await tick(); const b = $('#editor').find('gate-files');"
        " return [b.findAll('check').map(c => [c.textContent.split(' ')[0], c.kids[0].checked]),"
        " b.find('gate-files-head').kids[1].textContent];"
    )
    shown = [u["name"] for u in [*PBMC, EXTRA[1], *ones]]
    assert got == [
        [[name, name != "a4.fcs"] for name in shown],
        "8 of 9 selected, up to 8 per gate",
    ]


@pytest.fixture(scope="module")
def panels(tmp_path_factory):
    """FCS files of 202's recorded events, read in the tab: 202.fcs as recorded; 202-less.fcs
    without its last fluorescence column; 202-more.fcs with its BV510 events again as a channel
    of the PBMC panel's (P[0], with its PBMC stain); 202-stain.fcs with BV510's stain renamed."""
    root = tmp_path_factory.mktemp("fcs")
    pnn = ["FSC-A", "SSC-A", "FJComp-Alexa Fluor 700-A", "FJComp-BV510-A", "FJComp-Spark Blue-A"]
    pns = ["", "", "CD8", "CD3", "CD4"]
    pbmc = {c["name"]: c["label"] for c in PBMC[0]["columns"]}[P[0]]
    return {
        "202.fcs": fcs_202(root / "202.fcs", pnn, pns),
        "202-less.fcs": fcs_202(root / "202-less.fcs", pnn[:4], pns[:4], [0, 1, 2, 3]),
        "202-more.fcs": fcs_202(
            root / "202-more.fcs", [*pnn, P[0]], [*pns, pbmc], [0, 1, 2, 3, 4, 3]
        ),
        "202-stain.fcs": fcs_202(root / "202-stain.fcs", pnn, [*pns[:3], "CD3 BV510", "CD4"]),
    }


def read_in_tab(panels) -> str:
    """JS that hands the page the panels' files, file(name), as a browser's file chooser would,
    and waits with until(n) for n uploads read in the tab."""
    paths = {name: str(path) for name, path in panels.items()}
    return (
        "const { readFile } = await import('node:fs/promises');"
        " globalThis.FileReader = class { readAsArrayBuffer(f) { this.result = f.buf; queueMicrotask(() => this.onload()); } };"
        f" const paths = {json.dumps(paths)};"
        " const file = async name => { const b = await readFile(paths[name]);"
        "   return { name, size: b.length, buf: b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) }; };"
        " const until = async n => { for (let i = 0; i < 500 && S.localUploads.length < n; i++) await tick(); await tick(); };"
    )


def new_note(n: int, channels: list[str]) -> str:
    """The uploader's note for Dataset n, of these colour channels, against the PBMC panel's."""

    def names(cs):
        cs = sorted(cs)
        return ", ".join(cs[:3]) + (f" and {len(cs) - 3} more" if len(cs) > 3 else "")

    lacks, adds = set(P) - set(channels), set(channels) - set(P)
    diff = "; ".join(
        [*([f"lacks {names(lacks)}"] * bool(lacks)), *([f"adds {names(adds)}"] * bool(adds))]
    )
    return f"Dataset {n} is a new dataset: compared with Dataset 1, it {diff}."


FLUOR = ["FJComp-Alexa Fluor 700-A", "FJComp-BV510-A", "FJComp-Spark Blue-A"]


def test_a_batch_announces_each_dataset_it_makes(page, panels):
    """After a batch, each file that made a dataset of its own while others were there gets a
    toast, one after another, and a line in the activity log, naming its dataset and what it lacks
    or adds against the largest other one. Files dropped on a gate form are ticked there only when
    they are in its dataset: 202-stain.fcs is, with a stain warning, and 202-more.fcs is not."""
    got = page(
        read_in_tab(panels) + " const real = setTimeout; let at = 0; const seen = [];"
        " globalThis.setTimeout = (f, ms = 0, ...a) => real(() => { const was = at; at = ms; try { f(...a); } finally { at = was; } }, 0);"
        " Object.defineProperty($('#toast'), 'textContent', { get() { return this.own; },"
        "   set(v) { this.own = String(v); seen.push([at, this.own]); } });"
        " const log = () => S.activity.map(a => a.msg).filter(m => m.includes('new dataset'));"
        " emit(EV.filesDrop, { files: [await file('202.fcs'), await file('202-less.fcs')] }); await until(2);"
        " const first = [seen.splice(0), log(), S.tabs.active];"
        " emit(EV.openTab, { key: 'upload:local1' }); await tick();"
        " $('#editor').find('gate-files').dispatch('drop', { dataTransfer: { files: [await file('202-stain.fcs'), await file('202-more.fcs')] } });"
        " await until(4);"
        " const b = $('#editor').find('gate-files');"
        " return [first, [seen.splice(0), log().length, S.tabs.active, S.tabs.open.slice(-2)],"
        "   b.findAll('check').map(c => [c.textContent, c.kids[0].checked]),"
        "   b.findAll('note').filter(n => !n.hidden).map(n => n.textContent).slice(0, 2),"
        "   [...S.view['upload:local1'].form.uploads]];"
    )
    first, second, checks, notes, ticked = got
    four, five, six = new_note(4, FLUOR), new_note(5, FLUOR[:2]), new_note(6, [*FLUOR, P[0]])
    assert first == [[[0, four], [3600, five]], [four, five], "upload:local2"]
    assert second == [[[0, six]], 3, "upload:local1", ["upload:local3", "upload:local4"]]
    assert checks == [["202.fcs (50,000 events)", True], ["202-stain.fcs (50,000 events)", True]]
    # The form holds no file it does not list, 202-more.fcs (local4) included.
    assert ticked == ["local1", "local3"]
    assert notes == [
        "9 files in other datasets are not shown: a gate takes files from one dataset.",
        (
            "Stains differ between the ticked files: FJComp-BV510-A: CD3 (202.fcs) or CD3 BV510"
            " (202-stain.fcs). One stain can be spelled two ways; check these name the same markers."
        ),
    ]


def test_a_batchs_notes_follow_its_refusal_and_failure_toasts(page, panels):
    """The page has one toast, so a note shown at once would hide the last file's refusal or
    failure; the notes wait their turn after it. 202.txt is 202.fcs's bytes under a name the
    uploader refuses, and 202-cut.fcs its first 64 bytes, which the reader cannot parse."""
    got = page(
        read_in_tab(panels) + " const real = setTimeout; let at = 0; const seen = [];"
        " globalThis.setTimeout = (f, ms = 0, ...a) => real(() => { const was = at; at = ms; try { f(...a); } finally { at = was; } }, 0);"
        " Object.defineProperty($('#toast'), 'textContent', { get() { return this.own; },"
        "   set(v) { this.own = String(v); seen.push([at, this.own]); } });"
        " const whole = await file('202.fcs'), less = await file('202-less.fcs');"
        " const txt = { ...whole, name: '202.txt' }, cut = { ...whole, name: '202-cut.fcs', size: 64, buf: whole.buf.slice(0, 64) };"
        " emit(EV.filesDrop, { files: [whole, txt, less, cut] }); await until(2);"
        " for (let i = 0; i < 50 && seen.length < 4; i++) await tick();"
        " return seen;"
    )
    four, five = new_note(4, FLUOR), new_note(5, FLUOR[:2])
    assert got[0] == [0, "Only .fcs files are accepted."]
    assert got[1][0] == 0 and got[1][1].startswith("202-cut.fcs: ")
    assert got[2:] == [[3600, four], [7200, five]]


def test_a_dataset_is_named_once_when_batches_overlap(page, panels):
    """A batch dropped while another is still uploading knows only the datasets from before both,
    yet a dataset the first one named is not named again when the second one ends."""
    got = page(
        read_in_tab(panels) + " const up = api.upload, held = [];"
        " api.upload = (f, p) => new Promise(ok => held.push(() => ok(up(f, p))));"
        " const [whole, less] = [await file('202.fcs'), await file('202-less.fcs')];"
        " emit(EV.filesDrop, { files: [whole] }); emit(EV.filesDrop, { files: [less] });"
        " held[0](); await until(1); held[1](); await until(2);"
        " return S.activity.map(a => a.msg).filter(m => m.includes('new dataset'));"
    )
    assert got == [new_note(4, FLUOR), new_note(5, FLUOR[:2])]


def test_escape_and_leaving_the_field_cancel_and_close_nothing_else(page):
    """Escape puts the row back, focuses its rename button and stops there: the explorer's drawer,
    open at phone width, stays open, where Escape anywhere else closes it. Leaving the field
    cancels too. Neither sends a name. While the field is open the explorer does not redraw, so a
    redraw from elsewhere keeps what is typed; it redraws once the field closes, so a gate that
    came meanwhile shows then."""
    got = page(
        "window.innerWidth = 700; $('#btn-files').click();"
        " item('Dataset 2').find('tree-act').click(); const f = field(); f.value = 'Typed';"
        " const gate = () => rows().some(r => r[1] === 'Gate g9');"
        " S.ws.gates.push({ id: 'g9', status: 'done', files: [] });"
        " emit(EV.render); emit(EV.jobsChange, { changed: true });"
        " const kept = [field() === f, f.value, gate()];"
        " const esc = press(f, 'Escape');"
        " const escaped = [esc.defaultPrevented, names(), field(), $('#explorer').classList.contains('open'),"
        " document.activeElement === item('Dataset 2').find('tree-act'), gate()];"
        " item('Dataset 2').find('tree-act').click(); field().value = 'Elsewhere'; field().blur();"
        " const left = [names(), field()];"
        " press($('#editor'), 'Escape');"
        " return [kept, escaped, left, $('#explorer').classList.contains('open'), sent];"
    )
    kept, escaped, left, drawer, posted = got
    assert kept == [True, "Typed", False]
    assert escaped == [True, ["Dataset 1", "Dataset 2", "Dataset 3"], None, True, True, True]
    assert left == [["Dataset 1", "Dataset 2", "Dataset 3"], None]
    assert drawer is False
    assert posted == []
