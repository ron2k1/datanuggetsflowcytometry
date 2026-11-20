// The point card (docs/app/cluster-panel.md "A point's numbers"): the nugget or sampled cell
// clicked last, beside the plot, with each marker's value as plotted and in the file's units.
// point.js works the numbers out; this draws them.
import { el, iconBtn, copyText } from '../../shared/dom.js';
import { fmtInt, fmtNum } from '../../shared/format.js';
import { plotTransform, fmtCofactor } from '../../shared/cofactor.js';
import { pointNumbers, fmtFile } from './point.js';

const fileText = f => (f ? `F${f.number} ${f.name}${f.group ? ` · ${f.group}` : ''}` : '');

// What the In the file column means, for this point and this run's Transform stage.
function note(o, t) {
  if (o.transform === 'none') return 'This run clustered the values as stored, so the plot shows the file’s own values.';
  const c = o.perChannel ? 'c is each channel’s cofactor' : `c is ${fmtCofactor(t.cofactor, t.cofactor_from)} for every channel`;
  const what = o.src === 'cells'
    ? 'the value the run read for this event from the .fcs file, as stored (uncompensated)'
    : 'the nugget’s center on the scale of the .fcs file’s values, as stored (uncompensated); its cells spread around it';
  return `Plotted: arcsinh(x / c), the plot’s units, to four significant digits. In the file: c × sinh(plotted), ${what}; ${c}. In the file is rounded to the place those four digits fix.`;
}

// The card's numbers as tab-separated text, a header line first, for a spreadsheet: In the file
// to the card's place, the cofactor exact (it is the run's own parameter, not a measurement).
function tsv(o) {
  const head = ['Marker', 'Channel', 'Plotted', ...(o.transform === 'none' ? [] : ['In the file', 'Cofactor'])];
  const lines = o.rows.map(r => [r.short, r.name, r.plotted, ...(o.transform === 'none' ? [] : [fmtFile(r.file, r.step, true), r.cofactor])].join('\t'));
  return [head.join('\t'), ...lines].join('\n');
}

/**
 * The card for row i of model M.
 * @param {object} P  the plot payload
 * @param {object} M  the plot model
 * @param {number} i  the model's row
 * @param {{drawn: string[], color: string, onClose: () => void, onBoxPlots: (c: number) => void}} opt
 *   drawn: the 2D or 3D view's axes, whose markers the table tags x, y and z
 */
export function pointCard(P, M, i, opt) {
  const o = pointNumbers(P, M, i, opt.drawn), t = plotTransform(P), raw = o.transform === 'none';
  const name = o.src === 'cells' ? `Event ${fmtInt(o.event)}` : `Nugget ${fmtInt(o.nugget)}`;
  const facts = [
    ['File', fileText(o.file)],
    o.src === 'cells' ? ['Nugget', `${fmtInt(o.nugget)} of its file`] : ['Cells', fmtInt(o.weight)],
  ];
  // [text, class]: the table lays out fixed, so the number columns keep their widths and the
  // marker's name takes the rest (pc-v, pc-x and pc-c in plot.css).
  const head = [['Marker', ''], [raw ? 'Value' : 'Plotted', 'num pc-v'], ...(raw ? [] : [['In the file', 'num pc-x']]), ...(o.perChannel ? [['c', 'num pc-c']] : [])];
  const table = el('table', { class: 'pc-table' },
    el('thead', null, el('tr', null, ...head.map(([h, cls]) => el('th', { scope: 'col', class: cls, text: h })))),
    el('tbody', null, ...o.rows.map(r => el('tr', { class: r.axis ? 'on-axis' : '' },
      // The axis tag leads, so a long name's ellipsis never hides it.
      el('th', { scope: 'row', title: r.name }, r.axis ? el('span', { class: 'pc-axis', title: `On the ${r.axis} axis`, text: r.axis }) : null, r.short),
      el('td', { class: 'num', text: fmtNum(r.plotted) }),
      ...(raw ? [] : [el('td', { class: 'num strong', text: fmtFile(r.file, r.step) })]),
      ...(o.perChannel ? [el('td', { class: 'num muted', text: fmtCofactor(r.cofactor, t.cofactor_from) })] : [])))));
  const copy = el('button', { type: 'button', class: 'btn sm', text: 'Copy', title: 'Copy the numbers as tab-separated text',
    onclick: () => copyText(tsv(o)) });
  const box = el('button', { type: 'button', class: 'btn sm primary', text: `Box plots of cluster ${o.cluster}`, onclick: () => opt.onBoxPlots(o.cluster) });
  return el('div', { class: 'pc' },
    el('div', { class: 'pc-head' },
      el('span', { class: 'sw', style: `background:${opt.color}`, 'aria-hidden': 'true' }),
      el('div', { class: 'pc-title' }, el('h3', { text: name }), el('div', { class: 'muted', text: `Cluster ${o.cluster}` })),
      iconBtn('close', 'Close the point card (Esc)', opt.onClose)),
    el('dl', { class: 'pc-facts' }, ...facts.flatMap(([k, v]) => [el('dt', { text: k }), el('dd', { text: v, title: v })])),
    table,
    el('p', { class: 'pc-note muted', text: note(o, t) }),
    el('div', { class: 'pc-actions' }, copy, box));
}
