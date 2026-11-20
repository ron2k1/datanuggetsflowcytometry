// "Run it locally": the Docker commands from /config, with copy buttons, and this server's facts.
import { el, docHead, copyText } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { S, activity } from '../../shared/store.js';
import { registerView } from '../../shared/views.js';

function cmdRow(label, cmd) {
  return el('div', {}, el('div', { class: 'field' }, el('span', { text: label })),
    el('div', { class: 'cmd' }, el('code', { text: cmd }),
      el('button', { type: 'button', class: 'btn', 'aria-label': `Copy: ${label}`, html: svg('copy') + '<span>Copy</span>', onclick: () => { copyText(cmd); activity(`Copied ${label.toLowerCase()}`); } })));
}
function renderLocal(body) {
  const cfg = S.config || {};
  body.append(el('div', { class: 'doc', style: 'max-width:860px' },
    docHead('Run it locally', 'Run the same app on your own computer. You need Docker; nothing else is installed.'),
    el('div', { class: 'card pad' },
      cmdRow('Start the app', cfg.docker_command || ''),
      el('div', { class: 'note', text: 'Then open http://127.0.0.1:8000. The first start downloads the image of this version. Uploads and results stay in the Docker volume named in the command, on this computer, until you remove it.' })),
    el('h3', { text: 'Or build it from the source' }),
    el('div', { class: 'card pad' },
      cmdRow('1. Build the image', cfg.build_command || ''),
      el('div', { style: 'height:14px' }),
      cmdRow('2. Start it', cfg.build_run_command || ''),
      el('div', { class: 'note', text: 'The build reads this version\'s release tag from GitHub and downloads the demo files, so it needs internet access.' })),
    el('h3', { text: 'This server' }),
    el('dl', { class: 'kv' },
      el('dt', { text: 'Mode' }), el('dd', { text: cfg.mode === 'local' ? 'Local' : 'Trial' }),
      el('dt', { text: 'Storage' }), el('dd', { text: cfg.storage_note || '' }),
      el('dt', { text: 'App version' }), el('dd', { class: 'mono', text: cfg.version || '' }),
      el('dt', { text: 'datanuggets-flow' }), el('dd', { class: 'mono', text: cfg.package_version || '' }))));
}

export function mount() {
  registerView('local', {
    title: () => ({ name: 'Run it locally', icon: 'local' }),
    crumbs: () => ['datanuggets', 'Run it locally'],
    render: renderLocal,
  });
}
