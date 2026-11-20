// The fixture transport (?fixtures=1): every call reads app/web/fixtures/<METHOD>__<path>.json,
// named as contract section 6 pins it. Uploads are read in this tab and never sent (DELETE
// /uploads/{uid} forgets one), and dataset names are kept in this tab.
import { FIXTURE_DIR, DATASET_NAME_MAX, DATASET_CHANNELS_MAX, DATASET_CHANNEL_CHARS, DATASET_CHANNELS_BYTES, DATASETS_MAX } from '../config.js';
import { colourChannels } from '../datasets.js';
import { pyStrip } from '../format.js';
import { ApiError } from './errors.js';
import { readLocalUpload } from './local-upload.js';

const LOCAL_FIXTURES = new URLSearchParams(location.search).get('mode') === 'local';
// Fixtures that have a local-mode twin, swapped in by ?fixtures=1&mode=local.
const LOCAL_TWINS = new Set(['GET__config.json', 'GET__workspace.json']);

export function fixtureName(method, path) {
  const p = path.split('?')[0].replace(/^\/+/, '').replace(/\/+$/, '');
  const name = `${method.toUpperCase()}__${p.split('/').join('__')}.json`;
  return LOCAL_FIXTURES && LOCAL_TWINS.has(name) ? name.replace(/\.json$/, '.local.json') : name;
}

// The fixture list is read once, so a missing fixture becomes the API's error shape without a
// 404 request (which a browser would log as a console error).
let indexPromise = null;
function fixtureIndex() {
  if (!indexPromise) {
    indexPromise = fetch(`${FIXTURE_DIR}/index.json`).then(r => r.json()).then(j => ({ names: new Set(j.fixtures), files: j.files || {} }));
  }
  return indexPromise;
}

// POST /datasets as the server answers it (features/datasets): its checks in its order and words,
// a length counted in code points and the name trimmed of what Python's str.strip() trims, as the
// server counts and trims. Then one record per colour channel set (matched in any order, stored
// sorted); a blank name removes the set's record. The records start as the recorded workspace's,
// which has none.
let named = null, lastId = 0;
const setKey = channels => JSON.stringify([...channels].sort());
const refuse = (param, message) => new ApiError(422, { error: { code: 'invalid_setting', message, param } });
const chars = s => [...s].length;
// the server's CONTROL: Unicode Cc, the line and paragraph separators and the bidi controls
const CONTROL = /[\p{Cc}\u2028\u2029\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u;
// the server's LONE: half a surrogate pair (with the u flag, a whole pair is one character)
const LONE = /[\ud800-\udfff]/u;
// A non-empty list of names as long as Python's json.dumps writes it, as the server measures one:
// 4 bytes a name ('["a", "b"]'), and per character 1 in printable ASCII, 2 for a quote, a
// backslash, a backspace, a form feed, a line feed, a return or a tab, 12 past U+FFFF (a
// surrogate pair, each escaped) and 6 (one escape) otherwise.
const SHORT_ESCAPED = '"\\\b\f\n\r\t';
const jsonChars = ch => {
  const cp = ch.codePointAt(0);
  return SHORT_ESCAPED.includes(ch) ? 2 : cp >= 0x20 && cp < 0x7f ? 1 : cp > 0xffff ? 12 : 6;
};
const pyJsonLength = list => list.reduce((n, s) => n + 4 + [...s].reduce((m, ch) => m + jsonChars(ch), 0), 0);
// The body as pydantic checks it (features/datasets/schemas.py), before the checks below, in its
// order and words: an object, then channels and name, then the first field the model does not have
// (one that is undefined would not be in the JSON).
const shape = (param, msg) => refuse(param, `${param}: ${msg}`);
function checkedBody(body) {
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    throw refuse(null, 'Input should be a valid dictionary or object to extract fields from');
  }
  const { channels, name } = body;
  if (channels === undefined) throw shape('channels', 'Field required');
  if (!Array.isArray(channels)) throw shape('channels', 'Input should be a valid list');
  if (channels.some(c => typeof c !== 'string')) throw shape('channels', 'Input should be a valid string');
  if (name === undefined) throw shape('name', 'Field required');
  if (typeof name !== 'string') throw shape('name', 'Input should be a valid string');
  const extra = Object.keys(body).find(k => k !== 'channels' && k !== 'name' && body[k] !== undefined);
  if (extra !== undefined) throw shape(extra, 'Extra inputs are not permitted');
  return body;
}
function checkedChannels(channels) {
  if (!channels.length) throw refuse('channels', 'List at least one channel.');
  if (channels.length > DATASET_CHANNELS_MAX) throw refuse('channels', `channels is ${channels.length}; this server allows at most ${DATASET_CHANNELS_MAX}.`);
  for (const c of channels) {
    if (!c) throw refuse('channels', 'A channel name cannot be empty.');
    if (chars(c) > DATASET_CHANNEL_CHARS) {
      throw refuse('channels', `A channel name is ${chars(c)} characters long; this server allows at most ${DATASET_CHANNEL_CHARS}.`);
    }
    if (LONE.test(c)) throw refuse('channels', 'A channel name has a lone surrogate (U+D800 to U+DFFF), which is not a character.');
  }
  if (new Set(channels).size < channels.length) throw refuse('channels', 'List each channel once.');
  const size = pyJsonLength(channels);
  if (size > DATASET_CHANNELS_BYTES) throw refuse('channels', `The channel list is ${size} bytes as JSON; this server allows at most ${DATASET_CHANNELS_BYTES}.`);
  return [...channels].sort();
}
function checkedName(name) {
  const n = pyStrip(name);
  if (chars(n) > DATASET_NAME_MAX) throw refuse('name', `The name is ${chars(n)} characters long; a dataset name is at most ${DATASET_NAME_MAX}.`);
  if (CONTROL.test(n)) throw refuse('name', 'The name has a control character, such as a tab, a line break or a text direction mark.');
  if (LONE.test(n)) throw refuse('name', 'The name has a lone surrogate (U+D800 to U+DFFF), which is not a character.');
  return n;
}
// The files read in this tab, by id, with their colour channel sets. DELETE /uploads/{uid} of
// one forgets it, as the server deletes an upload; a recorded upload has no DELETE fixture.
const tabSets = new Map();
// The sets of this tab's uploads, the recorded workspace's (a loaded demo's are the same files)
// and the files read in the tab, as the server reads its uploads' at the cap.
async function uploadSets() {
  const ws = await (await fetch(`${FIXTURE_DIR}/${fixtureName('GET', '/workspace')}`)).json();
  return new Set([...ws.uploads.filter(u => u.kind === 'fcs').map(u => setKey(colourChannels(u))), ...tabSets.values()]);
}
function nameDataset(body) {
  const { channels, name } = checkedBody(body);
  const set = checkedChannels(channels), n = checkedName(name);
  named = named || [];
  const key = setKey(set), i = named.findIndex(d => setKey(d.channels) === key);
  const add = () => { named.push({ id: `d${++lastId}`, channels: set, name: n }); return { datasets: structuredClone(named) }; };
  if (!n) { if (i >= 0) named.splice(i, 1); } else if (i >= 0) named[i] = { ...named[i], name: n };
  else if (named.length < DATASETS_MAX) return add();
  else {
    // at the cap, the names of sets no upload has go first, and a refusal removes none
    return uploadSets().then(held => {
      const kept = named.filter(d => held.has(setKey(d.channels)));
      if (kept.length >= DATASETS_MAX) throw refuse('name', `This workspace holds ${DATASETS_MAX} dataset names, the most it can; remove one first.`);
      named = kept;
      return add();
    });
  }
  return { datasets: structuredClone(named) };
}

export async function request(method, path, body) {
  if (method === 'POST' && path === '/datasets') return nameDataset(body);
  const tabFile = method === 'DELETE' && path.match(/^\/uploads\/([^/]+)$/);
  if (tabFile && tabSets.has(tabFile[1])) { tabSets.delete(tabFile[1]); return null; }
  const idx = await fixtureIndex();
  const name = fixtureName(method, path);
  if (!idx.names.has(name)) {
    throw new ApiError(404, { error: { code: 'not_found', message: `No fixture for ${method} ${path.split('?')[0]} (fixture mode).`, param: null } });
  }
  const r = await fetch(`${FIXTURE_DIR}/${name}`);
  const data = await r.json();
  if (name !== fixtureName('GET', '/workspace')) return data;
  if (!named) {
    named = data.datasets || [];
    lastId = Math.max(0, ...named.map(d => parseInt(d.id.slice(1), 10) || 0));
  }
  return { ...data, datasets: structuredClone(named) };
}

// The picked file's real stats, computed in this tab.
export async function upload(file, onProgress) {
  const u = await readLocalUpload(file, onProgress);
  tabSets.set(u.id, setKey(colourChannels(u)));
  return u;
}

// Fixture mode keeps only the small run files a builder copied.
export async function fileUrl(rid, name) {
  const idx = await fixtureIndex();
  return (idx.files[rid] || []).includes(name) ? `${FIXTURE_DIR}/files/${rid}/${name}` : null;
}
export const zipUrl = () => null;
