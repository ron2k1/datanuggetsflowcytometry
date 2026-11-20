// The plot inspector: points (nuggets or cells), view, axes, the cluster legend, display and the
// run summary. Every control calls ctx.change(mutator, message, opts); the view redraws.
// The cluster legend is whatever part is registered for slot 'plot.legend': render(M, st,
// onChange(msg, typing), onHover(cluster)) -> { tools, acts, list, sum, focusSearch }.
import { el, seg } from '../../shared/dom.js';
import { svg, THUMB } from '../../shared/icons.js';
import { fmtInt } from '../../shared/format.js';
import { transformText } from '../../shared/cofactor.js';
import { clusteringOf, methodText, centersText } from '../../shared/clustering.js';
import { FILE_COLORS, OTHERS, POINT_SCALE } from '../../shared/config.js';
import { plotTheme, fileColor } from '../../shared/plot-base.js';
import { presetAxes, presetOf, SLOTS } from './model.js';
import { drawnKeys, spatialCount } from './figure.js';
import { weightKey } from './sizes.js';
import { slotParts } from '../../shared/views.js';

export const VIEWS = [
  ['2d', '2D', 'Two axes'], ['3d', '3D', 'Three axes, drag to turn'],
  ['pairs', 'Pairs', 'Every pair of the three axes'], ['par', 'Parallel', 'Parallel coordinates over every dimension'],
];
const TAGS = ['x', 'y', 'z'];
const times = v => `${v.toFixed(1)}×`;

// Why the run cannot draw a view, or null when it can. Each axis needs its own dimension, a
// marker, a PC or a component of the view's t-SNE (the 2-D fit in 2D, the 3-D fit in the other
// views that draw axes), so a run with two markers and no PCA has no 3D and no Pairs.
export function viewBlocked(M, view) {
  const tsne = view === '2d' ? M.tsneKeys.length : view === 'par' ? 0 : M.tsne3Keys.length;
  const need = spatialCount(view), have = M.vars.length + M.pcs.length + tsne;
  if (view === 'par' || have >= need) return null;
  const name = VIEWS.find(v => v[0] === view)[1], vars = `${M.vars.length} marker${M.vars.length === 1 ? '' : 's'}`;
  return `${name} needs ${need} dimensions; this run has ${have} (${vars}, ${M.pcs.length} PC${M.pcs.length === 1 ? '' : 's'})`;
}

// Keys a slot may take: markers and PCs; the 2-D t-SNE only on x and y of the 2D view, the
// 3-D t-SNE only on x, y and z of the other views that draw axes.
function options(M, st, slot) {
  const groups = [['Markers', M.vars], ['Principal components', M.pcs]];
  if (st.view === '2d' && slot < 2 && M.tsneKeys.length) groups.push(['t-SNE (2 components)', M.tsneKeys]);
  if (st.view !== '2d' && slot < spatialCount(st.view) && M.tsne3Keys.length) groups.push(['t-SNE (3 components)', M.tsne3Keys]);
  return groups.filter(([, ks]) => ks.length).map(([g, ks]) => [g, ks.map(k => [k, M.label(k, st.units)])]);
}

export function inspector(ctx) {
  const { M, P, man, st } = ctx;
  const secs = [];
  const cellsOk = !(man.settings && man.settings.cells_per_file === 0);

  secs.push(el('div', { class: 'sec inline' }, el('h4', { text: 'Points' }),
    seg('Points', [['nuggets', `Nuggets (${fmtInt(P.nuggets.n)})`], ['cells', ctx.cells ? `Cells (${fmtInt(ctx.cells.n)})` : 'Cells', !cellsOk, cellsOk ? 'Sampled events, each in its cluster colour' : 'This run sampled no cells']],
      M.src, v => ctx.setSrc(v), 'seg full')));

  secs.push(el('div', { class: 'sec' }, el('h4', { text: 'View' }),
    el('div', { class: 'views', role: 'group', 'aria-label': 'View' }, ...VIEWS.map(([v, label, title]) => {
      const blocked = viewBlocked(M, v);
      return el('button', { type: 'button', class: 'vt', 'aria-pressed': String(st.view === v), title: blocked || title, disabled: !!blocked,
        onclick: () => ctx.change(() => {
          const was = presetOf(st.axes, st.view);
          st.view = v;
          if (was === 'tsne') st.axes = presetAxes(M, 'tsne', v);
          fixAxes(M, st);
        }, `View: ${label}`) },
      el('span', { html: THUMB[v] }), el('span', { text: label }));
    }))));

  // Axes: a preset, then one picker per slot.
  const axSec = el('div', { class: 'sec' }, el('h4', { text: 'Axes' }));
  const preset = presetOf(st.axes, st.view);
  const tsneKeys = st.view === '2d' ? M.tsneKeys : st.view === 'par' ? [] : M.tsne3Keys;
  const tsneWhy = M.src === 'cells' ? 't-SNE is fitted on nuggets only' : !M.tsneKeys.length ? 'This run has no t-SNE'
    : st.view === 'par' ? 'Parallel coordinates draw markers and components' : !tsneKeys.length ? 'This run has no 3-D t-SNE: use the 2D view' : null;
  axSec.append(seg('Dimensions', [
    ['vars', 'Markers'],
    ['pca', 'PCA', !M.pcs.length, M.pcs.length ? null : 'This run has no PCA'],
    ['tsne', 't-SNE', !tsneKeys.length, tsneWhy],
  ], preset, p => ctx.change(() => { st.axes = presetAxes(M, p, st.view); fixAxes(M, st); }, `Dimensions: ${p}`, { tween: true }), 'seg full'));
  if (!tsneKeys.length) { const note = tsneNote(ctx); if (note) axSec.append(note); }
  if (st.view === 'par') {
    const n = drawnKeys(M, st).length;
    axSec.append(el('div', { class: 'note', text: `${n} axes, one per ${preset === 'pca' ? 'principal component' : preset === 'vars' ? 'marker' : 'marker and component'}. Drag along an axis to filter lines; drag a title to reorder.` }));
  } else {
    const rows = el('div', { class: 'axes', style: 'margin-top:6px' });
    const n = spatialCount(st.view);
    for (let a = 0; a < n; a++) {
      const label = `${TAGS[a]} axis`;
      const sel = el('select', { 'aria-label': label, onchange: e => {
        const v = e.target.value;
        ctx.change(() => { const other = st.axes.indexOf(v); if (other >= 0) st.axes[other] = st.axes[a]; st.axes[a] = v; fixAxes(M, st); }, `${label}: ${M.label(v, st.units)}`, { tween: true });
      } }, ...options(M, st, a).map(([g, opts]) => el('optgroup', { label: g }, ...opts.map(([k, t]) => el('option', { value: k, selected: st.axes[a] === k, text: t })))));
      const pair = a < n - 1 ? `Swap ${TAGS[a]} and ${TAGS[a + 1]}` : null;
      rows.append(el('div', { class: 'axis-row' }, el('span', { class: 'axis-tag ' + TAGS[a], text: TAGS[a] }), sel,
        pair ? el('button', { type: 'button', class: 'axis-swap', 'aria-label': pair, title: pair, html: svg('swapv'),
          onclick: () => ctx.change(() => { [st.axes[a], st.axes[a + 1]] = [st.axes[a + 1], st.axes[a]]; fixAxes(M, st); }, pair, { tween: true }) }) : null));
    }
    axSec.append(rows);
  }
  secs.push(axSec);

  for (const part of slotParts('plot.legend')) {
    const lg = part.render(M, st, ctx.legendChange, ctx.hover);
    secs.push(el('div', { class: 'sec grow' }, el('h4', {}, `Clusters (${M.colors.size})`), lg.tools, lg.acts, lg.list, lg.sum));
  }

  const disp = el('div', { class: 'sec' }, el('h4', { text: 'Display' }));
  if (M.file && P.files) {
    const tooMany = P.files.length > FILE_COLORS.length;
    disp.append(seg('Colour by', [['cluster', 'Colour by cluster'], ['file', 'Colour by file', tooMany, tooMany ? `More than ${FILE_COLORS.length} files` : null]], st.colorBy,
      c => ctx.change(() => { st.colorBy = c; }, `Colour by ${c}`), 'seg full'));
    const T = plotTheme();
    if (st.colorBy === 'file') disp.append(el('div', { class: 'legend-files' }, ...P.files.map(f =>
      el('div', { title: f.name }, el('span', { class: 'dot', style: `background:${fileColor(T, f.number)}` }), `F${f.number} · ${f.name}`))));
  }
  disp.append(el('div', { class: 'switch-row', title: 'How clusters outside the selection, or the one under the pointer in the legend, are drawn' }, el('span', { text: 'Other clusters' }),
    seg('Other clusters', OTHERS, st.others, o => ctx.change(() => { st.others = o; }, `Other clusters: ${OTHERS.find(([k]) => k === o)[1].toLowerCase()}`), 'seg xs')));
  const canW = !!M.weight && st.view !== 'par';
  const why = !M.weight ? 'Cells have no weight' : st.view === 'par' ? 'Parallel coordinates draw lines' : null;
  disp.append(el('div', { class: 'switch-row', title: why }, el('span', { text: 'Size by nugget weight' }),
    el('button', { type: 'button', class: 'switch', role: 'switch', 'aria-checked': String(st.sizeW && canW), 'aria-label': 'Size by nugget weight', disabled: !canW, title: why,
      onclick: () => ctx.change(() => { st.sizeW = !st.sizeW; }, `Size by weight ${st.sizeW ? 'off' : 'on'}`) })));
  const key = st.sizeW && canW ? el('div', { class: 'size-key', role: 'img', 'aria-label': 'Marker size by nugget weight' }, ...sizeKey(M, st)) : null;
  if (key) disp.append(key);
  disp.append(pointSize(ctx, key));
  secs.push(disp);
  secs.push(runSection(ctx));
  return secs;
}

// The weight sizes' key: a circle per power of ten and one for the largest weight, each at the
// size the view draws a nugget of that weight (sizes.js weightKey), capped at KEY_MAX_PX here.
const KEY_MAX_PX = 48;
function sizeKey(M, st) {
  return weightKey(M, st, st.view).map(k => {
    const px = Math.min(k.size, KEY_MAX_PX);
    return el('span', { class: 'sk', title: `Weight ${fmtInt(k.w)}: ${k.size.toFixed(1)} px across` },
      el('span', { class: 'sk-dot', style: `width:${px}px;height:${px}px` }), el('span', { class: 'sk-w', text: fmtInt(k.w) }));
  });
}

// Point size: a factor on every marker (nuggets, cells, and the weight sizes when those are on).
// Dragging redraws the points, and the size key when it shows, without rebuilding the inspector,
// which would drop the drag; the Activity log gets one line when the slider is let go.
function pointSize(ctx, key) {
  const { st, M } = ctx;
  const can = st.view !== 'par';
  const why = can ? 'Draw every point larger or smaller' : 'Parallel coordinates draw lines';
  const out = el('output', { class: 'size-val', text: times(st.pointScale) });
  const range = el('input', { type: 'range', min: String(POINT_SCALE.min), max: String(POINT_SCALE.max), step: String(POINT_SCALE.step), value: String(st.pointScale),
    'aria-label': 'Point size', 'aria-valuetext': times(st.pointScale), disabled: !can, title: why,
    oninput: e => { st.pointScale = +e.target.value; out.textContent = times(st.pointScale); e.target.setAttribute('aria-valuetext', out.textContent); if (key) key.replaceChildren(...sizeKey(M, st)); ctx.restyle(); },
    onchange: () => ctx.restyle(`Point size ${times(st.pointScale)}`) });
  return el('div', { class: 'switch-row', title: why }, el('span', { text: 'Point size' }), el('span', { class: 'size-ctl' }, range, out));
}

// Keeps the view and st.axes valid: a view the run has too few dimensions for falls back to 2D
// (a two-marker run opens there, not in 3D); then SLOTS distinct keys, the 2-D t-SNE only on 2D
// x/y, the 3-D t-SNE only on x/y/z of the other views that draw axes. A key the view cannot show
// drops out and the keys after it move up, so leaving t-SNE lands on PC1, PC2, ... rather than
// on the first channels.
export function fixAxes(M, st) {
  if (viewBlocked(M, st.view)) st.view = '2d';
  const ok = (k, slot) => M.has(k) && (k[0] === 't' ? st.view === '2d' && slot < 2
    : k[0] === 'u' ? st.view !== '2d' && slot < spatialCount(st.view) : true);
  const out = [];
  st.axes.forEach((k, slot) => { if (ok(k, slot) && !out.includes(k)) out.push(k); });
  for (const k of [...M.pcs, ...M.vars]) if (out.length < SLOTS && !out.includes(k)) out.push(k);
  st.axes = out.slice(0, SLOTS);
}

// Why the t-SNE button is off, in words under it: the tooltip alone left a dead button with no
// visible reason. Parallel coordinates never take t-SNE and say what they draw in their own note.
// The package leaves the 3-D fit out below three columns or nuggets; any other run with a 2-D fit
// and no 3-D one was clustered before the package fitted it (no tsne3d.csv).
function tsneNote(ctx) {
  const { M, P, st } = ctx;
  const has3 = !!(P.tsne && P.tsne.d3), cols = P.columns.length, n = P.nuggets.n;
  const note = (why, link) => el('div', { class: 'note' }, why, ...(link ? [' ', link] : []));
  if (!P.tsne) return note('This run was clustered with t-SNE off, so it has no t-SNE axes.');
  // The nuggets' t-SNE in this view, or in 2D when this view cannot draw it.
  const toTsne = N => { if (st.view === 'par' || (st.view !== '2d' && !has3)) st.view = '2d'; st.axes = presetAxes(N, 'tsne', st.view); };
  if (M.src === 'cells') return note('t-SNE is fitted on the nuggets, so the sampled cells have no t-SNE axes.',
    el('button', { type: 'button', class: 'linkbtn', text: "Show the nuggets' t-SNE", onclick: () => ctx.setSrc('nuggets', toTsne) }));
  if (st.view === '2d' || st.view === 'par' || has3) return null;
  const why = cols < 3 ? `t-SNE in 3D needs three or more markers; this run has ${cols}, so its t-SNE plots in 2D only.`
    : n < 3 ? `t-SNE in 3D needs three or more nuggets; this run has ${n}, so its t-SNE plots in 2D only.`
    : 'This run was clustered before 3-D t-SNE was added. Cluster it again to plot t-SNE in 3D, or use the 2D view.';
  return note(why, el('button', { type: 'button', class: 'linkbtn', text: 'Show the 2-D t-SNE',
    onclick: () => ctx.change(() => { toTsne(M); fixAxes(M, st); }, 'View: 2D, t-SNE') }));
}

function runSection(ctx) {
  const { P, man, S0 } = ctx;
  const s = man.settings || {};
  // The run's transform list ends with its Scale stage, {name: 'scale'}, when it had one.
  const steps = P.transform || [], scaled = steps.some(t => t.name === 'scale');
  // An arcsinh gives its units and how its cofactor was chosen, "arcsinh(x / 150), cofactor
  // set", or the range of the channels' own under per-channel auto.
  const tf = steps.filter(t => t.name !== 'scale').map(t => t.name !== 'arcsinh' ? t.name : transformText(t)).join(', ') || 'none';
  // Settings that name no clustering are a run from before the app sent it: the tree on means.
  const c = clusteringOf(s);
  const kv = [
    ['Run', man.id], ['Clusters', `K=${P.k}`],
    ['Clustering', methodText(c.method)], ['Nugget centers', centersText(c.center_method)],
    ['Nuggets', fmtInt(P.nuggets.n)], ctx.cells ? ['Cells sampled', fmtInt(ctx.cells.n)] : null, ['Transform', tf],
    ['Scale', scaled ? 'mean 0, SD 1, pooled over the files' : 'none'],
    s.seed != null ? ['Seed', String(s.seed)] : null,
    P.groups ? ['Groups', P.groups.join(', ')] : null,
  ].filter(Boolean);
  return el('details', { class: 'sec', open: S0.runOpen, ontoggle: e => { S0.runOpen = e.currentTarget.open; } },
    el('summary', { class: 'run-sum' }, el('span', { html: svg('chev') }), el('h4', { text: 'Run' }), el('span', { class: 'muted', text: man.title })),
    el('dl', { class: 'kv run-kv' }, ...kv.flatMap(([k, v]) => [el('dt', { text: k }), el('dd', { text: v })])),
    (P.warnings || []).length ? el('div', { class: 'note warn', text: P.warnings.join(' ') }) : null,
    el('div', { class: 'links' },
      el('button', { type: 'button', class: 'btn sm', html: svg('files') + '<span>Files</span>', onclick: () => ctx.open(`files:${man.id}`) }),
      el('button', { type: 'button', class: 'btn sm', html: svg('json') + '<span>Run record</span>', onclick: () => ctx.open(`record:${man.id}`) }),
      el('button', { type: 'button', class: 'btn sm', html: svg('compare') + '<span>Compare</span>', onclick: () => ctx.open(`compare:${man.id}`) })));
}
