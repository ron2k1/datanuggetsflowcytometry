// DOM helpers shared by every feature: element builder, toast, copy, the confirm for what cannot
// be undone, doc header, segmented buttons and log lines.
import { TOAST_MS } from './config.js';
import { svg } from './icons.js';

export const $ = (s, r = document) => r.querySelector(s);
export function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k === 'value') n.value = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c)));
  return n;
}
// replaceChildren with el()'s child rules: null/false are skipped (the native call writes "null").
export function fill(n, ...kids) {
  n.replaceChildren(...kids.flat().filter(c => c != null && c !== false));
  return n;
}
export const iconBtn =(icon, label, onclick, cls = 'icon-btn') => el('button', { type: 'button', class: cls, 'aria-label': label, title: label, html: svg(icon), onclick });

let toastTimer = 0;
export function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.toggle('err', !!isErr);
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), TOAST_MS);
}

export function copyText(text, onDone) {
  const done = () => { toast('Copied to the clipboard.'); if (onDone) onDone(); };
  const fallback = () => {
    const ta = el('textarea', { style: 'position:fixed;left:-9999px;top:0' });
    ta.value = text; document.body.append(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove();
    if (ok) done(); else toast('Copy is blocked here; select the text and copy it by hand.');
  };
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
  } catch (e) { fallback(); }
}

// A confirm for what cannot be undone: a modal dialog with the title, the text, Cancel and the
// action, with the focus on Cancel, so the Enter that opened it cannot confirm it too. Escape
// shuts it as Cancel does. No key goes further than the dialog, so Escape closes no drawer or
// menu behind it and no shortcut acts on the page under it. Resolves true for the action and
// false otherwise. The focus goes back where it was while that is still on the page, or else to
// back(), when given: the element now standing for it (a button drawn anew, a menu's button).
let dialogs = 0;
export function confirmDanger(title, text, action, back) {
  const was = document.activeElement, id = `confirm-${++dialogs}`;
  return new Promise(resolve => {
    const cancel = el('button', { type: 'button', class: 'btn', text: 'Cancel', onclick: () => dlg.close('') });
    const go = el('button', { type: 'button', class: 'btn danger', text: action, onclick: () => dlg.close('go') });
    const dlg = el('dialog', { class: 'confirm', 'aria-labelledby': `${id}-t`, 'aria-describedby': `${id}-d` },
      el('h3', { class: 'confirm-title', id: `${id}-t`, text: title }),
      el('p', { class: 'confirm-text', id: `${id}-d`, text }),
      el('div', { class: 'confirm-actions' }, cancel, go));
    // Tab, Enter and Escape are the browser's own doing, so they still work.
    dlg.addEventListener('keydown', e => e.stopPropagation());
    dlg.addEventListener('close', () => {
      dlg.remove();
      const to = was && was !== document.body && was.isConnected ? was : back && back();
      if (to && to.isConnected && to.focus) to.focus();
      resolve(dlg.returnValue === 'go');
    });
    document.body.append(dlg);
    dlg.showModal();
    cancel.focus();
  });
}

// The doc header used by every document view.
export function docHead(title, sub, ...right) {
  return el('div', { class: 'doc-head' },
    el('div', {}, el('div', { class: 'doc-title', text: title }), sub ? el('div', { class: 'doc-sub', text: sub }) : null),
    ...right);
}

export function seg(label, options, current, onpick, cls = 'seg') {
  const box = el('div', { class: cls, role: 'group', 'aria-label': label });
  for (const [value, text, disabled, title] of options) {
    box.append(el('button', {
      type: 'button', 'aria-pressed': String(value === current), text, disabled: !!disabled, title: title || null,
      onclick: () => onpick(value),
    }));
  }
  return box;
}

// File names, percentages and numbers in a log line, each drawn in its own colour. A number must
// stand alone: the 5s in "PerCP-Cy5-5-A" and the 1 in "g1" are part of a name.
const LOG_TOKENS = /(\b[\w.-]+\.(?:fcs|csv|png|json|zip)\b)|((?<![\w.-])-?\d+(?:,\d{3})*(?:\.\d+)?%)|((?<![\w.-])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\w%-]))/gi;
const LOG_CLASS = ['hl-f', 'hl-p', 'hl-n'];
function logText(t) {
  const out = [];
  let at = 0;
  for (const m of t.matchAll(LOG_TOKENS)) {
    if (m.index > at) out.push(t.slice(at, m.index));
    out.push(el('span', { class: LOG_CLASS[m[1] ? 0 : m[2] ? 1 : 2], text: m[0] }));
    at = m.index + m[0].length;
  }
  if (at < t.length) out.push(t.slice(at));
  return out;
}
export function logLines(lines) {
  return (lines || []).map((t, i) => el('div', { class: 'ln' + (/warning/i.test(t) ? ' warn' : /error|failed/i.test(t) ? ' err' : '') },
    el('span', { class: 'n', text: i + 1 }), el('span', { class: 't' }, ...(t ? logText(t) : [' ']))));
}

// Shows "Loading…" in body until promise settles, then draw(value, isDead) or the error.
// Returns the cleanup that stops a late answer from drawing into a closed tab.
export function loadDoc(body, promise, draw) {
  let dead = false;
  body.append(el('div', { class: 'doc muted', text: 'Loading…' }));
  promise.then(v => { if (!dead) { body.replaceChildren(); draw(v, () => dead); } },
    e => { if (!dead) body.replaceChildren(el('div', { class: 'doc' }, el('div', { class: 'callout', text: e.message }))); });
  return () => { dead = true; };
}
