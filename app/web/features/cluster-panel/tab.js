// The box plots tab, 'cluster:<rid>' (docs/app/cluster-panel.md): one cluster of a run at the
// page's width, drawn by panel.js, with a cluster picker in its head. S.view[key] keeps the
// cluster and the marker split by group, so closing the tab and opening it again from the "+"
// menu comes back to them. The plot opens it on a cluster through EV.boxPlots.
import { el, docHead } from '../../shared/dom.js';
import { plotUnits } from '../../shared/cofactor.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, idOf, activity, getPlot, getCells, getManifest } from '../../shared/store.js';
import { registerView } from '../../shared/views.js';
import { renderPanel } from './panel.js';

const keyOf = rid => `cluster:${rid}`;
const stateOf = key => S.view[key] || (S.view[key] = { cluster: null, boxMarker: 0 });

// EV.boxPlots: open the run's box plots on cluster c, or show them if the tab is open. The marker
// split by group stays, so one marker can be read cluster after cluster.
function openOn({ rid, cluster: c }) {
  const key = keyOf(rid), st = stateOf(key);
  st.cluster = c;
  emit(EV.openTab, { key });
  activity(`${rid}: box plots of cluster ${c}`);
}

function render(body, key) {
  const rid = idOf(key), st = stateOf(key);
  // The page sits in a size container: its two columns follow the editor's width, which the
  // explorer and the window share, not the window's.
  const page = el('div', { class: 'cp-page' });
  body.append(el('div', { class: 'cp-wrap' }, page));
  page.append(el('div', { class: 'doc muted', text: 'Loading the box plots…' }));
  let P = null, cells = null, cellsWhy = 'loading', off = null, dead = false;
  // A channel's sampled values, read once from the cells payload's rows.
  const cols = new Map();
  const column = j => {
    if (!cols.has(j)) cols.set(j, Float64Array.from(cells.values, r => r[j]));
    return cols.get(j);
  };

  function draw(focusPick = false) {
    if (dead) return;
    if (off) { off(); off = null; }
    const ks = P.clusters.map(x => x.cluster), colors = new Map(P.clusters.map(x => [x.cluster, x.color]));
    if (!ks.includes(st.cluster)) st.cluster = ks[0];
    const pick = el('select', { 'aria-label': 'Cluster', onchange: e => {
      st.cluster = +e.target.value;
      activity(`${rid}: box plots of cluster ${st.cluster}`);
      draw(true);
    } }, ...ks.map(c => el('option', { value: String(c), selected: c === st.cluster, text: `Cluster ${c}` })));
    const show = el('button', { type: 'button', class: 'btn sm', title: `Open the plot of ${rid} with cluster ${st.cluster} selected`,
      text: 'Show in the plot', onclick: () => emit(EV.clusterFocus, { rid, cluster: st.cluster }) });
    off = renderPanel(page, {
      P, st, cluster: st.cluster, color: c => colors.get(c), cells, cellsWhy, column,
      label: (j, short) => (short ? P.short_columns[j] : P.columns[j]),
      units: plotUnits(P, P.columns.map((_, j) => j)),
      tools: [el('div', { class: 'cp-tools' }, pick, show)],
    }) || null;
    if (focusPick) pick.focus({ preventScroll: true });
  }

  Promise.all([getPlot(rid), getManifest(rid)]).then(([p, man]) => {
    if (dead) return;
    P = p;
    // A run made with cells_per_file = 0 sampled none: the counts still draw, the boxes can't.
    const none = !!(man.settings && man.settings.cells_per_file === 0);
    cellsWhy = none ? 'none' : 'loading';
    draw();
    if (none) return;
    getCells(rid).then(c => { cells = c; cellsWhy = null; draw(); }, e => { cellsWhy = e.message; draw(); });
  }, e => {
    if (!dead) body.replaceChildren(el('div', { class: 'doc' }, docHead(`Box plots · ${rid}`, null), el('div', { class: 'callout', text: e.message })));
  });

  // The charts' colours come from the theme: a switch redraws them.
  const offTheme = subscribe(EV.themeChange, () => { if (P) draw(); });
  return () => { dead = true; offTheme(); if (off) off(); };
}

export function registerBoxPlots() {
  registerView('cluster', {
    title: key => ({ name: `Box plots ${idOf(key)}`, icon: 'boxes' }),
    crumbs: key => ['Runs', idOf(key), 'Box plots'],
    render,
  });
  subscribe(EV.boxPlots, openOn);
}
