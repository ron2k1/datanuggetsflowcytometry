// The workbench frame: crumbs, the editor (which draws the active tab's registered view), the
// status bar, the titlebar menus, the narrow-screen drawer and the keyboard.
import { DRAWER_MAX_PX, PLOTLY_VERSION } from '../../shared/config.js';
import { $, el, toast, confirmDanger } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtBytes, fmtDate } from '../../shared/format.js';
import { openMenu, closeMenus, mi } from '../../shared/menu.js';
import { api, FIXTURES } from '../../shared/api/index.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, tabsNow, kindOf, activity, fcsUploads, flowRuns, loadWorkspace } from '../../shared/store.js';
import { themeNow, setTheme } from '../../shared/theme.js';
import { viewFor } from '../../shared/views.js';

const openTab = key => emit(EV.openTab, { key });

/* crumbs */
function renderCrumbs() {
  const c = $('#crumbs'), key = tabsNow().active;
  c.replaceChildren();
  if (!key) return;
  const v = viewFor(kindOf(key));
  const parts = v && v.crumbs ? v.crumbs(key) : [v ? v.title(key).name : key];
  parts.forEach((p, i) => { if (i) c.append(el('span', { html: svg('chev') })); c.append(el('span', { text: p })); });
}

/* editor: the open view's keys (Backspace, Esc) and status text live here while it is shown */
let cleanup = null, keys = null, statusText = null, shown = null;
const host = {
  setKeys: k => { keys = k; },
  setStatus: f => { statusText = f; renderStatus(); },
  refreshStatus: () => renderStatus(),
  refreshPanel: () => emit(EV.panelRender),
};
function renderEditor() {
  if (cleanup) { try { cleanup(); } catch (e) { /* a view's teardown must not stop the next one */ } cleanup = null; }
  keys = null; statusText = null;
  const body = $('#editor');
  const key = tabsNow().active;
  // Redrawing the tab on screen keeps its scroll; another tab starts at the top.
  const same = key !== null && shown === key, top = same ? body.scrollTop : 0;
  shown = key;
  body.replaceChildren(); body.scrollTop = 0;
  if (!key) {
    body.append(el('div', { class: 'empty' }, el('div', {}, el('div', { text: 'No open tabs' }),
      el('button', { class: 'btn', onclick: () => openTab('start'), html: svg('start') + '<span>Open Start</span>' }))));
    return;
  }
  const v = viewFor(kindOf(key));
  if (!v) { body.append(el('div', { class: 'empty', text: 'Unknown tab.' })); return; }
  cleanup = v.render(body, key, host) || null;
  if (top) body.scrollTop = top;
}
function bootFailed({ error }) {
  $('#editor').replaceChildren(el('div', { class: 'empty' }, el('div', {},
    el('div', { text: `The server did not answer: ${error.message}` }),
    el('button', { type: 'button', class: 'btn', html: svg('rotate') + '<span>Try again</span>', onclick: () => location.reload() }))));
}

/* status */
function renderStatus() {
  const cfg = S.config || {}, right = $('#status-right');
  $('#status-mode').textContent = (cfg.mode === 'local' ? 'LOCAL' : 'TRIAL') + (FIXTURES ? ' · FIXTURES' : '');
  $('#status-note').textContent = cfg.storage_note || '';
  $('#status-note').title = cfg.storage_note || '';
  right.replaceChildren();
  if (statusText) right.append(el('span', { class: 'wide', text: statusText() }));
  right.append(el('span', { class: 'wide', text: `Plotly ${PLOTLY_VERSION}` }),
    el('button', { class: 'sb-btn', type: 'button', html: svg('local') + '<span>Run it locally</span>', onclick: () => openTab('local') }));
}

/* titlebar menus */
function buildMainMenu(m) {
  m.append(el('h5', { text: 'Add' }),
    mi('upload', 'Upload files…', { hint: 'FCS', run: () => emit(EV.filesPick) }),
    mi('start', 'Start and demo data', { run: () => openTab('start') }),
    el('hr'), el('h5', { text: 'View' }),
    mi('terminal', S.panelOpen ? 'Hide terminal' : 'Show terminal', { hint: 'Ctrl+J', run: () => emit(EV.panelToggle, {}) }),
    ...[['light', 'Light theme'], ['dark', 'Dark theme']].map(([t, text]) => mi('theme', text, { radio: true, checked: themeNow() === t, run: () => setTheme(t) })),
    el('hr'),
    mi('local', 'Run it locally', { run: () => openTab('local') }));
}
function buildWorkspaceMenu(m) {
  const cfg = S.config || {}, ws = S.ws || {}, trial = cfg.mode !== 'local';
  // What the explorer lists, so an older workspace's CSV uploads and general runs are left out.
  const used = fcsUploads().reduce((s, u) => s + (u.bytes || 0), 0), runs = flowRuns().length;
  const cap = cfg.caps && cfg.caps.workspace_bytes;
  m.append(el('div', { class: 'ws-card' },
    el('div', { class: 'who', text: trial ? 'Temporary workspace' : 'Workspace on this computer' }),
    el('div', { class: 'sub', text: cfg.storage_note || '' }),
    trial && ws.expires_at ? el('div', { class: 'sub', text: `Deleted by ${fmtDate(ws.expires_at)} at the latest${ws.idle_expires_at ? `, or ${fmtDate(ws.idle_expires_at)} if left idle` : ''}.` }) : null),
  el('div', { class: 'meter-row' }, `${fmtBytes(used)} of uploads${cap ? ` · limit ${fmtBytes(cap)}` : ''} · ${runs} run${runs === 1 ? '' : 's'}`,
    cap ? el('div', { class: 'bar' }, el('i', { style: `width:${Math.min(100, (100 * used) / cap).toFixed(1)}%` })) : null),
  el('hr'),
  mi('local', 'Run it locally', { run: () => openTab('local') }),
  mi('trash', 'Delete this workspace', { danger: true, run: deleteWorkspace }));
}
async function deleteWorkspace() {
  // the menu item that asked has gone with its menu, so the focus goes back to the menu's button
  if (!(await confirmDanger('Delete this workspace?', 'Every upload, gate, run and job in it is removed and cannot be restored.', 'Delete workspace', () => $('#btn-ws')))) return;
  try {
    await api.deleteWorkspace();
    S.localUploads = [];
    await loadWorkspace();
    S.tabs = { open: ['start'], active: 'start' };
    activity('Workspace deleted');
    toast('Workspace deleted.');
    emit(EV.render);
  } catch (e) { toast(e.message, true); activity(`Delete workspace: ${e.message}`); }
}

/* drawer: the explorer slides in over the editor on narrow screens */
function openDrawer() { if (window.innerWidth > DRAWER_MAX_PX) return; $('#explorer').classList.add('open'); $('#backdrop').classList.add('show'); $('#btn-files').setAttribute('aria-expanded', 'true'); }
function closeDrawer() { $('#explorer').classList.remove('open'); $('#backdrop').classList.remove('show'); $('#btn-files').setAttribute('aria-expanded', 'false'); }

export function mount() {
  $('#btn-files').innerHTML = svg('panel');
  $('#btn-files').addEventListener('click', () => ($('#explorer').classList.contains('open') ? closeDrawer() : openDrawer()));
  $('#backdrop').addEventListener('click', closeDrawer);
  $('#btn-menu').innerHTML = svg('menu') + '<span class="tb-menu-label">Menu</span>';
  $('#btn-menu').addEventListener('click', e => openMenu(e.currentTarget, buildMainMenu));
  $('#btn-ws').innerHTML = svg('workspace');
  $('#btn-ws').addEventListener('click', e => openMenu(e.currentTarget, buildWorkspaceMenu));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { if (keys) keys.cancelBox(); closeMenus(); closeDrawer(); }
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.code === 'Backquote' || (e.key || '').toLowerCase() === 'j')) { e.preventDefault(); emit(EV.panelToggle, {}); }
    const typing = e.target instanceof Element && e.target.closest('input, select, textarea, [contenteditable="true"]');
    const backKey = (e.key === 'Backspace' && !e.altKey && !e.ctrlKey && !e.metaKey) || (e.altKey && e.key === 'ArrowLeft');
    if (keys && backKey && !typing) { e.preventDefault(); keys.back(); }
  });
  window.addEventListener('resize', () => { if (window.innerWidth > DRAWER_MAX_PX) closeDrawer(); closeMenus(); });
  subscribe(EV.openTab, closeDrawer);
  subscribe(EV.render, () => { renderCrumbs(); renderEditor(); renderStatus(); });
  subscribe(EV.bootFailed, bootFailed);
}
