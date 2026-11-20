// App state and the event bus. S holds what the server said (config, workspace), what is open,
// and per-tab view state; features read and write it, and tell each other about changes only
// through emit/subscribe with the names in events.js. Payload caches live here so tabs of one
// run share one download.
import { api } from './api/index.js';
import { STORAGE, DRAWER_MAX_PX, K_FALLBACK_MAX } from './config.js';
import { groupDatasets } from './datasets.js';
import { EV } from './events.js';
import { clock } from './format.js';

function terminalPref() {
  try { const v = localStorage.getItem(STORAGE.terminal); if (v === '1' || v === '0') return v === '1'; } catch (e) { /* storage unavailable */ }
  return window.innerWidth > DRAWER_MAX_PX;
}

export const S = {
  config: null,
  ws: { uploads: [], gates: [], runs: [], jobs: [], datasets: [] },
  localUploads: [],              // fixture mode: files read in this tab
  inflight: [],                  // uploads on their way: {name, bytes, p, err}
  lastBatch: [],                 // ids of the last batch of uploads, ticked when a gate form opens
  tabs: { open: ['start'], active: 'start' },
  expanded: new Set(['datasets', 'runs', 'gates', 'jobs']),
  view: {},                      // per tab key: view state (plot, picker, forms, sorting)
  cache: { plot: {}, cells: {}, compare: {}, manifest: {}, gate: {} },
  activity: [],
  panelOpen: terminalPref(),
  panelTab: 'output',
  runOpen: false,
};

/* the bus */
const bus = new Map();
// Calls f(payload) on every emit(name); returns the function that unsubscribes it.
export function subscribe(name, f) {
  if (!bus.has(name)) bus.set(name, new Set());
  bus.get(name).add(f);
  return () => bus.get(name).delete(f);
}
export function emit(name, payload) {
  for (const f of [...(bus.get(name) || [])]) f(payload);
}

export const tabsNow = () => S.tabs;
export const kindOf = key => key.split(':')[0];
export const idOf = key => (key.split(':')[1] || '').split('~')[0];

export function activity(msg) {
  const a = { t: clock(), msg };
  S.activity.push(a);
  emit(EV.activity, a);
}

export const allUploads = () => [...S.ws.uploads, ...S.localUploads];
export const uploadById = id => allUploads().find(u => u.id === id) || null;
export const runById = id => S.ws.runs.find(r => r.id === id) || null;
export const jobById = id => S.ws.jobs.find(j => j.id === id) || null;
export const gateById = id => S.cache.gate[id] || S.ws.gates.find(g => g.id === id) || null;
// A workspace made before the app was flow only can still hold CSV uploads and general runs and
// jobs, and the server lists them so they can be deleted; the page lists and opens only these.
export const fcsUploads = () => allUploads().filter(u => u.kind === 'fcs');
// The FCS uploads' datasets (shared/datasets.js), with the names the workspace gives them.
export const datasets = () => groupDatasets(fcsUploads(), S.ws.datasets);
export const datasetOf = uid => datasets().find(d => d.files.some(u => u.id === uid)) || null;
export const flowRuns = () => S.ws.runs.filter(r => r.kind === 'flow');
export const flowJobs = () => S.ws.jobs.filter(j => j.kind !== 'general');
// A job that made a gate. Live-cells jobs carry their gate's id too, so gate_id alone is not enough.
export const isGateJob = j => j.kind === 'gate' && !!j.gate_id;
// The job of kind 'gate' that made gate gid.
export const gateJob = gid => S.ws.jobs.find(j => isGateJob(j) && j.gate_id === gid) || null;
// The gate job's log for the terminal.
export function gateLog(gid) {
  const j = gateJob(gid);
  return j ? { path: `job ${j.id} · gate ${gid}`, lines: j.log_tail } : null;
}
export const kMax = () => (S.config && S.config.limits && S.config.limits.k_max) || K_FALLBACK_MAX;
export const caps = () => (S.config && S.config.caps) || null;

// How many dataset names have been saved: a reload that a save overtook keeps the save's names,
// since the server answered the reload before it kept them. deleted holds the deletes done, in
// order, by tab key ('upload:u3', 'gate:g1'): a reload that a delete overtook leaves the item out,
// since the server may have answered before it deleted it. A page makes few deletes, so all stay.
let namesSaved = 0;
const deleted = [];
const deletedSince = n => new Set(deleted.slice(n));
export async function loadWorkspace() {
  const saves = namesSaved, dels = deleted.length;
  const ws = await api.workspace();
  const gone = deletedSince(dels);
  const keep = (list, kind) => (gone.size && list ? list.filter(x => !gone.has(`${kind}:${x.id}`)) : list);
  // A server that keeps no names leaves them out.
  S.ws = { ...ws, uploads: keep(ws.uploads, 'upload'), gates: keep(ws.gates, 'gate'),
    datasets: saves === namesSaved ? ws.datasets || [] : S.ws.datasets };
  return S.ws;
}
// Names a set of colour channels (POST /datasets; a blank name removes its name) and keeps the
// names the server answers with in the workspace as it is when they arrive.
export async function nameDataset(channels, name) {
  const { datasets } = await api.nameDataset({ channels, name });
  S.ws.datasets = datasets;
  namesSaved += 1;
}

// Closes the tabs gone(key) picks and forgets their view state. When the active tab goes, the
// next tab left takes over, or else the one before it, as closing it by hand would.
function closeTabs(gone) {
  const T = S.tabs, i = T.open.indexOf(T.active);
  if (i >= 0 && gone(T.active)) T.active = T.open.slice(i + 1).find(k => !gone(k)) || T.open.slice(0, i).filter(k => !gone(k)).pop() || null;
  T.open.filter(gone).forEach(k => { delete S.view[k]; });
  T.open = T.open.filter(k => !gone(k));
}
// Deletes an upload (DELETE /uploads/{uid}) and closes its tab. The server refuses a file a gate
// uses (409), in its own words; nothing else changes with the file, so the workspace drops just it.
export async function deleteUpload(uid) {
  await api.deleteUpload(uid);
  deleted.push(`upload:${uid}`);
  S.ws.uploads = S.ws.uploads.filter(u => u.id !== uid);
  S.localUploads = S.localUploads.filter(u => u.id !== uid);
  closeTabs(key => kindOf(key) === 'upload' && idOf(key) === uid);
}
// Deletes a gate (DELETE /flow/gates/{gid}) and closes its tab and its figures'. The server
// refuses while the gate's job, a run from it or a live-cells set of it is on its way; its runs
// outlive it, and its live-cells sets go with it, which the workspace does not list.
export async function deleteGate(gid) {
  await api.deleteGate(gid);
  deleted.push(`gate:${gid}`);
  S.ws.gates = S.ws.gates.filter(g => g.id !== gid);
  delete S.cache.gate[gid];
  closeTabs(key => ['gate', 'figure'].includes(kindOf(key)) && idOf(key) === gid);
}

// Payload getters, cached per run.
async function cached(bucket, id, load) {
  if (!S.cache[bucket][id]) S.cache[bucket][id] = load(id).catch(e => { delete S.cache[bucket][id]; throw e; });
  return S.cache[bucket][id];
}
export const getPlot = rid => cached('plot', rid, api.plot);
export const getCells = rid => cached('cells', rid, api.cells);
export const getCompare = rid => cached('compare', rid, api.compare);
export const getManifest = rid => cached('manifest', rid, api.manifest);
// A gate deleted while its answer was on its way stays out of the cache.
export async function getGate(gid) {
  const dels = deleted.length;
  const g = await api.gate(gid);
  if (!deletedSince(dels).has(`gate:${gid}`)) S.cache.gate[gid] = g;
  return g;
}

// Adds or replaces a job, upload or run in the workspace lists after a POST.
export function upsert(list, item) {
  const arr = S.ws[list];
  const i = arr.findIndex(x => x.id === item.id);
  if (i >= 0) arr[i] = item; else arr.push(item);
}
