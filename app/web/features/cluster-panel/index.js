// A cluster's box plots, as their own tab ('cluster:<rid>', tab.js): its cells per sample group,
// and box plots of its markers pooled and by group (docs/app/cluster-panel.md). The plot opens it
// on a cluster, and the "+" menu on the one it showed last.
import { registerBoxPlots } from './tab.js';

export function mount() { registerBoxPlots(); }
