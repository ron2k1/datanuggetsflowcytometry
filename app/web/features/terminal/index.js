// The terminal panel: Output (the open tab's log, from its view's output()) and Activity (this
// session's log). Shown or hidden by EV.panelToggle; the choice persists.
import { STORAGE } from '../../shared/config.js';
import { $, el, logLines } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { EV } from '../../shared/events.js';
import { S, subscribe, tabsNow, kindOf } from '../../shared/store.js';
import { viewFor } from '../../shared/views.js';

function renderPanel() {
  const panel = $('#panel'), bodyEl = $('#panel-body'), btn = $('#btn-term');
  panel.hidden = !S.panelOpen;
  btn.setAttribute('aria-pressed', String(S.panelOpen));
  btn.title = `${S.panelOpen ? 'Hide' : 'Show'} terminal (Ctrl+J)`;
  if (!S.panelOpen) return;
  document.querySelectorAll('.panel-tab').forEach(b => b.setAttribute('aria-selected', String(b.dataset.ptab === S.panelTab)));
  if (S.panelTab === 'output') {
    const key = tabsNow().active, v = key && viewFor(kindOf(key));
    const out = v && v.output ? v.output(key) : null;
    $('#panel-path').textContent = out ? out.path : '';
    bodyEl.replaceChildren(...(out && out.lines.length ? logLines(out.lines) : [el('div', { class: 'ln' }, el('span', { class: 't', text: 'No output for this tab.' }))]));
    bodyEl.scrollTop = bodyEl.scrollHeight;
  } else {
    $('#panel-path').textContent = 'this session';
    bodyEl.replaceChildren(...S.activity.map(a => el('div', { class: 'ln act' }, el('span', { class: 'ts', text: a.t }), el('span', { class: 't', text: a.msg }))));
    bodyEl.scrollTop = bodyEl.scrollHeight;
  }
}
function setPanel(open) {
  const refocus = !open && $('#panel').contains(document.activeElement);
  S.panelOpen = open;
  try { localStorage.setItem(STORAGE.terminal, open ? '1' : '0'); } catch (e) { /* storage unavailable */ }
  renderPanel();
  if (refocus) $('#btn-term').focus({ preventScroll: true });
}

export function mount() {
  $('#panel-close').innerHTML = svg('close');
  $('#panel-close').addEventListener('click', () => setPanel(false));
  $('#btn-term').innerHTML = svg('terminal') + '<span>Terminal</span>';
  $('#btn-term').addEventListener('click', () => setPanel(!S.panelOpen));
  document.querySelectorAll('.panel-tab').forEach(b => b.addEventListener('click', () => { S.panelTab = b.dataset.ptab; renderPanel(); }));
  subscribe(EV.panelToggle, (p = {}) => setPanel(typeof p.open === 'boolean' ? p.open : !S.panelOpen));
  subscribe(EV.activity, () => { if (S.panelOpen && S.panelTab === 'activity') renderPanel(); });
  subscribe(EV.panelRender, renderPanel);
  subscribe(EV.render, renderPanel);
}
