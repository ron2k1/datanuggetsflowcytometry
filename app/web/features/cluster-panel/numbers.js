// The cluster panel's numbers as text (docs/app/cluster-panel.md): the label beside each box, its
// hover label, the invisible points along it that carry that hover, and the rows of the tables
// under the charts. A box is stats.js's { q1, median, q3, lo, hi }. No DOM and no Plotly here, so
// app/tests runs it in Node.
import { BOX_HOVER_POINTS } from '../../shared/config.js';
import { fmtInt, fmtNum } from '../../shared/format.js';

const NF = new Intl.NumberFormat('en-US');
const NONE = '–';
// Three significant digits, for the narrow column beside the boxes; whole numbers from 100 up,
// so a large value never turns into an exponent.
const fmt3 = v => (Math.abs(v) >= 100 ? NF.format(Math.round(v)) : String(Number(v.toPrecision(3))));
const span = (a, b) => `${fmtNum(a)} to ${fmtNum(b)}`;
// Plotly reads hover text as HTML: a marker named "CD3 <BV421>" keeps its brackets.
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// Beside a box: its median, then its quartiles in brackets.
export const boxLabel = s => `${fmt3(s.median)} [${fmt3(s.q1)}, ${fmt3(s.q3)}]`;

// Over a box: its name, its five numbers to four digits, and the sampled cells it was drawn from.
export const boxHover = (name, s, n) =>
  `<b>${esc(name)}</b><br>median ${fmtNum(s.median)}<br>quartiles ${span(s.q1, s.q3)}`
  + `<br>whiskers ${span(s.lo, s.hi)}<br>${fmtInt(n)} sampled cells`;

// Plotly gives a horizontal box's five numbers five labels piled over each other, so the boxes
// take no hover and these points do: BOX_HOVER_POINTS per box, evenly from whisker to whisker at
// the box's row y, each carrying the box's hover text. items: [{ y, s, hover }].
export function hoverPoints(items) {
  const x = [], y = [], text = [], k = BOX_HOVER_POINTS;
  for (const it of items) {
    for (let i = 0; i < k; i++) {
      x.push(it.s.lo + ((it.s.hi - it.s.lo) * i) / (k - 1));
      y.push(it.y);
      text.push(it.hover);
    }
  }
  return { x, y, text };
}

const middle = s => (s ? [fmtNum(s.median), span(s.q1, s.q3)] : [NONE, NONE]);

// The markers table: one row per marker, the cluster's box beside the rest's. labels[j] names
// marker j; B[j] is stats.js boxes() for it.
export const MARKER_HEAD = ['Marker', 'Cluster median', 'Cluster Q1 to Q3', 'Rest median', 'Rest Q1 to Q3'];
export const markerRows = (labels, B) => B.map((b, j) => [labels[j], ...middle(b.all), ...middle(b.rest)]);

// The one-marker table: the cluster, each group or file in it and the rest, with the sampled
// cells each box was drawn from. rows: [{ label, s, n }], s null where there are too few cells.
export const PART_HEAD = ['', 'Cells', 'Median', 'Q1 to Q3', 'Whiskers'];
export const partRows = rows => rows.map(r => [r.label, fmtInt(r.n), ...middle(r.s), r.s ? span(r.s.lo, r.s.hi) : NONE]);
