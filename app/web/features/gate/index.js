// Gating: the "Find populations" form under an FCS upload (slot 'upload.fcs') and the gate's
// full figure tab.
import { el, docHead, seg } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtInt, plural } from '../../shared/format.js';
import { api } from '../../shared/api/index.js';
import { DISC, GATE_SCATTER } from '../../shared/config.js';
import { datasetKey, stainDiffs, stainText } from '../../shared/datasets.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, fcsUploads, datasetOf, caps, getGate, gateById, gateLog } from '../../shared/store.js';
import { registerView, registerSlot } from '../../shared/views.js';
import { numField, selectField, textField } from '../../shared/forms.js';

const openTab = key => emit(EV.openTab, { key });
// Waits for a POST that queues work and hands the 202 to the jobs feature.
const startJob = async (request, what) => emit(EV.jobStarted, { res: await request, what });
const listOf = s => s.split(/[,\s]+/).filter(Boolean).map(Number);

const perGate = () => (caps() || {}).fcs_files_per_gate || Infinity;
// A scatter dropdown's options: the channels named with its prefix, or all of them when none is.
const scatterOf = (chans, prefix) => {
  const s = chans.filter(([name]) => name.toUpperCase().startsWith(prefix));
  return s.length ? s : chans;
};

// A new form ticks this file and, when it came in one batch with others, the batch's files among
// fcs (its dataset's), up to the workspace's files-per-gate cap.
function gateForm(u, fcs) {
  const d = (S.config && S.config.defaults && S.config.defaults.gate) || {};
  const mine = new Set(fcs.map(x => x.id));
  const batch = S.lastBatch.includes(u.id) ? [u.id, ...S.lastBatch.filter(id => id !== u.id && mine.has(id))].slice(0, perGate()) : [u.id];
  return { uploads: new Set(batch), fsc: d.fsc || 'FSC-A', ssc: d.ssc || 'SSC-A', disc: d.disc || 'reference',
    t11: (d.t11 || []).join(', '), t21: (d.t21 || []).join(', '), t12: d.t12, t22: d.t22, n_row: d.n_row, n_col: d.n_col };
}

const SEVERAL = 'In the file picker, hold Ctrl (⌘ on a Mac) or Shift to choose several files at once.';

// The box on screen: its progress line and "Add FCS files" button follow EV.uploadsChange.
let shownBox = null;
function syncBox() {
  if (!shownBox || !shownBox.box.isConnected) { shownBox = null; return; }
  shownBox.progress.textContent = S.inflight.length ? `Uploading ${S.inflight.map(it => `${it.name} ${Math.round(it.p * 100)}%`).join(', ')}` : '';
  shownBox.add.disabled = S.inflight.length > 0;
}

// The files to gate: every FCS upload of the opened file's dataset (fcs, the files with colour
// channels key) as a check, with a note counting the files of other datasets it leaves out; the
// count ticked; a warning while the ticked files' stains differ; and "Add FCS files", which
// uploads more without leaving this tab and ticks those in the dataset. Dropping files on the
// box does the same.
function filesBox(f, fcs, key) {
  const picked = () => fcs.filter(x => f.uploads.has(x.id));
  const count = el('span', { class: 'muted' }), max = perGate();
  const stains = el('div', { class: 'note warn' });
  const setCount = () => {
    const on = picked(), differ = stainDiffs(on);
    count.textContent = `${on.length} of ${fcs.length} selected${max < Infinity ? `, up to ${max} per gate` : ''}`;
    stains.textContent = differ.length ? `Stains differ between the ticked files: ${stainText(differ)}. One stain can be spelled two ways; check these name the same markers.` : '';
    stains.hidden = !differ.length;
  };
  const boxes = fcs.map(x => el('input', { type: 'checkbox', checked: f.uploads.has(x.id),
    onchange: e => { e.target.checked ? f.uploads.add(x.id) : f.uploads.delete(x.id); setCount(); } }));
  const all = on => { fcs.forEach((x, i) => { boxes[i].checked = on; on ? f.uploads.add(x.id) : f.uploads.delete(x.id); }); setCount(); };
  const tick = ups => ups.filter(x => x.kind === 'fcs' && datasetKey(x) === key).forEach(x => f.uploads.add(x.id));
  const others = fcsUploads().length - fcs.length;
  const add = el('button', { type: 'button', class: 'btn', html: svg('upload') + '<span>Add FCS files</span>', onclick: () => emit(EV.filesPick, { done: tick }) });
  const progress = el('span', { class: 'muted' });
  const one = fcs.length < 2;
  const box = el('div', {
    class: 'gate-files', role: 'group', 'aria-label': 'Files to gate together',
    ondragover: e => { e.preventDefault(); box.classList.add('over'); },
    ondragleave: () => box.classList.remove('over'),
    ondrop: e => { e.preventDefault(); box.classList.remove('over'); emit(EV.filesDrop, { files: [...(e.dataTransfer ? e.dataTransfer.files : [])], done: tick }); },
  },
    el('div', { class: 'gate-files-head' }, el('span', { text: 'Files to gate together' }), count),
    el('div', { class: 'checks' }, ...fcs.map((x, i) => el('label', { class: 'check' }, boxes[i], `${x.name} (${fmtInt(x.rows)} events)`))),
    others ? el('div', { class: 'note', text: `${plural(others, 'file')} in ${others === 1 ? 'another dataset is' : 'other datasets are'} not shown: a gate takes files from one dataset.` }) : null,
    stains,
    el('div', { class: 'gate-files-actions' }, add,
      one ? null : el('button', { type: 'button', class: 'linkbtn', text: 'Select all', onclick: () => all(true) }),
      one ? null : el('button', { type: 'button', class: 'linkbtn', text: 'Select none', onclick: () => all(false) }),
      progress),
    one ? el('div', { class: 'callout', text: `Gate several FCS files together to compare samples, for example unstimulated and stimulated. Add the others here or drop them on this box. ${SEVERAL}` })
      : el('div', { class: 'note', text: `Add more with the button or by dropping files on this box. ${SEVERAL}` }));
  setCount();
  shownBox = { box, progress, add };
  syncBox();
  return box;
}

function gateSection(u, st) {
  // A gate takes files from one dataset (the server refuses others): the opened file's.
  const d = datasetOf(u.id), fcs = d ? d.files : [u];
  const f = st.form || (st.form = gateForm(u, fcs));
  const chans = u.columns.map(x => [x.name, x.label ? `${x.name} · ${x.label}` : x.name]);
  const max = perGate();
  const msg = el('span', { class: 'grow' });
  const go = el('button', { type: 'button', class: 'btn primary', html: svg('play') + '<span>Find populations</span>', onclick: async () => {
    const ids = fcs.filter(x => f.uploads.has(x.id)).map(x => x.id);
    const t11 = listOf(f.t11), t21 = listOf(f.t21);
    const problem = !ids.length ? 'Pick at least one FCS file.' : ids.length > max ? `Gate at most ${max} files at once here.`
      : [1, ids.length].includes(t11.length) && [1, ids.length].includes(t21.length) ? null : 't11 and t21 take one value, or one per file.';
    if (problem) { msg.textContent = problem; msg.className = 'grow note err'; return; }
    go.disabled = true;
    try {
      await startJob(api.startGate({ uploads: ids, settings: { fsc: f.fsc, ssc: f.ssc, disc: f.disc, t11, t21, t12: f.t12, t22: f.t22, n_row: f.n_row, n_col: f.n_col } }),
        `gating ${ids.length} file${ids.length === 1 ? '' : 's'}`);
    } catch (e) { msg.textContent = e.param ? `${e.param}: ${e.message}` : e.message; msg.className = 'grow note err'; go.disabled = false; }
  } });
  const done = (S.ws.gates || []).filter(g => (g.files || []).some(x => x.upload === u.id));
  return el('div', { class: 'section' }, el('h3', { text: 'Find populations (gate)' }),
    done.length ? el('div', { class: 'callout info', style: 'margin-bottom:10px' }, `Already gated in ${done.map(g => g.id).join(', ')}. `,
      ...done.map(g => el('button', { type: 'button', class: 'linkbtn', text: `Open gate ${g.id}`, onclick: () => openTab(`gate:${g.id}`) }))) : null,
    filesBox(f, fcs, datasetKey(u)),
    el('div', { class: 'form-grid', style: 'margin-top:10px' },
      selectField(f, 'fsc', 'Forward scatter', scatterOf(chans, GATE_SCATTER.fsc)),
      selectField(f, 'ssc', 'Side scatter', scatterOf(chans, GATE_SCATTER.ssc)),
      selectField(f, 'disc', 'Area rule', DISC, { wide: true, hint: 'Reference reproduces the original gates. Peak-centred centres each area on its peak; they differ for peaks off the diagonal.' })),
    el('details', { class: 'more' }, el('summary', { text: 'Peak finder thresholds' }),
      el('div', { class: 'form-grid' },
        textField(f, 't11', 't11', { hint: 'One value, or one per file' }), textField(f, 't21', 't21', { hint: 'One value, or one per file' }),
        numField(f, 't12', 't12', { min: 0 }), numField(f, 't22', 't22', { min: 0 }),
        numField(f, 'n_row', 'Window rows', { min: 1, int: true }), numField(f, 'n_col', 'Window columns', { min: 1, int: true }))),
    el('div', { class: 'form-actions' }, msg, go));
}

function renderFigure(body, key) {
  const [, gid, name] = key.split(':');
  const st = S.view[key] || (S.view[key] = { mode: 'fit' });
  const draw = g => {
    const img = el('img', { src: g.figures[name], alt: `${name} figure of gate ${gid}` });
    const stage = el('div', { class: 'img-stage ' + st.mode }, img);
    const z = seg('Zoom', [['fit', 'Fit'], ['actual', '100%']], st.mode, m => { st.mode = m; stage.className = 'img-stage ' + m; z.querySelectorAll('button').forEach((b, i) => b.setAttribute('aria-pressed', String(['fit', 'actual'][i] === m))); });
    body.replaceChildren(el('div', { class: 'doc doc-fill' }, docHead(`${name}.png`, `Gate ${gid} · drawn by datanuggets`, z), stage));
  };
  const g = gateById(gid);
  if (g && g.figures) draw(g); else getGate(gid).then(draw, e => body.replaceChildren(el('div', { class: 'empty', text: e.message })));
}

export function mount() {
  subscribe(EV.uploadsChange, syncBox);
  registerSlot('upload.fcs', { render: gateSection });
  registerView('figure', {
    title: key => ({ name: `${key.split(':')[2]}.png`, hint: key.split(':')[1], icon: 'png' }),
    crumbs: key => ['Gates', key.split(':')[1], `${key.split(':')[2]}.png`],
    render: renderFigure,
    output: key => gateLog(key.split(':')[1]),
  });
}
