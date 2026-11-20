// The plot's Back stack and the 3D camera guard, carried over from the v3 mock-up with its review
// fixes: F1 (2D ranges re-applied on every draw), F2 (flush a moving 3D camera before Back, Fit
// and teardown) and F3 (a box gesture is told from a wheel turn by pointerdown time).
import { HISTORY, EYE, DEFAULT_CAMERA, SETTLE_MS } from '../../shared/config.js';
import { AXES3, zoomBox } from './zoom3.js';

export const copy = o => JSON.parse(JSON.stringify(o));
const viewKey = v => JSON.stringify(v, (k, x) => (typeof x === 'number' ? +x.toPrecision(6) : x));
export const sameView = (a, b) => !!a && !!b && viewKey(a) === viewKey(b);
export const is3 = view => view === '3d';
export const newHist = () => ({ id: null, stack: [], now: null, base: null, based: false, last: 0, mute: 0, wheelAt: 0, downAt: 0, settle: 0 });

// A 3D view: camera cam and the wheel's box (st.box3, zoom3.js; null at Fit's).
export const view3 = (st, cam) => (cam ? { camera: copy(cam), box: st.box3 ? copy(st.box3) : null } : null);
// A box as a relayout: each scene axis's range, or autorange back to Fit's.
export function boxLayout(box) {
  const upd = {};
  for (const k of AXES3) if (box) upd[`scene.${k}.range`] = box[k].slice(); else upd[`scene.${k}.autorange`] = true;
  return upd;
}

// The view Back returns to: every axis range in 2D and Pairs, the camera and the box in 3D.
export function viewOf(div, st) {
  const fl = div._fullLayout;
  if (!fl) return null;
  if (is3(st.view)) {
    const sc = fl.scene && fl.scene._scene;
    return sc ? view3(st, sc.getCamera()) : null;
  }
  if (st.view === 'par') return null;
  const v = {};
  for (const k of Object.keys(fl)) if (/^[xy]axis\d*$/.test(k) && fl[k] && Array.isArray(fl[k].range)) v[k] = fl[k].range.slice();
  return v;
}
function pushView(H, v) {
  if (!v || sameView(H.stack[H.stack.length - 1], v)) return;
  H.stack.push(copy(v));
  if (H.stack.length > HISTORY.cap) H.stack.shift();
}
// A user change starts a gesture unless one ended under gapMs ago, so one wheel spin or one drag
// is one Back step. The view from before the gesture is pushed once it is known to differ.
export function beginChange(st) {
  const H = st.hist, t = performance.now();
  if (H.mute) return false;
  if (t - H.last > HISTORY.gapMs) { H.base = H.now; H.based = false; }
  H.last = t;
  return true;
}
export function endChange(st, now) {
  const H = st.hist;
  if (H.base && !H.based && now && !sameView(H.base, now)) { pushView(H, H.base); H.based = true; }
  if (now) H.now = now;
}
// Moves the view without recording it, for Back and Fit.
export function quietRelayout(div, st, upd) {
  const H = st.hist;
  H.mute++;
  const done = () => { H.mute--; H.last = 0; };
  return window.Plotly.relayout(div, upd).then(done, done);
}

// A turntable drag can take the camera under the floor or inside the box, and Plotly then draws
// the floor on top. The eye stays within these elevations and distances.
export function clampEye(e) {
  const r0 = Math.hypot(e.x, e.y, e.z) || 1, deg0 = (Math.asin(e.z / r0) * 180) / Math.PI;
  const r = Math.min(EYE.maxR, Math.max(EYE.minR, r0)), deg = Math.min(EYE.maxDeg, Math.max(EYE.minDeg, deg0));
  if (r === r0 && deg === deg0) return null;
  const az = Math.atan2(e.y, e.x), t = (deg * Math.PI) / 180;
  return { x: r * Math.cos(t) * Math.cos(az), y: r * Math.cos(t) * Math.sin(az), z: r * Math.sin(t) };
}
const sceneOf = div => { const fl = div._fullLayout; return fl && fl.scene && fl.scene._scene; };
const arr = v => [v.x, v.y, v.z];

// F2: read the camera as it is now (a drag or wheel may still be settling), clamp it, store it
// and record it, so Back, Fit and a tab switch never lose or misorder the last move.
export function flush(div, st) {
  const H = st.hist;
  clearTimeout(H.settle); H.settle = 0;
  if (!is3(st.view)) return;
  const sc = sceneOf(div);
  if (!sc) return;
  const cam = sc.getCamera(), eye = clampEye(cam.eye);
  st.camera = copy(eye ? { ...cam, eye } : cam);
  endChange(st, view3(st, st.camera));
}

// One step of the 3D wheel (view.js): the box scaled by f about point p, which keeps its place on
// screen, recorded as a 2D wheel turn is (one spin, one Back step). fit: Fit's box (zoom3.js
// fitBox). The camera stays put.
export function zoomView3(div, st, fit, p, f) {
  if (!fit || !div._fullLayout || !beginChange(st)) return Promise.resolve();
  st.box3 = zoomBox(fit, st.box3, p, f);
  return window.Plotly.relayout(div, boxLayout(st.box3)).then(() => endChange(st, view3(st, st.camera || DEFAULT_CAMERA)));
}

export function backView(div, st, sync) {
  flush(div, st);
  const H = st.hist;
  if (!H.stack.length || !div._fullLayout) return;
  const v = H.stack.pop();
  H.base = null; H.now = copy(v);
  if (is3(st.view)) {
    st.camera = copy(v.camera); st.box3 = v.box ? copy(v.box) : null;
    quietRelayout(div, st, { 'scene.camera': copy(v.camera), ...boxLayout(v.box) }).then(sync);
  } else {
    const upd = {};
    for (const [k, r] of Object.entries(v)) upd[k + '.range'] = r.slice();
    quietRelayout(div, st, upd).then(() => { H.now = viewOf(div, st); sync(); });
  }
  sync();
}
export function fitView(div, st, sync) {
  flush(div, st);
  const H = st.hist;
  if (!div._fullLayout) return;
  H.base = H.now; H.based = false;
  if (is3(st.view)) {
    st.camera = copy(DEFAULT_CAMERA); st.box3 = null;
    quietRelayout(div, st, { 'scene.camera': copy(DEFAULT_CAMERA), ...boxLayout(null) }).then(() => { endChange(st, view3(st, st.camera)); sync(); });
    return;
  }
  const upd = {};
  for (const k of Object.keys(viewOf(div, st) || {})) upd[k + '.autorange'] = true;
  quietRelayout(div, st, upd).then(() => { endChange(st, viewOf(div, st)); sync(); });
}
export function setBox(div, st, on, sync) {
  st.boxArmed = on;
  if (div._fullLayout && !is3(st.view) && st.view !== 'par') window.Plotly.relayout(div, { dragmode: on ? 'zoom' : 'pan' });
  sync();
}
export function setDrag3d(div, st, mode, sync) {
  st.drag3d = mode;
  if (div._fullLayout && is3(st.view)) window.Plotly.relayout(div, { 'scene.dragmode': mode });
  sync();
}

// Wires one freshly drawn figure: the 3D eye clamp and settle pass, and 2D range tracking.
export function wire(div, st, sync) {
  const H = st.hist;
  const sc0 = sceneOf(div);
  if (sc0) try { sc0.camera.view.setDistanceLimits(EYE.minR, EYE.maxR); } catch (e) { /* the settle pass still clamps */ }
  div.on('plotly_relayouting', ev => {
    const cam = ev && ev['scene.camera'], sc = sceneOf(div);
    if (cam) beginChange(st);
    const eye = cam && sc && clampEye(cam.eye);
    if (eye) sc.camera.lookAt(arr(eye), arr(cam.center), arr(cam.up));
  });
  let last = '';
  const rest = () => {
    const sc = sceneOf(div);
    if (!sc) return;
    const cam = sc.getCamera(), seen = JSON.stringify(cam.eye);
    if (seen !== last) { last = seen; H.settle = setTimeout(rest, SETTLE_MS); return; }
    H.settle = 0;
    const eye = clampEye(cam.eye);
    st.camera = eye ? { ...cam, eye } : cam;
    if (eye) window.Plotly.relayout(div, { 'scene.camera.eye': eye });
    endChange(st, view3(st, st.camera));
    sync();
  };
  const settleSoon = () => { if (!beginChange(st)) return; clearTimeout(H.settle); last = ''; H.settle = setTimeout(rest, SETTLE_MS); };
  div.on('plotly_relayout', ev => {
    if (!ev) return;
    if (ev['scene.camera']) { settleSoon(); return; }
    if (is3(st.view) || st.view === 'par') return;
    const ranged = Object.keys(ev).some(k => /^[xy]axis\d*\.(range|autorange)/.test(k));
    if (ranged && beginChange(st)) {
      endChange(st, viewOf(div, st));
      // F3: a box drawn after the last wheel turn ends Box zoom; a wheel turn while armed does not.
      if (st.boxArmed && H.downAt > H.wheelAt) setBox(div, st, false, sync);
    } else H.now = viewOf(div, st) || H.now;
    sync();
  });
  // Plotly listens on the canvas only, so a drag that leaves it keeps turning past EYE; follow
  // the pointer on the window until release. A property, so redraws replace it.
  const clampLive = () => {
    const sc = sceneOf(div), cam = sc && sc.getCamera(), eye = cam && clampEye(cam.eye);
    if (eye) sc.camera.lookAt(arr(eye), arr(cam.center), arr(cam.up));
  };
  div.onpointerdown = e => {
    H.downAt = performance.now();
    if (!sc0 || e.button !== 0) return;
    const move = () => { clampLive(); requestAnimationFrame(clampLive); };
    const up = () => { window.removeEventListener('pointermove', move, true); window.removeEventListener('pointerup', up, true); settleSoon(); };
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', up, true);
  };
  if (!H.now) H.now = viewOf(div, st);
}
