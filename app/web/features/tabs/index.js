// The tab strip: open (EV.openTab), activate, close, and the "+" menu, which also clones a plot
// tab. The open tabs are kept in S.tabs.
import { $, el, toast } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { openMenu, mi } from '../../shared/menu.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, tabsNow, kindOf, idOf, activity, allUploads, fcsUploads, flowRuns, flowJobs } from '../../shared/store.js';
import { viewFor } from '../../shared/views.js';

const render = () => emit(EV.render);
// The kinds of tab that show one run; a plot's clone keys too, since idOf drops the ~n.
const RUN_TABS = new Set(['plot', 'compare', 'cluster', 'files', 'record']);

function label(key) {
  const v = viewFor(kindOf(key));
  return v ? v.title(key) : { name: key, icon: 'files' };
}
function renderTabs() {
  const T = tabsNow(), bar = $('#tabs');
  bar.replaceChildren();
  for (const key of T.open) {
    const { name, hint, icon, cls } = label(key);
    bar.append(el('div', {
      class: 'tab', role: 'tab', tabindex: '0', 'aria-selected': String(key === T.active), title: hint ? `${name} · ${hint}` : name,
      onclick: () => activate(key),
      onmousedown: e => { if (e.button === 1) e.preventDefault(); },
      onauxclick: e => { if (e.button === 1) { e.preventDefault(); closeTab(key); } },
      // v3 review F4: Enter on the close button must not re-activate the tab it is closing.
      onkeydown: e => { if (e.target !== e.currentTarget) return; if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(key); } },
    },
      el('span', { class: 'k-' + (cls || icon), html: svg(icon) }),
      el('span', { text: name }),
      hint ? el('span', { class: 'hint', text: hint }) : null,
      el('button', { type: 'button', class: 'x', 'aria-label': `Close ${name}${hint ? ' ' + hint : ''}`, html: svg('close'), onclick: e => { e.stopPropagation(); closeTab(key); } })));
  }
  const act = bar.querySelector('[aria-selected="true"]');
  if (act) act.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

// True when key names an upload, run or job the workspace holds but the page does not list: a CSV
// upload, or a general run or job, of a workspace made before the app was flow only. A key whose
// item is not in the workspace is not one; it opens, and its view says the item is missing.
function unlisted(key) {
  const kind = kindOf(key), id = idOf(key), has = list => list.some(x => x.id === id);
  if (kind === 'upload') return has(allUploads()) && !has(fcsUploads());
  if (RUN_TABS.has(kind)) return has(S.ws.runs) && !has(flowRuns());
  if (kind === 'job') return has(S.ws.jobs) && !has(flowJobs());
  return false;
}

// EV.openTab: opens key and shows it. background: only adds the tab to the strip, and the sender
// redraws. Every tab opens here, so a key for an item the page does not list stops here, whoever
// sent it.
function openTab({ key, background = false }) {
  if (unlisted(key)) {
    const msg = `${idOf(key)} is from General mode, which this app no longer has.`;
    toast(msg, true); activity(`Open ${key}: ${msg}`);
    return;
  }
  const T = tabsNow();
  if (!T.open.includes(key)) T.open.push(key);
  if (background) return;
  T.active = key;
  render();
}
function activate(key) { tabsNow().active = key; render(); }
function closeTab(key) {
  const T = tabsNow(), i = T.open.indexOf(key);
  if (i < 0) return;
  T.open.splice(i, 1);
  if (T.active === key) T.active = T.open[Math.min(i, T.open.length - 1)] || null;
  if (key.includes('~')) delete S.view[key];
  render();
}
// A clone tab of a plot: '<key>~n', own view state, shared payload.
function newPlotTab(rid) {
  const base = `plot:${rid}`, isOpen = k => tabsNow().open.includes(k);
  let key = base, n = 1;
  while (isOpen(key)) key = `${base}~${++n}`;
  delete S.view[key];
  emit(EV.openTab, { key });
  activity(`New plot tab for ${rid}${n > 1 ? ` (${n})` : ''}`);
}

function buildNewTabMenu(m) {
  const runs = flowRuns().filter(r => r.status === 'done');
  const open = key => () => emit(EV.openTab, { key });
  m.append(el('h5', { text: 'New tab' }),
    ...runs.map(r => mi('plot', `New plot: ${r.title}`, { hint: r.id, run: () => newPlotTab(r.id) })),
    ...runs.map(r => mi('compare', `Compare samples: ${r.id}`, { run: open(`compare:${r.id}`) })),
    // A run's box plots open on the cluster they showed last, or its first.
    ...runs.map(r => mi('boxes', `Box plots: ${r.id}`, { run: open(`cluster:${r.id}`) })),
    el('hr'), mi('upload', 'Upload files…', { hint: 'FCS', run: () => emit(EV.filesPick) }),
    mi('start', 'Start', { run: open('start') }), mi('local', 'Run it locally', { run: open('local') }));
}

export function mount() {
  $('#tab-add').innerHTML = svg('plus');
  $('#tab-add').addEventListener('click', e => openMenu(e.currentTarget, buildNewTabMenu));
  subscribe(EV.openTab, openTab);
  subscribe(EV.render, renderTabs);
}
