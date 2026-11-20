// Fixture mode only: turns an FCS file picked in this tab into the API's Upload shape, computed
// from the file's own DATA segment, so the upload screen shows the real numbers of the real file.
// Nothing leaves the browser.
import { pyStrip } from '../format.js';

let seq = 0;

function readBuffer(file, onProgress) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(fr.error);
    fr.readAsArrayBuffer(file);
  });
}

const sig4 = v => (Number.isFinite(v) ? Number(v.toPrecision(4)) : null);
// A refusal in the server's code and words (features/uploads).
const refusal = (code, message) => Object.assign(new Error(message), { code });

// The TEXT segment's keywords as flowio reads them: UTF-8, else ISO-8859-1 (not the Windows-1252
// a 'latin1' TextDecoder gives); every $ dropped; split at each delimiter that is not doubled
// (none first); keys lowercased; then a doubled delimiter halved, except that for |, \ and *
// flowio halves their regex-escaped pair (\|\| to \|), so a doubled | or * stays as written and
// four backslashes read as two.
const UTF8 = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
function keywords(bytes) {
  let text;
  try { text = UTF8.decode(bytes); } catch { text = Array.from(bytes, b => String.fromCharCode(b)).join(''); }
  const d = text[0], s = text.slice(1, -1).split('$').join(''), parts = [];
  let from = 0;
  for (let i = 1; i < s.length; i++) if (s[i] === d && s[i - 1] !== d && s[i + 1] !== d) { parts.push(s.slice(from, i)); from = i + 1; }
  parts.push(s.slice(from));
  const e = '|\\*'.includes(d) ? `\\${d}` : d, halve = x => x.split(e + e).join(e);
  const kw = {};
  for (let i = 0; i + 1 < parts.length; i += 2) kw[halve(parts[i].toLowerCase())] = halve(parts[i + 1]);
  return kw;
}

function fcsUpload(buf) {
  const bytes = new Uint8Array(buf);
  const ascii = (a, b) => String.fromCharCode(...bytes.subarray(a, b));
  const head = ascii(0, 58);
  if (!/^FCS(2\.0|3\.0|3\.1)/.test(head)) throw refusal('unsupported_type', 'This is not an FCS 2.0, 3.0 or 3.1 file.');
  const t0 = parseInt(head.slice(10, 18), 10), t1 = parseInt(head.slice(18, 26), 10);
  const kw = keywords(bytes.subarray(t0, t1 + 1));
  const npar = parseInt(kw.par, 10) || 0, tot = parseInt(kw.tot, 10) || 0;
  let d0 = parseInt(head.slice(26, 34), 10), d1 = parseInt(head.slice(34, 42), 10);
  if (!d0 && kw.begindata) { d0 = parseInt(kw.begindata, 10); d1 = parseInt(kw.enddata, 10); }
  const type = (kw.datatype || '').toUpperCase();
  const little = (kw.byteord || '1,2,3,4').trim().startsWith('1');
  const bits = range => parseInt(kw[`p${range}b`], 10);
  const dv = new DataView(buf, d0, d1 - d0 + 1);
  const width = type === 'D' ? 8 : type === 'F' ? 4 : bits(1) / 8;
  const read = type === 'D' ? o => dv.getFloat64(o, little) : type === 'F' ? o => dv.getFloat32(o, little)
    : width === 2 ? o => dv.getUint16(o, little) : o => dv.getUint32(o, little);
  const sums = new Float64Array(npar), mins = new Float64Array(npar).fill(Infinity), maxs = new Float64Array(npar).fill(-Infinity);
  for (let e = 0; e < tot; e++) {
    for (let p = 0; p < npar; p++) {
      const v = read((e * npar + p) * width);
      sums[p] += v; if (v < mins[p]) mins[p] = v; if (v > maxs[p]) maxs[p] = v;
    }
  }
  // As the server reads them: $PnN as stored (the package's channel rule reads it so) and $PnS
  // trimmed as Python's str.strip() trims it.
  const columns = Array.from({ length: npar }, (_, p) => ({
    name: kw[`p${p + 1}n`] || `P${p + 1}`, label: pyStrip(kw[`p${p + 1}s`] || ''), numeric: true,
    min: tot ? sig4(mins[p]) : null, max: tot ? sig4(maxs[p]) : null, mean: tot ? sig4(sums[p] / tot) : null, missing: 0,
  }));
  return { rows: tot, columns };
}

export async function readLocalUpload(file, onProgress) {
  if (!/\.fcs$/i.test(file.name)) throw refusal('unsupported_type', 'Only .fcs files are accepted.');
  const buf = await readBuffer(file, onProgress);
  let parsed;
  try {
    parsed = fcsUpload(buf);
  } catch (e) {  // the server names the error flowio raised; here it is the reader's own
    throw e.code ? e : refusal('unreadable_file', `The FCS file could not be read: ${e.name}.`);
  }
  seq += 1;
  return {
    id: `local${seq}`, name: file.name, kind: 'fcs', bytes: file.size, rows: parsed.rows,
    columns: parsed.columns, created: new Date().toISOString(), demo: null, local: true,
  };
}
