// The cluster's box plots (docs/app/cluster-panel.md), drawn by the box plots tab (tab.js) at the
// page's width: one cluster's cells per sample group or file,
// exact from the nugget weights; every marker's box over the cluster's sampled cells, groups
// pooled, beside the rest of the run's; and one marker's box for the cluster, each group in it
// and the rest. Charts are Plotly boxes from stats.js's numbers (no points), coloured like
// Compare's groups; the rest's boxes are hollow, apart from the reference group's filled grey.
// Each box carries its numbers (numbers.js): median [Q1, Q3] beside it, a hover label over it,
// its cell count in the key or its row, and a table under each box chart.
import { el } from '../../shared/dom.js';
import { fmtInt, fmtNum, fmtPct, hexA } from '../../shared/format.js';
import { BOX_MIN_CELLS } from '../../shared/config.js';
import { plotTheme, baseLayout, groupColor, fileColor, PLOT_MONO } from '../../shared/plot-base.js';
import { counts, cellWeights, boxes, level } from './stats.js';
import { boxLabel, boxHover, hoverPoints, MARKER_HEAD, markerRows, PART_HEAD, partRows } from './numbers.js';

const CONFIG = { responsive: false, displaylogo: false, displayModeBar: false, scrollZoom: false };
const ROW = 22;                         // px per bar or box
const PAIR = 30;                        // px per marker's cluster and rest boxes
const SHIFT = 0.19, NARROW = 0.32;      // a pair's boxes: offset from the row and width, in rows
const MARGIN = { l: 8, r: 12, t: 6, b: 34 };
const BOX_MARGIN = { ...MARGIN, b: 24 };  // box charts have no axis title; their notes give the units
const LABEL = { size: 9.5, em: 0.6 };   // the column beside the boxes: font px, a mono digit's width in em
// A row name on the one-marker chart's axis is cut to this many characters, so a very long file
// name leaves room for the boxes and their label column; its hover and table row give it in full.
const NAME_CHARS = 40;
const clip = s => (s.length > NAME_CHARS ? s.slice(0, NAME_CHARS - 1) + '…' : s);
const share = (a, b) => (b ? fmtPct((100 * a) / b) : '–');
const axis = (T, title, extra = {}) => ({ title: { text: title, font: { size: 11, color: T.fg2 } }, gridcolor: T.grid, linecolor: T.line, color: T.fg3, tickfont: { size: 10 }, automargin: true, zeroline: false, fixedrange: true, ...extra });
// Rows by position, top to bottom, so two markers with one short name keep a box each.
const rows = (T, labels) => axis(T, '', { tickvals: labels.map((_, i) => i), ticktext: labels, autorange: 'reversed', showgrid: false, title: null });
const height = n => 46 + ROW * Math.max(n, 1);
const partColor = (T, p) => (p.gi != null ? groupColor(T, p.gi) : fileColor(T, p.file));
const ARROW = { high: ' ↑', low: ' ↓', mid: '' };
const SAYS = { high: 'higher than the rest of the run', low: 'lower than the rest of the run', mid: "inside the rest's middle half" };
const quartiles = s => `median ${fmtNum(s.median)}, quartiles ${fmtNum(s.q1)} to ${fmtNum(s.q3)}`;

// Horizontal boxes at rows ys, one per stats object in S, filled with color or hollow. Plotly
// labels a box's five numbers separately, piled over each other on a horizontal box, so the
// boxes skip hover and hoverTrace's points along them carry one label per box, its hover and
// click events, and the chart's readout line.
const boxTrace = (ys, S, color, { hollow = false, width = 0.6 } = {}) => ({
  type: 'box', orientation: 'h', y: ys, boxpoints: false, whiskerwidth: 0.5, hoverinfo: 'skip', width,
  q1: S.map(s => s.q1), median: S.map(s => s.median), q3: S.map(s => s.q3),
  lowerfence: S.map(s => s.lo), upperfence: S.map(s => s.hi),
  fillcolor: hollow ? 'rgba(0,0,0,0)' : hexA(color, 0.32), line: { color, width: hollow ? 1.4 : 1.2 },
});
// Invisible points whisker to whisker along each box of items [{ y, s, hover }] (numbers.js).
const hoverTrace = items => ({
  type: 'scatter', mode: 'markers', ...hoverPoints(items), showlegend: false,
  marker: { size: 8, color: 'rgba(0,0,0,0)' }, hovertemplate: '%{text}<extra></extra>',
});
// The median [Q1, Q3] column in the right margin, one label per box of items [{ y, s, ink }],
// and the margin that holds the longest in the plot's monospace font.
function labelColumn(items) {
  const text = items.map(it => boxLabel(it.s));
  return {
    annotations: items.map((it, i) => ({ xref: 'paper', x: 1, xanchor: 'left', xshift: 6, yref: 'y', y: it.y, text: text[i],
      showarrow: false, font: { family: PLOT_MONO, size: LABEL.size, color: it.ink } })),
    r: 14 + Math.ceil(LABEL.em * LABEL.size * Math.max(0, ...text.map(t => t.length))),
  };
}
// A chart's numbers as a table: head, then rows whose first cell names the row. The name column
// stays put while the numbers scroll sideways, cut short with its full text as its title.
const numTable = (head, body) => el('div', { class: 'cp-table' }, el('table', {},
  el('thead', {}, el('tr', {}, ...head.map(h => el('th', { scope: 'col', text: h })))),
  el('tbody', {}, ...body.map(r => el('tr', {}, el('th', { scope: 'row', title: r[0], text: r[0] }), ...r.slice(1).map(v => el('td', { text: v })))))));

// Draws ctx.cluster's box plots into box and returns the cleanup that frees its charts.
// ctx: { P, st, cluster, color(c), cells, cellsWhy, column(j), label(j, short), units, tools }:
// tools are the head's controls, at its right. It keeps the marker split by group in st.boxMarker.
// Each section has a class (cp-counts, cp-markers, cp-one) the tab's grid places it by.
export function renderPanel(box, ctx) {
  const { P, st, cluster: c } = ctx;
  const n = counts(P, c), colour = ctx.color(c);
  const charts = [];
  let dead = false;
  const boxText = (name, s, k) => `${name}\n${quartiles(s)}, whiskers ${fmtNum(s.lo)} to ${fmtNum(s.hi)} · ${fmtInt(k)} sampled cells`;
  // The row under the pointer: a pair's boxes sit SHIFT either side of it.
  const rowOf = ev => { const p = ev && ev.points && ev.points[0]; return p && Number.isFinite(p.y) ? Math.round(p.y) : null; };

  // A chart: draw(T) -> { data, layout }, drawn into its own host once the panel is in the page.
  // read(row): its readout line for the box at row, or for row null its resting line.
  const chart = (draw, cls = '', read = null) => {
    const ch = { host: el('div'), draw, read, click: null, wired: false };
    ch.out = read ? el('div', { class: 'cp-read', 'aria-live': 'polite' }) : null;
    charts.push(ch);
    ch.box = el('div', { class: 'cp-chart' + (cls ? ' ' + cls : '') }, ch.host, ch.out);
    return ch;
  };
  const plot = ch => {
    if (!window.Plotly) { ch.host.replaceChildren(el('div', { class: 'fallback', text: 'Plotly did not load.' })); return; }
    const T = plotTheme(), { data, layout } = ch.draw(T);
    ch.host.style.height = `${layout.height}px`;
    if (ch.read) ch.out.textContent = ch.read(null);
    ch.busy = window.Plotly.react(ch.host, data, { ...baseLayout(T), dragmode: false, showlegend: false, hovermode: 'closest', ...layout }, CONFIG).then(() => {
      if (dead || ch.wired) return;
      ch.wired = true;
      ch.host.on('plotly_click', ev => { const y = rowOf(ev); if (ch.click && y != null) ch.click(y); });
      if (!ch.read) return;
      ch.host.on('plotly_hover', ev => { const y = rowOf(ev); if (y != null) ch.out.textContent = ch.read(y); });
      ch.host.on('plotly_unhover', () => { ch.out.textContent = ch.read(null); });
    });
  };

  const secs = [el('div', { class: 'cp-head' },
    el('span', { class: 'sw', style: `background:${colour}` }),
    el('div', { class: 'cp-title' },
      el('h3', { text: `Cluster ${c}` }),
      el('div', { class: 'cp-sub', text: `${fmtInt(n.cells)} cells · ${share(n.cells, n.total)} of the run · ${fmtInt(n.nuggets)} nugget${n.nuggets === 1 ? '' : 's'}` })),
    ...(ctx.tools || []))];

  // 1. Cells per group (or file): exact, from the nugget weights.
  const ps = n.parts, byGroup = ps.length > 0 && ps[0].gi != null, unit = byGroup ? 'group' : 'file';
  if (ps.length) {
    const top = Math.max(1, ...ps.map(p => p.count));
    const bars = chart(T => ({
      data: [{
        type: 'bar', orientation: 'h', y: ps.map((_, i) => i), x: ps.map(p => p.count),
        marker: { color: ps.map(p => partColor(T, p)), line: { width: 0 } },
        text: ps.map(p => `${fmtInt(p.count)} · ${share(p.count, p.of)}`), textposition: 'outside', cliponaxis: false,
        textfont: { size: 10.5, color: T.fg2 },
        hovertext: ps.map(p => `${p.label}: ${fmtInt(p.count)} of its ${fmtInt(p.of)} kept cells (${share(p.count, p.of)})`),
        hovertemplate: '%{hovertext}<extra></extra>',
      }],
      layout: { height: height(ps.length), margin: MARGIN, bargap: 0.35,
        xaxis: axis(T, `Cells in cluster ${c}`, { range: [0, top * 1.45], tickformat: '~s' }), yaxis: rows(T, ps.map(p => p.label)) },
    }));
    secs.push(el('section', { class: 'cp-sec cp-counts' }, el('h4', { text: `Cells per ${unit}` }), bars.box,
      el('div', { class: 'note', text: `Exact: the sum of the cluster's nugget weights in each ${unit}, then its share of that ${unit}'s kept cells.` })));
  }

  // 2 and 3 need the sampled cells.
  const markers = P.columns.map((_, j) => j);
  const sec2 = (...kids) => el('section', { class: 'cp-sec cp-markers' }, el('h4', { text: `Markers: cluster ${c} and the rest` }), ...kids);
  const B = ctx.cells ? (w => markers.map(j => boxes(P, ctx.cells, ctx.column(j), c, w)))(cellWeights(P, ctx.cells)) : null;
  const sampled = B && B.length ? B[0].n : 0, restN = B && B.length ? B[0].restN : 0;
  if (!B) {
    secs.push(sec2(el('div', { class: 'note', text: ctx.cellsWhy === 'loading' ? 'Loading the sampled cells…'
      : ctx.cellsWhy === 'none' ? 'This run sampled no cells (cells_per_file = 0), so it has no boxes.'
      : `The sampled cells did not load: ${ctx.cellsWhy}` })));
  } else if (sampled < BOX_MIN_CELLS) {
    secs.push(sec2(el('div', { class: 'note', text: `${fmtInt(sampled)} sampled cells fall in cluster ${c}; a box needs ${BOX_MIN_CELLS}.` })));
  } else {
    if (!(st.boxMarker >= 0 && st.boxMarker < markers.length)) st.boxMarker = 0;
    const hasRest = B[0].rest != null;
    const tick = j => ctx.label(j, true) + (ARROW[level(B[j].all, B[j].rest)] || '');
    // Each marker's row: the cluster's box above, the rest's hollow box below; ↑ or ↓ on a marker
    // whose cluster median leaves the rest's middle half.
    const all = chart(T => {
      const at = markers.flatMap(j => [
        { y: j - (hasRest ? SHIFT : 0), s: B[j].all, ink: T.fg, hover: boxHover(`${ctx.label(j)}, cluster ${c}`, B[j].all, B[j].n) },
        ...(hasRest ? [{ y: j + SHIFT, s: B[j].rest, ink: T.fg3, hover: boxHover(`${ctx.label(j)}, rest of the run`, B[j].rest, B[j].restN) }] : []),
      ]);
      const col = labelColumn(at);
      return {
        data: [
          boxTrace(markers.map(j => j - (hasRest ? SHIFT : 0)), B.map(b => b.all), colour, { width: hasRest ? NARROW : 0.6 }),
          hasRest ? boxTrace(markers.map(j => j + SHIFT), B.map(b => b.rest), T.fg3, { hollow: true, width: NARROW }) : null,
          hoverTrace(at),
        ].filter(Boolean),
        // The scale on top: this chart runs to a row per marker, taller than the window.
        layout: { height: 30 + (hasRest ? PAIR : ROW) * markers.length, margin: { ...BOX_MARGIN, t: 24, b: 6, r: col.r }, annotations: col.annotations,
          xaxis: axis(T, null, { side: 'top' }), yaxis: rows(T, markers.map(tick)) },
      };
    }, ps.length ? 'clickable' : '', y => {
      const j = y == null ? st.boxMarker : y, b = B[j], lv = level(b.all, b.rest);
      return `${ctx.label(j)}${lv ? `: ${SAYS[lv]}` : ''}\nCluster ${c}: ${quartiles(b.all)}\nRest: ${b.rest ? quartiles(b.rest) : 'no box'}`;
    });
    // n: the sampled cells behind every box of that kind, the same for each marker.
    const key = el('div', { class: 'cp-key' },
      el('span', { class: 'ki' }, el('span', { class: 'kd', style: `background:${hexA(colour, 0.32)};border-color:${colour}` }), `Cluster ${c} · n = ${fmtInt(sampled)}`),
      hasRest ? el('span', { class: 'ki' }, el('span', { class: 'kd hollow' }), `Rest of the run · n = ${fmtInt(restN)}`) : null);
    secs.push(sec2(key, all.box, numTable(MARKER_HEAD, markerRows(markers.map(tick), B)), el('div', { class: 'note', text:
      `${fmtInt(sampled)} sampled cells in the cluster, ${fmtInt(restN)} in the rest, each counted as its file's kept over sampled cells. `
      + `Values: ${ctx.units}. Boxes are weighted quartiles; whiskers reach the last value within 1.5 IQR. Beside each box: its median [Q1, Q3]; hover a box for all its numbers. `
      + `${hasRest ? "↑ or ↓: the cluster's median is above the rest's upper quartile or below its lower one. " : `The rest has fewer than ${BOX_MIN_CELLS} sampled cells, so it has no box. `}`
      + `${ps.length ? `Click a marker to split it by ${unit} below.` : ''}` })));

    // 3. One marker for the cluster, each group (or file) in it, and the rest.
    if (ps.length) {
      // Its rows, top to bottom: the cluster, each group or file in it, the rest. Every row
      // shows its sampled cells; s is null where too few fell there for a box.
      const oneRows = b => [
        { label: `Cluster ${c}`, name: `Cluster ${c}, all ${unit}s`, s: b.all, n: b.n },
        ...b.parts.map(p => ({ label: p.label, name: `${p.label} in cluster ${c}`, s: p.stats, n: p.n, part: p })),
        ...(b.rest ? [{ label: 'Rest of the run', name: 'Rest of the run', s: b.rest, n: b.restN, rest: true }] : []),
      ];
      const one = chart(T => {
        const R = oneRows(B[st.boxMarker]);
        const at = R.map((r, y) => ({ ...r, y, ink: r.rest ? T.fg3 : T.fg, hover: r.s ? boxHover(r.name, r.s, r.n) : '' })).filter(r => r.s);
        const col = labelColumn(at);
        return {
          data: [
            ...at.map(r => boxTrace([r.y], [r.s], r.rest ? T.fg3 : r.part ? partColor(T, r.part) : colour, { hollow: !!r.rest })),
            hoverTrace(at),
          ],
          layout: { height: 30 + ROW * R.length, margin: { ...BOX_MARGIN, r: col.r }, annotations: col.annotations,
            xaxis: axis(T, null), yaxis: rows(T, R.map(r => `${clip(r.label)} (${fmtInt(r.n)})`)) },
        };
      }, '', y => {
        const R = oneRows(B[st.boxMarker]), r = y != null && R[y] && R[y].s ? R[y] : R[0];
        return boxText(r.name, r.s, r.n);
      });
      const oneTable = el('div');
      const fillTable = () => oneTable.replaceChildren(numTable(PART_HEAD, partRows(oneRows(B[st.boxMarker]))));
      const few = el('div', { class: 'note' });
      const fewText = () => {
        const out = B[st.boxMarker].parts.filter(p => !p.stats).map(p => p.label);
        few.textContent = out.length ? `No box for ${out.join(', ')}: fewer than ${BOX_MIN_CELLS} sampled cells there (the count is in brackets).` : '';
      };
      const sel = el('select', { 'aria-label': `Marker to split by ${unit}`, onchange: e => pick(+e.target.value) },
        ...markers.map(j => el('option', { value: String(j), selected: j === st.boxMarker, text: ctx.label(j) })));
      const pick = j => { st.boxMarker = j; sel.value = String(j); fewText(); fillTable(); all.out.textContent = all.read(null); plot(one); };
      all.click = pick;
      fewText();
      fillTable();
      secs.push(el('section', { class: 'cp-sec cp-one' }, el('h4', {}, `One marker by ${unit}`, sel), one.box, oneTable, few));
    }
  }

  box.replaceChildren(...secs);
  charts.forEach(plot);
  // The page's width follows the window; redraw the charts at the new width.
  const ro = new ResizeObserver(() => { if (window.Plotly) for (const ch of charts) if (ch.host._fullLayout) window.Plotly.Plots.resize(ch.host); });
  ro.observe(box);
  // A draw ends by reading the chart's layout (an automargin redraw can still be queued), so a
  // chart is purged once its last draw settles: the cells arriving re-render a panel mid-draw.
  return () => {
    dead = true;
    ro.disconnect();
    if (window.Plotly) for (const ch of charts) { const free = () => window.Plotly.purge(ch.host); Promise.resolve(ch.busy).then(free, free); }
  };
}
