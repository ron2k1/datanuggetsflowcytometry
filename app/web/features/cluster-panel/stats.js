// The cluster panel's numbers (docs/app/cluster-panel.md), from the plot and cells payloads: a
// cluster's cells per sample group or file, exact, since a nugget's weight is its cell count; and
// its boxes from the sampled cells, each standing for its file's kept / sampled cells, because
// cells.csv takes the same number from every file whatever its size.
import { BOX_MIN_CELLS } from '../../shared/config.js';

// Quantile q of xs, sorted ascending, with weights ws. Value i sits at its weight's midpoint,
// (C_i - w_i / 2) / W; q interpolates between the two values around it and takes the first or
// last value outside them. Equal weights give the Hazen rule, (i - 0.5) / n.
export function quantile(xs, ws, q) {
  const n = xs.length;
  let W = 0;
  for (let i = 0; i < n; i++) W += ws[i];
  let cum = 0, before = 0;
  for (let i = 0; i < n; i++) {
    const p = (cum + ws[i] / 2) / W;
    if (q <= p) return i === 0 ? xs[0] : xs[i - 1] + ((xs[i] - xs[i - 1]) * (q - before)) / (p - before);
    cum += ws[i];
    before = p;
  }
  return xs[n - 1];
}

// The box of values xs with weights ws: weighted quartiles, and whiskers at the most extreme
// values within 1.5 IQR of the box (Tukey). null below BOX_MIN_CELLS values.
export function boxStats(xs, ws) {
  const n = xs.length;
  if (n < BOX_MIN_CELLS) return null;
  const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => xs[a] - xs[b]);
  const x = order.map(i => xs[i]), w = order.map(i => ws[i]);
  const [q1, median, q3] = [0.25, 0.5, 0.75].map(q => quantile(x, w, q));
  const iqr = q3 - q1, lf = q1 - 1.5 * iqr, uf = q3 + 1.5 * iqr;
  // q1 and q3 lie within the values, so some value is inside each fence. An interpolated q1 can
  // sit in a gap with no value between it and its fence; the whisker then stays at the box.
  const lo = Math.min(x.find(v => v >= lf), q1), hi = Math.max(x.findLast(v => v <= uf), q3);
  return { n, q1, median, q3, lo, hi };
}

// How the panel splits a flow run: its sample groups in the payload's order (the reference group,
// the first kept file's, first), or each file when it has none. None without files, which no
// longer happens: only a general run's plot had none, and the server now answers 409 for it.
function splits(P) {
  if (!P.files) return [];
  if (P.groups && P.groups.length) {
    return P.groups.map((g, gi) => ({ key: `g:${g}`, label: g, gi, files: new Set(P.files.filter(f => f.group === g).map(f => f.number)) }));
  }
  return P.files.map(f => ({ key: `f:${f.number}`, label: `F${f.number} ${f.name}`, file: f.number, files: new Set([f.number]) }));
}
const partOf = s => ({ key: s.key, label: s.label, gi: s.gi, file: s.file });

// Cluster c's cells (the sum of its nuggets' weights), the run's, its nugget count, and per group
// or file its cells (count) out of that part's kept cells (of).
export function counts(P, c) {
  const { weight, cluster, file } = P.nuggets;
  const inC = new Map(), all = new Map();
  let cells = 0, total = 0, nuggets = 0;
  for (let i = 0; i < weight.length; i++) {
    const w = weight[i];
    total += w;
    if (file) all.set(file[i], (all.get(file[i]) || 0) + w);
    if (cluster[i] !== c) continue;
    cells += w;
    nuggets++;
    if (file) inC.set(file[i], (inC.get(file[i]) || 0) + w);
  }
  const parts = splits(P).map(s => {
    let count = 0, of = 0;
    for (const n of s.files) { count += inC.get(n) || 0; of += all.get(n) || 0; }
    return { ...partOf(s), count, of };
  });
  return { cells, total, nuggets, parts };
}

// What each sampled cell stands for: its file's kept cells (the sum of the file's nugget weights)
// over the file's cells in the payload. 1 without file numbers, which no longer happens: only a
// general run's payloads lacked them, and the server now answers 409 for those.
export function cellWeights(P, cells) {
  const out = new Float64Array(cells.n).fill(1);
  if (!cells.file || !P.nuggets.file) return out;
  const kept = new Map(), sampled = new Map();
  P.nuggets.file.forEach((f, i) => kept.set(f, (kept.get(f) || 0) + P.nuggets.weight[i]));
  for (const f of cells.file) sampled.set(f, (sampled.get(f) || 0) + 1);
  for (let i = 0; i < cells.n; i++) {
    const f = cells.file[i];
    out[i] = (kept.get(f) || sampled.get(f)) / sampled.get(f);
  }
  return out;
}

// Cluster c's boxes of one column of the sampled cells (col[i] is cell i's value), weighted by w:
// all its cells, then each group or file, with the cells each was drawn from (n); and the rest of
// the run, every other cluster's cells with all groups together, to hold it against.
export function boxes(P, cells, col, c, w) {
  const idx = [], others = [];
  for (let i = 0; i < cells.n; i++) (cells.cluster[i] === c ? idx : others).push(i);
  const box = (from, keep) => {
    const xs = [], ws = [];
    for (const i of from) if (keep(i)) { xs.push(col[i]); ws.push(w[i]); }
    return { n: xs.length, stats: boxStats(xs, ws) };
  };
  const all = box(idx, () => true), rest = box(others, () => true);
  const parts = splits(P).map(s => ({ ...partOf(s), ...box(idx, i => s.files.has(cells.file[i])) }));
  return { all: all.stats, n: all.n, rest: rest.stats, restN: rest.n, parts };
}

// Where a cluster's box sits against the rest's: 'high' with its median above the rest's upper
// quartile, 'low' below its lower one, else 'mid'. null without both boxes.
export function level(box, rest) {
  if (!box || !rest) return null;
  return box.median > rest.q3 ? 'high' : box.median < rest.q1 ? 'low' : 'mid';
}
