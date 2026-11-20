// A dropdown menu under a button: arrow keys, Home/End, Esc and Tab, one menu open at a time.
// A click outside closes it (installed once by the first menu).
import { el, toast } from './dom.js';
import { svg } from './icons.js';

let menu = null, menuBtn = null, outsideWired = false;

export function closeMenus(refocus) {
  const btn = menuBtn;
  if (menu) { menu.remove(); menu = null; }
  if (btn) { btn.setAttribute('aria-expanded', 'false'); menuBtn = null; if (refocus && btn.isConnected) btn.focus({ preventScroll: true }); }
}

function wireOutside() {
  if (outsideWired) return;
  outsideWired = true;
  document.addEventListener('pointerdown', e => {
    if (!menu || menu.contains(e.target) || e.target.closest('[data-menu-btn]')) return;
    const btn = menuBtn;
    closeMenus();
    setTimeout(() => { if (document.activeElement === document.body && btn.isConnected) btn.focus({ preventScroll: true }); });
  });
}

// Opens build(menuElement)'s items under btn; a second click on the same button closes it.
export function openMenu(btn, build) {
  wireOutside();
  const was = menuBtn === btn;
  closeMenus();
  if (was) return;
  const m = el('div', { class: 'menu', role: 'menu', 'aria-label': btn.getAttribute('aria-label') || btn.textContent });
  build(m);
  m.addEventListener('keydown', e => {
    const items = [...m.querySelectorAll('[role^="menuitem"]')], n = items.length, i = items.indexOf(document.activeElement);
    const to = { ArrowDown: i < 0 ? 0 : (i + 1) % n, ArrowUp: i <= 0 ? n - 1 : i - 1, Home: 0, End: n - 1 }[e.key];
    if (n && to != null) { e.preventDefault(); items[to].focus(); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenus(true); }
    else if (e.key === 'Tab') closeMenus(true);
  });
  document.body.append(m);
  const r = btn.getBoundingClientRect();
  m.style.top = r.bottom + 6 + 'px';
  m.style.left = Math.max(8, Math.min(r.left, window.innerWidth - m.offsetWidth - 8)) + 'px';
  menu = m; menuBtn = btn; btn.setAttribute('aria-expanded', 'true');
  const first = m.querySelector('[role^="menuitem"]');
  if (first) first.focus({ preventScroll: true });
}

// One menu item. opts: run, hint, danger, disabled (a toast text), radio + checked.
export function mi(icon, text, opts = {}) {
  return el('button', {
    type: 'button', class: 'mi' + (opts.danger ? ' danger' : ''), role: opts.radio ? 'menuitemradio' : 'menuitem',
    'aria-disabled': opts.disabled ? 'true' : null, 'aria-checked': opts.radio ? String(!!opts.checked) : null,
    onclick: () => {
      if (opts.disabled) { toast(opts.disabled); return; }
      const btn = menuBtn;
      closeMenus();
      if (opts.run) opts.run();
      if (btn && btn.isConnected && document.activeElement === document.body) btn.focus({ preventScroll: true });
    },
  }, el('span', { class: opts.radio ? 'chk' : '', html: svg(opts.radio ? 'check' : icon) }), el('span', { text }), opts.hint ? el('span', { class: 'hint', text: opts.hint }) : null);
}
