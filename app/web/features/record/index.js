// A run's record: the settings sent to the server and run.json, each as a collapsible JSON tree.
import { el, docHead, loadDoc } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { EV } from '../../shared/events.js';
import { emit, idOf, getManifest } from '../../shared/store.js';
import { registerView } from '../../shared/views.js';
import { plural } from '../../shared/format.js';
import { runTransform, cofactorTag, cofactorWhy, cofactorRows } from '../../shared/cofactor.js';
import { clusteringRows } from '../../shared/clustering.js';

const openTab = key => emit(EV.openTab, { key });

// A flow run's Transform and Scale stages in words, from run.json: the cofactor used and how it
// was chosen, "arcsinh(x / c), c per channel (150–338), cofactor auto (each channel: ...)",
// "arcsinh(x / 150), cofactor auto (channels up to 262,144)" for an older auto run, or "...,
// cofactor set". Under per-channel auto a closed table lists each channel's cofactor and what it
// was picked from. A run.json written before the stages were recorded has neither key: its
// transform follows settings.cofactor, read as set, and it ran unscaled; one written before
// cofactor_from reads as set too.
function flowStages(rec) {
  const t = runTransform(rec) || { name: 'none' };
  const s = rec.standardize;
  const scale = s && typeof s === 'object'
    ? `every channel to mean 0 and SD 1, pooled over ${plural(s.cells, 'cell')} of the clustered files`
    : `none${'standardize' in rec ? '' : ' (this run.json predates the Scale stage)'}`;
  const rows = cofactorRows(t, rec.labels || rec.channels || []);
  return [el('dl', { class: 'rec-stages card pad' },
    el('dt', { text: 'Transform' }), el('dd', { text: t.name === 'arcsinh' ? `${cofactorTag(t)}, cofactor ${cofactorWhy(t)}` : 'none (linear)' }),
    el('dt', { text: 'Scale' }), el('dd', { text: scale })),
  rows ? el('details', { class: 'more' }, el('summary', { text: `Each channel’s cofactor (${rows.length})` }),
    el('div', { class: 'tbl-wrap' }, el('table', { class: 'tbl' },
      el('thead', {}, el('tr', {}, ...['Channel', 'Cofactor', 'Cells below 0', 'SD of those cells'].map((h, i) => el('th', { class: i ? 'num' : '', text: h })))),
      el('tbody', {}, ...rows.map(r => el('tr', {}, el('td', { text: r.channel }),
        el('td', { class: 'num', text: r.cofactor }), el('td', { class: 'num', text: r.below }), el('td', { class: 'num', text: r.sd }))))))) : null];
}

// A flow run's Cluster stage in words, from run.json's clustering block (shared/clustering.js):
// the clustering and its k, the nugget centers, the nuggets clustered and dropped, the total
// WWCSS, and the create.DN and clustering calls that rebuild the run in R, set as code.
function flowClustering(rec) {
  return el('dl', { class: 'rec-stages rec-clustering card pad' },
    ...clusteringRows(rec).flatMap(([t, d, code]) => [el('dt', { text: t }), el('dd', { class: code ? 'code' : null, text: d })]));
}

// A collapsible JSON tree; objects and arrays open to depth 1.
function node(k, v, depth) {
  const keyEl = k == null ? null : el('span', { class: 'k', text: JSON.stringify(String(k)) + ': ' });
  if (v !== null && typeof v === 'object') {
    const entries = Array.isArray(v) ? v.map((x, i) => [i, x]) : Object.entries(v);
    const open = Array.isArray(v) ? '[' : '{', close = Array.isArray(v) ? ']' : '}';
    if (!entries.length) return el('div', { class: 'leaf' }, keyEl, el('span', { class: 'c', text: open + close }));
    const d = el('details', { open: depth < 1 }, el('summary', {}, keyEl, el('span', { class: 'c', text: `${open} ${entries.length} ${Array.isArray(v) ? 'items' : 'keys'} ${close}` })));
    let built = false;
    const build = () => { if (built) return; built = true; d.append(el('div', { class: 'kids' }, ...entries.map(([kk, vv]) => node(Array.isArray(v) ? null : kk, vv, depth + 1)))); };
    if (d.open) build(); else d.addEventListener('toggle', build);
    return d;
  }
  const cls = typeof v === 'string' ? 's' : typeof v === 'number' ? 'n' : typeof v === 'boolean' ? 'b' : 'c';
  return el('div', { class: 'leaf' }, keyEl, el('span', { class: cls, text: JSON.stringify(v) }));
}

function renderRecord(body, key) {
  const rid = idOf(key);
  return loadDoc(body, getManifest(rid), m => {
    body.append(el('div', { class: 'doc' },
      docHead(`Run record of ${rid}`, 'run.json as datanuggets wrote it: inputs, settings, versions. With the same data and settings the run repeats exactly.',
        el('button', { type: 'button', class: 'btn', html: svg('files') + '<span>Files</span>', onclick: () => openTab(`files:${rid}`) })),
      m.record && m.record.settings ? [el('h3', { text: 'Stages before clustering' }), ...flowStages(m.record),
        el('h3', { text: 'Clustering' }), flowClustering(m.record)] : null,
      el('h3', { text: 'Settings sent to the server' }), el('div', { class: 'card pad json' }, node(null, m.settings, 0)),
      el('h3', { text: 'run.json' }), el('div', { class: 'card pad json' }, node(null, m.record, 0))));
  });
}

export function mount() {
  registerView('record', {
    title: key => ({ name: 'run.json', hint: idOf(key), icon: 'json' }),
    crumbs: key => ['Runs', idOf(key), 'Run record'],
    render: renderRecord,
  });
}
