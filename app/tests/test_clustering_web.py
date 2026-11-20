"""The clustering choices on the page, run in Node: the cluster form's Clustering and Nugget
centers selects and what Cluster sends, "Use rX's choice" copying a run's two choices back, and
the words the run record and the plot's inspector give them (shared/clustering.js). A run's
settings name both choices; settings written before the app sent them name neither, and that run
clustered with the hierarchical tree on mean centers, as the package reads such a record. The
modules are copied beside a package.json that marks them as ES modules and drawn into a small
stand-in for the DOM, so any Node from 18 on runs them; the tests skip where Node isn't
installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
FEATURES = ("population-picker", "record")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")

# A stand-in for the DOM calls the forms, the picker and the record view make: elements keep
# their children, attributes, properties, listeners and text. find(pred) gives every node below
# one that pred accepts, labelled(label) the one with that aria-label, and words(node) its text.
PRELUDE = """
const stub = (k, v) => Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true });
class Fake {
  constructor(tag) {
    this.tag = tag; this.kids = []; this.attrs = {}; this.on = {}; this.style = {};
    this.own = ''; this.innerHTML = ''; this.className = '';
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
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, f) { (this.on[type] ||= []).push(f); }
  querySelector() { return (this.inner ||= new Fake('span')); }
  querySelectorAll() { return []; }
  focus() {}
  remove() {}
}
const text = s => Object.assign(new Fake('#text'), { own: String(s) });
const node = n => (typeof n === 'string' ? text(n) : n);
stub('document', { querySelector: () => new Fake('q'), createElement: tag => new Fake(tag), createTextNode: text,
  addEventListener() {}, body: new Fake('body'), documentElement: new Fake('html'), activeElement: null });
stub('window', { innerWidth: 1440, addEventListener() {} });
stub('location', { search: '' });
stub('localStorage', { getItem: () => null, setItem() {} });
const find = (n, pred, out = []) => { for (const k of n.kids) { if (pred(k)) out.push(k); find(k, pred, out); } return out; };
const labelled = (n, label) => find(n, k => k.attrs['aria-label'] === label)[0] || null;
const words = n => n.textContent.replace(/\\s+/g, ' ').trim();
const tick = () => new Promise(ok => setTimeout(ok));
const { S } = await import('./shared/store.js');
const cl = await import('./shared/clustering.js');
const config = await import('./shared/config.js');
"""

# A gate of two files with two colour channels each, as GET /flow/gates/{gid} sends one.
GATE = {
    "id": "g1",
    "settings": {"fsc": "FSC-A", "ssc": "SSC-A"},
    "figures": {"local_maxima": "lm.png", "gates": "gates.png"},
    "files": [
        {"number": n, "upload": f"u{n}", "name": f"{n}.fcs", "n_events": 1000, "local_maxima": 2,
         "default_channels": ["B-A", "C-A"],
         "channels": [{"pnn": c, "pns": ""} for c in ("FSC-A", "SSC-A", "B-A", "C-A")],
         "populations": [{"pop": 1, "events": 900, "percent": 90.0, "median_fsc": 1.0,
                          "median_ssc": 1.0, "peak": [1, 1], "color": "#000000"}]}
        for n in (1, 2)
    ],
}  # fmt: skip
# The picker's state for GATE, as population-picker/index.js starts it: Pop 1 of each file ticked.
STATE = (
    "const st = { step: 'cluster', sets: [new Set([1]), new Set([1])], groups: ['', ''],"
    " fig: 'local_maxima', form: clusterForm(), channels: new Set(['B-A', 'C-A']), dye: null, live: {} };"
)


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """js(body) runs body as an async function in Node with the stand-in DOM, S (store.js), cl
    (shared/clustering.js) and config (shared/config.js) in scope, and returns what it returns,
    through JSON."""
    root = tmp_path_factory.mktemp("web")
    shutil.copytree(WEB / "shared", root / "shared")
    for name in FEATURES:
        shutil.copytree(WEB / "features" / name, root / "features" / name)
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = root / "run.js"

    def run(body: str):
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


def test_the_choices_are_the_packages(js):
    """The selects offer the package's two methods, weighted k-means first (the default), and two
    of create_dn's center methods, the original points first (the default)."""
    from datanuggets_flow._defaults import (
        CENTER_METHODS,
        FLOW_CENTER_METHOD,
        FLOW_LEGACY_CENTER_METHOD,
        FLOW_LEGACY_METHOD,
        FLOW_METHOD,
        FLOW_METHODS,
    )

    got = js("return [config.FLOW_METHODS, config.CENTER_METHODS, config.FLOW_LEGACY];")
    assert got == [
        [["wkmeans", "Weighted k-means"], ["tree", "Hierarchical tree"]],
        [["original", "Original points"], ["mean", "Means"]],
        {"method": "tree", "center_method": "mean"},
    ]
    methods, centers, legacy = got
    assert [v for v, _ in methods] == list(FLOW_METHODS) and methods[0][0] == FLOW_METHOD
    assert {v for v, _ in centers} <= set(CENTER_METHODS) and centers[0][0] == FLOW_CENTER_METHOD
    assert legacy == {"method": FLOW_LEGACY_METHOD, "center_method": FLOW_LEGACY_CENTER_METHOD}


def test_settings_without_a_method_read_as_the_tree_on_means(js):
    """As ClusterSettings.from_dict reads them: no method is the tree, on mean centers unless the
    settings name others; a method without centers takes the default, the original points."""
    got = js(
        "return [{}, null, { k: 8 }, { center_method: 'original' }, { method: 'wkmeans', center_method: 'original' },"
        " { method: 'tree', center_method: 'mean' }, { method: 'wkmeans' }, { method: 'tree', center_method: 'random' }]"
        ".map(s => { const c = cl.clusteringOf(s); return [c.method, c.center_method, cl.methodText(c.method), cl.centersText(c.center_method)]; });"
    )
    assert got == [
        ["tree", "mean", "Hierarchical tree", "Means"],
        ["tree", "mean", "Hierarchical tree", "Means"],
        ["tree", "mean", "Hierarchical tree", "Means"],
        ["tree", "original", "Hierarchical tree", "Original points"],
        ["wkmeans", "original", "Weighted k-means", "Original points"],
        ["tree", "mean", "Hierarchical tree", "Means"],
        ["wkmeans", "original", "Weighted k-means", "Original points"],
        ["tree", "random", "Hierarchical tree", "random"],
    ]


def test_the_cluster_form_sends_the_two_choices(js):
    """The form starts on GET /config's defaults, or on the first entries when /config has none,
    and Cluster sends what the selects show as method and center_method. The draws and the
    weighted k-means starts and rounds are never sent."""
    got = js(
        "const { clusterForm, renderCluster } = await import('./features/population-picker/cluster.js');"
        f" const g = {json.dumps(GATE)};"
        " const draw = async pick => {"
        f"  {STATE}"
        "  const doc = document.createElement('div'); let sent = null;"
        "  renderCluster(doc, { g, st, steps: null, back() {}, backLabel: 'Back', start: async body => { sent = body; } });"
        "  const sel = ['Clustering', 'Nugget centers'].map(l => labelled(doc, l));"
        "  const shown = sel.map(s => find(s, k => k.tag === 'option').map(o => [o.value, o.textContent, 'selected' in o.attrs]));"
        "  const heads = sel.map(s => s && find(doc, k => k.kids.includes(s))[0].kids[0].textContent);"
        "  if (pick) sel.forEach((s, i) => s.on.change[0]({ target: { value: pick[i] } }));"
        "  await find(doc, k => k.className === 'btn primary')[0].on.click[0]();"
        "  return { shown, heads, sent: sent && [sent.method, sent.center_method, ['draws', 'num_init', 'max_iter'].filter(x => x in sent)] }; };"
        " const none = await draw(null), picked = await draw(['tree', 'mean']);"
        " S.config = { defaults: { cluster: { method: 'tree', center_method: 'mean' } } };"
        " const served = await draw(null);"
        " return { none, picked, served };"
    )
    options = [
        [["wkmeans", "Weighted k-means", True], ["tree", "Hierarchical tree", False]],
        [["original", "Original points", True], ["mean", "Means", False]],
    ]
    assert got["none"] == {
        "shown": options,
        "heads": ["Clustering", "Nugget centers"],
        "sent": ["wkmeans", "original", []],
    }
    assert got["picked"]["sent"] == ["tree", "mean", []]
    flipped = [[[v, t, not on] for v, t, on in o] for o in options]
    assert got["served"] == {
        "shown": flipped,
        "heads": ["Clustering", "Nugget centers"],
        "sent": ["tree", "mean", []],
    }


def test_centers_the_page_doesnt_offer_show_as_sent(js):
    """A run the API made with the package's "random" centers, copied by "Use rX's choice": the
    Nugget centers select shows them as an option of their own, selected, and Cluster sends them,
    so the select never shows one value while the form sends another."""
    got = js(
        "const { clusterForm, renderCluster } = await import('./features/population-picker/cluster.js');"
        f" const g = {json.dumps(GATE)}; {STATE}"
        " st.form.center_method = 'random';"
        " const doc = document.createElement('div'); let sent = null;"
        " renderCluster(doc, { g, st, steps: null, back() {}, backLabel: 'Back', start: async body => { sent = body; } });"
        " const sel = labelled(doc, 'Nugget centers');"
        " const shown = find(sel, k => k.tag === 'option').map(o => [o.value, o.textContent, 'selected' in o.attrs]);"
        " await find(doc, k => k.className === 'btn primary')[0].on.click[0]();"
        " return [shown, sent.center_method];"
    )
    assert got == [
        [
            ["original", "Original points", False],
            ["mean", "Means", False],
            ["random", "random (the copied run's)", True],
        ],
        "random",
    ]


@pytest.mark.parametrize(
    ("settings", "want"),
    [
        ({"method": "wkmeans", "center_method": "original"}, ["wkmeans", "original"]),
        ({"method": "tree", "center_method": "random"}, ["tree", "random"]),
        ({"method": "tree", "center_method": "mean"}, ["tree", "mean"]),
        ({}, ["tree", "mean"]),  # a run made before the app sent them
    ],
)
def test_use_a_runs_choice_copies_its_clustering(js, settings, want):
    """The "Use rX's choice" button copies the run's method and centers into the cluster form
    with its populations, groups, k and channels; a run whose settings name neither ran the tree
    on mean centers, and the form takes those."""
    sent = {"pops": [[1], []], "groups": ["a", "b"], "k": 5, "channels": ["B-A", "C-A"], **settings}
    got = js(
        "const { clusterForm } = await import('./features/population-picker/cluster.js');"
        " const { renderPops } = await import('./features/population-picker/pops.js');"
        f" const g = {json.dumps(GATE)}; {STATE}"
        f" S.cache.manifest.r4 = Promise.resolve({{ id: 'r4', settings: {json.dumps(sent)} }});"
        " st.form.method = 'wkmeans'; st.form.center_method = 'original';"
        " const doc = document.createElement('div');"
        " renderPops(doc, { g, st, steps: null, next() {}, nextLabel: 'Next', redraw() {}, openTab() {}, prior: { id: 'r4' } });"
        " const use = find(doc, k => k.textContent === \"Use r4's choice\" && k.tag === 'button')[0];"
        " await use.on.click[0](); await tick();"
        " return [st.form.method, st.form.center_method, st.form.k, st.sets.map(s => [...s]), st.groups];"
    )
    assert got == [*want, 5, [[1], []], ["a", "b"]]


RECORD = {
    "settings": {"k": 12, "method": "wkmeans", "center_method": "original", "draws": "r"},
    "labels": ["B", "C"],
    "transform": {"name": "arcsinh", "cofactor": 150.0, "cofactor_from": "set"},
    "standardize": False,
    "clustering": {
        "method": "wkmeans", "k": 12, "k_used": 12, "nuggets_clustered": 290,
        "nuggets_dropped": 10, "total_wwcss": 1234.5678,
        "r": {"create.DN": 'create.DN(x, center.method = "original", seed = 291102)',
              "cluster": "Wkmeans(centers, k = 12, obs.weights = weights, seed = 291102)"},
    },
}  # fmt: skip


def record_view(js, record: dict) -> list:
    """The record view of a run with run.json record: its Clustering section's terms and
    definitions, in order, or None when it has none."""
    got = js(
        "const { mount } = await import('./features/record/index.js');"
        " const { viewFor } = await import('./shared/views.js'); mount();"
        f" S.cache.manifest.r4 = Promise.resolve({{ id: 'r4', settings: {{}}, record: {json.dumps(record)} }});"
        " const body = document.createElement('div'); viewFor('record').render(body, 'record:r4'); await tick();"
        " const dl = find(body, k => k.tag === 'dl' && k.className.split(' ').includes('rec-clustering'))[0];"
        " return dl ? dl.kids.map(words) : null;"
    )
    return got


def test_the_record_view_says_how_the_run_clustered(js):
    """From run.json's clustering block: the method and k, the centers, the nuggets clustered
    and dropped, the total WWCSS, and the R calls that rebuild the run."""
    assert record_view(js, RECORD) == [
        "Clustering", "Weighted k-means, k = 12",
        "Nugget centers", "Original points",
        "Nuggets", "290 clustered, 10 dropped (weight 0)",
        "Total WWCSS", "1235",  # four significant digits, as the API rounds; run.json has all
        "create.DN in R", RECORD["clustering"]["r"]["create.DN"],
        "Clustering in R", RECORD["clustering"]["r"]["cluster"],
    ]  # fmt: skip


def test_the_record_view_of_a_clamped_tree_on_numpy_draws(js):
    """The tree clusters into no more clusters than nuggets in use, and the record names both
    k's; nuggets drawn with NumPy have no create.DN call."""
    rec = json.loads(json.dumps(RECORD))
    rec["settings"].update(method="tree", center_method="mean", draws="numpy", k=40)
    rec["clustering"].update(method="tree", k=40, k_used=30, nuggets_clustered=30,
                             nuggets_dropped=0, total_wwcss=0.5)  # fmt: skip
    rec["clustering"]["r"] = {
        "create.DN": None,
        "cluster": "cutree(Whclust(centers, w = weights), k = 30)",
    }
    assert record_view(js, rec) == [
        "Clustering", "Hierarchical tree, k = 30 (k = 40 asked, more than the 30 nuggets in use)",
        "Nugget centers", "Means",
        "Nuggets", "30 clustered, 0 dropped (weight 0)",
        "Total WWCSS", "0.5",
        "create.DN in R", "none: these nuggets were drawn with NumPy's generator, not R's set.seed draws",
        "Clustering in R", "cutree(Whclust(centers, w = weights), k = 30)",
    ]  # fmt: skip


def test_the_record_view_of_weighted_kmeans_with_a_cluster_that_emptied(js):
    """Weighted k-means can end with a cluster empty, its numbers then compacted, and k_used is
    below k with every nugget still in use: the record says so, not that k outran the nuggets."""
    rec = json.loads(json.dumps(RECORD))
    rec["clustering"].update(k_used=11)
    assert record_view(js, rec)[:2] == [
        "Clustering", "Weighted k-means, k = 11 (k = 12 asked, 1 cluster ended empty)",
    ]  # fmt: skip
    rec["clustering"].update(k_used=9)
    assert (
        record_view(js, rec)[1] == "Weighted k-means, k = 9 (k = 12 asked, 3 clusters ended empty)"
    )


def test_the_record_view_of_a_run_json_from_before_the_clustering_record(js):
    """A run.json with no clustering block, and settings with no method: the tree on means. Its
    settings hold only the k asked, which the tree lowered when fewer nuggets had cells, so the
    record says asked rather than show it as the k used."""
    rec = {k: v for k, v in RECORD.items() if k != "clustering"}
    rec["settings"] = {"k": 12}
    assert record_view(js, rec) == [
        "Clustering",
        "Hierarchical tree, k = 12 asked (this run.json predates the clustering record)",
        "Nugget centers", "Means",
    ]  # fmt: skip
