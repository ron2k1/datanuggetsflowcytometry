// Number, size, date and count formats. Four significant digits match what the API sends.

const NF = new Intl.NumberFormat('en-US');
export const fmtInt = v => (v == null ? '–' : NF.format(v));
export const fmtBytes = b => (b == null ? '–' : b >= 1e9 ? (b / 1e9).toFixed(2) + ' GB' : b >= 1e6 ? (b / 1e6).toFixed(1) + ' MB' : b >= 1e3 ? (b / 1e3).toFixed(1) + ' kB' : b + ' B');
// Four significant digits, as the API sends them; large values keep thousands separators.
export const fmtNum = v => {
  if (v == null || Number.isNaN(v)) return '–';
  if (typeof v !== 'number') return String(v);
  if (Number.isInteger(v)) return NF.format(v);
  if (Math.abs(v) >= 1e4) return NF.format(Math.round(v));
  return String(Number(v.toPrecision(4)));
};
export const fmtPct = (v, d = 1) => (v == null ? '–' : v.toFixed(d) + '%');
export const fmtDate = s => {
  if (!s) return '–';
  const d = new Date(s);
  return Number.isNaN(+d) ? s : d.toLocaleString([], { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};
// How long something took, from milliseconds: "<1 s", "42 s", "3 min 5 s", "1 h 4 min".
export const fmtDuration = ms => {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return '–';
  if (ms < 1000) return '<1 s';
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${s % 60} s`;
  return `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`;
};
export const hexA = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
export const clock = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
export const plural = (n, w, ws = w + 's') => `${fmtInt(n)} ${n === 1 ? w : ws}`;
// s trimmed of what Python's str.strip() trims, as the server trims stains and dataset names:
// JS's trim() keeps \x1c-\x1f and \x85, which it trims, and trims U+FEFF, which it keeps.
const PY_SPACE = '[\\t-\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
const PY_STRIP = new RegExp(`^${PY_SPACE}+|${PY_SPACE}+$`, 'g');
export const pyStrip = s => s.replace(PY_STRIP, '');
