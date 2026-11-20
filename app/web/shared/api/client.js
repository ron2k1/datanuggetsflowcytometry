// The API client: one method per endpoint the web calls, over whichever transport index.js chose.
// Shapes are pinned in docs/app/contract.md section 3 and docs/app/contract-livecells.md section 2.3;
// the typedefs below name only the fields the web reads.

/** @typedef {'queued'|'running'|'done'|'failed'|'cancelled'} JobStatus */
/**
 * @typedef {object} Job
 * @property {string} id
 * @property {'general'|'gate'|'flow'|'livecells'} kind
 * @property {JobStatus} status
 * @property {number} progress  0..1
 * @property {string|null} stage
 * @property {string|null} message
 * @property {string[]} log_tail
 * @property {{code: string, message: string, param: string|null}|null} error
 * @property {string|null} gate_id
 * @property {string|null} run_id
 */
/** @typedef {{job: Job, run_id?: string, gate_id?: string, livecells_id?: string}} JobStart  202 from a POST that queues work. */
/**
 * @typedef {{name: string, label: string, numeric: boolean, min: number|null, max: number|null, mean: number|null,
 *   missing: number, range?: number|null}} Column  range: an FCS channel's $PnR range (null when its header gives none;
 *   absent on a CSV and on an upload made before ranges were recorded)
 */
/** @typedef {{id: string, kind: 'csv'|'fcs', name: string, bytes: number, rows: number, columns: Column[]}} Upload */
/** @typedef {{id: string, files: object[]|null, figures: Object<string, string>|null, status: JobStatus}} Gate */
/** @typedef {{id: string, channels: string[], name: string}} DatasetName  the name given to a colour channel set */
/**
 * @typedef {{mode: 'trial'|'local', uploads: Upload[], runs: object[], gates: Gate[], jobs: Job[],
 *   datasets?: DatasetName[]}} Workspace  datasets: absent from a server that keeps no names
 */
/**
 * @typedef {{mode: 'trial'|'local', defaults: object, limits: object, caps: Object<string, number|null>|null}} Config
 *   defaults.cluster.cofactor is 'auto'; defaults.cofactor_auto {rule: 'per_channel', floor, min_negative_fraction}
 *   is the rule auto picks each channel's cofactor by
 */
/** @typedef {{column: string, op: string, value?: number, value2?: number}} Filter  one row filter (contract 3.4). */
/**
 * @typedef {object} LivecellsRequest
 * @property {number[][]} pops  one list of population numbers per gate file
 * @property {string[]} channels  $PnN names
 * @property {number} [bins]
 * @property {number|'auto'} [cofactor]  'auto' (the default) or a number from 0
 */
/**
 * @typedef {object} LivecellsStep  GET /flow/gates/{gid}/livecells
 * @property {string} gate_id
 * @property {{pnn: string, pns: string}[]} channels  gate file 1's channels
 * @property {{viability: string|null, cd45: string|null, candidates: {viability: string[], cd45: string[]}}} suggested
 * @property {{id: string, status: JobStatus, created: string, request: LivecellsRequest}[]} livecells
 */
/**
 * @typedef {object} LivecellsRecord  GET /flow/gates/{gid}/livecells/{lid}; histograms null until done
 * @property {string} id
 * @property {JobStatus} status
 * @property {string} job
 * @property {LivecellsRequest} request
 * @property {object|null} histograms  channel_histograms(): cofactor (the number every channel is drawn on;
 *   absent under per-channel auto), cofactor_from ('auto'|'set'), and under per-channel auto cofactors,
 *   negative_fraction and negative_sd (one each per entry of channels, in its order); a set made before auto
 *   went per channel has range (auto's widest marker channel range, or null) instead; edges, per channel
 *   lo/hi/counts/below/above
 */
/**
 * @typedef {object} LivecellsCounts  POST /flow/gates/{gid}/livecells/{lid}/counts
 * @property {string[]} row_filters  the filters as the package wrote them
 * @property {number} kept
 * @property {number} passed
 * @property {{number: number, name: string, events: number, kept: number, passed: number, left_out: boolean}[]} files
 */

/**
 * @typedef {object} ApiClient
 * @property {() => Promise<Config>} config  GET /config
 * @property {() => Promise<Workspace>} workspace  GET /workspace
 * @property {() => Promise<null>} deleteWorkspace  DELETE /workspace
 * @property {(file: File, onProgress?: (fraction: number) => void) => Promise<Upload>} upload  POST /uploads
 * @property {(uid: string) => Promise<Upload>} uploadInfo  GET /uploads/{uid}
 * @property {(uid: string) => Promise<null>} deleteUpload  DELETE /uploads/{uid}
 * @property {() => Promise<{demos: object[]}>} demos  GET /demos
 * @property {(id: string) => Promise<{uploads: Upload[]}>} loadDemo  POST /demos/{id}/load
 * @property {(body: {channels: string[], name: string}) => Promise<{datasets: DatasetName[]}>} nameDataset  POST /datasets
 * @property {(body: object) => Promise<JobStart>} startGate  POST /flow/gates
 * @property {(gid: string) => Promise<Gate>} gate  GET /flow/gates/{gid}
 * @property {(gid: string) => Promise<null>} deleteGate  DELETE /flow/gates/{gid}
 * @property {(body: object) => Promise<JobStart>} startFlowRun  POST /flow/runs
 * @property {(jid: string) => Promise<Job>} job  GET /jobs/{jid}
 * @property {(jid: string) => Promise<Job>} cancelJob  POST /jobs/{jid}/cancel
 * @property {(rid: string) => Promise<object>} manifest  GET /runs/{rid}
 * @property {(rid: string) => Promise<object>} plot  GET /runs/{rid}/plot
 * @property {(rid: string) => Promise<object>} cells  GET /runs/{rid}/cells
 * @property {(rid: string) => Promise<object>} compare  GET /runs/{rid}/compare
 * @property {(rid: string, name: string) => Promise<string|null>} fileUrl  a run file's link, null when it cannot be fetched
 * @property {(rid: string) => string|null} zipUrl  GET /runs/{rid}/download.zip, null in fixture mode
 * @property {(gid: string) => Promise<LivecellsStep>} livecells  GET /flow/gates/{gid}/livecells
 * @property {(gid: string, body: LivecellsRequest) => Promise<JobStart>} startLivecells  POST /flow/gates/{gid}/livecells
 * @property {(gid: string, lid: string) => Promise<LivecellsRecord>} livecellsRecord  GET /flow/gates/{gid}/livecells/{lid}
 * @property {(gid: string, lid: string, rowFilters: Filter[]) => Promise<LivecellsCounts>} livecellsCounts  POST .../livecells/{lid}/counts
 */

/**
 * @param {{request: (method: string, path: string, body?: object) => Promise<any>,
 *          upload: Function, fileUrl: Function, zipUrl: Function}} t  the transport
 * @returns {ApiClient}
 */
export function makeClient(t) {
  const get = path => t.request('GET', path);
  const post = (path, body) => t.request('POST', path, body === undefined ? {} : body);
  return {
    config: () => get('/config'),
    workspace: () => get('/workspace'),
    deleteWorkspace: () => t.request('DELETE', '/workspace'),
    upload: (file, onProgress) => t.upload(file, onProgress),
    uploadInfo: uid => get(`/uploads/${uid}`),
    deleteUpload: uid => t.request('DELETE', `/uploads/${uid}`),
    demos: () => get('/demos'),
    loadDemo: id => post(`/demos/${id}/load`),
    nameDataset: body => post('/datasets', body),
    startGate: body => post('/flow/gates', body),
    gate: gid => get(`/flow/gates/${gid}`),
    deleteGate: gid => t.request('DELETE', `/flow/gates/${gid}`),
    startFlowRun: body => post('/flow/runs', body),
    job: jid => get(`/jobs/${jid}`),
    cancelJob: jid => post(`/jobs/${jid}/cancel`),
    manifest: rid => get(`/runs/${rid}`),
    plot: rid => get(`/runs/${rid}/plot`),
    cells: rid => get(`/runs/${rid}/cells`),
    compare: rid => get(`/runs/${rid}/compare`),
    fileUrl: (rid, name) => t.fileUrl(rid, name),
    zipUrl: rid => t.zipUrl(rid),
    livecells: gid => get(`/flow/gates/${gid}/livecells`),
    startLivecells: (gid, body) => post(`/flow/gates/${gid}/livecells`, body),
    livecellsRecord: (gid, lid) => get(`/flow/gates/${gid}/livecells/${lid}`),
    livecellsCounts: (gid, lid, rowFilters) => post(`/flow/gates/${gid}/livecells/${lid}/counts`, { row_filters: rowFilters }),
  };
}
