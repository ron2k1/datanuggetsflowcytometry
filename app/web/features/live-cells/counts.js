// The counts under the histograms. Before any line: each file's kept cells, from the record.
// With lines: POST .../counts COUNTS_QUIET_MS after the last change, each request numbered so an
// answer older than the newest is dropped, and a table of the payload's exact ints.
import { el, fill } from '../../shared/dom.js';
import { fmtInt, fmtPct } from '../../shared/format.js';
import { COUNTS_QUIET_MS } from '../../shared/config.js';
import { api } from '../../shared/api/index.js';

export const errText = e => (e.param ? `${e.param}: ${e.message}` : e.message);

/** A fresh counts state: nothing shown, nothing pending, and any answer in flight dropped. */
export function resetCounts(s) {
  const c = s.counts;
  if (c) { clearTimeout(c.timer); s.counts = { seq: c.seq + 1, shown: null, err: null, pending: false, timer: 0 }; }
  else s.counts = { seq: 0, shown: null, err: null, pending: false, timer: 0 };
}

/**
 * Counts the filters after a quiet spell; an empty list clears the counts instead.
 * @param {object} s  the step's state (s.lid, s.counts, s.view)
 * @param {string} gid
 * @param {import('../../shared/api/client.js').Filter[]} filters
 */
export function scheduleCounts(s, gid, filters) {
  const c = s.counts;
  c.seq += 1; clearTimeout(c.timer); c.timer = 0; c.err = null;
  if (!filters.length) { c.shown = null; c.pending = false; return; }
  const seq = c.seq, lid = s.lid;
  c.pending = true;
  c.timer = setTimeout(() => {
    c.timer = 0;
    api.livecellsCounts(gid, lid, filters).then(r => { if (seq === c.seq) c.shown = r; },
      e => { if (seq === c.seq) c.err = errText(e); })
      .finally(() => { if (seq !== c.seq) return; c.pending = false; if (s.view) s.view.counts(); });
  }, COUNTS_QUIET_MS);
}

const pct = (part, whole) => (whole ? fmtPct((100 * part) / whole) : '–');
const num = v => el('td', { class: 'num', text: fmtInt(v) });

/** The counts section; update() redraws it from the state. */
export function countsView(s) {
  const node = el('section', { class: 'lc-counts', 'aria-live': 'polite' });
  function update() {
    const h = s.record && s.record.histograms;
    if (!h) { fill(node); return; }
    const c = s.counts, r = c.shown;
    node.classList.toggle('pending', c.pending);
    const status = c.err ? el('div', { class: 'note err', text: c.err }) : c.pending ? el('div', { class: 'note', text: 'Counting…' }) : null;
    if (!r) {
      fill(node, el('h3', { text: 'Kept cells' }),
        el('div', { class: 'tbl-wrap' }, el('table', { class: 'tbl' },
          el('thead', {}, el('tr', {}, el('th', { text: 'File' }), el('th', { class: 'num', text: 'Events' }), el('th', { class: 'num', text: 'Kept' }))),
          el('tbody', {}, ...h.files.map(f => el('tr', {}, el('td', { text: `F${f.number} ${f.name}` }), num(f.events), num(f.kept))),
            el('tr', { class: 'lc-total' }, el('td', { text: 'All files' }), el('td'), num(h.kept))))),
        status || el('div', { class: 'note', text: 'These are the cells your populations keep. Place a line on a histogram to count the cells that pass it.' }));
      return;
    }
    const left = r.files.some(f => f.left_out);
    fill(node, el('h3', { text: 'Cells that pass the lines' }),
      el('div', { class: 'lc-echo' }, el('span', { class: 'muted', text: 'Counted with ' }), r.row_filters.join(' and ')),
      el('div', { class: 'tbl-wrap' }, el('table', { class: 'tbl' },
        el('thead', {}, el('tr', {}, el('th', { text: 'File' }), el('th', { class: 'num', text: 'Kept' }), el('th', { class: 'num', text: 'Passing' }), el('th', { class: 'num', text: '% of kept' }))),
        el('tbody', {}, ...r.files.map(f => el('tr', {},
          el('td', {}, `F${f.number} ${f.name}`, f.left_out ? el('span', { class: 'lc-left', text: 'left out' }) : null),
          num(f.kept), num(f.passed), el('td', { class: 'num', text: pct(f.passed, f.kept) }))),
        el('tr', { class: 'lc-total' }, el('td', { text: 'All files' }), num(r.kept), num(r.passed), el('td', { class: 'num', text: pct(r.passed, r.kept) }))))),
      status,
      left ? el('div', { class: 'note warn', text: 'A file marked left out keeps too few cells after the lines, so the clustering leaves it out.' }) : null);
  }
  update();
  return { node, update };
}
