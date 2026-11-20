// The cluster legend: one row per cluster (up to k = 100) with its payload colour and count,
// a search box, select (stays bright; the others turn grey, fade or are hidden, per st.others),
// hide/show per row, isolate and show all, and a hover highlight. It edits st.sel / st.hidden /
// st.hover and calls back. It is the part of the plot inspector's slot 'plot.legend'.
import { el } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtInt } from '../../shared/format.js';
import { HOVER_DEBOUNCE_MS } from '../../shared/config.js';
import { registerSlot } from '../../shared/views.js';

// What a click on a row does, per st.others ('Other clusters' under Display).
const PICK = { grey: 'keep it bright and turn the rest grey', own: 'keep it bright and fade the rest', hide: 'keep it and hide the rest' };
// Each tab's live summary refresh, so a hover that lands after the legend was redrawn updates the new one.
const sums = new WeakMap();

// The clusters drawn, by the plot's rule: not hidden by their eye and, when the others are hidden,
// in the selection or under the pointer. Their point count is the header's.
function summary(M, st, all, what) {
  const keep = st.others === 'hide' ? new Set(st.sel) : null;
  if (keep && st.hover != null) keep.add(st.hover);
  const drawn = all.filter(c => !st.hidden.has(c) && (!keep || !keep.size || keep.has(c)));
  const pts = drawn.reduce((s, c) => s + (M.counts.get(c) || 0), 0);
  return `${drawn.length} of ${all.length} clusters shown · ${fmtInt(pts)} of ${fmtInt(M.n)} ${what}${st.sel.size ? ` · ${st.sel.size} selected` : ''}`;
}

function legend(M, st, onChange, onHover) {
  const all = [...M.colors.keys()].sort((a, b) => a - b);
  const q = (st.search || '').trim().toLowerCase();
  const match = c => !q || String(c) === q || `cluster ${c}`.startsWith(q) || String(c).startsWith(q.replace(/^cluster\s*/, ''));
  const shown = all.filter(match);
  const what = M.src === 'cells' ? 'cells' : 'nuggets';

  let timer = 0;
  const hover = c => { clearTimeout(timer); timer = setTimeout(() => { onHover(c); sums.get(st)(); }, HOVER_DEBOUNCE_MS); };
  const list = el('div', { class: 'legend', role: 'list', 'aria-label': 'Clusters', onmouseleave: () => hover(null) });
  for (const c of shown) {
    const off = st.hidden.has(c), sel = st.sel.has(c), n = M.counts.get(c) || 0;
    const name = el('button', { type: 'button', class: 'nm', 'aria-pressed': String(sel), title: `Cluster ${c}: ${fmtInt(n)} ${what}. ${sel ? 'Selected. Click to unselect it.' : `Click to ${PICK[st.others] || PICK.grey}.`}`,
      text: `Cluster ${c}`, onclick: () => { sel ? st.sel.delete(c) : st.sel.add(c); onChange(`Cluster ${c} ${sel ? 'unselected' : 'selected'}`); } });
    const eye = el('button', { type: 'button', class: 'eye', 'aria-label': `${off ? 'Show' : 'Hide'} cluster ${c}`, title: `${off ? 'Show' : 'Hide'} cluster ${c}`, 'aria-pressed': String(!off), html: svg(off ? 'eyeOff' : 'eye'),
      onclick: () => { off ? st.hidden.delete(c) : st.hidden.add(c); onChange(`Cluster ${c} ${off ? 'shown' : 'hidden'}`); } });
    list.append(el('div', { class: 'lg' + (off ? ' off' : '') + (sel ? ' is-sel' : ''), role: 'listitem', onmouseenter: () => hover(off ? null : c) },
      el('span', { class: 'sw', style: `background:${M.colors.get(c)}` }), name, el('span', { class: 'cnt', text: fmtInt(n) }), eye));
  }
  if (!shown.length) list.append(el('div', { class: 'note', style: 'margin:8px', text: `No cluster matches "${st.search}".` }));

  const search = el('input', { type: 'search', placeholder: `Find among ${all.length} clusters`, 'aria-label': 'Find a cluster by number', value: st.search || '',
    oninput: e => { st.search = e.target.value; onChange(null, true); } });
  const target = st.sel.size ? [...st.sel] : q ? shown : [];
  const acts = el('div', { class: 'legend-acts' },
    el('button', { type: 'button', class: 'btn', text: 'Show all', disabled: !st.hidden.size, onclick: () => { st.hidden.clear(); onChange('All clusters shown'); } }),
    el('button', { type: 'button', class: 'btn', text: st.sel.size ? `Isolate ${st.sel.size} selected` : q ? `Only ${shown.length} found` : 'Isolate',
      disabled: !target.length, title: 'Hide every other cluster',
      onclick: () => { const keep = new Set(target); st.hidden = new Set(all.filter(c => !keep.has(c))); onChange(`Isolated clusters ${[...keep].join(', ')}`); } }),
    el('button', { type: 'button', class: 'btn', text: 'Hide all', disabled: st.hidden.size === all.length, onclick: () => { st.hidden = new Set(all); onChange('All clusters hidden'); } }),
    el('button', { type: 'button', class: 'btn', text: 'Clear selection', disabled: !st.sel.size, onclick: () => { st.sel.clear(); onChange('Cluster selection cleared'); } }));
  const sum = el('div', { class: 'legend-sum', text: summary(M, st, all, what) });
  sums.set(st, () => { sum.textContent = summary(M, st, all, what); });
  return { tools: el('div', { class: 'legend-tools' }, search), acts, list, sum, focusSearch: () => search.focus() };
}

export function mount() { registerSlot('plot.legend', { render: legend }); }
