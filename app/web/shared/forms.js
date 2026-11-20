// Form pieces shared by the gate and cluster forms: number fields, the k slider and the
// row-filter builder. Each writes straight into a plain settings object.
import { el, iconBtn } from './dom.js';
import { svg } from './icons.js';
import { fmtNum } from './format.js';
import { FILTER_OPS, K_MIN } from './config.js';
import { kMax } from './store.js';

export function numField(obj, key, label, opts = {}) {
  const input = el('input', {
    type: 'number', value: obj[key] == null ? '' : String(obj[key]), step: opts.step || 'any',
    min: opts.min == null ? null : String(opts.min), max: opts.max == null ? null : String(opts.max), 'aria-label': label,
    oninput: e => {
      const v = e.target.value === '' ? null : Number(e.target.value);
      const bad = v == null || !Number.isFinite(v) || (opts.int && !Number.isInteger(v)) || (opts.min != null && v < opts.min) || (opts.max != null && v > opts.max);
      e.target.classList.toggle('bad', bad);
      if (!bad) obj[key] = v;
    },
  });
  const hint = opts.max != null && opts.cap ? `up to ${fmtNum(opts.max)} here` : opts.hint;
  return el('label', { class: 'field' }, el('span', { text: label }), input, hint ? el('small', { text: hint }) : null);
}

// A number box that is 'auto' while empty: obj[key] is 'auto' or the last valid number typed.
// Clearing the box or "Use auto" goes back to 'auto'. opts.autoLine() is the line shown under it
// while on auto (what auto picks, and why); opts.hint is shown always; onchange hears each change.
export function autoNumField(obj, key, label, opts = {}, onchange = () => {}) {
  const input = el('input', { type: 'number', step: 'any', min: opts.min == null ? null : String(opts.min), placeholder: 'Auto',
    value: typeof obj[key] === 'number' ? String(obj[key]) : '', 'aria-label': label });
  const back = el('button', { type: 'button', class: 'linkbtn', text: 'Use auto' });
  const line = el('small', { 'aria-live': 'polite' });
  const show = () => {
    const auto = obj[key] === 'auto';
    back.hidden = auto;
    line.textContent = auto && opts.autoLine ? opts.autoLine() : '';
    line.hidden = !line.textContent;
  };
  input.addEventListener('input', () => {
    const raw = input.value.trim(), v = Number(raw);
    const empty = raw === '' && !input.validity.badInput;
    const bad = !empty && (raw === '' || !Number.isFinite(v) || (opts.min != null && v < opts.min));
    input.classList.toggle('bad', bad);
    if (empty) obj[key] = 'auto'; else if (!bad) obj[key] = v;
    show(); onchange();
  });
  back.addEventListener('click', () => {
    obj[key] = 'auto'; input.value = ''; input.classList.remove('bad');
    show(); onchange(); input.focus();
  });
  show();
  return el('div', { class: 'field' }, el('span', { text: label }), el('div', { class: 'auto-row' }, input, back), line,
    opts.hint ? el('small', { text: opts.hint }) : null);
}

export function textField(obj, key, label, opts = {}) {
  return el('label', { class: 'field' }, el('span', { text: label }),
    el('input', { type: 'text', value: obj[key] == null ? '' : String(obj[key]), 'aria-label': label, placeholder: opts.placeholder || null,
      oninput: e => { obj[key] = opts.parse ? opts.parse(e.target.value) : e.target.value; } }),
    opts.hint ? el('small', { text: opts.hint }) : null);
}

export function selectField(obj, key, label, options, opts = {}) {
  return el('label', { class: opts.wide ? 'field wide' : 'field' }, el('span', { text: label }),
    el('select', { 'aria-label': label, onchange: e => { obj[key] = e.target.value; } },
      ...options.map(([v, t]) => el('option', { value: v, selected: obj[key] === v, text: t }))),
    opts.hint ? el('small', { text: opts.hint }) : null);
}

export function checkField(obj, key, label) {
  return el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!obj[key], onchange: e => { obj[key] = e.target.checked; } }), label);
}

// k from 2 to the server's limit (100): a slider and, beside it, a box to type the number in.
// Each follows the other; onchange(k) hears every valid value.
export function kSlider(obj, key, label = 'Clusters (k)', onchange = () => {}) {
  const max = kMax();
  obj[key] = Math.min(max, Math.max(K_MIN, obj[key] || K_MIN));
  const box = el('input', { type: 'number', class: 'k-box', min: String(K_MIN), max: String(max), step: '1', value: String(obj[key]), 'aria-label': `${label}, typed`,
    oninput: e => {
      const v = Number(e.target.value);
      const ok = e.target.value !== '' && Number.isInteger(v) && v >= K_MIN && v <= max;
      e.target.classList.toggle('bad', !ok);
      if (ok) { obj[key] = v; range.value = String(v); onchange(v); }
    } });
  const range = el('input', { type: 'range', min: String(K_MIN), max: String(max), step: '1', value: String(obj[key]), 'aria-label': label,
    oninput: e => { obj[key] = +e.target.value; box.value = e.target.value; box.classList.remove('bad'); onchange(obj[key]); } });
  return el('div', { class: 'field' }, el('span', { text: `${label}, ${K_MIN} to ${max}` }), el('div', { class: 'slider-row' }, range, box));
}

// Filters as the API takes them: {column, op, value}. columns: [{name, label, numeric}].
export function filterBuilder(filters, columns, onchange = () => {}) {
  const box = el('div', { class: 'filters' });
  const toValue = (col, op, a, b) => {
    const num = col && col.numeric;
    const conv = s => (num && s.trim() !== '' && Number.isFinite(Number(s)) ? Number(s) : s.trim());
    if (op === 'between') return [conv(a), conv(b)];
    if (op === 'in') return a.split(',').map(s => conv(s)).filter(s => s !== '');
    return conv(a);
  };
  function draw() {
    box.replaceChildren(...filters.map((f, i) => {
      const col = () => columns.find(c => c.name === f.column);
      const parts = Array.isArray(f.value) ? f.value : [f.value];
      const a = el('input', { type: 'text', class: 'v1', 'aria-label': 'Value', placeholder: f.op === 'in' ? 'a, b, c' : 'value',
        value: f.op === 'in' ? parts.join(', ') : (parts[0] ?? '') === '' ? '' : String(parts[0] ?? '') });
      const b = el('input', { type: 'text', class: 'v2', 'aria-label': 'Upper value', placeholder: 'to', value: f.op === 'between' && parts[1] != null ? String(parts[1]) : '', hidden: f.op !== 'between' });
      const sync = () => { f.value = toValue(col(), f.op, a.value, b.value); onchange(); };
      a.addEventListener('input', sync); b.addEventListener('input', sync);
      return el('div', { class: 'filter-row' },
        el('select', { 'aria-label': 'Column', onchange: e => { f.column = e.target.value; sync(); } },
          ...columns.map(c => el('option', { value: c.name, selected: c.name === f.column, text: c.label ? `${c.label} (${c.name})` : c.name }))),
        el('select', { 'aria-label': 'Comparison', onchange: e => { f.op = e.target.value; b.hidden = f.op !== 'between'; sync(); } },
          ...FILTER_OPS.map(op => el('option', { value: op, selected: op === f.op, text: op }))),
        a, f.op === 'between' ? b : el('span', { class: 'v2' }),
        iconBtn('close', 'Remove this filter', () => { filters.splice(i, 1); draw(); onchange(); }));
    }));
    box.append(el('div', {}, el('button', { type: 'button', class: 'btn sm', html: svg('plus') + '<span>Add a row filter</span>',
      onclick: () => { const c = columns.find(x => x.numeric) || columns[0]; filters.push({ column: c ? c.name : '', op: '>', value: '' }); draw(); onchange(); } })));
  }
  draw();
  return box;
}

// Every filter has a column and a value of the right shape; returns a message or null.
export function filterProblem(filters) {
  for (const f of filters) {
    const v = f.value;
    if (!f.column) return 'A row filter has no column.';
    if (f.op === 'between' && (!Array.isArray(v) || v.length !== 2 || v.some(x => x === ''))) return `The filter on ${f.column} needs two values.`;
    if (f.op === 'in' && (!Array.isArray(v) || !v.length)) return `The filter on ${f.column} needs at least one value.`;
    if (f.op !== 'between' && f.op !== 'in' && (v === '' || v == null)) return `The filter on ${f.column} needs a value.`;
    const strs = (Array.isArray(v) ? v : [v]).filter(x => typeof x === 'string');
    if (strs.some(s => /[,[\]]/.test(s))) return `Filter values cannot contain commas or brackets (${f.column}).`;
  }
  return null;
}
