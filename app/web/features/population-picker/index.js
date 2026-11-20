// A finished gate, in steps: Populations and groups (pops.js), then Live cells when a part is
// registered for slot 'gate.livecells', then Cluster (cluster.js). The step and every choice live
// in S.view[key], so a redraw, a tab switch or Back keeps them.
//
// Slot 'gate.livecells': a part is { render(host, ctx) -> cleanup | void }, drawing the whole step
// into host. ctx: { gid, gate, pops (one sorted list per file), cofactor (the cluster form's
// Transform stage: 'auto', a typed number, or 0 for None),
// choice (the populations as text), steps (the step indicator to show first), state (an object
// kept for the part across redraws), back(), skip(), done({ row_filters, exclude }) }. done hands
// on Filter objects for the filter builder and the channel to leave out of the clustering, or null.
import { el } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { api } from '../../shared/api/index.js';
import { EV } from '../../shared/events.js';
import { S, emit, idOf, getGate, gateById, gateJob, gateLog, flowRuns } from '../../shared/store.js';
import { registerView, slotParts } from '../../shared/views.js';
import { renderPops, popsOf, choiceText } from './pops.js';
import { renderCluster, clusterForm, applyHandoff, cofactorOf } from './cluster.js';

const openTab = key => emit(EV.openTab, { key });
const STEP_NAMES = { pops: 'Populations and groups', live: 'Live cells', cluster: 'Cluster' };
const CRUMBS = { pops: 'Populations', live: 'Live cells', cluster: 'Cluster' };

function stepBar(order, now) {
  const at = order.indexOf(now);
  return el('div', { class: 'pk-steps', 'aria-label': 'Flow steps' },
    el('span', { class: 'st done' }, el('b', { html: svg('check') }), 'Gate files'),
    ...order.flatMap((s, i) => [el('span', { class: 'sep' }),
      el('span', { class: 'st' + (i < at ? ' done' : i === at ? ' now' : ''), 'aria-current': i === at ? 'step' : null },
        i < at ? el('b', { html: svg('check') }) : el('b', { text: String(i + 2) }), STEP_NAMES[s])]));
}

// Draws the step st.step names; returns the live-cells part's cleanup when it drew that step.
function renderGate(body, key, g, redraw) {
  const st = S.view[key] || (S.view[key] = {
    step: 'pops', sets: g.files.map(() => new Set()), groups: g.files.map(() => ''), fig: 'local_maxima', form: clusterForm(),
    channels: new Set(g.files[0] ? g.files[0].default_channels : []), dye: null, live: {},
  });
  const part = slotParts('gate.livecells')[0] || null;
  const order = part ? ['pops', 'live', 'cluster'] : ['pops', 'cluster'];
  if (!order.includes(st.step)) st.step = 'cluster';
  // A step change redraws everything, so the crumbs follow and the editor scrolls to the top.
  const go = step => { st.step = step; emit(EV.render); };
  const steps = stepBar(order, st.step);
  const doc = el('div', { class: 'doc' });
  body.append(doc);

  if (st.step === 'pops') {
    renderPops(doc, { g, st, steps, redraw, openTab, next: () => go(part ? 'live' : 'cluster'),
      nextLabel: part ? 'Next: Live cells' : 'Next: Cluster settings',
      prior: flowRuns().find(r => r.source === g.id) || null });
    return null;
  }
  if (st.step === 'live') {
    const host = el('div', { class: 'pk-live' });
    doc.append(host);
    return part.render(host, {
      gid: g.id, gate: g, pops: popsOf(st), cofactor: cofactorOf(st.form), choice: choiceText(g, st), steps, state: st.live,
      back: () => go('pops'),
      skip: () => { applyHandoff(st, null); go('cluster'); },
      done: result => { applyHandoff(st, result); go('cluster'); },
    }) || null;
  }
  renderCluster(doc, { g, st, steps, back: () => go(part ? 'live' : 'pops'), backLabel: part ? 'Back to Live cells' : 'Back to populations',
    start: async body => emit(EV.jobStarted, { res: await api.startFlowRun(body), what: `clustering gate ${g.id}` }) });
  return null;
}

function render(body, key) {
  const gid = idOf(key);
  let partCleanup = null, dead = false;
  const stopPart = () => { if (partCleanup) { try { partCleanup(); } catch (e) { /* a part's teardown must not stop the redraw */ } partCleanup = null; } };
  const show = g => {
    if (dead) return;
    stopPart();
    body.replaceChildren();
    if (g.status !== 'done') {
      const job = gateJob(gid);
      body.append(el('div', { class: 'empty' }, el('div', {}, el('div', { text: `Gate ${gid} is ${g.status}.` }),
        job ? el('button', { type: 'button', class: 'btn', text: `Open job ${job.id}`, onclick: () => openTab(`job:${job.id}`) }) : null)));
      return;
    }
    partCleanup = renderGate(body, key, g, () => show(g));
  };
  const have = gateById(gid);
  if (have && have.files && have.files.length) show(have);
  else {
    body.append(el('div', { class: 'doc muted', text: 'Loading the gate…' }));
    getGate(gid).then(show, e => { if (!dead) body.replaceChildren(el('div', { class: 'empty', text: e.message })); });
  }
  return () => { dead = true; stopPart(); };
}

export function mount() {
  registerView('gate', {
    title: key => ({ name: `Gate ${idOf(key)}`, icon: 'picker' }),
    crumbs: key => ['Gates', idOf(key), CRUMBS[(S.view[key] && S.view[key].step) || 'pops']],
    render,
    output: key => gateLog(idOf(key)),
  });
}
