// One table of points for the plot, from the plot payload (nuggets) or the cells payload
// (sampled events). Dimensions are keyed: 'v3' = variable 3, 'p0' = PC1, 't0' = t-SNE 1 of the
// 2-D fit, 'u0' = t-SNE 1 of the 3-D fit (a fit of its own, not the 2-D one plus an axis).
// Every value is exactly a payload number. A run's centers are in its Transform stage's units:
// the Scale stage is recorded as "scale" and the tables undo it, so the plot names those units
// (shared/cofactor.js plotUnits).

export function makeModel(P, cells, src) {
  const useCells = src === 'cells' && !!cells;
  const n = useCells ? cells.n : P.nuggets.n;
  const pca = useCells ? cells.pca : P.pca ? P.pca.scores : null;
  const nPC = P.pca && pca ? P.pca.variance.length : 0;
  const tsne = !useCells && P.tsne ? P.tsne.d2 : null;
  const tsne3 = tsne && P.tsne.d3 ? P.tsne.d3 : null;
  const rows = useCells ? cells.values : P.nuggets.centers;
  const colors = new Map(P.clusters.map(c => [c.cluster, c.color]));
  const cache = new Map();

  // figure.js and view.js pass the tab's st.units, and the Back stack keys a figure on it
  // (view.js figId); point.js passes none. A run's values come in one set of units, so neither
  // function reads it.
  function column(key, units) {
    let out = cache.get(key);
    if (out) return out;
    const k = +key.slice(1);
    out = new Float64Array(n);
    if (key[0] === 'v') for (let i = 0; i < n; i++) out[i] = rows[i][k];
    else if (key[0] === 'p') for (let i = 0; i < n; i++) out[i] = pca[i][k];
    else if (key[0] === 'u') for (let i = 0; i < n; i++) out[i] = tsne3[i][k];
    else for (let i = 0; i < n; i++) out[i] = tsne[i][k];
    cache.set(key, out);
    return out;
  }
  function label(key, units, short = false) {
    const k = +key.slice(1);
    if (key[0] === 'p') return short ? `PC${k + 1}` : `PC${k + 1} (${(P.pca.variance[k] * 100).toFixed(1)}%)`;
    if (key[0] === 't' || key[0] === 'u') return `t-SNE ${k + 1}`;
    return short ? P.short_columns[k] : P.columns[k];
  }
  const has = key => {
    const k = +key.slice(1);
    if (key[0] === 'v') return k < P.columns.length;
    if (key[0] === 'p') return k < nPC;
    if (key[0] === 'u') return !!tsne3 && k < 3;
    return !!tsne && k < 2;
  };
  const counts = new Map();
  const cl = useCells ? cells.cluster : P.nuggets.cluster;
  for (const c of cl) counts.set(c, (counts.get(c) || 0) + 1);

  return {
    src: useCells ? 'cells' : 'nuggets', n, nPC, tsne, colors, counts,
    cluster: cl,
    file: useCells ? cells.file : P.nuggets.file,
    weight: useCells ? null : P.nuggets.weight,
    index: useCells ? cells.row0 : P.nuggets.nugget0,
    // Each point's nugget, numbered within its file from 0: a cell's own, a nugget itself.
    nugget: useCells ? cells.nugget0 : P.nuggets.nugget0,
    vars: P.columns.map((_, k) => 'v' + k),
    pcs: Array.from({ length: nPC }, (_, k) => 'p' + k),
    tsneKeys: tsne ? ['t0', 't1'] : [],
    tsne3Keys: tsne3 ? ['u0', 'u1', 'u2'] : [],
    column, label, has,
  };
}

// st.axes holds this many keys, x, y and z: the 2D view draws the first two and keeps z for 3D.
export const SLOTS = 3;

// Default axes for a preset: the first three PCs, the first variables, or the view's t-SNE (the
// 2-D fit in the 2D view, the 3-D fit in the others) then PCs.
export function presetAxes(M, preset, view) {
  const fill = list => {
    const out = list.filter(k => M.has(k));
    for (const k of [...M.pcs, ...M.vars]) if (out.length < SLOTS && !out.includes(k)) out.push(k);
    return out.slice(0, SLOTS);
  };
  if (preset === 'vars') return fill(M.vars.slice(0, SLOTS));
  if (preset === 'tsne') return fill([...(view === '2d' ? M.tsneKeys : M.tsne3Keys), ...M.pcs]);
  return fill(M.pcs.length ? M.pcs.slice(0, SLOTS) : M.vars.slice(0, SLOTS));
}

// The preset an axis list belongs to, or 'custom' when the axes the view draws mix kinds.
export function presetOf(axes, view) {
  const first = axes.slice(0, view === '2d' ? 2 : SLOTS);
  if (first.every(k => k[0] === 't' || k[0] === 'u')) return 'tsne';
  const kinds = new Set(first.map(k => k[0]));
  if (kinds.size !== 1) return 'custom';
  return { v: 'vars', p: 'pca' }[[...kinds][0]];
}

