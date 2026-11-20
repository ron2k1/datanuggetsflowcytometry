// Start: the steps, a drop zone (files go to the uploader by event), demo data and runs.
import { el, docHead, toast } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtBytes, fmtInt, fmtDate } from '../../shared/format.js';
import { api, FIXTURES } from '../../shared/api/index.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, flowRuns, caps, activity, upsert } from '../../shared/store.js';
import { registerView, slotParts } from '../../shared/views.js';

const openTab = key => emit(EV.openTab, { key });
const pickFiles = () => emit(EV.filesPick);

let demosPromise = null;
const demos = () => (demosPromise || (demosPromise = api.demos().then(r => r.demos).catch(e => { demosPromise = null; throw e; })));

// The steps follow the population picker: Live cells is a step only when a part fills its slot
// 'gate.livecells' (features/live-cells), and the picker lets you skip it.
function stepNames() {
  const live = slotParts('gate.livecells').length > 0;
  return ['Upload FCS files', 'Find populations (gate)', 'Pick populations and groups', live ? 'Live cells (optional)' : null, 'Cluster, plot and compare'].filter(Boolean);
}
function leadText() {
  const live = slotParts('gate.livecells').length > 0 ? ', optionally keep only live cells' : '';
  return `Gate FCS files, choose the populations to keep${live}, then cluster their events with data nuggets and compare samples.`;
}

function dropzone() {
  const list = el('div', { class: 'uploading' });
  const draw = () => list.replaceChildren(...S.inflight.map(it => el('div', { class: 'up-row' },
    el('span', { text: it.name }), el('span', { class: 'mono muted', text: `${Math.round(it.p * 100)}% of ${fmtBytes(it.bytes)}` }),
    el('div', { class: 'bar', role: 'progressbar', 'aria-label': `Uploading ${it.name}`, 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(it.p * 100)) },
      el('i', { style: `width:${(it.p * 100).toFixed(1)}%` })))));
  const off = subscribe(EV.uploadsChange, draw);
  draw();
  const c = caps();
  const limits = c ? `FCS files up to ${fmtBytes(c.upload_fcs_bytes)}` : 'FCS files';
  const zone = el('div', {
    class: 'dropzone', role: 'button', tabindex: '0', 'aria-label': 'Upload files: click or drop FCS files here',
    onclick: pickFiles, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pickFiles(); } },
    ondragover: e => { e.preventDefault(); zone.classList.add('over'); },
    ondragleave: () => zone.classList.remove('over'),
    ondrop: e => { e.preventDefault(); zone.classList.remove('over'); emit(EV.filesDrop, { files: [...(e.dataTransfer ? e.dataTransfer.files : [])] }); },
  }, el('span', { html: svg('upload') }), el('b', { text: 'Drop files here, or click to choose' }),
  el('span', { text: 'Hold Ctrl (⌘ on a Mac) or Shift to choose several files at once.' }), el('span', { class: 'muted', text: limits }));
  return { node: el('div', {}, zone, list), off };
}

async function loadDemo(demo) {
  try {
    const res = await api.loadDemo(demo.id);
    res.uploads.forEach(u => upsert('uploads', u));
    activity(`Loaded demo ${demo.title}: ${res.uploads.map(u => u.name).join(', ')}`);
    const first = res.uploads[0];
    if (first) openTab(`upload:${first.id}`);
  } catch (e) { toast(e.message, true); activity(`Load demo ${demo.id}: ${e.message}`); }
}

// The license names its own text when the manifest links it, and the attribution is the credit
// the license asks for, so the card shows both as /demos sends them.
function demoCard(d) {
  const ext = { target: '_blank', rel: 'noopener noreferrer' };
  const license = d.license_url ? el('a', { href: d.license_url, ...ext, text: d.license }) : d.license;
  return el('div', { class: 'card demo' },
    el('div', { class: 't', text: d.title }),
    el('div', { class: 'd' }, `${d.description} ${fmtInt(d.rows)} events, ${fmtBytes(d.files.reduce((s, f) => s + f.bytes, 0))}. `,
      'License: ', license, '. ', el('a', { href: d.source_url, ...ext, text: 'Source' })),
    d.attribution ? el('div', { class: 'd attribution', text: d.attribution }) : null,
    el('button', { type: 'button', class: 'btn', disabled: !d.available, title: d.available ? `Copy ${d.title} into this workspace` : 'Not available on this server', onclick: () => loadDemo(d), html: svg('download') + '<span>Load</span>' }));
}

function renderStart(body) {
  const cfg = S.config || {};
  const dz = dropzone();
  const demoBox = el('div', { class: 'demo-list' }, el('div', { class: 'muted', text: 'Loading demo data…' }));
  demos().then(ds => {
    // A server that still offers CSV demos lists them too; only the FCS ones load into this app.
    const fcs = ds.filter(d => d.kind === 'fcs');
    demoBox.replaceChildren(...(fcs.length ? fcs.map(demoCard) : [el('div', { class: 'muted', text: 'No demo data on this server.' })]));
  }, e => demoBox.replaceChildren(el('div', { class: 'note err', text: e.message })));
  // Each entry opens a plot, so only finished runs are listed, as in the new-tab menu.
  const runs = flowRuns().filter(r => r.status === 'done');
  const runList = el('div', { class: 'run-list' }, ...(runs.length ? runs.map(r => el('button', { type: 'button', class: 'run-item', onclick: () => openTab(`plot:${r.id}`) },
    el('span', { class: 'k-plot', html: svg('plot') }), el('span', { text: r.title }), el('span', { class: 'meta', text: `${r.id} · ${fmtDate(r.created)}` }))) : [el('div', { class: 'muted', text: 'No runs yet.' })]));
  const steps = el('div', { class: 'pk-steps', 'aria-label': 'Steps' }, ...stepNames().flatMap((s, i) => [i ? el('span', { class: 'sep' }) : null, el('span', { class: 'st' }, el('b', { text: String(i + 1) }), s)]));
  body.append(el('div', { class: 'doc start' },
    docHead('Flow cytometry', leadText()),
    steps,
    el('div', { class: 'callout' + (cfg.mode === 'local' ? ' info' : ''), text: cfg.storage_note || '' }),
    FIXTURES ? el('div', { class: 'callout info', style: 'margin-top:8px', text: 'Fixture mode: every screen reads recorded API responses from real datanuggets runs on public data. Files you pick are read in this tab only and never sent.' }) : null,
    el('div', { class: 'start-grid', style: 'margin-top:16px' },
      el('div', {}, el('h3', { text: 'Your files' }), dz.node, el('h3', { text: 'Demo data' }), demoBox),
      el('div', {}, el('h3', { text: 'Runs' }), runList,
        el('h3', { text: 'Run it locally' }),
        el('div', { class: 'card pad' }, el('div', { class: 'note', style: 'margin-top:0', text: 'The same app runs on your own computer with Docker, with no size limits and files kept on your disk.' }),
          el('div', { class: 'links' }, el('button', { type: 'button', class: 'btn', onclick: () => openTab('local'), html: svg('local') + '<span>Show the commands</span>' })))))));
  return dz.off;
}

export function mount() {
  registerView('start', {
    title: () => ({ name: 'Start', icon: 'start' }),
    crumbs: () => ['datanuggets', 'Start'],
    render: renderStart,
  });
}
