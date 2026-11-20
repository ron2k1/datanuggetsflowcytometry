// Step "Live cells", the part in the population picker's slot 'gate.livecells': choose the
// channels to filter on (a row for a viability dye and one for CD45, on the channels the package
// names for them, and as many more as there are marker channels through "Add a channel"), load
// their histograms for the chosen populations (a livecells job), place a line on each, and hand
// the row filters on to the cluster form. The dropdowns list marker channels only, never forward
// or side scatter (the gate settings take those) nor Time. Behaviour is
// docs/app/contract-livecells.md section 3; the rows are rows.js. Everything is kept in
// ctx.state, so Back, a redraw or a finished job keeps the choices and the lines; late answers
// redraw through state.view.
import { el, fill, docHead, seg } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtNum, plural } from '../../shared/format.js';
import { LIVECELLS_BINS, PICK_QUIET_MS, POLL_MS } from '../../shared/config.js';
import { plotTheme, fileColor } from '../../shared/plot-base.js';
import { api } from '../../shared/api/index.js';
import { EV } from '../../shared/events.js';
import { emit, subscribe, jobById, caps, upsert } from '../../shared/store.js';
import { histogram, channelScale, roundIn } from './histogram.js';
import { countsView, scheduleCounts, resetCounts, errText } from './counts.js';
import { ROLES, isMarker, markerChannels, startRows, addRow, removeRow, rowName, maxRows, chosen, taken, clashes, rowFilters } from './rows.js';

const KEEP = [['<', 'Keep below'], ['>', 'Keep above']];
const SUB = 'Optional: drop dead cells and cells that are not leukocytes before clustering, and filter on other markers. The first two dropdowns start on the channels whose names look like a viability dye and CD45; Add a channel adds another. The dropdowns list marker channels only: forward and side scatter are set in the gate settings. Click a histogram to place a line, drag it or type a value to move it, and choose which side to keep. Lines are raw values, so the Transform chosen on the next step does not move them. Skip goes on without filters.';

const active = j => !!j && (j.status === 'queued' || j.status === 'running');
const label = c => (c.pns ? `${c.pns} (${c.pnn})` : c.pnn);

function init(s) {
  if (s.lines) return;
  Object.assign(s, { info: null, infoErr: null, rows: null, reqKey: null, lid: null, jobId: null, record: null, loadErr: null,
    busy: false, retry: 0, wait: 0, posted: null, focus: null, lines: {}, perFile: false, leaveOut: null, view: null });
  resetCounts(s);
}

const picked = s => (s.rows ? chosen(s.rows) : []);
const clash = s => !!s.rows && clashes(s.rows).length > 0;
const histOf = (s, pnn) => (s.record && s.record.histograms.channels.find(h => h.channel === pnn)) || null;
const dye = s => { const r = s.rows && s.rows.find(x => x.role === 'viability'); return (r && r.channel) || null; };
const leaveOut = s => !!dye(s) && s.leaveOut !== false;
const filtersOf = s => (s.rows ? rowFilters(s.rows, s.lines, pnn => !!histOf(s, pnn)) : []);
// trial mode caps the channels of a set (contract-livecells 2.4); local mode sends no caps
const channelCap = () => { const c = caps(); return c ? c.livecells_channels_max : null; };

// A line kept from an earlier request (Back, other populations) stays only inside the new range,
// read on the channel's own cofactor.
function dropLinesOutside(s) {
  for (const h of s.record.histograms.channels) {
    const { toRaw } = channelScale(s.record.histograms, h);
    const v = s.lines[h.channel];
    if (v != null && (v < toRaw(h.lo) || v > toRaw(h.hi))) delete s.lines[h.channel];
  }
}

/**
 * The slot part's render; see the slot's ctx in features/population-picker/index.js.
 * @param {HTMLElement} host
 * @param {object} ctx
 */
export function render(host, ctx) {
  const s = ctx.state;
  init(s);
  let dead = false, charts = [], counts = null, barUpdate = () => {};
  const live = {
    all: () => { if (!dead) { advance(); draw(); } },
    advance: () => { if (!dead) advance(); },
    counts: () => { if (!dead && counts) { counts.update(); barUpdate(); } },
  };
  s.view = live;
  const again = () => { if (s.view) s.view.all(); };
  const recount = () => { scheduleCounts(s, ctx.gid, filtersOf(s)); if (counts) counts.update(); barUpdate(); };
  const short = pnn => { const c = s.info && s.info.channels.find(x => x.pnn === pnn); return c && c.pns ? c.pns : pnn; };
  const rowId = i => `lc-${ctx.gid}-row-${i}`;

  // The next thing to load: the channels, then the request's record (POST, the job, GET).
  function advance() {
    if (s.busy || s.retry) return;
    if (!s.info) {
      if (s.infoErr) return;
      s.busy = true;
      api.livecells(ctx.gid).then(info => {
        s.info = info;
        if (!s.rows) s.rows = startRows(info.suggested);
      }, e => { s.infoErr = errText(e); }).finally(() => { s.busy = false; again(); });
      return;
    }
    const ch = picked(s);
    if (!ch.length || clash(s)) return;
    // 'auto' unless the cluster form has a number. Under auto each channel's axis uses its own
    // cofactor from histograms.cofactors, the one a run without row filters on these cells picks;
    // a number is the one in histograms.cofactor
    const req = { pops: ctx.pops, channels: ch, bins: LIVECELLS_BINS, cofactor: ctx.cofactor ?? 'auto' };
    const key = JSON.stringify(req);
    if (key !== s.reqKey) { queue(req, key); return; }
    if (s.loadErr || !s.lid) return;
    if (s.record) {
      if (!s.counts.shown && !s.counts.pending && !s.counts.err && filtersOf(s).length) recount();
      return;
    }
    if (active(jobById(s.jobId))) return; // the jobs poller ends it: EV.render, EV.jobsChange
    fetchRecord(key);
  }
  // A changed choice drops the old histograms at once but sends its POST only after
  // PICK_QUIET_MS without another change, so picking several channels in a row (or arrowing
  // through a closed dropdown, which fires a change per step) starts one job, not one per pick.
  // The step's first request goes out at once. A wait that ends after the step was left sends
  // nothing, and the request is queued again when the step is drawn again.
  function queue(req, key) {
    const first = s.reqKey == null;
    Object.assign(s, { reqKey: key, lid: null, jobId: null, record: null, loadErr: null });
    resetCounts(s);
    clearTimeout(s.wait);
    s.wait = setTimeout(() => {
      s.wait = 0;
      if (s.reqKey !== key) return;
      if (s.view) post(req, key); else s.reqKey = null;
    }, first ? 0 : PICK_QUIET_MS);
  }
  // The job of an earlier, different request is cancelled first while still queued or running,
  // so it does not hold one of the address's pending jobs (trial mode allows 2). One that ended
  // before the cancel arrived comes back as it is and is left to the jobs poll, which announces
  // it; only a cancelled or still running job is recorded here, and not over a list that has
  // already seen the job end. A failed cancel (the network, say) does not stop the new request.
  function post(req, key) {
    s.busy = true;
    const old = s.posted && s.posted.key !== key && active(jobById(s.posted.job)) ? s.posted.job : null;
    const ended = j => { const mine = jobById(j.id); return !!mine && !active(mine); };
    const record = j => { if ((j.status === 'cancelled' || active(j)) && !ended(j)) upsert('jobs', j); };
    const freed = old ? api.cancelJob(old).then(record, () => {}) : Promise.resolve();
    freed.then(() => api.startLivecells(ctx.gid, req)).then(res => {
      s.posted = { key, job: res.job.id };
      emit(EV.jobStarted, { res, what: `live cells for gate ${ctx.gid}`, open: false });
      if (s.reqKey !== key) return;
      s.lid = res.livecells_id; s.jobId = res.job.id;
    }, e => { if (s.reqKey === key) s.loadErr = errText(e); }).finally(() => { s.busy = false; again(); });
  }
  function fetchRecord(key) {
    s.busy = true;
    api.livecellsRecord(ctx.gid, s.lid).then(r => {
      if (s.reqKey !== key) return;
      if (r.status === 'done' && r.histograms) { s.record = r; dropLinesOutside(s); }
      else if (r.status === 'failed' || r.status === 'cancelled') {
        const j = jobById(r.job);
        s.loadErr = `The live-cells job ${r.job} ${r.status}${j && j.error ? `: ${j.error.message}` : '.'}`;
      } else s.retry = setTimeout(() => { s.retry = 0; if (s.view) s.view.advance(); }, POLL_MS);
    }, e => { if (s.reqKey === key) s.loadErr = errText(e); }).finally(() => { s.busy = false; again(); });
  }

  function problemBox(text, retry) {
    return el('div', { class: 'callout lc-problem' }, el('span', { text }),
      el('button', { type: 'button', class: 'btn sm', text: 'Try again', onclick: retry }));
  }

  // Row i's dropdown: None and the marker channels, a channel another row holds shown but not
  // offered. A role row notes a missing suggestion; an added row can be removed.
  function picker(row, i, markers) {
    const info = s.info, sug = info.suggested || {}, role = ROLES.find(r => r.role === row.role);
    const name = rowName(row, i, s.rows), id = rowId(i), others = taken(s.rows, i);
    const nameOf = pnn => { const c = info.channels.find(x => x.pnn === pnn); return c ? label(c) : pnn; };
    const sel = el('select', { id, onchange: e => { row.channel = e.target.value || null; live.all(); } },
      el('option', { value: '', text: 'None' }),
      ...markers.map(c => el('option', { value: c.pnn, disabled: others.has(c.pnn), text: others.has(c.pnn) ? `${label(c)}, in another row` : label(c) })));
    sel.value = row.channel || '';
    let note = null;
    if (role && !sug[role.role]) {
      const cands = ((sug.candidates && sug.candidates[role.role]) || []).filter(isMarker);
      note = cands.length ? `Several channels look like ${role.what}: ${cands.map(nameOf).join(', ')}. Choose one.`
        : `No channel's name looks like ${role.what}. Choose one, or leave it on None.`;
    }
    const remove = role ? null : el('button', { type: 'button', class: 'linkbtn', text: 'Remove', 'aria-label': `Remove ${name}`,
      onclick: () => { s.rows = removeRow(s.rows, i); s.focus = rowId(i - 1); live.all(); } });
    return el('div', { class: 'field lc-row' }, el('span', { class: 'lc-row-head' }, el('label', { for: id, text: name }), remove),
      sel, note ? el('small', { text: note }) : null);
  }

  // "Add a channel": a row per marker channel at most, fewer under the trial cap.
  function adder(markers) {
    const max = maxRows(markers.length, channelCap()), full = s.rows.length >= max;
    const why = !full ? null : max < markers.length ? `This server filters on at most ${max} channels.` : 'Every marker channel has a row.';
    return el('div', { class: 'lc-add' },
      el('button', { type: 'button', class: 'btn sm', html: svg('plus') + '<span>Add a channel</span>', disabled: full,
        onclick: () => { s.focus = rowId(s.rows.length); s.rows = addRow(s.rows); live.all(); } }),
      why ? el('span', { class: 'note', text: why }) : null);
  }

  function panel(row, i, h) {
    const { cof, from, toRaw } = channelScale(s.record.histograms, h);
    const rawLo = toRaw(h.lo), rawHi = toRaw(h.hi), pnn = h.channel;
    const names = Object.fromEntries(s.record.histograms.files.map(f => [f.number, `F${f.number} ${f.name}`]));
    const input = el('input', { type: 'number', step: 'any', placeholder: 'No line yet', 'aria-label': `Line on ${h.label}, raw value` });
    const remove = el('button', { type: 'button', class: 'linkbtn', text: 'Remove line' });
    const tip = el('span', { class: 'note lc-tip' });
    const keep = seg(`Side of the line to keep for ${h.label}`, KEEP, row.keep, v => { row.keep = v; redraw(); recount(); });
    const chartHost = el('div');
    const chart = histogram(chartHost, t => setLine(toRaw(t)));
    charts.push(chart);

    function setLine(raw) {
      if (raw == null) delete s.lines[pnn]; else s.lines[pnn] = roundIn(raw, rawLo, rawHi);
      redraw(); recount();
    }
    function redraw() {
      const line = s.lines[pnn] ?? null, side = row.keep;
      chart.draw(plotTheme(), h, { cof, from, line, keep: side, perFile: s.perFile, names });
      keep.querySelectorAll('button').forEach((b, k) => b.setAttribute('aria-pressed', String(KEEP[k][0] === side)));
      input.value = line == null ? '' : String(line);
      remove.hidden = line == null;
      tip.textContent = line == null ? 'Click the histogram to place a line.'
        : `Keeping the cells ${side === '<' ? 'below' : 'above'} ${fmtNum(line)}. Drag the line or type a value to move it.`;
    }
    input.addEventListener('change', () => {
      if (input.validity.badInput) { redraw(); return; }
      const v = input.value.trim();
      setLine(v === '' ? null : Number(v));
    });
    remove.addEventListener('click', () => setLine(null));

    const node = el('div', { class: 'card lc-chan' },
      el('div', { class: 'lc-head' }, el('div', { class: 'lc-name' }, el('span', { class: 'lc-role', text: rowName(row, i, s.rows) }), h.label), keep),
      el('div', { class: 'lc-chart' }, chartHost),
      el('div', { class: 'lc-ends' },
        el('span', { text: `${plural(h.below, 'cell')} below the range` }),
        h.nan ? el('span', { text: `${plural(h.nan, 'cell')} without a value` }) : null,
        el('span', { text: `${plural(h.above, 'cell')} above the range` })),
      el('div', { class: 'lc-line' }, el('label', { class: 'field' }, el('span', { text: 'Line at (raw value)' }), input), remove, tip));
    return { node, redraw };
  }

  // A row whose channel the loaded set holds no histogram for (fixture mode answers every
  // request with its one set).
  function noHistogram(row, i) {
    const node = el('div', { class: 'card lc-chan' },
      el('div', { class: 'lc-name' }, el('span', { class: 'lc-role', text: rowName(row, i, s.rows) }), short(row.channel)),
      el('div', { class: 'note', text: 'The loaded set has no histogram for this channel.' }));
    return { node, redraw() {} };
  }

  function stepBar() {
    const sum = el('span', { class: 'sum' }), hint = el('span', { class: 'hint' });
    const go = el('button', { type: 'button', class: 'btn primary', html: '<span>Continue</span>' + svg('chev') });
    const problem = () => (!s.info ? (s.infoErr ? 'The channels did not load. Try again, or Skip.' : 'Reading the channels.')
      : clash(s) ? 'Choose a different channel in each row, or None.'
        : picked(s).length && !s.record ? (s.loadErr ? 'The histograms did not load. Try again, or Skip.' : 'Waiting for the histograms.')
          : null);
    function update() {
      const parts = filtersOf(s).map(f => `${short(f.column)} ${f.op} ${fmtNum(f.value)}`);
      if (leaveOut(s)) parts.push(`${short(dye(s))} left out of the clustering`);
      sum.textContent = !s.info ? '–' : !picked(s).length ? 'No live-cell filters' : parts.length ? parts.join(' · ') : 'No lines placed yet';
      const pr = problem();
      if (pr) go.setAttribute('aria-disabled', 'true'); else go.removeAttribute('aria-disabled');
      hint.textContent = pr || '';
      hint.className = 'hint';
    }
    go.addEventListener('click', () => {
      const pr = problem();
      if (pr) { hint.textContent = pr; hint.className = 'hint note err'; return; }
      if (!picked(s).length) { ctx.skip(); return; }
      ctx.done({ row_filters: filtersOf(s), exclude: leaveOut(s) ? dye(s) : null });
    });
    const node = el('div', { class: 'step-bar' },
      el('div', { class: 'step-bar-text' }, el('span', { class: 'lbl', text: 'Your choice' }), sum, hint),
      el('button', { type: 'button', class: 'btn', html: svg('back') + '<span>Back to populations</span>', onclick: () => ctx.back() }),
      el('button', { type: 'button', class: 'btn', text: 'Skip', onclick: () => ctx.skip() }), go);
    return { node, update };
  }

  function draw() {
    charts.forEach(c => c.destroy());
    charts = []; counts = null;
    const bar = stepBar();
    barUpdate = bar.update;
    const head = docHead('Live cells', SUB);
    if (!s.info) {
      fill(host, ctx.steps, head, s.infoErr ? problemBox(s.infoErr, () => { s.infoErr = null; live.all(); })
        : el('div', { class: 'note', text: 'Reading the channels…' }), bar.node);
      bar.update();
      return;
    }
    const markers = markerChannels(s.info.channels);
    const pick = el('div', { class: 'form-grid lc-pick' }, ...s.rows.map((r, i) => picker(r, i, markers)));
    const leave = dye(s) ? el('label', { class: 'check lc-leave' },
      el('input', { type: 'checkbox', checked: leaveOut(s), onchange: e => { s.leaveOut = e.target.checked; barUpdate(); } }),
      'Leave the viability dye out of the clustering') : null;
    let main = [], panels = [];
    if (clash(s)) main = [el('div', { class: 'callout', text: `More than one row names ${clashes(s.rows).map(short).join(', ')}. Choose another channel in one of them, or None.` })];
    else if (!picked(s).length) main = [el('div', { class: 'callout info', text: 'No channels chosen, so there is nothing to filter: Continue goes on to the cluster settings without live-cell filters, as Skip does.' })];
    else if (s.loadErr) main = [problemBox(s.loadErr, () => { s.loadErr = null; s.reqKey = null; live.all(); })];
    else if (!s.record) {
      main = [el('div', { class: 'callout info lc-wait' }, `Sorting the cells your populations keep into histograms${s.jobId ? ` (job ${s.jobId})` : ''}… `,
        s.jobId ? el('button', { type: 'button', class: 'linkbtn', text: 'Open the job', onclick: () => emit(EV.openTab, { key: `job:${s.jobId}` }) }) : null)];
    } else {
      const T = plotTheme(), files = s.record.histograms.files;
      panels = s.rows.map((r, i) => {
        if (!r.channel) return null;
        const h = histOf(s, r.channel);
        return h ? panel(r, i, h) : noHistogram(r, i);
      }).filter(Boolean);
      counts = countsView(s);
      main = [el('div', { class: 'lc-tools' },
        el('label', { class: 'check' }, el('input', { type: 'checkbox', id: `lc-${ctx.gid}-per-file`, checked: s.perFile, onchange: e => { s.perFile = e.target.checked; draw(); } }), 'Split the bars by file'),
        s.perFile ? el('div', { class: 'lc-legend' }, ...files.map(f => el('span', {}, el('i', { style: `background:${fileColor(T, f.number)}` }), `F${f.number} ${f.name}`))) : null),
      el('div', { class: 'lc-grid' }, ...panels.map(p => p.node)), counts.node];
    }
    // fill() rebuilds the step, so the focus goes back to the control that had it (found by its
    // id), or to the one an action named in s.focus: the new row after Add, the row above after
    // Remove.
    const act = document.activeElement;
    const focusId = s.focus || (act && host.contains(act) && act.id) || null;
    s.focus = null;
    fill(host, ctx.steps, head, pick, adder(markers), leave, ...main, bar.node);
    panels.forEach(p => p.redraw());
    bar.update();
    const back = focusId && document.getElementById(focusId);
    if (back) back.focus();
  }

  const offJobs = subscribe(EV.jobsChange, () => live.advance());
  const offTheme = subscribe(EV.themeChange, () => { if (!dead) draw(); });
  live.all();
  return () => {
    dead = true;
    if (s.view === live) s.view = null;
    offJobs(); offTheme();
    charts.forEach(c => c.destroy());
  };
}
