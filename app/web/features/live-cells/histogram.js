// One channel's histogram on the axis the package binned on, t = asinh(raw / c) with c the
// channel's cofactor (raw itself at cofactor 0), with raw tick labels, and the user's line as an
// editable Plotly shape. A click on the plot area places the line, a drag moves it; both report
// the axis value through onPick and the caller rounds it and draws again. Nothing here places a
// line on its own.
import { CLICK_SLOP_PX } from '../../shared/config.js';
import { fmtInt, fmtNum } from '../../shared/format.js';
import { cofactorFor, fmtCofactor } from '../../shared/cofactor.js';
import { PLOT_MONO, baseLayout, fileColor } from '../../shared/plot-base.js';

const CONFIG = { responsive: false, displaylogo: false, displayModeBar: false, scrollZoom: false, doubleClick: false, edits: { shapePosition: true } };
const DROPPED_OPACITY = 0.3;

/** @param {number} cof  a channel's cofactor, the number the server drew it on (never 'auto'); 0 keeps the axis linear */
export const scale = cof => (cof > 0
  ? { toT: raw => Math.asinh(raw / cof), toRaw: t => cof * Math.sinh(t) }
  : { toT: raw => raw, toRaw: t => t });

/**
 * Channel h's axis in a Live cells set: its cofactor (its own under auto, from H.cofactors in
 * H.channels order; else the set's one number), how it was chosen, and the scale on it.
 * @param {object} H  a record's histograms
 * @param {object} h  one entry of H.channels
 * @returns {{cof: number, from: string|undefined, toT: (raw: number) => number, toRaw: (t: number) => number}}
 */
export function channelScale(H, h) {
  const cof = cofactorFor(H, H.channels.findIndex(c => c.channel === h.channel));
  return { cof, from: H.cofactor_from, ...scale(cof) };
}

// The x axis title: the raw values on an arcsinh axis and the channel's cofactor, as the job's
// log gives it (auto's a whole number), or a linear axis.
export const axisTitle = (cof, from) => (cof > 0 ? `raw value, arcsinh axis (cofactor ${fmtCofactor(cof, from)}${from ? `, ${from}` : ''})` : 'raw value');

export const sig4 = v => Number(v.toPrecision(4));
const unit4 = x => 10 ** (Math.floor(Math.log10(Math.abs(x))) - 3);

// v clamped to [a, b] and rounded to 4 significant digits, rounding inward at the ends so the
// line never leaves the axis.
export function roundIn(v, a, b) {
  const r = sig4(Math.min(b, Math.max(a, v)));
  if (r > b) return b === 0 ? 0 : sig4(Math.floor(b / unit4(b)) * unit4(b));
  if (r < a) return a === 0 ? 0 : sig4(Math.ceil(a / unit4(a)) * unit4(a));
  return r;
}

// Round raw values (0 and ±1, 5, 2 × 10^k, in that order of preference) as ticks on the t axis,
// each at least a tenth of the axis from the others. Null on a linear axis, where Plotly's own
// ticks are raw values already.
export function rawTicks(lo, hi, cof) {
  if (!(cof > 0)) return null;
  const { toT, toRaw } = scale(cof);
  const gap = (hi - lo) / 10;
  const chosen = [];
  const offer = raw => { const t = toT(raw); if (t >= lo && t <= hi && chosen.every(c => Math.abs(c.t - t) >= gap)) chosen.push({ raw, t }); };
  offer(0);
  for (const m of [1, 5, 2]) for (let k = -2; k <= 9; k++) { offer(m * 10 ** k); offer(-m * 10 ** k); }
  // A range between two round values gets three ticks at 2 significant digits instead.
  if (chosen.length < 2) {
    chosen.length = 0;
    for (const f of [0.1, 0.5, 0.9]) { const raw = Number(toRaw(lo + f * (hi - lo)).toPrecision(2)); chosen.push({ raw, t: toT(raw) }); }
  }
  chosen.sort((a, b) => a.t - b.t);
  return { tickvals: chosen.map(c => c.t), ticktext: chosen.map(c => fmtNum(sig4(c.raw))) };
}

/**
 * The figure for channel h (one entry of a record's histograms.channels).
 * @param {object} T  plotTheme()
 * @param {object} h  {channel, label, lo, hi, edges, counts, files: [{number, counts}]}
 * @param {{cof: number, from?: string, line: number|null, keep: '<'|'>', perFile: boolean, names: Object<number, string>}} o
 *   cof is channel h's cofactor (channelScale); line is the raw value of the user's line, or null
 */
function figure(T, h, o) {
  const { toT, toRaw } = scale(o.cof);
  const t = o.line == null ? null : toT(o.line);
  const centers = h.counts.map((_, i) => (h.edges[i] + h.edges[i + 1]) / 2);
  const widths = h.counts.map((_, i) => h.edges[i + 1] - h.edges[i]);
  const kept = x => t == null || (o.keep === '<' ? x < t : x > t);
  const bin = i => `${fmtNum(sig4(toRaw(h.edges[i])))} to ${fmtNum(sig4(toRaw(h.edges[i + 1])))}`;
  const data = o.perFile
    ? h.files.map(f => ({ type: 'bar', x: centers, y: f.counts, width: widths, name: o.names[f.number] || `F${f.number}`,
      marker: { color: fileColor(T, f.number), opacity: centers.map(x => (kept(x) ? 1 : DROPPED_OPACITY)) },
      text: f.counts.map((c, i) => `${o.names[f.number] || `F${f.number}`}<br>${bin(i)}: ${fmtInt(c)} cells`),
      hovertemplate: '%{text}<extra></extra>', textposition: 'none' }))
    : [{ type: 'bar', x: centers, y: h.counts, width: widths,
      marker: { color: centers.map(x => (t == null ? T.fg3 : kept(x) ? T.accent : T.line)) },
      text: h.counts.map((c, i) => `${bin(i)}: ${fmtInt(c)} cells`), hovertemplate: '%{text}<extra></extra>', textposition: 'none' }];
  const ticks = rawTicks(h.lo, h.hi, o.cof);
  const axis = { fixedrange: true, gridcolor: T.grid, linecolor: T.line, color: T.fg3, tickfont: { size: 10 }, zeroline: false, automargin: true };
  const right = t != null && t > h.lo + 0.7 * (h.hi - h.lo);
  return { data, layout: {
    ...baseLayout(T), dragmode: false, hovermode: 'closest', bargap: 0, barmode: 'stack', showlegend: false,
    margin: { l: 8, r: 12, t: 10, b: 8 },
    xaxis: { ...axis, range: [h.lo, h.hi], ...(ticks ? { tickmode: 'array', tickvals: ticks.tickvals, ticktext: ticks.ticktext } : {}),
      title: { text: axisTitle(o.cof, o.from), font: { size: 10.5, color: T.fg3 }, standoff: 6 } },
    yaxis: { ...axis, rangemode: 'tozero', tickformat: ',d', title: { text: 'cells', font: { size: 10.5, color: T.fg3 }, standoff: 4 } },
    shapes: t == null ? [] : [{ type: 'line', xref: 'x', yref: 'paper', x0: t, x1: t, y0: 0, y1: 1, line: { color: T.accent, width: 2.5 } }],
    annotations: t == null ? [] : [{ x: t, xref: 'x', y: 1, yref: 'paper', yanchor: 'top', xanchor: right ? 'right' : 'left', xshift: right ? -6 : 6,
      showarrow: false, text: fmtNum(o.line), font: { family: PLOT_MONO, size: 11, color: T.fg }, bgcolor: T.hover, bordercolor: T.accent, borderpad: 3 }],
  } };
}

/**
 * A histogram in host. onPick(t) gets the axis value of a click on the plot area or of the
 * dragged line's new place, clamped to [lo, hi].
 * @param {HTMLElement} host
 * @param {(t: number) => void} onPick
 */
export function histogram(host, onPick) {
  let h = null, cur = null, wired = false, press = null, dead = false;
  const clampT = t => Math.min(h.hi, Math.max(h.lo, t));

  function draw(T, channel, o) {
    h = channel; cur = o;
    if (!window.Plotly) { host.textContent = 'Plotly did not load.'; return; }
    const { data, layout } = figure(T, h, o);
    window.Plotly.react(host, data, layout, CONFIG).then(() => {
      if (dead || wired) return;
      wired = true;
      // The line was dragged: Plotly reports the moved shape. Dragging one end moves only that x,
      // so the end that moved further is the new place; the redraw stands the line upright again.
      host.on('plotly_relayout', d => {
        if (!d || !('shapes[0].x0' in d || 'shapes[0].x1' in d)) return;
        const x0 = d['shapes[0].x0'] ?? d['shapes[0].x1'], x1 = d['shapes[0].x1'] ?? x0;
        const before = cur.line == null ? null : scale(cur.cof).toT(cur.line);
        const t = before == null || Math.abs(x0 - before) >= Math.abs(x1 - before) ? x0 : x1;
        if (Number.isFinite(t)) onPick(clampT(t));
      });
    });
  }

  // A press and release on the plot area within CLICK_SLOP_PX is a click. Plotly covers the page
  // while a press lasts, so the release is read on window and the place from the press.
  function down(e) {
    const area = e.button === 0 && h && e.target.closest && e.target.closest('.nsewdrag');
    if (!area) return;
    const r = area.getBoundingClientRect();
    press = { x: e.clientX, y: e.clientY, t: h.lo + ((e.clientX - r.left) / r.width) * (h.hi - h.lo) };
    window.addEventListener('pointerup', up, { once: true });
  }
  function up(e) {
    const p = press;
    press = null;
    if (dead || !p || Math.hypot(e.clientX - p.x, e.clientY - p.y) > CLICK_SLOP_PX) return;
    onPick(clampT(p.t));
  }
  host.addEventListener('pointerdown', down, true);
  const ro = new ResizeObserver(() => { if (window.Plotly && host._fullLayout) window.Plotly.Plots.resize(host); });
  ro.observe(host);

  return {
    draw,
    destroy() {
      dead = true;
      ro.disconnect();
      window.removeEventListener('pointerup', up);
      if (window.Plotly) window.Plotly.purge(host);
    },
  };
}
