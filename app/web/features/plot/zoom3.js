// A 3D view's zoom (docs/app/cluster-panel.md "Nuggets grow as the view zooms in"). Plotly's own
// 3D wheel moves the camera, and the camera's floor (EYE.minR) stops it about 1.8 times closer
// than Fit, so a clump stays a clump. The wheel narrows the three axis ranges instead, as the 2D
// wheel narrows two: the camera stays put, the box keeps its place on screen, the points inside it
// spread out, and Plotly clips the ones outside. A box is { xaxis: [lo, hi], yaxis, zaxis }, in
// the drawn columns' units; null is Fit's. No DOM here, so app/tests runs it in Node.
import { ZOOM_3D } from '../../shared/config.js';

export const AXES3 = ['xaxis', 'yaxis', 'zaxis'];
const span = r => r[1] - r[0];

// Fit's box as Plotly's 3D autorange draws it: each axis from the lowest to the highest value of
// the rows drawn (of cols[0], cols[1], cols[2]), padded by 1/32 of that span either side; -1 to 1
// with no rows, and the value plus or minus 1 when every row has the same one.
export function fitBox(cols, rows) {
  const box = {};
  AXES3.forEach((k, a) => {
    let lo = Infinity, hi = -Infinity;
    for (const i of rows) { const v = cols[a][i]; if (v < lo) lo = v; if (v > hi) hi = v; }
    if (lo > hi) { box[k] = [-1, 1]; return; }
    const pad = (hi - lo) / 32;
    box[k] = hi > lo ? [lo - pad, hi + pad] : [lo - 1, hi + 1];
  });
  return box;
}

// How far one wheel event scales the box's spans, as Plotly's 2D wheel scales an axis: a mouse
// notch (deltaY 100, held to 20) zooms in or out by exp(0.1), about 1.105.
export const wheelFactor = deltaY => Math.exp(Math.max(-ZOOM_3D.wheelMax, Math.min(ZOOM_3D.wheelMax, deltaY)) / ZOOM_3D.wheelScale);

// How far box is zoomed in from fit: the smallest of its axes' fit span over its span, as 2D takes
// the less zoomed of its two. 1 at Fit (box null).
export function boxZoom(fit, box) {
  if (!fit || !box) return 1;
  const z = Math.min(...AXES3.map(k => span(fit[k]) / span(box[k])));
  return Number.isFinite(z) && z > 0 ? z : 1;
}

// box (null: fit) with every span scaled by f about point p ([x, y, z]), which so keeps its place
// in the box and on screen: f < 1 zooms in. No span goes under its fit span / ZOOM_3D.maxZoom.
// null once every span is as wide as fit's or wider, to a part in 1e9 (a spin in and back out
// multiplies its steps back to 1 only that closely): zoomed back out to Fit.
export function zoomBox(fit, box, p, f) {
  const cur = box || fit, out = {};
  let wide = true;
  AXES3.forEach((k, a) => {
    const [lo, hi] = cur[k], s = hi - lo, full = span(fit[k]);
    const g = Math.max(s * f, full / ZOOM_3D.maxZoom) / s;
    out[k] = [p[a] - (p[a] - lo) * g, p[a] + (hi - p[a]) * g];
    if (s * g < full * (1 - 1e-9)) wide = false;
  });
  return wide ? null : out;
}

// The middle of box, where the wheel zooms when no point is hovered.
export const middle = box => AXES3.map(k => (box[k][0] + box[k][1]) / 2);
