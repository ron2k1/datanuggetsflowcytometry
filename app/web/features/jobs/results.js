// What a finished job made, drawn on its job tab: a gate's populations per file with its figures,
// or a run's clusters with the way to more of them.
import { el } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtInt, fmtNum, fmtPct, plural } from '../../shared/format.js';
import { kMax } from '../../shared/store.js';

const FIGURES = { local_maxima: 'Local maxima', gates: 'Populations' };

// One file of a gate: its name and events, the peak count, and a row per population with the
// population's colour on its dot and on its share bar.
function fileCard(f, settings) {
  const fsc = settings.fsc || 'x', ssc = settings.ssc || 'y';
  const rows = f.populations.map(p => el('tr', {},
    el('td', {}, el('span', { class: 'sw', style: `background:${p.color}` }), `Pop ${p.pop}`),
    el('td', { class: 'num strong', text: fmtInt(p.events) }),
    el('td', {}, el('div', { class: 'share' },
      el('div', { class: 'share-bar' }, el('i', { style: `width:${Math.min(100, p.percent).toFixed(1)}%;background:${p.color}` })),
      el('b', { text: fmtPct(p.percent) }))),
    el('td', { class: 'num', text: fmtNum(p.median_fsc) }),
    el('td', { class: 'num', text: fmtNum(p.median_ssc) })));
  return el('div', { class: 'card job-file' },
    el('div', { class: 'job-file-head' },
      el('span', { class: 'fname', text: f.name }),
      el('span', { class: 'muted', text: `${fmtInt(f.n_events)} events` }),
      el('span', { class: 'chip', text: `${plural(f.local_maxima, 'local maximum', 'local maxima')}, ${plural(f.populations.length, 'population')} kept` })),
    el('div', { class: 'tbl-wrap flat' }, el('table', { class: 'tbl' },
      el('thead', {}, el('tr', {}, el('th', { text: 'Population' }), el('th', { class: 'num', text: 'Events' }), el('th', { text: 'Share of the file' }),
        el('th', { class: 'num', text: `Median ${fsc}` }), el('th', { class: 'num', text: `Median ${ssc}` }))),
      el('tbody', {}, ...rows))));
}

/**
 * A finished gate: the populations of each file, then its figures.
 * @param {object} g  GET /flow/gates/{gid}
 * @param {(key: string) => void} open  opens a tab
 */
export function gateResults(g, open) {
  const files = g.files || [];
  const pops = files.reduce((n, f) => n + f.populations.length, 0);
  const figs = Object.entries(g.figures || {}).map(([name, url]) => el('button', { type: 'button', class: 'job-fig', title: `Open ${name}.png`, onclick: () => open(`figure:${g.id}:${name}`) },
    el('img', { src: url, alt: `${FIGURES[name] || name} figure of gate ${g.id}`, loading: 'lazy' }),
    el('span', {}, el('b', { text: FIGURES[name] || name }), el('span', { class: 'muted', text: ` ${name}.png` }))));
  return el('div', {},
    el('h3', { text: `${plural(pops, 'population')} found in ${plural(files.length, 'file')}` }),
    files.length === 1 ? el('div', { class: 'note', style: 'margin:-2px 0 10px' }, 'One file in this gate. To compare samples, gate several together: in an FCS upload tab, tick them under ',
      el('b', { text: 'Files to gate together' }), '.') : null,
    el('div', { class: 'job-files' }, ...files.map(f => fileCard(f, g.settings || {}))),
    figs.length ? el('h3', { text: 'Figures' }) : null,
    figs.length ? el('div', { class: 'job-figs' }, ...figs) : null);
}

/**
 * A finished run: k front and centre, then the comparison of samples and how to cluster again
 * with another k from its gate (r.source).
 * @param {object} r  the run from GET /workspace
 * @param {(key: string) => void} open
 */
export function runResults(r, open) {
  const gid = r.source;
  return el('div', {},
    el('h3', { text: 'Result' }),
    el('div', { class: 'card pad job-run' },
      el('div', { class: 'job-k' }, el('b', { text: String(r.k) }), el('span', { text: r.k === 1 ? 'cluster' : 'clusters' })),
      el('div', { class: 'job-run-text' },
        el('div', { class: 'fname', text: r.title }),
        el('div', { class: 'note', style: 'margin-top:4px' }, `For more or fewer clusters, cluster again and set `, el('b', { text: 'Clusters (k)' }),
          ` in Cluster settings, anywhere from 2 to ${kMax()}.`),
        gid ? el('div', { class: 'links', style: 'margin-top:8px' },
          el('button', { type: 'button', class: 'btn sm', html: svg('compare') + '<span>Compare samples by cluster</span>', onclick: () => open(`compare:${r.id}`) }),
          el('button', { type: 'button', class: 'btn sm', html: svg('picker') + '<span>Cluster again with another k</span>', onclick: () => open(`gate:${gid}`) })) : null)));
}
