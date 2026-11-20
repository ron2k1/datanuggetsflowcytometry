// A flow run's Cluster stage in words: which clustering it ran and where its nuggets sat. A run's
// settings name both, method and center_method; settings written before the app sent them name
// neither, and the package reads such a run as the hierarchical tree on mean centers
// (ClusterSettings.from_dict), as clusteringOf does here. The cluster form, "Use rX's choice",
// the run record and the plot's inspector all read a run's choices through it.
import { FLOW_METHODS, CENTER_METHODS, FLOW_LEGACY } from './config.js';
import { fmtInt, fmtNum } from './format.js';

const label = (list, v) => (list.find(([x]) => x === v) || [null, v])[1];

// { method, center_method } a run clustered with, from its settings (null or {} for none). With
// no method the run is a legacy one: the tree, on mean centers unless the settings name others.
// A method without centers takes the default, the first of CENTER_METHODS (the original points).
export function clusteringOf(settings) {
  const s = settings || {};
  if (s.method == null) return { method: FLOW_LEGACY.method, center_method: s.center_method ?? FLOW_LEGACY.center_method };
  return { method: s.method, center_method: s.center_method ?? CENTER_METHODS[0][0] };
}

// The words for a method or a center method; a value the lists don't hold (the package's
// "random" centers, which the CLI can set) shows as it is.
export const methodText = v => label(FLOW_METHODS, v);
export const centersText = v => label(CENTER_METHODS, v);

// Why a run's k used is below the k asked: the tree cuts into no more clusters than the nuggets
// in use, and weighted k-means, which needs two nuggets in use per cluster, can end with a
// cluster empty, its numbers then compacted.
function lowered(c) {
  if (c.k_used === c.k) return '';
  if (c.k > c.nuggets_clustered) return ` (k = ${fmtInt(c.k)} asked, more than the ${fmtInt(c.nuggets_clustered)} nuggets in use)`;
  const n = c.k - c.k_used;
  return ` (k = ${fmtInt(c.k)} asked, ${fmtInt(n)} cluster${n === 1 ? '' : 's'} ended empty)`;
}

// The record view's rows, [term, definition, code], from run.json (rec): the clustering and its
// k, the centers, the nuggets clustered and dropped (weight 0), the total WWCSS, and the R calls
// that rebuild the run, with code true for those. The clustering block gives the k used beside
// the k asked (lowered above). A run.json written before the block has the first two rows only,
// from its settings, which hold the k asked: the tree cut into fewer when fewer nuggets had cells.
export function clusteringRows(rec) {
  const s = rec.settings || {};
  const c = rec.clustering;
  const { method, center_method } = clusteringOf(s);
  if (!c) {
    return [
      ['Clustering', `${methodText(method)}, k = ${fmtInt(s.k)} asked (this run.json predates the clustering record)`, false],
      ['Nugget centers', centersText(center_method), false],
    ];
  }
  const r = c.r || {};
  return [
    ['Clustering', `${methodText(c.method)}, k = ${fmtInt(c.k_used)}${lowered(c)}`, false],
    ['Nugget centers', centersText(center_method), false],
    ['Nuggets', `${fmtInt(c.nuggets_clustered)} clustered, ${fmtInt(c.nuggets_dropped)} dropped (weight 0)`, false],
    ['Total WWCSS', fmtNum(c.total_wwcss), false],
    r['create.DN'] == null
      ? ['create.DN in R', "none: these nuggets were drawn with NumPy's generator, not R's set.seed draws", false]
      : ['create.DN in R', r['create.DN'], true],
    ['Clustering in R', r.cluster, true],
  ];
}
