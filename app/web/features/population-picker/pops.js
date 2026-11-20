// Step "Populations and groups": each file's figure panel next to its populations (payload
// colours) and a group name per file. Next goes on to Live cells, or to Cluster without it.
import { el, fill, docHead, seg } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtInt, fmtNum } from '../../shared/format.js';
import { GROUP_RE } from '../../shared/config.js';
import { getManifest, uploadById, activity } from '../../shared/store.js';
import { clusteringOf } from '../../shared/clustering.js';

export const FIGS = [['local_maxima', 'Local maxima'], ['gates', 'Gate regions']];

// Each file's ticked populations, sorted, [] for a file left out: the pops of every request.
export const popsOf = st => st.sets.map(s => [...s].sort((a, b) => a - b));

// "F1 Pop 1 · F3 Pop 1, 2 (Demo B) · F2 left out", or null when nothing is ticked.
export function choiceText(g, st) {
  const counts = st.sets.map(s => s.size);
  if (!counts.some(Boolean)) return null;
  const picked = g.files.map((f, i) => counts[i] ? `F${f.number} Pop ${popsOf(st)[i].join(', ')}${st.groups[i] ? ` (${st.groups[i]})` : ''}` : null).filter(Boolean);
  const left = g.files.filter((_, i) => !counts[i]).map(f => 'F' + f.number);
  return `${picked.join(' · ')}${left.length ? ` · ${left.join(', ')} left out` : ''}`;
}

// What stops the populations step, or null.
export function popsProblem(g, st) {
  if (!st.sets.some(s => s.size)) return 'Tick at least one population.';
  const named = st.groups.filter(Boolean);
  if (named.length && named.length < g.files.length) return 'Give every file a group name, or leave them all empty.';
  const bad = named.find(x => !GROUP_RE.test(x));
  if (bad) return `"${bad}" is not a usable group name: letters, digits, space and _ . + - only, up to 40 characters.`;
  return null;
}

// File k's panel, cropped out of a figure the package draws two across in equal cells, so the
// question for a file sits next to its own picture.
function panelOf(src, k, n, alt) {
  const cols = Math.min(n, 2), rows = Math.ceil(n / cols);
  const img = el('img', { src, alt, style: `width:${cols * 100}%;left:${-(k % cols) * 100}%;top:${-Math.floor(k / cols) * 100}%` });
  const box = el('div', { class: 'pk-panel' }, img);
  const fit = () => { box.style.aspectRatio = `${img.naturalWidth / cols} / ${img.naturalHeight / rows}`; };
  if (img.complete && img.naturalWidth) fit(); else img.addEventListener('load', fit, { once: true });
  return box;
}

/**
 * @param {HTMLElement} doc  the step's document
 * @param {{g: object, st: object, steps: HTMLElement, next: () => void, nextLabel: string,
 *   redraw: () => void, openTab: (key: string) => void, prior: object|null}} p
 */
export function renderPops(doc, p) {
  const { g, st } = p;
  const n = g.files.length;
  const grid = el('div', { class: 'pk-grid' });
  const sum = el('span', { class: 'sum' }), hint = el('span', { class: 'hint' });
  const go = el('button', { type: 'button', class: 'btn primary', html: `<span>${p.nextLabel}</span>` + svg('chev') });
  let cards = [];

  function card(file, i) {
    const set = st.sets[i];
    const pill = el('span', { class: 'pk-state' });
    const boxes = [];
    const opts = file.populations.map(pop => {
      const box = el('input', { type: 'checkbox', checked: set.has(pop.pop), disabled: !pop.events, 'aria-label': `Pop ${pop.pop} from ${file.name}` });
      box.addEventListener('change', () => { box.checked ? set.add(pop.pop) : set.delete(pop.pop); update(); });
      if (pop.events) boxes.push([box, pop.pop]);
      return el('label', { class: 'pk-opt', title: `Median ${g.settings.fsc} ${fmtInt(Math.round(pop.median_fsc))}, ${g.settings.ssc} ${fmtInt(Math.round(pop.median_ssc))}` },
        box, el('span', { class: 'dot', style: `background:${pop.color || 'var(--fg-3)'}` }),
        el('span', { class: 'nm', text: `Pop ${pop.pop}` }),
        el('span', { class: 'ev', text: `${fmtInt(pop.events)} · ${fmtNum(pop.percent)}%` }));
    });
    const setAll = on => { boxes.forEach(([b, pop]) => { b.checked = on; on ? set.add(pop) : set.delete(pop); }); update(); };
    const group = el('input', { type: 'text', value: st.groups[i], placeholder: 'e.g. control', 'aria-label': `Group for ${file.name}`, maxlength: '40',
      oninput: e => { st.groups[i] = e.target.value.trim(); e.target.classList.toggle('bad', !!st.groups[i] && !GROUP_RE.test(st.groups[i])); update(); } });
    const node = el('div', { class: 'card pk-card' },
      el('div', { class: 'pk-card-head' },
        el('div', {}, el('div', { class: 'pk-file' }, el('span', { class: 'fno', text: 'F' + file.number }), file.name),
          el('div', { class: 'pk-meta', text: `${fmtInt(file.n_events)} events · ${file.local_maxima} local maxima · ${file.populations.length} kept` })),
        pill),
      panelOf(g.figures[st.fig], i, n, `${FIGS.find(f => f[0] === st.fig)[1]} of ${file.name}`),
      el('div', {},
        el('div', { class: 'pk-q', text: `Which populations from ${file.name}?` }),
        el('div', { class: 'pk-list' }, ...opts),
        el('div', { class: 'pk-quick' },
          el('button', { type: 'button', class: 'linkbtn', text: 'Tick all', onclick: () => setAll(true) }),
          el('button', { type: 'button', class: 'linkbtn', text: 'Clear', onclick: () => setAll(false) })),
        el('label', { class: 'field pk-group' }, el('span', { text: 'Group (optional)' }), group)));
    return { node, pill };
  }
  function update() {
    const counts = st.sets.map(s => s.size), total = counts.reduce((a, b) => a + b, 0);
    cards.forEach(({ node, pill }, i) => {
      const k = counts[i], m = g.files[i].populations.length;
      pill.textContent = k ? `${k} of ${m} ticked` : total ? 'Left out' : 'Not chosen yet';
      pill.className = 'pk-state' + (k ? ' yes' : total ? ' skip' : '');
      node.classList.toggle('answered', k > 0);
    });
    sum.textContent = choiceText(g, st) || 'None yet. Tick at least one population above.';
    const problem = total ? popsProblem(g, st) : null;
    if (total && !problem) go.removeAttribute('aria-disabled'); else go.setAttribute('aria-disabled', 'true');
    hint.textContent = problem || '';
    hint.className = 'hint' + (problem ? ' note warn' : '');
  }
  go.addEventListener('click', () => {
    const problem = popsProblem(g, st);
    if (problem) { hint.textContent = problem; hint.className = 'hint note err'; return; }
    p.next();
  });
  cards = g.files.map(card);
  grid.replaceChildren(...cards.map(x => x.node));
  update();

  // Copies a finished run's populations and groups back into the picker, with its k, channels,
  // clustering and nugget centers; a run whose settings name no clustering ran the hierarchical
  // tree on mean centers (shared/clustering.js clusteringOf), and the form takes those.
  const prior = p.prior;
  const useBtn = prior ? el('button', { type: 'button', class: 'btn', text: `Use ${prior.id}'s choice`, onclick: async () => {
    try {
      const m = await getManifest(prior.id);
      const s = m.settings || {};
      (s.pops || []).forEach((pops, i) => { if (st.sets[i]) { st.sets[i].clear(); pops.forEach(v => st.sets[i].add(v)); } });
      if (Array.isArray(s.groups)) s.groups.forEach((x, i) => { st.groups[i] = x || ''; });
      if (s.k) st.form.k = s.k;
      Object.assign(st.form, clusteringOf(s));
      if (Array.isArray(s.channels)) st.channels = new Set(s.channels);
      activity(`Picker filled from ${prior.id}: pops ${JSON.stringify(s.pops)}, groups ${JSON.stringify(s.groups)}`);
      p.redraw();
    } catch (e) { hint.textContent = e.message; }
  } }) : null;

  const demo = g.files.some(f => { const u = uploadById(f.upload); return u && u.demo; });
  const figSeg = seg('Picture in each file', FIGS.map(([k, t]) => [k, t]), st.fig, v => { st.fig = v; p.redraw(); });
  fill(doc,
    p.steps,
    docHead('Which populations should be clustered?', `Gating found the populations below in ${n} file${n === 1 ? '' : 's'}. Tick the ones to keep from each file and name a group per file if you want to compare groups, then press Next at the bottom. Pop numbers belong to each file, so Pop 1 here can be a different peak in another file; shares can add past 100% because populations can overlap.`,
      el('div', { class: 'pk-tools' }, figSeg, el('button', { type: 'button', class: 'btn', text: 'Full figure', onclick: () => p.openTab(`figure:${g.id}:${st.fig}`) }))),
    demo ? el('div', { class: 'callout info', style: 'margin-bottom:12px', text: 'These are public PBMC demo files. Group names you give them are labels for trying the comparison screens, not experimental conditions.' }) : null,
    grid,
    el('div', { class: 'step-bar' }, el('div', { class: 'step-bar-text' }, el('span', { class: 'lbl', text: 'Your choice' }), sum, hint), useBtn, go));
}
