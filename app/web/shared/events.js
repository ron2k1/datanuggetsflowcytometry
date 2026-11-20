// Every event the features send each other, by name, with its payload. Features never import one
// another: one emits a name from this list through emit() in store.js, and whoever cares has
// subscribed to it. app/tests/architecture/test_web_boundaries.py fails when a feature emits or
// subscribes to a name that is not declared here.

/** @typedef {{ key: string, background?: boolean }} OpenTab  Show tab `key`; with `background`, only add it to the strip and leave the redraw to the sender. */
/** @typedef {{ theme: ('light'|'dark') }} ThemeChange  The colour theme switched (shared/theme.js). */
/** @typedef {{ t: string, msg: string }} ActivityAdd  A line was added to the session's activity log. */
/** @typedef {{ open?: boolean }} PanelToggle  Show or hide the terminal; without `open` it flips. */
/** @typedef {{ files: File[] }} FilesDrop  Files dropped on the page, to upload. */
/** @typedef {{ res: { job: object, run_id?: string, gate_id?: string, livecells_id?: string }, what: string, open?: boolean }} JobStarted
 *  A POST that starts a job answered 202; `what` names it for the activity log. The job's tab
 *  opens unless `open` is false (a step that waits for its job in place). */
/** @typedef {{ changed: boolean }} JobsChange  Job records were refreshed; `changed` when a status or progress moved. */
/** @typedef {{ rid: string, cluster: number }} ClusterFocus  Show cluster `cluster` of run `rid` in its plot. */
/** @typedef {{ rid: string, cluster: number }} BoxPlots  Open run `rid`'s box plots tab on cluster `cluster`. */
/** @typedef {{ error: Error }} BootFailed  /config or /workspace did not load. */

export const EV = Object.freeze({
  /** Redraw everything from the store: explorer, tabs, editor, terminal, status. No payload. */
  render: 'app:render',
  /** /config and /workspace are loaded and the first render is done. No payload. */
  ready: 'app:ready',
  /** payload BootFailed */
  bootFailed: 'app:boot-failed',
  /** payload OpenTab */
  openTab: 'tab:open',
  /** payload ThemeChange */
  themeChange: 'theme:change',
  /** payload ActivityAdd */
  activity: 'activity:add',
  /** Redraw the terminal panel only (its output follows the open tab). No payload. */
  panelRender: 'panel:render',
  /** payload PanelToggle */
  panelToggle: 'panel:toggle',
  /** Open the file chooser for an upload. No payload. */
  filesPick: 'files:pick',
  /** payload FilesDrop */
  filesDrop: 'files:drop',
  /** The uploads in flight (S.inflight) moved. No payload. */
  uploadsChange: 'uploads:change',
  /** payload JobStarted */
  jobStarted: 'job:started',
  /** payload JobsChange */
  jobsChange: 'jobs:change',
  /** payload ClusterFocus */
  clusterFocus: 'cluster:focus',
  /** payload BoxPlots */
  boxPlots: 'cluster:box-plots',
});
