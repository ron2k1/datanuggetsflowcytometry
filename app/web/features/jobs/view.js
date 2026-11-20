// One job: what it is and how it stands, a progress bar while it runs, then what it made
// (results.js) with the next step, the log (folded once done) and its times beside.
// Polling lives in poll.js; this view follows EV.jobsChange and redraws its own nodes only.
import { el, fill, logLines } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtDate, fmtDuration } from '../../shared/format.js';
import { EV } from '../../shared/events.js';
import { emit, subscribe, idOf, jobById, isGateJob, runById, getGate } from '../../shared/store.js';
import { registerView } from '../../shared/views.js';
import { cancelJob, ensurePolling } from './poll.js';
import { gateResults, runResults } from './results.js';

const openTab = key => emit(EV.openTab, { key });
const ACTIVE = new Set(['queued', 'running']);
const pct = p => Math.round(Math.max(0, Math.min(1, p || 0)) * 100);
const span = (a, b) => (a && b ? Date.parse(b) - Date.parse(a) : null);

const subject = j => (isGateJob(j) ? `Gate ${j.gate_id}` : j.run_id ? `Run ${j.run_id}` : `Job ${j.id}`);
function statusLine(j) {
  const took = fmtDuration(span(j.started, j.finished));
  if (j.status === 'queued') return 'Waiting for a free worker. Closing this tab does not stop it.';
  if (j.status === 'running') return `Running on the server since ${fmtDate(j.started)}. Closing this tab does not stop it.`;
  if (j.status === 'done') return `Finished ${fmtDate(j.finished)}, took ${took}.`;
  if (j.status === 'failed') return `Failed ${fmtDate(j.finished)}${j.started ? `, after ${took}` : ''}.`;
  return `${j.status[0].toUpperCase()}${j.status.slice(1)} ${fmtDate(j.finished)}.`;
}
function nextStep(j) {
  if (j.status !== 'done') return null;
  const [text, icon, label, key] = isGateJob(j) ? ['Pick the populations to keep, then cluster them.', 'picker', 'Pick populations', `gate:${j.gate_id}`]
    : j.run_id ? ['Explore the clusters in the plot.', 'plot', 'Open the plot', `plot:${j.run_id}`] : [];
  return text ? el('div', { class: 'callout job-next' }, el('span', {}, el('b', { text: 'Next: ' }), text),
    el('button', { type: 'button', class: 'btn primary', html: svg(icon) + `<span>${label}</span>`, onclick: () => openTab(key) })) : null;
}

function render(body, key, host) {
  const id = idOf(key);
  let dead = false, lastSig = '', lastStatus = null, shown = null;
  const title = el('div', { class: 'doc-title' }), sub = el('div', { class: 'doc-sub' });
  const badge = el('span', { class: 'badge' });
  const bar = el('i'), pctEl = el('span', { class: 'job-pct' }), stage = el('span', { class: 'muted' });
  const progress = el('div', { class: 'progress', role: 'progressbar', 'aria-label': `Job ${id} progress`, 'aria-valuemin': '0', 'aria-valuemax': '1' }, bar);
  const live = el('div', { class: 'job-live' }, el('div', { class: 'job-live-row' }, pctEl, stage), progress);
  const err = el('div', { class: 'callout job-err', hidden: true });
  const next = el('div');
  const results = el('div');
  const log = el('div', { class: 'logdoc', 'aria-label': 'Log tail' });
  const logSum = el('summary');
  const logBox = el('details', { class: 'more job-log' }, logSum, log);
  const times = el('dl', { class: 'kv' });
  const actions = el('div', { class: 'links' });

  // A finished job's results load once; a gate's come from GET /flow/gates/{gid}.
  function showResults(j) {
    if (j.status !== 'done' || shown) return;
    if (isGateJob(j)) {
      shown = 'gate';
      results.replaceChildren(el('div', { class: 'note', text: 'Loading the populations…' }));
      getGate(j.gate_id).then(g => { if (!dead) results.replaceChildren(gateResults(g, openTab)); },
        e => { if (!dead) results.replaceChildren(el('div', { class: 'note err', text: `The gate's results did not load: ${e.message}` })); });
    } else if (j.run_id && runById(j.run_id)) {
      shown = 'run';
      results.replaceChildren(runResults(runById(j.run_id), openTab));
    }
  }

  function draw() {
    const j = jobById(id);
    if (!j) { body.replaceChildren(el('div', { class: 'empty', text: `Job ${id} is not in this workspace.` })); return; }
    showResults(j);
    const sig = JSON.stringify([j.status, j.progress, j.stage, j.message, j.log_tail, j.error]);
    if (sig === lastSig) return;
    lastSig = sig;
    const active = ACTIVE.has(j.status);
    title.textContent = subject(j);
    sub.textContent = statusLine(j);
    badge.textContent = j.status;
    badge.className = 'badge ' + j.status;
    live.hidden = !active;
    const p = j.progress || 0;
    pctEl.textContent = `${pct(p)}%`;
    bar.style.width = `${pct(p)}%`;
    progress.setAttribute('aria-valuenow', String(Math.round(p * 1000) / 1000));
    progress.setAttribute('aria-valuetext', `${pct(p)}%${j.stage ? `, ${j.stage}` : ''}`);
    stage.textContent = [j.stage, j.message].filter(Boolean).join(' · ') || (j.status === 'queued' ? 'Waiting for a free worker.' : '');
    err.hidden = !j.error;
    err.textContent = j.error ? `${j.error.code}: ${j.error.message}` : '';
    fill(next, nextStep(j));
    const lines = j.log_tail || [];
    log.replaceChildren(...(lines.length ? logLines(lines) : [el('div', { class: 'ln' }, el('span', { class: 't muted', text: 'No log lines yet.' }))]));
    log.scrollTop = log.scrollHeight;
    logSum.textContent = `Log · ${lines.length} line${lines.length === 1 ? '' : 's'}`;
    // Open while it runs or after it fails, folded once done; a click in between is kept.
    if (j.status !== lastStatus) { logBox.open = j.status !== 'done'; lastStatus = j.status; }
    host.refreshPanel();
    const waited = span(j.created, j.started);
    fill(times,
      el('dt', { text: 'Job' }), el('dd', { class: 'mono', text: j.id }),
      el('dt', { text: 'Kind' }), el('dd', { text: j.kind }),
      j.gate_id ? [el('dt', { text: 'Gate' }), el('dd', {}, el('button', { type: 'button', class: 'linkbtn mono', text: j.gate_id, title: 'Pick populations from this gate', onclick: () => openTab(`gate:${j.gate_id}`) }))] : null,
      j.run_id ? [el('dt', { text: 'Run' }), el('dd', {}, el('button', { type: 'button', class: 'linkbtn mono', text: j.run_id, title: 'Open the plot', onclick: () => openTab(`plot:${j.run_id}`) }))] : null,
      el('dt', { text: 'Started' }), el('dd', { text: fmtDate(j.started) }),
      waited > 2000 ? [el('dt', { text: 'Queued for' }), el('dd', { text: fmtDuration(waited) })] : null,
      el('dt', { text: 'Finished' }), el('dd', { text: fmtDate(j.finished) }),
      j.started && j.finished ? [el('dt', { text: 'Took' }), el('dd', { class: 'strong', text: fmtDuration(span(j.started, j.finished)) })] : null);
    fill(actions, active ? el('button', { type: 'button', class: 'btn danger', html: svg('close') + '<span>Cancel job</span>', onclick: e => { e.currentTarget.disabled = true; cancelJob(id); } }) : null);
  }

  body.append(el('div', { class: 'doc job' },
    el('div', { class: 'doc-head' }, el('div', {}, title, sub), badge),
    el('div', { class: 'job-grid' },
      el('div', { class: 'job-main' }, live, err, next, actions, results, logBox),
      el('aside', { class: 'card pad job-aside', 'aria-label': 'Job details' }, times))));
  draw();
  ensurePolling();
  const off = subscribe(EV.jobsChange, draw);
  return () => { dead = true; off(); };
}

export function registerJobView() {
  registerView('job', {
    title: key => ({ name: `Job ${idOf(key)}`, icon: 'job' }),
    crumbs: key => ['Jobs', idOf(key)],
    render,
    output: key => { const j = jobById(idOf(key)); return j ? { path: `job ${j.id} · ${j.kind}`, lines: j.log_tail || [] } : null; },
  });
}
