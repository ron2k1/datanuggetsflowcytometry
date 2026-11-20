// Marker sizes in px for the nuggets and cells views. MARKER's nugget sizes are for a run of up to
// MARKER.refNuggets nuggets; a run of n nuggets past that draws them sqrt(refNuggets / n) as
// large, so the dots cover about the same area instead of piling up, down to the view's floor.
// n is the model's row count, the whole run, so hiding or picking clusters never resizes a point.
// Cells keep their sizes: they draw a density cloud. The Point size factor (st.pointScale)
// multiplies every size, and in 2D and 3D the zoom factor (st.zoomGrow, from zoomGrow or
// grow3) multiplies the nuggets' after it. No DOM and no Plotly here, so app/tests runs it in Node.
import { MARKER, ZOOM_GROW, DEFAULT_CAMERA } from '../../shared/config.js';

// view: '2d', '3d' or 'pairs'.
const BASE = { '2d': MARKER.size2d, '3d': MARKER.size3d, pairs: MARKER.pairs };
const FLOOR = { '2d': MARKER.floor2d, '3d': MARKER.floor3d, pairs: MARKER.floor2d * MARKER.pairs / MARKER.size2d };
// Pairs takes the 2D weight sizes, shrunk by its marker's ratio to the 2D one.
const PAIRS_OF_2D = MARKER.pairs / MARKER.size2d;

// The factor on a view's nugget sizes for a run of n nuggets: 1 up to refNuggets, then
// sqrt(refNuggets / n), but never below what takes the view's default size to its floor.
export function crowdFactor(n, view) {
  const f = n > MARKER.refNuggets ? Math.sqrt(MARKER.refNuggets / n) : 1;
  return Math.max(f, FLOOR[view] / BASE[view]);
}

// How much a 2D view's nuggets grow at view now, zoomed from home (Fit's view); both are
// { xaxis: [a, b], yaxis: [a, b] } as history.js viewOf reads them. The smaller axis zoom keeps a
// view zoomed on one axis from growing its dots past the room the other gives them. 1 without
// either view, at Fit, and zoomed out past it.
export function zoomGrow(home, now) {
  if (!home || !now) return 1;
  let z = Infinity;
  for (const k of ['xaxis', 'yaxis']) {
    const a = home[k], b = now[k];
    if (!a || !b) return 1;
    const r = Math.abs(a[1] - a[0]) / Math.abs(b[1] - b[0]);
    if (!Number.isFinite(r) || r <= 0) return 1;
    z = Math.min(z, r);
  }
  return Math.min(ZOOM_GROW.max, Math.max(1, z ** ZOOM_GROW.power));
}

// How much a 3D view's nuggets grow, by 2D's rule on its zoom: the box's zoom (zoom3.js boxZoom,
// what the wheel changes) times the camera's, Fit's eye-to-center distance (DEFAULT_CAMERA) over
// cam's ({ eye, center, up }, as history.js stores st.camera). A turn keeps the distance and a pan
// moves the eye and the center together, so neither grows a dot. 1 at Fit and further out.
const reach = cam => Math.hypot(cam.eye.x - cam.center.x, cam.eye.y - cam.center.y, cam.eye.z - cam.center.z);
export function grow3(cam, boxZ = 1, home = DEFAULT_CAMERA) {
  const e = cam && cam.eye && cam.center ? reach(home) / reach(cam) : 1;
  if (e === Infinity) return ZOOM_GROW.max;
  const z = (Number.isFinite(e) && e > 0 ? e : 1) * boxZ;
  return Math.min(ZOOM_GROW.max, Math.max(1, z ** ZOOM_GROW.power));
}
// Pairs keeps its sizes: its subplots don't zoom with the view.
const grown = (st, view) => ((view === '2d' || view === '3d') && st.zoomGrow > 1 ? st.zoomGrow : 1);

function maxWeight(weight) {
  let wmax = 0;
  for (const w of weight) if (w > wmax) wmax = w;
  return wmax;
}

// The sizes nuggets of weights ws draw in view: lo + span x ln(1 + w) / ln(1 + wmax) before the
// run's factor. Weights are heavy-tailed, and the log keeps the common small ones apart where a
// square root packed them near lo (docs/app/cluster-panel.md). Pairs takes the 2D sizes before
// the 2D zoom: its subplots don't zoom with the 2D view.
function weightSizes(M, st, ws, view) {
  if (view === 'pairs') return weightSizes(M, { ...st, zoomGrow: 1 }, ws, '2d').map(s => s * PAIRS_OF_2D);
  const wmax = maxWeight(M.weight);
  const three = view === '3d', f = st.pointScale * crowdFactor(M.n, view) * grown(st, view);
  const lo = three ? MARKER.weightMin3d : MARKER.weightMin2d, sp = three ? MARKER.weightSpan3d : MARKER.weightSpan2d;
  return ws.map(w => f * (lo + sp * (Math.log1p(w) / (Math.log1p(wmax) || 1))));
}

// Sizes for the points idx of model M: one per point by weight (nuggets, when asked), else one
// size for all.
export function markerSizes(M, st, idx, view) {
  const p = st.pointScale;
  if (M.src === 'cells') return p * (view === '3d' ? MARKER.cells3d : MARKER.cells2d);
  if (st.sizeW && M.weight) return weightSizes(M, st, idx.map(i => M.weight[i]), view);
  return p * crowdFactor(M.n, view) * BASE[view] * grown(st, view);
}

// The inspector's size key: powers of ten up to half the largest weight, then the largest, each
// with the size a nugget of that weight draws in view. Empty when the run has no weights.
export function weightKey(M, st, view) {
  const wmax = M.weight ? maxWeight(M.weight) : 0;
  if (!(wmax > 0)) return [];
  const ws = [];
  for (let w = 1; w <= wmax / 2; w *= 10) ws.push(w);
  ws.push(wmax);
  const size = weightSizes(M, st, ws, view);
  return ws.map((w, j) => ({ w, size: size[j] }));
}
