// Datasets: the FCS uploads whose colour channels are the same set (docs/app/flow-only-and-
// datasets.md part 2). A colour channel is a $PnN name, compared as stored, that ends in
// FLOW_CHANNEL_SUFFIX and does not start with a scatter prefix: the package's default clustering
// rule. Order never matters, and Time, -H and -W channels and the stains ($PnS) never count. A gate
// takes files from one dataset; the server refuses one that mixes them, with diffText's words.
// Pure: it reads only the uploads and names it is given (live, fixture and read-in-the-tab alike).
import { FLOW_CHANNEL_SUFFIX, LIVECELLS_SCATTER_PREFIXES } from './config.js';
import { plural, pyStrip } from './format.js';

const MAX_NAMES = 3;   // names a list shows before "and N more"

export const isColourChannel = name => name.endsWith(FLOW_CHANNEL_SUFFIX) && !LIVECELLS_SCATTER_PREFIXES.some(p => name.startsWith(p));
// An upload's colour channels, sorted, each once.
export const colourChannels = u => [...new Set((u.columns || []).map(c => c.name).filter(isColourChannel))].sort();
// Two uploads are in one dataset when their keys are equal: the sorted channels, as one string.
const keyOf = channels => JSON.stringify([...new Set(channels)].sort());
export const datasetKey = u => keyOf(colourChannels(u));

// Up to three of list, then how many more: "a, b, c and 2 more".
const listText = list => list.slice(0, MAX_NAMES).join(', ') + (list.length > MAX_NAMES ? ` and ${list.length - MAX_NAMES} more` : '');
export const namesText = names => listText([...names].sort());
// diff(a -> b): what channel list b lacks and adds against a, e.g. "lacks X; adds Y"; '' when equal.
export function diffText(a, b) {
  const inA = new Set(a), inB = new Set(b);
  const lacks = [...inA].filter(c => !inB.has(c)), adds = [...inB].filter(c => !inA.has(c));
  return [lacks.length ? `lacks ${namesText(lacks)}` : '', adds.length ? `adds ${namesText(adds)}` : ''].filter(Boolean).join('; ');
}

// The colour channels whose stains differ between files, by name: each with its stains, in the
// order the files first use them, and the uploads that use each. A stain is trimmed as the server
// trims it, and a file without one never differs. A warning only: one stain can be spelled two
// ways.
export function stainDiffs(files) {
  const by = new Map();
  for (const u of files) {
    for (const c of u.columns || []) {
      const label = pyStrip(c.label || '');
      if (!label || !isColourChannel(c.name)) continue;
      if (!by.has(c.name)) by.set(c.name, new Map());
      const users = by.get(c.name).get(label) || [];
      if (!users.includes(u)) by.get(c.name).set(label, [...users, u]);
    }
  }
  return [...by.keys()].sort().filter(c => by.get(c).size > 1)
    .map(channel => ({ channel, labels: [...by.get(channel)].map(([label, users]) => ({ label, files: users })) }));
}
// "X-A: CD3 (a.fcs, b.fcs) or CD3 BV510 (c.fcs)", one channel per part, three at most.
export function stainText(stains, sep = '; ') {
  const parts = stains.slice(0, MAX_NAMES).map(s => `${s.channel}: ${s.labels.map(l => `${l.label} (${listText(l.files.map(u => u.name))})`).join(' or ')}`);
  const more = stains.length > MAX_NAMES ? ` and ${plural(stains.length - MAX_NAMES, 'more channel')}` : '';
  return parts.join(sep) + more;
}

// The dataset with the most files, the earliest on a tie: the one the others' diffs are against.
export const largest = ds => ds.reduce((m, d) => (!m || d.files.length > m.files.length ? d : m), null);

/**
 * The datasets of uploads, ordered by their first upload: {key, channels, files (in upload
 * order), name (the name given to its channel set in named, else "Dataset N" by that order),
 * diff (against the largest dataset; '' for that one), stains (stainDiffs of its files)}.
 * @param {object[]} uploads  FCS uploads in upload order
 * @param {{channels: string[], name: string}[]} [named]  the workspace's given names
 */
export function groupDatasets(uploads, named = []) {
  const given = new Map(named.map(d => [keyOf(d.channels), d.name]));
  const byKey = new Map();
  for (const u of uploads) {
    const channels = colourChannels(u), key = keyOf(channels);
    if (!byKey.has(key)) byKey.set(key, { key, channels, files: [] });
    byKey.get(key).files.push(u);
  }
  const ds = [...byKey.values()].map((d, i) => ({ ...d, name: given.get(d.key) || `Dataset ${i + 1}` }));
  const base = largest(ds);
  return ds.map(d => ({ ...d, diff: d === base ? '' : diffText(base.channels, d.channels), stains: stainDiffs(d.files) }));
}

// After a batch of uploads: a line for each dataset it made while another dataset was already
// there (knownKeys holds the keys from before), with what it lacks or adds against the largest
// other dataset. Into a workspace with none, the batch's first dataset came with no other there,
// and so did one left alone by a workspace cleared during the batch, whose knownKeys are gone.
export function newDatasetNotes(knownKeys, ds) {
  const made = ds.filter(d => !knownKeys.has(d.key)).slice(knownKeys.size ? 0 : 1);
  return made.flatMap(d => {
    const other = largest(ds.filter(x => x !== d));
    return other ? [`${d.name} is a new dataset: compared with ${other.name}, it ${diffText(other.channels, d.channels)}.`] : [];
  });
}
