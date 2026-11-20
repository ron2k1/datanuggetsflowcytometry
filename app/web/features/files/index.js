// A run's files: download links and the whole run as a zip.
import { el, docHead, loadDoc } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtBytes, fmtDate } from '../../shared/format.js';
import { idOf, getManifest } from '../../shared/store.js';
import { registerView } from '../../shared/views.js';
import { api, FIXTURES } from '../../shared/api/index.js';

const ICONS = { csv: 'csv', png: 'png', json: 'json', txt: 'log', log: 'log' };

function renderFiles(body, key) {
  const rid = idOf(key);
  return loadDoc(body, getManifest(rid), (m, isDead) => {
    const zip = api.zipUrl(rid);
    const rows = el('tbody');
    body.append(el('div', { class: 'doc' },
      docHead(`Files of ${rid}`, `${m.title} · ${m.files.length} files · created ${fmtDate(m.created)}`,
        zip ? el('a', { class: 'btn primary', href: zip, download: `${rid}.zip`, html: svg('download') + '<span>Download all (.zip)</span>' })
          : el('button', { type: 'button', class: 'btn', disabled: true, title: 'The zip comes from the server; fixture mode has none', html: svg('download') + '<span>Download all (.zip)</span>' })),
      FIXTURES ? el('div', { class: 'callout info', style: 'margin-bottom:12px', text: 'Fixture mode keeps copies of the small text files only; the others download from a running server.' }) : null,
      (m.warnings || []).length ? el('div', { class: 'callout', style: 'margin-bottom:12px', text: m.warnings.join(' ') }) : null,
      el('div', { class: 'tbl-wrap' }, el('table', { class: 'tbl' },
        el('thead', {}, el('tr', {}, el('th', { text: 'File' }), el('th', { text: 'Kind' }), el('th', { class: 'num', text: 'Size' }), el('th', { text: '' }))),
        rows))));
    m.files.forEach(f => {
      const cell = el('td');
      rows.append(el('tr', {}, el('td', {}, el('span', { class: 'k-' + (ICONS[f.kind] || 'files'), html: svg(ICONS[f.kind] || 'files') }), ' ', f.name),
        el('td', { text: f.kind }), el('td', { class: 'num', text: fmtBytes(f.bytes) }), cell));
      api.fileUrl(rid, f.name).then(u => {
        if (isDead()) return;
        cell.append(u ? el('a', { class: 'btn sm', href: u, download: f.name, 'aria-label': `Download ${f.name}`, html: svg('download') + '<span>Download</span>' })
          : el('span', { class: 'muted', text: 'server only' }));
      });
    });
  });
}

export function mount() {
  registerView('files', {
    title: key => ({ name: `Files ${idOf(key)}`, icon: 'files' }),
    crumbs: key => ['Runs', idOf(key), 'Files'],
    render: renderFiles,
  });
}
