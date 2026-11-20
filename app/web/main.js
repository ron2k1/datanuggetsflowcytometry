// The composition root, and the only module that imports more than one feature: mount every
// feature, read /config and /workspace, then draw. Features talk to each other only through the
// store's events (shared/events.js) and the view registry and slots (shared/views.js).
// FEATURES is in draw order: EV.render reaches its subscribers in the order they mounted.
import { api, FIXTURES } from './shared/api/index.js';
import { EV } from './shared/events.js';
import { S, emit, loadWorkspace, activity, fcsUploads, flowRuns } from './shared/store.js';
import * as theme from './features/theme/index.js';
import * as explorer from './features/explorer/index.js';
import * as tabs from './features/tabs/index.js';
import * as shell from './features/shell/index.js';
import * as terminal from './features/terminal/index.js';
import * as upload from './features/upload/index.js';
import * as jobs from './features/jobs/index.js';
import * as start from './features/start/index.js';
import * as runLocally from './features/run-locally/index.js';
import * as gate from './features/gate/index.js';
import * as populationPicker from './features/population-picker/index.js';
import * as liveCells from './features/live-cells/index.js';
import * as plot from './features/plot/index.js';
import * as legend from './features/legend/index.js';
import * as clusterPanel from './features/cluster-panel/index.js';
import * as compare from './features/compare/index.js';
import * as files from './features/files/index.js';
import * as record from './features/record/index.js';

const FEATURES = [theme, explorer, tabs, shell, terminal, upload, jobs, start, runLocally, gate, populationPicker, liveCells, plot, legend, clusterPanel, compare, files, record];

async function boot() {
  FEATURES.forEach(f => f.mount());
  try {
    S.config = await api.config();
    await loadWorkspace();
  } catch (e) {
    emit(EV.bootFailed, { error: e });
    return;
  }
  activity(`Workspace ready${FIXTURES ? ' (fixture mode)' : ''}: ${fcsUploads().length} uploads, ${flowRuns().length} runs`);
  emit(EV.render);
  emit(EV.ready);
}

boot();
