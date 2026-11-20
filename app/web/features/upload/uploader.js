// Uploads the user starts, FCS files only: the file chooser (EV.filesPick) and dropped files
// (EV.filesDrop). A file is known as FCS by its header, whatever its name (a FACSCalibur names its
// files .B08): the uploader reads a file's first bytes and refuses one without the header before
// sending it, and the server, or the local reader, refuses it too when the browser can't read
// them. Files in flight sit in S.inflight; each move emits EV.uploadsChange. Every upload of a
// batch gets a tab: a plain batch shows its last upload, while a batch whose sender passed
// done(uploads) opens its tabs behind the current one, hands the uploads to done and redraws.
// S.lastBatch keeps the last batch's ids. Each dataset the batch made while another was there is
// named in a toast, one after another, and in the activity log.
import { FCS_HEAD_BYTES, FCS_HEADER_RE, TOAST_MS } from '../../shared/config.js';
import { newDatasetNotes } from '../../shared/datasets.js';
import { fmtBytes } from '../../shared/format.js';
import { toast } from '../../shared/dom.js';
import { api } from '../../shared/api/index.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, activity, upsert, caps, allUploads, datasets } from '../../shared/store.js';

const moved = () => emit(EV.uploadsChange);
// The datasets each batch still uploading knew of when it started. A batch that ends adds every
// dataset there is to the others', so a batch that overlapped it names none of them again.
const pending = new Set();

// A file's first FCS_HEAD_BYTES as text, or null when the browser can't read them.
function readHead(file) {
  return new Promise(resolve => {
    try {
      const fr = new FileReader();
      fr.onload = () => resolve(String.fromCharCode(...new Uint8Array(fr.result)));
      fr.onerror = () => resolve(null);
      fr.readAsArrayBuffer(file.slice(0, FCS_HEAD_BYTES));
    } catch { resolve(null); }
  });
}

async function precheck(file) {
  // The same name and size is the same file again; a second copy would count its sample twice.
  if (allUploads().some(u => u.name === file.name && u.bytes === file.size)) return `${file.name} is already uploaded.`;
  const cap = (caps() || {}).upload_fcs_bytes;
  if (cap && file.size > cap) return `${file.name} is ${fmtBytes(file.size)}; this workspace takes FCS files up to ${fmtBytes(cap)}.`;
  const head = await readHead(file);
  if (head !== null && !FCS_HEADER_RE.test(head)) return `${file.name} is not an FCS 2.0, 3.0 or 3.1 file.`;
  return null;
}

async function uploadFiles(files, { done = null } = {}) {
  const added = [], known = new Set(datasets().map(d => d.key));
  let warned = false;   // a refusal or failure toast, which the notes then wait behind
  pending.add(known);
  for (const file of files) {
    const item = { name: file.name, bytes: file.size, p: 0, err: null };
    const bad = await precheck(file);
    if (bad) { toast(bad, true); warned = true; activity(`Upload ${file.name}: ${bad}`); continue; }
    S.inflight.push(item); moved();
    try {
      const u = await api.upload(file, p => { item.p = p; moved(); });
      if (u.local) S.localUploads.push(u); else upsert('uploads', u);
      activity(`Uploaded ${u.name} (${fmtBytes(u.bytes)})${u.local ? ', read in this tab (fixture mode)' : ''}`);
      added.push(u);
    } catch (e) {
      item.err = e.message;
      toast(`${file.name}: ${e.message}`, true); warned = true;
      activity(`Upload ${file.name} failed: ${e.message}`);
    } finally {
      S.inflight.splice(S.inflight.indexOf(item), 1); moved();
    }
  }
  pending.delete(known);
  if (!added.length) return;
  S.lastBatch = added.map(u => u.id);
  // The page has one toast, so each note shows for its TOAST_MS before the next, and after the
  // batch's last refusal or failure has had its own.
  const ds = datasets();
  newDatasetNotes(known, ds).forEach((note, i) => {
    activity(note);
    const wait = (i + warned) * TOAST_MS;
    if (wait) setTimeout(() => toast(note), wait); else toast(note);
  });
  pending.forEach(k => ds.forEach(d => k.add(d.key)));
  const tab = (u, background) => emit(EV.openTab, { key: `upload:${u.id}`, background });
  if (done) { done(added); added.forEach(u => tab(u, true)); emit(EV.render); }
  else added.forEach(u => tab(u, false));
}

// The chooser's options wait here until its change event; each pick replaces them.
let picking = {};
const fileInput = Object.assign(document.createElement('input'), { type: 'file', multiple: true });
fileInput.hidden = true;
fileInput.addEventListener('change', () => { const fs = [...fileInput.files]; fileInput.value = ''; uploadFiles(fs, picking); });
function pickFiles(opts) {
  picking = opts || {};
  if (!fileInput.isConnected) document.body.append(fileInput);
  fileInput.click();
}

export function wireUploader() {
  subscribe(EV.filesPick, pickFiles);
  subscribe(EV.filesDrop, ({ files, done }) => uploadFiles(files, { done }));
}
