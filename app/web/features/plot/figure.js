// Plotly data + layout for one plot tab. Two point traces: points in view ("on") and points of
// clusters outside the current focus ("dim": faint, grey unless st.others is 'own', smaller for
// nuggets). With st.others 'hide', clusters outside the selection and the hovered one are left
// out. Colours are per point, straight from the payload's clusters[].color (or the file
// palette); markers are solid with no outline, sized by sizes.js: MARKER's sizes, smaller for a
// run of more than about 2,000 nuggets, times the inspector's Point size (st.pointScale). The
// legend is HTML, not Plotly's.
// Axis, grid and font colours follow the theme (shared/plot-base.js).
import { DIM, DEFAULT_CAMERA } from '../../shared/config.js';
import { fmtNum, fmtInt, hexA } from '../../shared/format.js';
import { plotTheme, baseLayout, fileColor, PLOT_FONT } from '../../shared/plot-base.js';
import { copy } from './history.js';
import { markerSizes } from './sizes.js';

export const spatialCount = view => (view === '2d' ? 2 : view === 'par' ? 0 : 3);

// The keys a view draws on its x/y/z axes (or every dimension, for parallel coordinates).
export function drawnKeys(M, st) {
  if (st.view === 'par') return parKeys(M, st);
  return st.axes.slice(0, spatialCount(st.view));
}
export function parKeys(M, st) {
  const kinds = new Set(st.axes.slice(0, 3).map(k => k[0]));
  if (kinds.size === 1 && kinds.has('v')) return M.vars;
  if (kinds.size === 1 && kinds.has('p') && M.pcs.length) return M.pcs;
  return [...M.vars, ...M.pcs];
}

function groupColor(M, st, T) {
  if (st.colorBy === 'file' && M.file) return i => fileColor(T, M.file[i]);
  return i => M.colors.get(M.cluster[i]);
}

// Which bucket each point falls in. focus: the clusters drawn bright (hover beats selection).
// kept: what 'hide' leaves on screen, or null for all. It holds the selection as well as the
// hovered cluster, so passing over the legend dims the picked clusters rather than removing them.
export const focusOf = st => (st.hover != null ? new Set([st.hover]) : st.sel);
export function keptOf(st) {
  if (st.others !== 'hide') return null;
  const keep = new Set(st.sel);
  if (st.hover != null) keep.add(st.hover);
  return keep.size ? keep : null;
}
export function classify(M, st) {
  const focus = focusOf(st), keep = keptOf(st);
  const out = { on: [], dim: [] };
  for (let i = 0; i < M.n; i++) {
    const c = M.cluster[i];
    if (st.hidden.has(c) || (keep && !keep.has(c))) continue;
    (focus.size && !focus.has(c) ? out.dim : out.on).push(i);
  }
  return out;
}

// The payload lists the kept files only, so a point's file is found by its number, never by its
// position in that list.
const namesOf = new WeakMap();
function fileNames(files) {
  if (!files) return new Map();
  let m = namesOf.get(files);
  if (!m) { m = new Map(files.map(f => [f.number, f.name])); namesOf.set(files, m); }
  return m;
}

function hoverText(M, st, keys, cols, i, fileOf) {
  // A cell is named by its event (its row in its file, from 1), as the point card names it.
  const what = M.src === 'cells' ? `Event ${fmtInt(M.index[i] + 1)}` : `Nugget ${fmtInt(M.index[i] + 1)}`;
  const name = M.file ? fileOf.get(M.file[i]) : null;
  const f = M.file ? ` · F${M.file[i]}${name ? ' ' + esc(name) : ''}` : '';
  const w = M.weight ? ` · weight ${fmtNum(M.weight[i])}` : '';
  // v3 review (2nd) F1: numbers are formatted here, four significant digits, not by d3-format.
  return `<b>Cluster ${M.cluster[i]}</b>${f}<br>${what}${w}` + keys.map((k, a) => `<br>${M.label(k, st.units, true)}: ${fmtNum(cols[a][i])}`).join('');
}

const esc = s => String(s).replace(/[<>&]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[c]);
const scaled = (s, f) => (Array.isArray(s) ? s.map(v => v * f) : s * f);
// Cells already draw at the smallest marker, so other clusters' cells keep their size: shrunk,
// they all but vanished.
const dimScale = M => (M.src === 'cells' ? 1 : DIM.scale);
const common = (T, uirevision) => ({ ...baseLayout(T), showlegend: false, hovermode: 'closest', uirevision });
const ax2 = (T, title) => ({ title: { text: title, font: { size: 11.5, color: T.fg2 } }, gridcolor: T.grid, zerolinecolor: T.line, linecolor: T.line, color: T.fg3, tickfont: { size: 10 }, showline: true, mirror: false });
const ax3 = (T, title, pane) => ({ title: { text: title, font: { size: 11.5, color: T.fg2 } }, backgroundcolor: pane, showbackground: true, gridcolor: T.line, zerolinecolor: T.fg3, color: T.fg3, tickfont: { size: 9.5 }, showspikes: false });

// The point card's point (view.js st.point) as an open ring over its dot, drawn last so it sits
// on top. In 2D it takes no hover, so a hover or click goes to the dot under it. In 3D it carries
// its point's label: Plotly's 3D scene hovers whatever its pick buffer finds nearest the pointer,
// ring included, and drops the pick of a trace that skips hovers, so a ring that took none left
// its point and the points around it with no hover and no click. view.js takes a pick of the ring
// as its point. null when the card is shut, the point is of the other source or its cluster is
// hidden.
function ringTrace(M, st, parts, C, three, T, keys, fileOf) {
  const p = st.point;
  if (!p || p.src !== M.src || !(parts.on.includes(p.i) || parts.dim.includes(p.i))) return null;
  const s = markerSizes(M, st, [p.i], three ? '3d' : '2d'), size = (Array.isArray(s) ? s[0] : s) + (three ? 6 : 8);
  const t = { type: three ? 'scatter3d' : 'scattergl', mode: 'markers', x: [C[0][p.i]], y: [C[1][p.i]],
    marker: { symbol: 'circle-open', size, color: T.fg, opacity: 1, line: { width: 2, color: T.fg } } };
  if (three) Object.assign(t, { z: [C[2][p.i]], text: [hoverText(M, st, keys, C, p.i, fileOf)], hovertemplate: '%{text}<extra></extra>' });
  else t.hoverinfo = 'skip';
  return t;
}

// cols: optional override of the drawn columns (the axis tween passes in-between values).
export function figure(M, st, files, uirevision, cols = null) {
  const T = plotTheme();
  if (st.view === 'par') return parallel(M, st, T, uirevision);
  const keys = drawnKeys(M, st);
  const C = cols || keys.map(k => M.column(k, st.units));
  const parts = classify(M, st), colorOf = groupColor(M, st, T), fileOf = fileNames(files);
  if (st.view === 'pairs') return pairs(M, st, T, keys, C, parts, colorOf, fileOf, uirevision);
  const three = keys.length === 3, own = st.others === 'own';
  const type = three ? 'scatter3d' : 'scattergl';
  const trace = (idx, kind) => {
    const size = markerSizes(M, st, idx, three ? '3d' : '2d');
    const t = {
      type, mode: 'markers', x: idx.map(i => C[0][i]), y: idx.map(i => C[1][i]),
      marker: { size: kind === 'dim' ? scaled(size, dimScale(M)) : size, line: { width: 0 } },
    };
    if (three) t.z = idx.map(i => C[2][i]);
    // Opacity is one number per trace; in 3D any value under 1 sends the trace to the transparent pass.
    if (kind === 'dim') Object.assign(t.marker, { color: own ? idx.map(colorOf) : T.dim, opacity: DIM[own ? 'own' : 'grey'][three ? 3 : 2] });
    else Object.assign(t.marker, { color: idx.map(colorOf), opacity: 1 });
    if (kind === 'on') { t.text = idx.map(i => hoverText(M, st, keys, C, i, fileOf)); t.hovertemplate = '%{text}<extra></extra>'; }
    else t.hoverinfo = 'skip';
    return t;
  };
  // "on" after "dim", so the points in view draw on top; the point card's ring over both.
  const data = [trace(parts.dim, 'dim'), trace(parts.on, 'on')];
  const ring = ringTrace(M, st, parts, C, three, T, keys, fileOf);
  if (ring) data.push(ring);
  const names = keys.map(k => M.label(k, st.units));
  if (three) {
    // A 3-D t-SNE keeps one unit the same length on every axis, as the 2-D one does below.
    const aspectmode = keys.every(k => k[0] === 'u') ? 'data' : 'cube';
    // The wheel's box (zoom3.js), else Fit's: Plotly's autorange, set each draw so a box the
    // last draw had never stays.
    const box = k => (st.box3 ? { range: st.box3[k].slice(), autorange: false } : { autorange: true });
    return { data, parts, layout: { ...common(T, uirevision), margin: { l: 0, r: 0, t: 0, b: 0 },
      scene: { xaxis: { ...ax3(T, names[0], T.paneX), ...box('xaxis') }, yaxis: { ...ax3(T, names[1], T.paneY), ...box('yaxis') },
        zaxis: { ...ax3(T, names[2], T.paneZ), ...box('zaxis') }, aspectmode, camera: copy(st.camera || DEFAULT_CAMERA), dragmode: st.drag3d } } };
  }
  const layout = { ...common(T, uirevision), margin: { l: 62, r: 16, t: 10, b: 48 }, xaxis: ax2(T, names[0]), yaxis: ax2(T, names[1]), dragmode: st.boxArmed ? 'zoom' : 'pan' };
  if (keys[0][0] === 't' && keys[1][0] === 't') { layout.yaxis.scaleanchor = 'x'; layout.yaxis.scaleratio = 1; }
  return { data, parts, layout };
}

function pairs(M, st, T, keys, C, parts, colorOf, fileOf, uirevision) {
  const idx = [...parts.dim, ...parts.on];
  const dimSet = new Set(parts.dim), own = st.others === 'own';
  const dimColor = i => (own ? hexA(colorOf(i), DIM.own[2]) : hexA(T.dim, DIM.grey[2]));
  const color = idx.map(i => (dimSet.has(i) ? dimColor(i) : hexA(colorOf(i), 1)));
  // One size for all, or one per point by weight; other clusters' nuggets at DIM.scale of theirs.
  const ds = dimScale(M), s = markerSizes(M, st, idx, 'pairs'), w = Array.isArray(s) ? s : null;
  const size = w || (dimSet.size && ds !== 1) ? idx.map((i, j) => (w ? w[j] : s) * (dimSet.has(i) ? ds : 1)) : s;
  // One object per axis: Plotly writes relayout ranges into layout.<axis> in place.
  const ax = () => ({ gridcolor: T.grid, zerolinecolor: T.line, linecolor: T.line, color: T.fg3, tickfont: { size: 9.5 }, title: { font: { size: 11, color: T.fg2 } } });
  const layout = { ...common(T, uirevision), margin: { l: 64, r: 16, t: 14, b: 54 }, dragmode: st.boxArmed ? 'zoom' : 'pan' };
  for (const k of ['xaxis', 'xaxis2', 'xaxis3', 'yaxis', 'yaxis2', 'yaxis3']) layout[k] = ax();
  return {
    parts, layout,
    data: [{
      type: 'splom', text: idx.map(i => hoverText(M, st, keys, C, i, fileOf)), hovertemplate: '%{text}<extra></extra>',
      dimensions: keys.map((k, a) => ({ label: M.label(k, st.units), values: idx.map(i => C[a][i]) })),
      marker: { color, size, line: { width: 0 } },
      diagonal: { visible: false }, showupperhalf: false,
    }],
  };
}

// Parallel coordinates over every dimension of the preset, one line per point, coloured by
// cluster through a stepped colourscale: the group at step s sits in [(s-1)/K, s/K] of
// [0.5, K+0.5]. Plotly draws a parcoords line over the others the higher its colour value,
// whatever the data order, so the focus clusters take the top steps.
function parallel(M, st, T, uirevision) {
  const keys = parKeys(M, st);
  const byFile = st.colorBy === 'file' && !!M.file;
  const groups = byFile ? [...new Set(M.file)].sort((a, b) => a - b) : [...M.colors.keys()].sort((a, b) => a - b);
  const g = byFile ? M.file : M.cluster, K = Math.max(...groups);
  const focus = focusOf(st), keep = keptOf(st);
  const all = Array.from({ length: K }, (_, i) => i + 1);
  const order = !byFile && focus.size ? [...all.filter(c => !focus.has(c)), ...all.filter(c => focus.has(c))] : all;
  const step = new Map(order.map((c, s) => [c, s + 1]));
  const scale = [];
  order.forEach((c, s) => {
    const base = byFile ? fileColor(T, c) : M.colors.get(c) || T.ghost;
    const col = !byFile && focus.size && !focus.has(c) ? hexA(st.others === 'own' ? base : T.ghost, 0.35) : base;
    scale.push([s / K, col], [(s + 1) / K, col]);
  });
  const idx = [];
  for (let i = 0; i < M.n; i++) if (!st.hidden.has(M.cluster[i]) && !(keep && !keep.has(M.cluster[i]))) idx.push(i);
  const many = keys.length > 8;
  return {
    parts: { on: idx, dim: [] },
    layout: { ...common(T, uirevision), margin: { l: 56, r: 56, t: many ? 96 : 56, b: 24 } },
    data: [{
      type: 'parcoords', labelangle: many ? -30 : 0, labelside: 'top',
      labelfont: { size: 11, color: T.fg2, family: PLOT_FONT }, tickfont: { size: 9.5, color: T.fg3, family: PLOT_FONT }, rangefont: { size: 9, color: T.fg3 },
      line: { color: idx.map(i => step.get(g[i])), colorscale: scale, cmin: 0.5, cmax: K + 0.5, showscale: false },
      dimensions: keys.map(k => { const col = M.column(k, st.units); return { label: M.label(k, st.units, true), values: idx.map(i => col[i]) }; }),
    }],
  };
}
