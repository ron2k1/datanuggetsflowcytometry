// The flow run's Transform stage cofactor in words: a run's transform as run.json or the plot
// payload records it, and the Live cells histograms' cofactors. Auto gives each clustered channel
// its own cofactor, picked from the cells the run clusters when it starts (the package's
// resolve_cofactor), so the page can't preview it; a number applies to every channel. Older runs
// recorded one number for every channel, auto from the files' headers or set.
import { fmtNum, fmtPct } from './format.js';
import { LIVECELLS_SCATTER_PREFIXES, LIVECELLS_TIME_RE } from './config.js';

// A marker channel: every channel but forward and side scatter and Time. The upload view shows a
// header range for these only.
export const isMarkerChannel = name => !LIVECELLS_SCATTER_PREFIXES.some(p => name.startsWith(p)) && !LIVECELLS_TIME_RE.test(name);

// The cluster form's line while the cofactor is on auto, with the floor when /config gives the
// rule (defaults.cofactor_auto): there is no number to show before the run.
export const autoText = rule => `Auto: picked per channel when the run starts, from the spread of the values below 0${
  rule && typeof rule.floor === 'number' ? `, at least ${fmtNum(rule.floor)}` : ''}`;

/**
 * A run's Transform stage from its run.json, read as the package reads it (run_transform): an
 * arcsinh written before cofactor_from was recorded is set; a run.json written before the stage
 * was recorded takes its settings' cofactor, 6000 when it has none. null when the record has
 * neither a transform nor a numeric cofactor (one that did not load).
 * @param {{transform?: object, settings?: object}|null|undefined} record
 */
export function runTransform(record) {
  const t = record && record.transform;
  if (t && typeof t === 'object') return t.name === 'arcsinh' && !t.cofactor_from ? { ...t, cofactor_from: 'set' } : t;
  if (!record || !record.settings) return null;
  const c = record.settings.cofactor ?? 6000;
  if (typeof c !== 'number') return null;
  return c > 0 ? { name: 'arcsinh', cofactor: c, cofactor_from: 'set' } : { name: 'none' };
}

// True when t (a transform, or a Live cells set's histograms) gives each channel its own
// cofactor: auto since it went per channel, which records cofactors and no single cofactor.
export const perChannel = t => !!t && Array.isArray(t.cofactors);

// Channel j's cofactor (j in the run's channel order, or the histograms' channels order): its
// own in a per-channel t, else the one number every channel shares.
export const cofactorFor = (t, j) => t.cofactors?.[j] ?? t.cofactor;

// A whole number, as the run's Transform lines and the Live cells job's log print an auto
// cofactor and its SD: their median is read to about 0.6%, so a fourth digit would claim more.
const whole = v => fmtNum(typeof v === 'number' ? Math.round(v) : v);

// One cofactor as the server's text gives it: auto's whole, a number set to four significant
// digits as typed (2.5 stays 2.5).
export const fmtCofactor = (c, from) => (from === 'auto' ? whole(c) : fmtNum(c));

// An arcsinh stage's units: "arcsinh(x / 150)" when the channels share one cofactor, else
// "arcsinh(x / c), c per channel (150–338)". js limits a per-channel t to those channels (the
// ones a plot draws); every channel when omitted.
export function cofactorTag(t, js) {
  if (!perChannel(t)) return `arcsinh(x / ${fmtCofactor(t.cofactor, t.cofactor_from)})`;
  const cs = (js || t.cofactors.map((_, j) => j)).map(j => t.cofactors[j]).filter(c => typeof c === 'number');
  if (!cs.length) return 'arcsinh(x / c), c per channel';
  const lo = whole(Math.min(...cs)), hi = whole(Math.max(...cs));
  return lo === hi ? `arcsinh(x / ${lo})` : `arcsinh(x / c), c per channel (${lo}–${hi})`;
}

// The values' units under a transform, with how the cofactor was chosen, as Compare, the plot
// and its inspector print them: "arcsinh(x / 150), cofactor auto", "arcsinh(x / 6,000), cofactor
// set", "arcsinh(x / c), c per channel (150–338), cofactor auto", or "raw values" with no arcsinh.
export const transformText = (t, js) => (t.name === 'arcsinh' ? `${cofactorTag(t, js)}, cofactor ${t.cofactor_from || 'set'}` : 'raw values');

// A plot payload's arcsinh stage, or { name: 'none' } for a run clustered on raw values. The Scale
// stage after it is not one the viewer converts by: the payload's tables undo it.
export const plotTransform = P => (P.transform || []).find(x => x.name === 'arcsinh') || { name: 'none' };
// A plot payload's values as the plot and the box plots show them, in the Transform stage's units
// with how the cofactor was chosen; js are the channels in view (P.columns indices), so
// per-channel auto names their own cofactor or the range of theirs.
export const plotUnits = (P, js) => transformText(plotTransform(P), js);

// How an arcsinh stage's cofactor was chosen, for a line that already shows its units: "set",
// auto's rule per channel with the floor and guard the run recorded, or an older auto's reason
// from the headers, "auto (channels up to 262,144)". A null range is either fallback of that
// rule, a marker channel with no usable range or no marker channel, so it names neither.
export function cofactorWhy(t) {
  if (t.cofactor_from !== 'auto') return 'set';
  if (perChannel(t)) {
    const floor = fmtNum(t.floor);
    return `auto (each channel: the SD of the cells below 0 where at least ${fmtNum(100 * t.min_negative_fraction)}% of the kept cells are below 0, at least ${floor}; else ${floor})`;
  }
  return `auto (${typeof t.range === 'number' ? `channels up to ${fmtNum(t.range)}` : 'no usable range in the headers'})`;
}

/**
 * The run record's table of a per-channel transform, as the run's Transform lines give it: each
 * channel's cofactor, the share of its kept cells below 0 and their SD, whole numbers, the SD
 * only where the rule used it ('–' where no cell is below 0, or fewer than min_negative_fraction
 * of them are and the channel took the floor without it), by the run's labels. null for a
 * transform with one cofactor.
 * @param {object} t
 * @param {string[]} labels  run.json's labels, in its channel order
 * @returns {{channel: string, cofactor: string, below: string, sd: string}[]|null}
 */
export function cofactorRows(t, labels) {
  if (!perChannel(t)) return null;
  const f = j => (t.negative_fraction ? t.negative_fraction[j] : null);
  const used = j => typeof t.min_negative_fraction !== 'number' || f(j) == null || f(j) >= t.min_negative_fraction;
  return t.cofactors.map((c, j) => ({
    channel: labels[j] ?? `Channel ${j + 1}`,
    cofactor: whole(c),
    below: f(j) == null ? '–' : fmtPct(100 * f(j)),
    sd: whole(t.negative_sd && used(j) ? t.negative_sd[j] : null),
  }));
}
