// Jobs: a started job (EV.jobStarted) is recorded, logged, opened and polled until it ends; every
// poll emits EV.jobsChange. A finished job reloads the workspace and redraws everything.
import { POLL_MS } from '../../shared/config.js';
import { api } from '../../shared/api/index.js';
import { toast } from '../../shared/dom.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, activity, upsert, loadWorkspace, isGateJob } from '../../shared/store.js';

let timer = 0;
const active = j => j.status === 'queued' || j.status === 'running';

async function poll() {
  timer = 0;
  const live = S.ws.jobs.filter(active);
  let changed = false;
  for (const j of live) {
    try {
      const n = await api.job(j.id);
      if (n.status !== j.status || n.progress !== j.progress) changed = true;
      upsert('jobs', n);
      if (n.status === 'done' && j.status !== 'done') await finished(n);
      else if ((n.status === 'failed' || n.status === 'cancelled') && j.status !== n.status) {
        activity(`Job ${n.id} ${n.status}${n.error ? `: ${n.error.message}` : ''}`);
      }
    } catch (e) { activity(`Job ${j.id}: ${e.message}`); }
  }
  emit(EV.jobsChange, { changed });
  if (S.ws.jobs.some(active)) timer = setTimeout(poll, POLL_MS);
}
async function finished(job) {
  activity(`Job ${job.id} done`);
  try { await loadWorkspace(); } catch (e) { activity(`Reload workspace: ${e.message}`); }
  toast(job.run_id ? `Run ${job.run_id} is ready.` : isGateJob(job) ? `Gate ${job.gate_id} is ready.`
    : job.kind === 'livecells' ? `The live-cell histograms of gate ${job.gate_id} are ready.` : `Job ${job.id} is done.`);
  emit(EV.render);
}
export function ensurePolling() { if (!timer && S.ws.jobs.some(active)) timer = setTimeout(poll, POLL_MS); }

function started({ res, what, open }) {
  upsert('jobs', res.job);
  activity(`Started ${what}: job ${res.job.id}${res.run_id ? ` -> run ${res.run_id}` : ''}${res.gate_id ? ` -> gate ${res.gate_id}` : ''}${res.livecells_id ? ` -> live cells ${res.livecells_id}` : ''}`);
  if (open !== false) emit(EV.openTab, { key: `job:${res.job.id}` });
  ensurePolling();
}

// A job that ended before the cancel arrived comes back as it is (200). It is left to the poll,
// which announces it and, for a done one, reloads the workspace; recording it here would hide
// its end from the poll. An answer that arrives after the poll saw the job end is older than
// what the list holds, so it is dropped too: it would set the job back to running.
export async function cancelJob(id) {
  try {
    const j = await api.cancelJob(id);
    const mine = S.ws.jobs.find(x => x.id === id);
    if (j.status === 'done' || j.status === 'failed' || (mine && !active(mine))) return;
    upsert('jobs', j);
    activity(`Cancelled job ${id}`);
    emit(EV.jobsChange, { changed: true });
  } catch (e) { toast(e.message, true); activity(`Cancel job ${id}: ${e.message}`); }
}

export function wirePolling() {
  subscribe(EV.jobStarted, started);
  subscribe(EV.ready, ensurePolling);
}
