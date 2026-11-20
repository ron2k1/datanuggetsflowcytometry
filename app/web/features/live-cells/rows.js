// The Live cells step's rows, one per channel the user filters on: {role, channel, keep}. The
// first two are the roles the package names channels for by their names, a viability dye and
// CD45; "Add a channel" appends rows with no role, up to one per marker channel. A channel is a
// $PnN or null (None), keep the side of the line kept. Plain data in, plain data out, so
// app/tests/test_livecells_web.py runs this module in Node.
import { LIVECELLS_SCATTER_PREFIXES, LIVECELLS_TIME_RE } from '../../shared/config.js';

export const ROLES = [
  { role: 'viability', name: 'Viability dye', what: 'a viability dye', keep: '<' },
  { role: 'cd45', name: 'CD45', what: 'CD45', keep: '>' },
];
const ADDED_KEEP = '>';

/** A marker channel: neither forward or side scatter (the package's rule) nor the time channel. */
export const isMarker = pnn => !LIVECELLS_SCATTER_PREFIXES.some(p => pnn.startsWith(p)) && !LIVECELLS_TIME_RE.test(pnn);

/** @param {{pnn: string, pns: string}[]} channels  @returns the marker channels, in order */
export const markerChannels = channels => channels.filter(c => isMarker(c.pnn));

/** The two role rows, each on the package's suggestion when that is a marker channel. */
export const startRows = suggested => ROLES.map(r => {
  const c = suggested && suggested[r.role];
  return { role: r.role, channel: c && isMarker(c) ? c : null, keep: r.keep };
});

export const addRow = rows => [...rows, { role: null, channel: null, keep: ADDED_KEEP }];

/** rows without row i; a role row stays (it goes to None instead). */
export const removeRow = (rows, i) => (rows[i] && rows[i].role ? rows : rows.filter((_, j) => j !== i));

/** A role row's name, or "Channel n" with n counting the added rows only, up to row i. */
export const rowName = (row, i, rows) => (row.role ? ROLES.find(r => r.role === row.role).name
  : `Channel ${rows.slice(0, i + 1).filter(r => !r.role).length}`);

/** How many rows the step offers: one per marker channel, or the server's cap when lower. */
export const maxRows = (markers, cap) => (cap > 0 ? Math.min(markers, cap) : markers);

/** The channels chosen, in row order. */
export const chosen = rows => rows.map(r => r.channel).filter(Boolean);

/** The channels chosen in rows other than row i. */
export const taken = (rows, i) => new Set(rows.filter((r, j) => j !== i && r.channel).map(r => r.channel));

/** The channels chosen in more than one row. */
export function clashes(rows) {
  const seen = new Set(), twice = new Set();
  for (const c of chosen(rows)) (seen.has(c) ? twice : seen).add(c);
  return [...twice];
}

/**
 * One Filter per row that has a channel with a histogram and a line, in row order, with the
 * row's side. lines holds each channel's raw line value by $PnN.
 * @param {{role: string|null, channel: string|null, keep: string}[]} rows
 * @param {Object<string, number>} lines
 * @param {(pnn: string) => boolean} hasHist
 */
export const rowFilters = (rows, lines, hasHist) => rows.flatMap(r =>
  (r.channel && hasHist(r.channel) && lines[r.channel] != null ? [{ column: r.channel, op: r.keep, value: lines[r.channel] }] : []));
