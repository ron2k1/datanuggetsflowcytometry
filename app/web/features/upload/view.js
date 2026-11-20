// An FCS upload: its dataset, its channels' stats, then every part of slot 'upload.fcs':
// render(upload, tabState) -> Node, where tabState is this tab's S.view entry.
import { el, docHead } from '../../shared/dom.js';
import { fmtBytes, fmtInt, fmtNum, plural } from '../../shared/format.js';
import { isMarkerChannel } from '../../shared/cofactor.js';
import { largest, stainText } from '../../shared/datasets.js';
import { api } from '../../shared/api/index.js';
import { S, uploadById, idOf, datasets, datasetOf } from '../../shared/store.js';
import { registerView, slotParts } from '../../shared/views.js';

// The upload's dataset: its name, files and colour channels, what it lacks or adds against the
// dataset with the most files, and a warning when stains differ between its files.
function datasetLines(u) {
  const d = datasetOf(u.id);
  if (!d) return [];
  return [
    el('div', { class: 'ds-line' }, 'Dataset: ', el('b', { text: d.name }), ` · ${plural(d.files.length, 'file')} · ${plural(d.channels.length, 'colour channel')}`),
    d.diff ? el('div', { class: 'note ds-note', text: `Compared with ${largest(datasets()).name}, the dataset with the most files, it ${d.diff}.` }) : null,
    d.stains.length ? el('div', { class: 'note warn ds-note', text: `Stains differ between this dataset's files: ${stainText(d.stains)}. One stain can be spelled two ways; check these name the same markers.` }) : null,
  ];
}

function statsTable(u) {
  // An FCS channel's range from its header ($PnR), shown only for the marker channels: a Time
  // channel's header range need not bound its values (an Aurora file's decodes to 0.0185 against
  // values up to about 181). An upload made before ranges were recorded has none, and shows no
  // Range column.
  const ranged = u.columns.some(c => 'range' in c);
  const body = el('tbody', {}, ...u.columns.map(c => el('tr', {},
    el('td', { text: c.name }), el('td', { text: c.label || '' }),
    el('td', { class: 'num', text: fmtNum(c.min) }), el('td', { class: 'num', text: fmtNum(c.max) }), el('td', { class: 'num', text: fmtNum(c.mean) }),
    ranged ? el('td', { class: 'num', text: isMarkerChannel(c.name) ? fmtNum(c.range) : '' }) : null)));
  return el('div', {},
    el('div', { class: 'tbl-wrap stats-wrap' }, el('table', { class: 'tbl' },
      el('thead', {}, el('tr', {}, el('th', { text: 'Channel' }), el('th', { text: 'Marker' }),
        el('th', { class: 'num', text: 'Min' }), el('th', { class: 'num', text: 'Max' }), el('th', { class: 'num', text: 'Mean' }),
        ranged ? el('th', { class: 'num', text: 'Range', title: 'The channel’s range in the file header ($PnR); blank for scatter and Time' }) : null)),
      body)),
    el('div', { class: 'form-actions', style: 'margin-top:8px' }, el('span', { class: 'muted', text: `${u.columns.length} channels` })));
}

function render(body, key) {
  const id = idOf(key);
  const u = uploadById(id);
  if (!u) {
    body.append(el('div', { class: 'doc' }, el('div', { class: 'muted', text: 'Loading…' })));
    // An upload the page has not listed. One that is not FCS, a CSV upload of a workspace made
    // before the app was flow only, is refused in the words the tabs refuse it in, and not kept.
    api.uploadInfo(id).then(x => {
      if (x.kind !== 'fcs') {
        body.replaceChildren(el('div', { class: 'empty', text: `${id} is from General mode, which this app no longer has.` }));
        return;
      }
      S.ws.uploads.push(x); body.replaceChildren(); render(body, key);
    }, e => body.replaceChildren(el('div', { class: 'empty', text: e.message })));
    return;
  }
  // Starts empty: the gate form (slot 'upload.fcs') keeps its settings in st.form.
  const st = S.view[key] || (S.view[key] = {});
  const sub = `FCS · ${fmtInt(u.rows)} events · ${u.columns.length} channels · ${fmtBytes(u.bytes)}`
    + (u.demo ? ` · demo data (${u.demo})` : '') + (u.local ? ' · read in this tab, not sent' : '');
  body.append(el('div', { class: 'doc' }, docHead(u.name, sub), datasetLines(u),
    el('h3', { text: 'Channels' }), statsTable(u), ...slotParts('upload.fcs').map(p => p.render(u, st))));
}

export function registerUploadView() {
  registerView('upload', {
    title: key => { const u = uploadById(idOf(key)); return { name: u ? u.name : idOf(key), icon: 'fcs' }; },
    crumbs: key => {
      const u = uploadById(idOf(key)), d = u && datasetOf(u.id);
      return d ? ['Datasets', d.name, u.name] : ['Datasets', u ? u.name : idOf(key)];
    },
    render,
  });
}
