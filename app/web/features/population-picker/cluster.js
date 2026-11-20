// Step "Cluster": the Transform and Scale stages, then the cluster settings (k, the clustering
// and the nugget centers among them), channels, row filters and t-SNE, then Cluster (POST
// /flow/runs). The draws and the weighted k-means starts and rounds are never sent: a run takes
// the package's. What the Live cells step hands on arrives through applyHandoff: its filters
// join the filter builder, and the viability dye is unticked in the channels.
import { el, fill, docHead } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { S, caps } from '../../shared/store.js';
import { FLOW_TRANSFORMS, FLOW_METHODS, CENTER_METHODS } from '../../shared/config.js';
import { numField, autoNumField, checkField, selectField, kSlider, filterBuilder, filterProblem } from '../../shared/forms.js';
import { autoText } from '../../shared/cofactor.js';
import { centersText } from '../../shared/clustering.js';
import { choiceText, popsOf } from './pops.js';

// v when the list offers it, else the list's first entry, the package's default.
const offered = (list, v) => (list.some(([x]) => x === v) ? v : list[0][0]);
// The centers the select offers, and v as an option of its own when they don't hold it: the
// package's "random" centers, which the API takes and "Use rX's choice" copies from such a run.
// The select then shows what Cluster sends.
const centersOffered = v => (CENTER_METHODS.some(([x]) => x === v) ? CENTER_METHODS
  : [...CENTER_METHODS, [v, `${centersText(v)} (the copied run's)`]]);

// transform 'none' is sent as cofactor 0; cofactor is 'auto' (the server's default, picked per
// channel from the cells the run clusters) or a typed number for every channel, and is kept for a
// switch back from None. method and center_method start on /config's defaults, or the first of
// FLOW_METHODS and CENTER_METHODS when /config names none the selects offer.
export function clusterForm() {
  const d = (S.config && S.config.defaults && S.config.defaults.cluster) || {};
  const c = d.cofactor ?? 'auto';
  return { k: d.k ?? 8, method: offered(FLOW_METHODS, d.method), center_method: offered(CENTER_METHODS, d.center_method),
    transform: c === 0 ? 'none' : 'arcsinh', cofactor: typeof c === 'number' && c > 0 ? c : 'auto', standardize: d.standardize ?? true,
    dn_num1: d.dn_num1 ?? 10000, dn_num2: d.dn_num2 ?? 1000, seed: d.seed ?? 291102,
    tsne: d.tsne ?? true, tsne_perplexity: d.tsne_perplexity ?? 30, tsne_seed: d.tsne_seed ?? 0, cells_per_file: d.cells_per_file ?? 2000, row_filters: [] };
}

// The cofactor the run gets: 'auto' or a number, 0 (linear) when the Transform stage is None.
export const cofactorOf = f => (f.transform === 'none' ? 0 : f.cofactor);

// What auto does, with the floor from the rule in /config. Auto reads the cells the run
// clusters, so there is no number to show before the run starts.
const autoLine = () => autoText(S.config && S.config.defaults ? S.config.defaults.cofactor_auto : null);

// The two stages between the populations and the nuggets, a card each, in run order. update
// recomputes the Cluster button's state after the transform or the cofactor changes.
function stages(f, update) {
  const head = name => el('div', { class: 'pk-stage-head' }, el('h3', { text: name }));
  const cof = autoNumField(f, 'cofactor', 'Cofactor', { min: 0, autoLine,
    hint: 'Near linear below the cofactor, logarithmic above it. A number applies to every channel.' }, update);
  cof.hidden = f.transform !== 'arcsinh';
  const pick = el('select', { 'aria-label': 'Transform', onchange: e => { f.transform = e.target.value; cof.hidden = f.transform !== 'arcsinh'; update(); } },
    ...FLOW_TRANSFORMS.map(([v, t]) => el('option', { value: v, selected: f.transform === v, text: t })));
  return el('div', { class: 'pk-stages' },
    el('section', { class: 'pk-stage', 'aria-label': 'Transform' }, head('Transform'),
      el('div', { class: 'pk-stage-body' }, el('label', { class: 'field' }, el('span', { text: 'Applied to every clustered channel' }), pick), cof)),
    el('section', { class: 'pk-stage', 'aria-label': 'Scale' }, head('Scale'),
      el('div', { class: 'pk-stage-body' }, checkField(f, 'standardize', 'Scale every channel to standard deviation 1'),
        el('small', { class: 'pk-stage-hint', text: 'Pooled over all files, so no channel’s spread outweighs the others.' }))));
}

/**
 * Takes what the Live cells step hands on, replacing what it handed on before; null (Skip) takes
 * back the earlier filters and re-ticks an earlier dye.
 * @param {object} st  the picker's state
 * @param {{row_filters: import('../../shared/api/client.js').Filter[], exclude: string|null}|null} result
 */
export function applyHandoff(st, result) {
  const rows = st.form.row_filters;
  for (const f of st.live.handed || []) { const i = rows.indexOf(f); if (i >= 0) rows.splice(i, 1); }
  const filters = result ? result.row_filters.map(f => ({ ...f })) : [];
  rows.push(...filters);
  if (st.dye && st.dye !== (result && result.exclude)) st.channels.add(st.dye);
  st.dye = (result && result.exclude) || null;
  if (st.dye) st.channels.delete(st.dye);
  st.live.handed = filters;
}

// channels and exclude_channels for the run: null + [dye] when the ticks are the defaults less
// the dye, so the package applies its own default rule; otherwise the ticked list and [], since
// the package refuses the two together.
export function channelsOf(g, st) {
  const ticked = [...st.channels];
  const defaults = g.files[0] ? g.files[0].default_channels : [];
  const dye = st.dye;
  if (dye && defaults.includes(dye)) {
    const rest = defaults.filter(c => c !== dye);
    if (ticked.length === rest.length && rest.every(c => st.channels.has(c))) return { channels: null, exclude_channels: [dye] };
  }
  return { channels: ticked, exclude_channels: [] };
}

/**
 * @param {HTMLElement} doc
 * @param {{g: object, st: object, steps: HTMLElement, back: () => void, backLabel: string,
 *   start: (body: object) => Promise<void>}} p
 */
export function renderCluster(doc, p) {
  const { g, st } = p;
  const c = caps() || {};
  const f = st.form;
  const sum = el('span', { class: 'sum', text: choiceText(g, st) || '' }), hint = el('span', { class: 'hint' });
  const go = el('button', { type: 'button', class: 'btn primary', html: svg('play') + '<span>Cluster</span>' });
  const total = st.sets.reduce((a, s) => a + s.size, 0);
  // The button names k, so the number of clusters is in sight where the run starts.
  const label = () => { go.querySelector('span').textContent = `Cluster ${total} population${total === 1 ? '' : 's'} into ${f.k} clusters`; };
  label();

  function problem() {
    if (st.channels.size < 2) return 'Pick at least two channels to cluster.';
    if (f.transform === 'arcsinh' && f.cofactor !== 'auto' && !(f.cofactor > 0)) return 'The arcsinh cofactor must be above 0. For no transform, pick None (linear).';
    return filterProblem(f.row_filters);
  }
  function update() {
    const pr = problem();
    if (pr) go.setAttribute('aria-disabled', 'true'); else go.removeAttribute('aria-disabled');
    hint.textContent = pr || '';
    hint.className = 'hint' + (pr ? ' note warn' : '');
    chanSum.textContent = `Channels to cluster (${st.channels.size} picked)`;
  }
  go.addEventListener('click', async () => {
    const pr = problem();
    if (pr) { hint.textContent = pr; hint.className = 'hint note err'; return; }
    const named = st.groups.some(Boolean);
    const body = { gate_id: g.id, pops: popsOf(st), groups: named ? st.groups : null,
      ...channelsOf(g, st), row_filters: f.row_filters, k: f.k, method: f.method, center_method: f.center_method,
      cofactor: cofactorOf(f), standardize: f.standardize,
      dn_num1: f.dn_num1, dn_num2: f.dn_num2, seed: f.seed, tsne: f.tsne, tsne_perplexity: f.tsne_perplexity,
      tsne_seed: f.tsne_seed, cells_per_file: f.cells_per_file };
    go.disabled = true;
    try { await p.start(body); }
    catch (e) { hint.textContent = e.param ? `${e.param}: ${e.message}` : e.message; hint.className = 'hint note err'; go.disabled = false; }
  });

  const allChans = g.files[0] ? g.files[0].channels : [];
  const nameOf = pnn => { const ch = allChans.find(x => x.pnn === pnn); return ch && ch.pns ? `${ch.pns} (${pnn})` : pnn; };
  const chanBox = el('div', { class: 'checks' }, ...allChans.map(ch => el('label', { class: 'check', title: ch.pnn },
    el('input', { type: 'checkbox', checked: st.channels.has(ch.pnn), onchange: e => { e.target.checked ? st.channels.add(ch.pnn) : st.channels.delete(ch.pnn); update(); } }),
    ch.pns ? `${ch.pns} (${ch.pnn})` : ch.pnn)));
  const chanSum = el('summary');
  const filterCols = allChans.map(ch => ({ name: ch.pnn, label: ch.pns, numeric: true }));
  const handed = (st.live.handed || []).filter(x => f.row_filters.includes(x)).length;
  const from = handed || st.dye
    ? el('div', { class: 'callout info pk-from', text: `From Live cells: ${[handed ? `${handed} row filter${handed === 1 ? '' : 's'}, below under Row filters, where you can change them` : null, st.dye ? `${nameOf(st.dye)} left out of the channels` : null].filter(Boolean).join('; ')}.` })
    : null;
  fill(doc,
    p.steps,
    docHead('Cluster settings', 'The populations you picked are transformed, scaled, then clustered with these settings. Press Cluster at the bottom to start the run.'),
    from,
    stages(f, update),
    el('details', { class: 'more', open: true }, el('summary', { text: 'Cluster settings' }),
      el('div', { class: 'form-grid' }, kSlider(f, 'k', 'Clusters (k)', label),
        selectField(f, 'method', 'Clustering', FLOW_METHODS,
          { hint: 'Weighted k-means is WCluster’s Wkmeans; the hierarchical tree is its Whclust, cut into k clusters.' }),
        selectField(f, 'center_method', 'Nugget centers', centersOffered(f.center_method),
          { hint: 'Original points: each nugget’s center is one of its own cells. Means: the mean of its cells.' }),
        numField(f, 'dn_num1', 'Nuggets per file, first pass', { min: 3, int: true, max: c.dn_num1_max, cap: true }),
        numField(f, 'dn_num2', 'Nuggets per file, kept', { min: 2, int: true, max: c.dn_num2_max, cap: true }),
        numField(f, 'cells_per_file', 'Cells per file for the plot', { min: 0, int: true, max: c.cells_per_file_max, cap: true }),
        numField(f, 'seed', 'Seed', { min: 0, int: true }))),
    el('details', { class: 'more', open: !!st.dye }, chanSum, chanBox,
      el('div', { class: 'note', text: 'The default is every -A channel except forward and side scatter.' }),
      st.dye ? el('div', { class: 'note', text: `${nameOf(st.dye)} is unticked: the Live cells step left the viability dye out of the clustering. Tick it to cluster on it.` }) : null),
    el('details', { class: 'more', open: f.row_filters.length > 0 }, el('summary', { text: 'Row filters and t-SNE' }),
      filterBuilder(f.row_filters, filterCols, update),
      el('div', { class: 'form-grid', style: 'margin-top:12px' },
        el('div', { class: 'field' }, el('span', { text: 't-SNE' }), checkField(f, 'tsne', 'Draw a t-SNE of the nuggets')),
        numField(f, 'tsne_perplexity', 't-SNE perplexity', { min: 1 }), numField(f, 'tsne_seed', 't-SNE seed', { min: 0, int: true }))),
    el('div', { class: 'step-bar' }, el('div', { class: 'step-bar-text' }, el('span', { class: 'lbl', text: 'Your choice' }), sum, hint),
      el('button', { type: 'button', class: 'btn', html: svg('back') + `<span>${p.backLabel}</span>`, onclick: p.back }), go));
  update();
}
