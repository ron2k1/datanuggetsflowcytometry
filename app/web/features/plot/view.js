// The plot tab: nuggets or cells of one run in 2D, 3D, pairs or parallel coordinates, with the
// v3 toolbar (Pan/Box or Rotate/Pan, Back, Fit) and inspector. A click on a point shows its own
// numbers in the point card beside the plot (point-card.js); the card, or the bar under the
// canvas, opens a cluster's box plots in their own tab (EV.boxPlots).
import { el, docHead } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtInt } from '../../shared/format.js';
import { plotUnits } from '../../shared/cofactor.js';
import { POINT_SCALE, TWEEN_MS, CLICK_SLOP, HISTORY } from '../../shared/config.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, idOf, activity, getPlot, getCells, getManifest } from '../../shared/store.js';
import { registerView } from '../../shared/views.js';
import { makeModel, presetAxes } from './model.js';
import { figure, drawnKeys } from './figure.js';
import { zoomGrow, grow3 } from './sizes.js';
import { newHist, is3, viewOf, flush, backView, fitView, setBox, setDrag3d, wire, zoomView3 } from './history.js';
import { fitBox, boxZoom, wheelFactor, middle, AXES3 } from './zoom3.js';
import { inspector, fixAxes, VIEWS } from './inspector.js';
import { pointCard } from './point-card.js';

// The wheel zooms 2D and Pairs as Plotly does; 3D's is this tab's (zoom3.js), so Plotly's own,
// which moves the camera, is off.
const CONFIG = { responsive: false, displaylogo: false, scrollZoom: 'cartesian', displayModeBar: false, doubleClick: 'autosize' };
const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function stateFor(key) {
  const st = S.view[key] || (S.view[key] = {
    src: 'nuggets', view: '3d', axes: null, units: 'orig', colorBy: 'cluster', sizeW: true, others: 'grey',
    pointScale: POINT_SCALE.start, sel: new Set(), hidden: new Set(), hover: null, search: '',
    // box3: the 3D wheel's axis ranges (zoom3.js), null at Fit's.
    camera: null, box3: null, drag3d: 'turntable', boxArmed: false, hist: newHist(),
    // The bar's cluster for the box plots: the one picked or clicked last.
    pick: null,
    // The point card's point, { src, i } (a row of that source's model), or null when it is shut.
    point: null,
  });
  // Defensive only: S.view lives in memory, so no state from before 4D and 5D were removed can
  // reach here today. A view not in VIEWS or a Point size out of range would open in 3D at 1x;
  // fixAxes trims the axes to x, y and z once the model has loaded.
  if (!VIEWS.some(([v]) => v === st.view)) st.view = '3d';
  if (!(st.pointScale >= POINT_SCALE.min && st.pointScale <= POINT_SCALE.max)) st.pointScale = POINT_SCALE.start;
  return st;
}
// EV.clusterFocus (Compare's "show in the plot"): open the run's plot with that cluster selected.
function focusCluster({ rid, cluster: c }) {
  const key = `plot:${rid}`, st = stateFor(key);
  st.sel = new Set([c]); st.hidden.delete(c); st.hover = null;
  emit(EV.openTab, { key });
  activity(`Cluster ${c} of ${rid} selected from Compare`);
}
// What makes a figure "the same" for uirevision and the Back stack.
const figId = (rid, st) => `${rid}|${st.src}|${st.view}|${st.axes.join('-')}|${st.units}`;

function render(body, key, host) {
  const rid = idOf(key), st = stateFor(key);
  const plotDiv = el('div', { class: 'plot-div' });
  const tools = el('div', { class: 'plot-tools', role: 'toolbar', 'aria-label': 'Plot navigation' });
  const canvas = el('div', { class: 'plot-canvas' }, plotDiv, tools);
  const head = el('div', { class: 'plot-head' });
  const insp = el('aside', { class: 'inspector', 'aria-label': 'Plot controls' });
  const foot = el('div', { class: 'plot-foot', hidden: true });
  const side = el('aside', { class: 'point-side', 'aria-label': 'Point', hidden: true });
  const view = el('div', { class: 'plotview' }, el('div', { class: 'plot-main' }, head, canvas, foot), side, insp);
  body.append(view);
  plotDiv.append(el('div', { class: 'fallback', text: 'Loading the plot…' }));
  plotDiv.addEventListener('wheel', () => { st.hist.wheelAt = performance.now(); }, { capture: true, passive: true });

  let P = null, man = null, cells = null, M = null, dead = false, drawnView = null, parts = null;
  let busy = false, pending = null, tweenRaf = 0, zoomRaf = 0, ro = null;
  const models = {};
  // makeModel falls back to the nuggets while the cells are not loaded, so a model is kept only
  // under its own source: a nuggets model cached as 'cells' would index cell rows by nugget.
  const model = (src = st.src) => {
    if (models[src]) return models[src];
    const m = makeModel(P, cells, src);
    if (m.src === src) models[src] = m;
    return m;
  };

  /* drawing: one draw at a time, the latest request wins */
  function schedule(opts = {}) { pending = opts; if (!busy) pump(); }
  async function pump() {
    busy = true;
    while (pending && !dead) {
      const o = pending; pending = null;
      try { await drawNow(o); } catch (e) { activity(`Plot ${rid}: ${e.message}`); }
    }
    busy = false;
  }
  async function drawNow(o) {
    if (!window.Plotly) { plotDiv.replaceChildren(el('div', { class: 'fallback', text: 'Plotly did not load, so the interactive plot is unavailable.' })); return; }
    const H = st.hist, id = figId(rid, st);
    // A new 2D figure starts at Fit, with no zoom (H.home: the 2D view Fit shows); a 3D one keeps
    // the camera, and with it the camera's zoom, but starts at Fit's box (H.fit3: that box, the
    // last draw's). change() drew the inspector before this draw, so a size key drawn at the old
    // zoom is drawn again at the new one.
    if (H.id !== id) {
      Object.assign(H, { id, stack: [], now: null, base: null, based: false, last: 0, home: null, refit: false, fit3: null });
      st.boxArmed = false; st.box3 = null;
      const was = st.zoomGrow || 1;
      st.zoomGrow = camGrow();
      if (st.zoomGrow !== was) renderInspector();
    }
    // H.refit (zoomed): Fit autoranged around grown dots, which pads it wide; autorange at 1x.
    const fit = !H.now, refit = !!H.refit && !o.cols && st.view === '2d';
    H.refit = false;
    const fig = figure(M, st, P.files, id, o.cols || null);
    parts = fig.parts;
    // Fit's box for the rows this draw shows (hiding a cluster changes it); a tween frame's
    // in-between columns are not the figure's.
    if (is3(st.view) && !o.cols) H.fit3 = fitBox(drawnKeys(M, st).map(k => M.column(k, st.units)), [...parts.dim, ...parts.on]);
    // v3 review F1: a redraw (react included) keeps the 2D view the user is looking at.
    if (refit) for (const k of ['xaxis', 'yaxis']) Object.assign(fig.layout[k], { autorange: true });
    else if (!is3(st.view) && st.view !== 'par' && H.now) for (const [k, r] of Object.entries(H.now)) if (fig.layout[k]) Object.assign(fig.layout[k], { range: r.slice(), autorange: false });
    sizeCanvas();
    if (st.view !== drawnView) {
      if (drawnView) window.Plotly.purge(plotDiv);
      plotDiv.replaceChildren();
      drawnView = st.view;
      near3 = null;
      await window.Plotly.newPlot(plotDiv, fig.data, fig.layout, CONFIG);
      if (dead || !plotDiv._fullLayout) return;
      wire(plotDiv, st, sync);
      plotDiv.on('plotly_relayout', zoomed);
      plotDiv.on('plotly_click', pointClick);
      plotDiv.on('plotly_hover', pointHover);
      plotDiv.on('plotly_unhover', () => { near3 = null; });
    } else {
      await window.Plotly.react(plotDiv, fig.data, fig.layout, CONFIG);
      // A tween frame (o.cols) is drawn on in-between columns, so its autoranged view is not
      // kept: each frame fits its own points and the final draw fixes the view on the new axes.
      if (!H.now && !o.cols) H.now = viewOf(plotDiv, st);
    }
    if ((fit || refit) && !o.cols && st.view === '2d') H.home = viewOf(plotDiv, st);
    // The refit view replaces Fit's padded one in place: Back still returns to the zoomed view.
    if (refit) H.now = viewOf(plotDiv, st);
    renderHead(); renderPoint(); sync();
  }
  // 2D nuggets grow as the view zooms in from Fit (sizes.js zoomGrow). Registered after wire's
  // handler, so H.now already holds the new ranges. Fit and a double-click autorange the axes,
  // which makes that view the new home; Plotly pads an autorange for the dots' size, so one taken
  // at a grown size is refit at 1x. The redraw waits a frame: a wheel spin sends many.
  function zoomed(ev) {
    if (!ev || st.view !== '2d' || !M || M.src !== 'nuggets') return;
    const H = st.hist, now = viewOf(plotDiv, st);
    if (Object.keys(ev).some(k => /^[xy]axis\d*\.autorange/.test(k))) {
      H.home = now;
      if (st.zoomGrow > 1) { st.zoomGrow = 1; H.refit = true; redrawSoon(); }
      return;
    }
    const g = zoomGrow(H.home, now);
    if (Math.abs(g - (st.zoomGrow || 1)) < 1e-3) return;
    st.zoomGrow = g;
    redrawSoon();
  }
  function redrawSoon() {
    cancelAnimationFrame(zoomRaf);
    zoomRaf = requestAnimationFrame(() => { if (!dead) { renderInspector(); schedule(); } });
  }
  // 3D nuggets grow as the wheel narrows the box, by 2D's rule (sizes.js grow3). sync() runs after
  // each wheel step, once the camera settles after a drag, and after Back and Fit, each with
  // st.box3 and st.camera stored, so it checks the factor; a draw ends in sync() with the factor
  // unchanged.
  const camGrow = () => (is3(st.view) && M && M.src === 'nuggets' ? grow3(st.camera, boxZoom(st.hist.fit3, st.box3)) : 1);
  function camZoomed() {
    if (!is3(st.view) || !M) return;
    const g = camGrow();
    if (Math.abs(g - (st.zoomGrow || 1)) < 1e-3) return;
    st.zoomGrow = g;
    redrawSoon();
  }
  // Parallel coordinates with many axes get a wider canvas that scrolls sideways.
  function sizeCanvas() {
    const n = st.view === 'par' ? drawnKeys(M, st).length : 0, wide = n > 10;
    canvas.classList.toggle('wide', wide);
    plotDiv.style.right = wide ? 'auto' : '';
    plotDiv.style.width = wide ? `${n * 70 + 112}px` : '';
  }

  /* axis tween: the drawn columns move from the old keys to the new ones */
  function tweenTo(fromKeys) {
    cancelAnimationFrame(tweenRaf);
    const toKeys = drawnKeys(M, st);
    if (reduced() || st.view === 'par' || fromKeys.length !== toKeys.length || fromKeys.every((k, i) => k === toKeys[i])) { schedule(); return; }
    const a = fromKeys.map(k => M.column(k, st.units)), b = toKeys.map(k => M.column(k, st.units));
    const t0 = performance.now(), ease = t => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
    const step = now => {
      if (dead) return;
      const t = Math.min(1, (now - t0) / TWEEN_MS), e = ease(t);
      if (t >= 1) { schedule(); return; }
      schedule({ cols: a.map((col, d) => col.map((v, i) => v + (b[d][i] - v) * e)) });
      tweenRaf = requestAnimationFrame(step);
    };
    tweenRaf = requestAnimationFrame(step);
  }

  /* inspector + head */
  function change(fn, msg, opts = {}) {
    flush(plotDiv, st);
    const before = drawnKeys(M, st), view0 = st.view, src0 = st.src;
    fn();
    if (msg) activity(`${rid}: ${msg}`);
    renderInspector();
    if (opts.tween && st.view === view0 && st.src === src0) tweenTo(before); else schedule();
  }
  const ctx = {
    st, change,
    legendChange: (msg, typing) => { if (msg) activity(`${rid}: ${msg}`); renderInspector(typing); renderFoot(); schedule(); },
    // A redraw of the points that leaves the inspector as it is (the Point size slider mid-drag).
    restyle: msg => { flush(plotDiv, st); if (msg) activity(`${rid}: ${msg}`); schedule(); },
    hover: c => { if (st.hover === c) return; st.hover = c; schedule(); },
    // then(M): optional, edits st for the new model before the redraw (a link to the nuggets' t-SNE).
    setSrc: (v, then) => {
      if (v === st.src) return;
      const to = () => { st.src = v; M = model(); if (then) then(M); fixAxes(M, st); };
      if (v === 'cells' && !cells) {
        getCells(rid).then(c => { cells = c; if (!dead) change(to, `Cells: ${fmtInt(c.n)} sampled`); },
          e => activity(`Cells for ${rid}: ${e.message}`));
        return;
      }
      change(to, v === 'cells' ? 'Cells' : 'Nuggets');
    },
    open: k => emit(EV.openTab, { key: k }),
  };
  function renderInspector(keepSearchFocus) {
    const ctlId = e => e.tagName + '|' + (e.getAttribute('aria-label') || e.textContent);
    const had = insp.contains(document.activeElement) ? ctlId(document.activeElement) : null;
    const scroll = insp.querySelector('.legend') ? insp.querySelector('.legend').scrollTop : 0;
    insp.replaceChildren(...inspector(Object.assign(ctx, { M, P, man, cells, S0: S })));
    const lg = insp.querySelector('.legend');
    if (lg) lg.scrollTop = scroll;
    const again = had && [...insp.querySelectorAll('button, select, summary, input')].find(e => ctlId(e) === had);
    if (again) again.focus({ preventScroll: true });
    if (keepSearchFocus) { const s = insp.querySelector('input[type="search"]'); if (s) { s.focus({ preventScroll: true }); s.setSelectionRange(s.value.length, s.value.length); } }
  }
  function renderHead() {
    // The points of the clusters drawn, as the legend counts them (before the first draw there are
    // no parts, so the count is every point).
    const inView = parts ? parts.on.length + parts.dim.length : M.n, what = M.src === 'cells' ? 'cells' : 'nuggets';
    const keys = drawnKeys(M, st), kinds = new Set(keys.map(k => k[0]));
    const vs = keys.filter(k => k[0] === 'v').map(k => +k.slice(1));
    // The centers are in the run's Transform stage's units, cofactors per channel.
    const scale = kinds.has('v') ? plotUnits(P, vs)
      : kinds.has('t') ? 't-SNE of the nuggets' : kinds.has('u') ? '3-D t-SNE of the nuggets' : 'weighted PCA scores';
    head.replaceChildren(
      el('div', { class: 'plot-title' }, man.title, el('small', { text: `${M.src === 'cells' ? 'sampled cells' : 'nugget centers'}, ${scale}` })),
      el('div', { class: 'plot-count', text: `${fmtInt(inView)} of ${fmtInt(M.n)} ${what} in view · K=${P.k}` }));
    host.refreshStatus();
  }

  /* the bar under the canvas: a cluster picker and its box plots, in their own tab */
  const boxPlots = c => { st.pick = c; renderFoot(); emit(EV.boxPlots, { rid, cluster: c }); };
  // The picker shows the cluster picked or clicked last, else the single selected cluster, else
  // the first.
  function renderFoot() {
    foot.hidden = !M;
    if (foot.hidden) return;
    const all = [...M.colors.keys()].sort((a, b) => a - b);
    const cur = st.pick != null ? st.pick : st.sel.size === 1 ? [...st.sel][0] : all[0];
    const had = foot.contains(document.activeElement) ? document.activeElement.tagName : null;
    const pick = el('select', { 'aria-label': 'Cluster for the box plots', onchange: e => { st.pick = +e.target.value; } },
      ...all.map(c => el('option', { value: String(c), selected: c === cur, text: `Cluster ${c}` })));
    const btn = el('button', { type: 'button', class: 'btn sm primary', text: 'Open box plots', onclick: () => boxPlots(+pick.value) });
    foot.replaceChildren(el('span', { class: 'plot-foot-hint', text: 'Click a point for its numbers, or pick a cluster' }), pick, btn);
    if (had === 'SELECT') pick.focus({ preventScroll: true }); else if (had === 'BUTTON') btn.focus({ preventScroll: true });
  }
  /* the point card: the point clicked last, with its own numbers (point-card.js) */
  // Drawn again only when its point or the drawn axes change: a zoom redraws the plot many times
  // a second, and the card would lose its scroll each time.
  let cardKey = null;
  function renderPoint() {
    // A point of the other source indexes another model's rows: the card shuts.
    const p = st.point;
    if (p && (!M || p.src !== M.src || !(p.i < M.n))) st.point = null;
    const drawn = st.point && (st.view === '2d' || is3(st.view)) ? drawnKeys(M, st) : [];
    const key = st.point ? `${st.point.src}|${st.point.i}|${drawn.join()}` : null;
    if (key === cardKey) return;
    cardKey = key;
    side.hidden = !key;
    view.classList.toggle('has-point', !!key);
    if (!key) { side.replaceChildren(); return; }
    const i = st.point.i;
    side.replaceChildren(pointCard(P, M, i, { drawn, color: M.colors.get(M.cluster[i]), onClose: closePoint, onBoxPlots: boxPlots }));
  }
  function showPoint(i) {
    st.point = { src: M.src, i };
    st.pick = M.cluster[i];
    renderFoot(); renderPoint(); schedule();
  }
  // true when there was a card to shut: Esc's answer to the shell.
  function closePoint() {
    if (!st.point) return false;
    st.point = null;
    renderPoint(); schedule();
    return true;
  }
  // A click on a point shows it in the card. 2D and 3D draw [dim, on] (then the card's ring) and
  // only "on" takes hovers and clicks; the 3D ring, curve 2, takes them as its point (figure.js
  // ringTrace). Pairs draws one splom over [...dim, ...on], so a dimmed point there is skipped.
  const pointAt = ev => {
    const p = ev && ev.points && ev.points[0];
    if (!p || !parts) return null;
    if (st.view === 'pairs' && p.pointNumber < parts.dim.length) return null;
    if (st.view !== 'pairs' && p.curveNumber === 2) return st.point ? st.point.i : null;
    const idx = st.view === 'pairs' ? [...parts.dim, ...parts.on] : p.curveNumber === 1 ? parts.on : parts.dim;
    const i = idx[p.pointNumber];
    return i == null ? null : i;
  };
  // 3D takes the point whose hover label shows, on a release that has not moved. gl3d sends
  // plotly_click only within 5 px of a point's center and plotly_hover elsewhere in its pick
  // radius, so a click on a point's edge would miss it; and it sends the click while the button
  // is still down, so a rotation that starts on a point would take it.
  let down3 = null, near3 = null;
  function pointClick(ev) {
    const i = pointAt(ev);
    if (i == null) return;
    if (is3(st.view)) near3 = i; else showPoint(i);
  }
  function pointHover(ev) { if (is3(st.view)) near3 = pointAt(ev); }
  plotDiv.addEventListener('pointerdown', e => { down3 = e.button === 0 ? [e.clientX, e.clientY] : null; }, true);
  plotDiv.addEventListener('pointerup', e => {
    if (!is3(st.view) || near3 == null || !down3) return;
    if (Math.hypot(e.clientX - down3[0], e.clientY - down3[1]) < CLICK_SLOP) showPoint(near3);
  }, true);

  // The 3D wheel narrows or widens the box (zoom3.js) about the point under the cursor, which so
  // stays under it, as 2D's wheel zooms about the cursor. Without one it zooms about the box's
  // middle. A spin keeps its first point, as the dots move under a still cursor; the wheel events
  // of one frame make one step.
  let wheel3 = 1, wheelRaf = 0, focus3 = null, focusAt = 0;
  const inBox = (box, p) => AXES3.every((k, a) => p[a] >= box[k][0] && p[a] <= box[k][1]);
  function wheelStep() {
    wheelRaf = 0;
    const f = wheel3, H = st.hist;
    wheel3 = 1;
    if (dead || !is3(st.view) || !M || !H.fit3 || f === 1) return;
    const box = st.box3 || H.fit3;
    let p = focus3 != null && focus3 < M.n ? drawnKeys(M, st).map(k => M.column(k, st.units)[focus3]) : null;
    if (!p || !inBox(box, p)) p = middle(box);
    zoomView3(plotDiv, st, H.fit3, p, f).then(sync);
  }
  plotDiv.addEventListener('wheel', e => {
    if (!is3(st.view) || !plotDiv._fullLayout || !st.hist.fit3) return;
    e.preventDefault();
    const t = performance.now();
    if (t - focusAt > HISTORY.gapMs) focus3 = near3;
    else if (focus3 == null) focus3 = near3;
    focusAt = t;
    wheel3 *= wheelFactor(e.deltaY);
    if (!wheelRaf) wheelRaf = requestAnimationFrame(wheelStep);
  }, { passive: false });

  /* toolbar (rebuilt only when its kind changes, so a focused button keeps focus) */
  let toolKind = null;
  const tb = {};
  function sync() {
    if (dead) return;
    camZoomed();
    const kind = st.view === 'par' ? 'none' : is3(st.view) ? '3d' : '2d', H = st.hist;
    tools.hidden = kind === 'none';
    if (kind !== toolKind) {
      toolKind = kind;
      const b = (k, icon, label, title, onclick) => (tb[k] = el('button', { type: 'button', title, 'aria-label': label, html: svg(icon), onclick }));
      for (const k of Object.keys(tb)) delete tb[k];
      if (kind === 'none') tools.replaceChildren();
      else tools.replaceChildren(
        ...(kind === '3d'
          ? [b('rotate', 'rotate', 'Rotate', 'Rotate: drag to turn the view', () => setDrag3d(plotDiv, st, 'turntable', sync)),
             b('pan', 'pan', 'Pan', 'Pan: drag to move the view', () => setDrag3d(plotDiv, st, 'pan', sync))]
          : [b('pan', 'pan', 'Pan', 'Pan: drag to move the view', () => setBox(plotDiv, st, false, sync)),
             b('box', 'boxzoom', 'Box zoom', 'Box zoom: drag one box, then back to Pan (Esc cancels)', () => setBox(plotDiv, st, !st.boxArmed, sync))]),
        el('span', { class: 'sep', 'aria-hidden': 'true' }),
        b('back', 'back', 'Back', 'Back to the previous view (Backspace)', () => backView(plotDiv, st, sync)),
        b('fit', 'fit', 'Fit', kind === '3d' ? 'Fit: reset the camera and show all points' : 'Fit: show all points', () => fitView(plotDiv, st, sync)));
    }
    if (kind === 'none') return;
    if (kind === '3d') { tb.rotate.setAttribute('aria-pressed', String(st.drag3d !== 'pan')); tb.pan.setAttribute('aria-pressed', String(st.drag3d === 'pan')); }
    else { tb.pan.setAttribute('aria-pressed', String(!st.boxArmed)); tb.box.setAttribute('aria-pressed', String(st.boxArmed)); }
    tb.back.disabled = !H.stack.length;
    tb.back.title = H.stack.length ? `Back to the previous view (Backspace) · ${H.stack.length} step${H.stack.length === 1 ? '' : 's'}` : 'Back: no earlier view yet';
  }

  /* load */
  Promise.all([getPlot(rid), getManifest(rid)]).then(([p, m]) => {
    if (dead) return;
    P = p; man = m;
    if (st.src === 'cells' && !cells) st.src = 'nuggets';
    M = model();
    // A run opens on its 2-D t-SNE; one clustered with t-SNE off opens on its PCs, or its
    // markers when it has no PCA either.
    if (!st.axes) { st.axes = presetAxes(M, M.pcs.length ? 'pca' : 'vars', st.view); if (M.tsneKeys.length) { st.view = '2d'; st.axes = presetAxes(M, 'tsne', st.view); } }
    fixAxes(M, st);
    // Esc cancels an armed box zoom, else shuts the point card.
    host.setKeys({ back: () => backView(plotDiv, st, sync), cancelBox: () => {
      if (st.boxArmed) { setBox(plotDiv, st, false, sync); return true; }
      return closePoint();
    } });
    host.setStatus(() => `${M.src === 'cells' ? 'Cells' : 'Nuggets'} ${fmtInt(M.n)} · ${st.view.toUpperCase()} · ${drawnKeys(M, st).map(k => M.label(k, st.units, true)).join(' / ')}`);
    renderHead(); renderInspector(); renderFoot(); renderPoint(); sync();
    requestAnimationFrame(() => {
      if (dead || !canvas.isConnected) return;
      schedule();
      ro = new ResizeObserver(() => { if (window.Plotly && plotDiv._fullLayout) window.Plotly.Plots.resize(plotDiv); });
      ro.observe(canvas);
    });
  }, e => {
    if (dead) return;
    body.replaceChildren(el('div', { class: 'doc' }, docHead(`Plot ${rid}`, null), el('div', { class: 'callout', text: e.message })));
  });

  // The figure's colours come from the theme (shared/plot-base.js): a switch redraws it and the
  // inspector's file colours in place, keeping the view.
  const offTheme = subscribe(EV.themeChange, () => { if (!dead && M) { renderInspector(); schedule(); } });

  return () => {
    dead = true;
    offTheme();
    cancelAnimationFrame(tweenRaf);
    cancelAnimationFrame(zoomRaf);
    cancelAnimationFrame(wheelRaf);
    if (ro) ro.disconnect();
    // v3 review F2: keep a camera that was still settling, then free the WebGL context.
    try { flush(plotDiv, st); } catch (e) { /* the figure may never have drawn */ }
    st.hover = null;
    if (window.Plotly && drawnView) window.Plotly.purge(plotDiv);
  };
}

export function registerPlot() {
  registerView('plot', {
    title: key => { const n = key.split('~')[1]; return { name: `Plot ${idOf(key)}`, hint: n ? `#${n}` : null, icon: 'plot' }; },
    crumbs: key => ['Runs', idOf(key), 'Plot'],
    render,
    output: key => {
      const j = S.ws.jobs.find(x => x.run_id === idOf(key));
      return j ? { path: `job ${j.id} · run ${j.run_id}`, lines: j.log_tail || [] } : null;
    },
  });
  subscribe(EV.clusterFocus, focusCluster);
}
