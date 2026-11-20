// The explorer: Start, the FCS uploads by dataset, gates, flow runs (with their tabs) and live
// jobs, then "Run it locally". Rows open tabs by event; files dropped on it are sent to the
// uploader. A dataset is renamed in place; a file or a gate is deleted from its row
// (docs/app/deleting.md).
import { $, el, iconBtn, toast, confirmDanger } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtBytes, fmtInt, plural } from '../../shared/format.js';
import { largest, stainText } from '../../shared/datasets.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, activity, tabsNow, fcsUploads, datasets, datasetOf, nameDataset, flowRuns, flowJobs, deleteUpload, deleteGate } from '../../shared/store.js';

const openTab = key => emit(EV.openTab, { key });
// A dataset's folder starts open; these are the keys of the ones closed.
const shut = new Set();
// The rename field while one is open: the explorer does not redraw under it, and stale says a
// redraw was asked for meanwhile. acts holds each dataset's rename button from the last draw.
let editing = null;
const acts = new Map();
// pressed while a mouse button (or a touch's mouse events) is down; held when the field closed
// during that press with a redraw to make, which waits for the click so it lands on its row.
let pressed = false, held = false;
// The deletes on their way, by the tab key of what they delete: a redraw draws their buttons off.
// dels holds each delete button from the last draw, by the same key.
const going = new Set();
const dels = new Map();

function row(depth, icon, kindCls, name, opts = {}) {
  return el('button', {
    class: 'tree-row' + (opts.active ? ' is-active' : '') + (opts.root ? ' is-root' : ''), style: `--depth:${depth}`,
    title: opts.title || name, 'aria-expanded': opts.open == null ? null : String(opts.open), onclick: opts.onclick,
  },
    el('span', { class: 'chev' + (opts.open ? ' open' : ''), html: opts.open == null ? '' : svg('chev') }),
    el('span', { class: 'k-' + kindCls, html: svg(icon) }),
    el('span', { class: 'tree-name', text: name }),
    opts.warn ? el('span', { class: 'tree-warn', title: opts.warn, html: svg('warn') }) : null,
    opts.meta ? el('span', { class: 'tree-meta', text: opts.meta }) : null);
}
function folder(tree, id, label, count, kids) {
  const open = S.expanded.has(id);
  tree.append(row(0, open ? 'folderOpen' : 'folder', 'folder', label, { open, meta: String(count), onclick: () => { toggle(id); } }));
  if (!open) return;
  if (!count) tree.append(el('div', { class: 'tree-empty', text: 'None yet' }));
  else kids();
}
function toggle(id) { if (S.expanded.has(id)) S.expanded.delete(id); else S.expanded.add(id); renderExplorer(); }

// Row r with a delete button beside it, shown on hover or focus as the rename button is. The
// button asks first (confirmDanger, the focus on Cancel), and is off while its delete is on its
// way. A refusal (a gate uses the file; the gate's run or live-cells set is on its way) leaves the
// item, with the server's words in a toast and the activity log. The explorer redraws as jobs
// move, so the button on the page by then may be a newer one than btn: dels.get(key) is it.
function withDelete(r, key, what, text, del) {
  const now = () => dels.get(key);
  const btn = iconBtn('trash', `Delete ${what}`, async () => {
    if (going.has(key) || !(await confirmDanger(`Delete ${what}?`, text, 'Delete', now))) return;
    going.add(key);
    if (now()) now().disabled = true;
    try {
      await del();
    } catch (e) {
      going.delete(key);
      // disabling the focused button blurred it
      if (now()) { now().disabled = false; if (document.activeElement === document.body) now().focus(); }
      toast(e.message, true); activity(`Delete ${what}: ${e.message}`);
      return;
    }
    going.delete(key);
    activity(`Deleted ${what}`); toast(`Deleted ${what}.`);
    emit(EV.render);
  }, 'icon-btn tree-act');
  btn.disabled = going.has(key);
  dels.set(key, btn);
  // the active row's mark spans its delete button too
  return el('div', { class: 'tree-item' + (r.classList.contains('is-active') ? ' is-active' : '') }, r, btn);
}
const FILE_GOES = 'The file is removed from this workspace and cannot be restored. A file that a gate uses is kept until the gate is deleted.';
const GATE_GOES = 'Its populations, figures and live-cells sets are removed and cannot be restored. Runs made from it keep their results.';

// A dataset's tooltip: its colour channels, what it lacks or adds against the largest dataset,
// and the stains that differ between its files (the warning mark's tooltip too).
const stainsText = d => (d.stains.length ? `Stains differ between its files:\n${stainText(d.stains, '\n')}` : null);
const datasetTitle = (d, base) => [`${d.name} · ${plural(d.channels.length, 'colour channel')}`,
  d.diff ? `Compared with ${base.name}, it ${d.diff}.` : null, stainsText(d)].filter(Boolean).join('\n');

// A dataset's folder row, its rename button and, while it is open, its files.
function drawDataset(tree, d, base, active) {
  const open = !shut.has(d.key);
  const item = el('div', { class: 'tree-item' }, row(1, open ? 'folderOpen' : 'folder', 'folder', d.name, {
    open, meta: plural(d.files.length, 'file'), title: datasetTitle(d, base), warn: stainsText(d),
    onclick: () => { if (shut.has(d.key)) shut.delete(d.key); else shut.add(d.key); renderExplorer(); },
  }));
  // A name is kept for a set of colour channels, so a dataset without any cannot have one.
  if (d.channels.length) {
    const btn = iconBtn('rename', `Rename ${d.name}`, () => rename(item, d), 'icon-btn tree-act');
    acts.set(d.key, btn);
    item.append(btn);
  }
  tree.append(item);
  if (open) d.files.forEach(u => tree.append(withDelete(row(2, u.kind, u.kind, u.name, {
    active: active === `upload:${u.id}`, meta: fmtBytes(u.bytes), title: `${u.name} · ${fmtInt(u.rows)} events`,
    onclick: () => openTab(`upload:${u.id}`),
  }), `upload:${u.id}`, u.name, FILE_GOES, () => deleteUpload(u.id))));
}

// The dataset's row becomes a field holding its name. Enter sends the name (POST /datasets) and
// redraws with the names the server answers with; an empty name removes it, so the dataset is
// numbered again. Escape, or leaving the field, cancels: blur never saves. Saving or Escape puts
// the focus back on the dataset's rename button. Escape goes no further, so it closes nothing
// else (the drawer, a menu). A refused name keeps the field open, with the server's words in a
// toast. The row comes back in the field's place, and a redraw put off while the field was open
// waits for the press to end, so a click that leaves the field still lands on the row it was aimed
// at. One field at a time: leaving one closes it before a click lands, so only a field whose name
// is on its way is still open, and its answer needs it.
function rename(item, d) {
  if (editing) return;
  const input = el('input', { type: 'text', class: 'tree-input', value: d.name, 'aria-label': `Name for ${d.name}`, spellcheck: 'false', autocomplete: 'off' });
  const field = el('div', { class: 'tree-row is-editing', style: '--depth:1' },
    el('span', { class: 'chev' }), el('span', { class: 'k-folder', html: svg('folder') }), input);
  const ed = editing = { stale: false, busy: false };
  const live = () => editing === ed && !ed.busy;
  const cancel = refocus => {
    if (!live()) return;
    editing = null;
    field.replaceWith(item);
    if (ed.stale) { if (pressed) held = true; else renderExplorer(); }
    if (refocus && acts.has(d.key)) acts.get(d.key).focus();
  };
  const save = async () => {
    if (!live()) return;
    if (input.value === d.name) { cancel(true); return; }
    ed.busy = true; input.disabled = true;
    try {
      await nameDataset(d.channels, input.value);
    } catch (e) {
      ed.busy = false; input.disabled = false; input.focus();
      toast(e.message, true); activity(`Rename ${d.name}: ${e.message}`);
      return;
    }
    editing = null;
    const now = datasetOf(d.files[0].id);  // none when that upload went meanwhile
    activity(`Renamed ${d.name}${now ? ` to ${now.name}` : ''}`);
    emit(EV.render);
    if (acts.has(d.key)) acts.get(d.key).focus();
  };
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); save(); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancel(true); }
  });
  input.addEventListener('blur', () => cancel(false));
  item.replaceWith(field);
  input.focus();
  input.select();
}

function renderExplorer() {
  if (editing) { editing.stale = true; return; }
  held = false;
  const tree = $('#tree'), active = tabsNow().active || '';
  const activeBase = active.split('~')[0];
  tree.replaceChildren();
  acts.clear();
  dels.clear();
  tree.append(row(0, 'start', 'start', 'Start', { root: true, active: active === 'start', onclick: () => openTab('start') }));
  const ups = fcsUploads(), ds = datasets(), base = largest(ds);
  folder(tree, 'datasets', 'Datasets', ds.length, () => ds.forEach(d => drawDataset(tree, d, base, active)));
  const gates = S.ws.gates || [];
  folder(tree, 'gates', 'Gates', gates.length, () => gates.forEach(g => tree.append(withDelete(row(1, 'picker', 'picker', `Gate ${g.id}`, {
    active: active === `gate:${g.id}`, meta: g.status === 'done' ? `${(g.files || []).length} files` : g.status,
    onclick: () => openTab(`gate:${g.id}`),
  }), `gate:${g.id}`, `gate ${g.id}`, GATE_GOES, () => deleteGate(g.id)))));
  const runs = flowRuns();
  folder(tree, 'runs', 'Runs', runs.length, () => runs.forEach(r => {
    const id = 'run:' + r.id, open = S.expanded.has(id), done = r.status === 'done';
    tree.append(row(1, open ? 'folderOpen' : 'folder', 'folder', `${r.id} · ${r.title}`, { open, title: r.title, meta: done ? null : r.status, onclick: () => toggle(id) }));
    if (!open) return;
    // A run that is not done has no outputs (a cancelled or failed one never will): only its record opens.
    const items = done
      ? [['plot', 'plot', 'Plot'], ['compare', 'compare', 'Compare samples'], ['files', 'files', 'Files'], ['record', 'json', 'Run record']]
      : [['record', 'json', 'Run record']];
    for (const [kind, icon, label] of items) {
      const key = `${kind}:${r.id}`;
      tree.append(row(2, icon, kind === 'record' ? 'json' : kind, label, { active: activeBase === key, onclick: () => openTab(key) }));
    }
  }));
  const jobs = flowJobs().filter(j => j.status !== 'done');
  folder(tree, 'jobs', 'Jobs', jobs.length, () => jobs.forEach(j => tree.append(row(1, 'job', 'job', `Job ${j.id} · ${j.kind}`, {
    active: active === `job:${j.id}`, meta: j.status === 'running' ? `${Math.round(j.progress * 100)}%` : j.status,
    onclick: () => openTab(`job:${j.id}`),
  }))));
  tree.append(row(0, 'local', 'local', 'Run it locally', { root: true, active: active === 'local', onclick: () => openTab('local') }));
  const bytes = ups.reduce((s, u) => s + (u.bytes || 0), 0);
  $('#ex-foot').replaceChildren(el('b', { text: `${ups.length} upload${ups.length === 1 ? '' : 's'}` }), ` · ${runs.length} run${runs.length === 1 ? '' : 's'} · ${fmtBytes(bytes)}`);
}

export function mount() {
  $('#ex-actions').append(
    el('button', { type: 'button', class: 'icon-btn', title: 'Upload FCS files, or drop them here', 'aria-label': 'Upload files', html: svg('upload'), onclick: () => emit(EV.filesPick) }),
    el('button', { type: 'button', class: 'icon-btn', title: 'Collapse folders', 'aria-label': 'Collapse folders', html: svg('collapse'), onclick: () => { S.expanded.clear(); datasets().forEach(d => shut.add(d.key)); renderExplorer(); } }));
  const ex = $('#explorer');
  ex.addEventListener('dragover', e => { e.preventDefault(); ex.classList.add('drop'); });
  ex.addEventListener('dragleave', () => ex.classList.remove('drop'));
  ex.addEventListener('drop', e => { e.preventDefault(); ex.classList.remove('drop'); emit(EV.filesDrop, { files: [...(e.dataTransfer ? e.dataTransfer.files : [])] }); });
  // capture, so a press is seen wherever it lands, even where a listener stops it
  document.addEventListener('mousedown', () => { pressed = true; }, true);
  document.addEventListener('mouseup', () => { pressed = false; if (held) setTimeout(() => { if (held) renderExplorer(); }); }, true);
  subscribe(EV.render, renderExplorer);
  subscribe(EV.jobsChange, ({ changed }) => { if (changed) renderExplorer(); });
}
