// Compare samples (flow runs): each sample's share of every cluster as a heatmap, stacked bars
// and a counts/percent table; with groups, the group summary (mean, SD, diff and log2FC against
// the reference group) and marker means per group with a difference view, both descriptive (no
// test). Clicking a cluster anywhere opens the plot with that cluster selected. Every number is
// a payload number.
import { el, docHead, seg } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { fmtInt, fmtNum } from '../../shared/format.js';
import { runTransform, perChannel, cofactorTag, transformText } from '../../shared/cofactor.js';
import { plotTheme, baseLayout, groupColor } from '../../shared/plot-base.js';
import { api } from '../../shared/api/index.js';
import { EV } from '../../shared/events.js';
import { S, emit, subscribe, idOf, getCompare, getManifest, allUploads } from '../../shared/store.js';
import { registerView } from '../../shared/views.js';

const openTab = key => emit(EV.openTab, { key });
// "Show in the plot": the plot opens the run with that cluster selected (EV.clusterFocus).
const focusCluster = (rid, cluster) => emit(EV.clusterFocus, { rid, cluster });

const CONFIG = { responsive: false, displaylogo: false, displayModeBar: false, scrollZoom: false };
// Colours come from the theme at draw time (shared/plot-base.js); a theme switch redraws.
const axis = (T, title, extra = {}) => ({ title: { text: title, font: { size: 11.5, color: T.fg2 } }, gridcolor: T.grid, linecolor: T.line, color: T.fg3, tickfont: { size: 10 }, automargin: true, ...extra });
const esc = s => String(s).replace(/[<>&]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[c]);
const pct = v => (v == null ? '–' : `${fmtNum(v)}%`);
// The marker means' units, the run's Transform stage (the tables undo the Scale stage), from its
// run.json: the cofactor used, or the range of the channels' own under per-channel auto, and
// whether it was auto or set ("auto" in the settings is not a number); nothing when the record
// did not load.
const transformOf = man => (man ? runTransform(man.record) : null);
const unitsOf = man => { const t = transformOf(man); return !t ? '' : ` (${transformText(t)})`; };
// Each channel's units for the marker means' hover under per-channel auto, ", arcsinh(x / 338)";
// C.channels is run.json's labels, so column j is channel j of the cofactors. Empty when the
// channels share one cofactor, which the heading already names.
const chanUnits = (man, n) => {
  const t = transformOf(man);
  return Array.from({ length: n }, (_, j) => (perChannel(t) ? `, ${cofactorTag(t, [j])}` : ''));
};

function render(body, key) {
  const rid = idOf(key);
  const st = S.view[key] || (S.view[key] = { table: 'percent', markers: null, share: 'heat' });
  const charts = [];
  let dead = false, ro = null;

  function chart(cls, draw) {
    const host = el('div');
    const box = el('div', { class: 'chart' + (cls ? ' ' + cls : '') }, host);
    charts.push({ host, draw });
    return box;
  }
  function drawCharts() {
    if (!window.Plotly) { charts.forEach(c => c.host.replaceChildren(el('div', { class: 'fallback', text: 'Plotly did not load.' }))); return; }
    const T = plotTheme();
    for (const c of charts) {
      const { data, layout } = c.draw(T);
      window.Plotly.react(c.host, data, { ...baseLayout(T), ...layout }, CONFIG).then(() => {
        if (dead || c.wired) return;
        c.wired = true;
        c.host.on('plotly_click', ev => { const p = ev && ev.points && ev.points[0]; const cl = p && p.customdata; if (cl) focusCluster(rid, Array.isArray(cl) ? cl[0] : cl); });
      });
    }
  }

  function page(C, man) {
    const k = C.k, cl = C.clusters, col = c => cl[c - 1].color, ks = cl.map(c => c.cluster);
    const fileName = f => `F${f.number} ${esc(f.name)}`;
    const groups = C.groups && C.groups.length ? C.groups : null;
    const demo = allUploads().some(u => u.demo && C.files.some(f => f.name === u.name));

    // 1. Shares per sample.
    const heat = T => ({
      data: [{ type: 'heatmap', z: C.percent, x: ks.map(c => `C${c}`), y: C.files.map(fileName), colorscale: T.seq, zmin: 0,
        customdata: C.percent.map(row => row.map((_, j) => ks[j])), xgap: 1, ygap: 1,
        text: C.percent.map((row, i) => row.map((v, j) => `${fileName(C.files[i])}<br>Cluster ${ks[j]}: ${pct(v)} (${fmtInt(C.counts[i][j])} cells)`)),
        hovertemplate: '%{text}<extra></extra>', colorbar: { title: { text: '% of sample', side: 'right' }, thickness: 10, outlinewidth: 0, tickfont: { size: 9.5, color: T.fg3 } } }],
      layout: { margin: { l: 10, r: 10, t: 8, b: 40 }, xaxis: axis(T, 'Cluster', { type: 'category' }), yaxis: axis(T, '', { autorange: 'reversed', type: 'category' }) },
    });
    const bars = T => ({
      data: ks.map((c, j) => ({ type: 'bar', name: `Cluster ${c}`, orientation: 'h', y: C.files.map(fileName), x: C.percent.map(row => row[j]), marker: { color: col(c), line: { width: 0 } },
        customdata: C.files.map(() => c), text: C.files.map((f, i) => `${fileName(f)}<br>Cluster ${c}: ${pct(C.percent[i][j])} (${fmtInt(C.counts[i][j])} cells)`),
        textposition: 'none', hovertemplate: '%{text}<extra></extra>' })),
      layout: { barmode: 'stack', showlegend: false, margin: { l: 10, r: 14, t: 8, b: 40 }, xaxis: axis(T, '% of the sample\'s kept cells', { range: [0, 100] }), yaxis: axis(T, '', { autorange: 'reversed', type: 'category' }) },
    });

    const table = el('div', { class: 'tbl-wrap' });
    const drawTable = () => {
      const pc = st.table === 'percent';
      table.replaceChildren(el('table', { class: 'tbl' },
        el('thead', {}, el('tr', {}, el('th', { text: 'Sample' }), el('th', { text: 'Group' }), el('th', { class: 'num', text: 'Cells' }),
          ...ks.map(c => el('th', { class: 'num sortable', title: `Show cluster ${c} in the plot`, onclick: () => focusCluster(rid, c) }, el('span', { class: 'sw', style: `background:${col(c)}` }), `C${c}`)))),
        el('tbody', {}, ...C.files.map((f, i) => el('tr', {},
          el('td', { text: `F${f.number} ${f.name}` }), el('td', { text: f.group || '–' }), el('td', { class: 'num', text: fmtInt(f.cells) }),
          ...ks.map((_, j) => el('td', { class: 'num', text: pc ? pct(C.percent[i][j]) : fmtInt(C.counts[i][j]) })))))));
    };
    drawTable();
    const tableSeg = seg('Table shows', [['percent', 'Percent'], ['counts', 'Counts']], st.table, v => { st.table = v; drawTable(); tableSeg.querySelectorAll('button').forEach((b, i) => b.setAttribute('aria-pressed', String(['percent', 'counts'][i] === v))); });

    const out = [
      docHead(`Compare samples · ${rid}`, `${C.files.length} samples, K=${k}. Shares are of each sample's kept cells. Click a cluster in a chart or a column head to open it in the plot.`,
        el('button', { type: 'button', class: 'btn', html: svg('plot') + '<span>Open the plot</span>', onclick: () => openTab(`plot:${rid}`) })),
      demo ? el('div', { class: 'callout info', style: 'margin-bottom:14px', text: 'These are public PBMC demo files. The group names are labels assigned to try this screen, not experimental conditions, so differences between them mean nothing biological.' }) : null,
      el('div', { class: 'cmp-grid' },
        el('div', {}, el('div', { class: 'chart-head' }, el('h3', { text: 'Share of each cluster (heatmap)' })), chart('', heat)),
        el('div', {}, el('div', { class: 'chart-head' }, el('h3', { text: 'Share of each cluster (stacked)' })), chart('', bars))),
      el('div', { class: 'section' }, el('h3', {}, 'Samples by cluster', tableSeg), table),
    ];

    // 2. Groups: descriptive only, no test. Rows run cluster by cluster with the reference group
    // first, so a log2FC sits just under the raw group mean and SD it is computed from.
    if (groups && C.group_summary) {
      const ref = C.reference;
      const order = groups.includes(ref) ? [ref, ...groups.filter(g => g !== ref)] : groups;
      const sum = [...C.group_summary].sort((a, b) => ks.indexOf(a.cluster) - ks.indexOf(b.cluster) || order.indexOf(a.group) - order.indexOf(b.group));
      const refRow = c => sum.find(r => r.group === ref && r.cluster === c);
      const gbars = T => ({
        data: order.map((g, gi) => {
          const rows = ks.map(c => sum.find(r => r.group === g && r.cluster === c));
          const vsRef = c => { const rr = refRow(c); return rr ? `<br>${esc(ref)} mean ${pct(rr.mean_percent)}, SD ${pct(rr.sd_percent)}` : ''; };
          return { type: 'bar', name: esc(g), x: ks.map(c => `C${c}`), y: rows.map(r => (r ? r.mean_percent : null)), customdata: ks,
            error_y: { type: 'data', array: rows.map(r => (r && r.sd_percent != null ? r.sd_percent : 0)), visible: true, color: T.fg3, thickness: 1, width: 3 },
            marker: { color: groupColor(T, gi), opacity: 0.85, line: { width: 0 } }, textposition: 'none',
            text: rows.map((r, j) => r ? `${esc(g)} · cluster ${ks[j]}<br>mean ${pct(r.mean_percent)}, SD ${pct(r.sd_percent)} over ${r.samples} sample${r.samples === 1 ? '' : 's'}${g === ref ? ' (reference)' : `${vsRef(ks[j])}<br>diff ${fmtNum(r.diff_vs_ref)} points, log2FC ${fmtNum(r.log2fc_vs_ref)}`}` : ''),
            hovertemplate: '%{text}<extra></extra>' };
        }),
        layout: { barmode: 'group', showlegend: true, legend: { orientation: 'h', y: 1.08, x: 0, font: { size: 11 } }, margin: { l: 10, r: 10, t: 30, b: 40 },
          xaxis: axis(T, 'Cluster', { type: 'category' }), yaxis: axis(T, 'Mean % of sample (±SD)') },
      });
      const gt = el('div', { class: 'tbl-wrap' }, el('table', { class: 'tbl' },
        el('thead', {}, el('tr', {}, ...['Cluster', 'Group', 'Samples', 'Mean %', 'SD', `Diff vs ${ref}`, `log2FC vs ${ref}`, 'Min %', 'Max %'].map((h, i) => el('th', { class: i > 1 ? 'num' : '', text: h })))),
        el('tbody', {}, ...sum.map(r => el('tr', { class: 'clickable' + (r.group === ref ? ' ref' : ''), title: `Show cluster ${r.cluster} in the plot`, onclick: () => focusCluster(rid, r.cluster) },
          el('td', {}, el('span', { class: 'sw', style: `background:${col(r.cluster)}` }), `C${r.cluster}`), el('td', { text: r.group }),
          el('td', { class: 'num', text: fmtInt(r.samples) }), el('td', { class: 'num', text: pct(r.mean_percent) }), el('td', { class: 'num', text: fmtNum(r.sd_percent) }),
          el('td', { class: 'num', text: r.group === ref ? 'reference' : fmtNum(r.diff_vs_ref) }), el('td', { class: 'num', text: r.group === ref ? '–' : fmtNum(r.log2fc_vs_ref) }),
          el('td', { class: 'num', text: pct(r.min_percent) }), el('td', { class: 'num', text: pct(r.max_percent) }))))));
      // The pseudocount is half a cell per file, in percentage points, averaged over the files
      // (log2fc_pseudocount); an older run's payload lacks it, so the number is left out.
      const pc = C.log2fc_pseudocount;
      const how = `log2FC adds half a cell per file${pc != null ? ` (${fmtNum(pc)} percentage points)` : ''} to every group.`;
      out.push(el('div', { class: 'section' }, el('h3', { text: `Groups (descriptive): ${groups.join(' vs ')}, reference ${ref}` }),
        el('div', { class: 'note', style: 'margin:-4px 0 10px', text: `Diff is in percentage points. ${how} Descriptive only: no significance test.` }),
        chart('', gbars), el('div', { style: 'height:12px' }), gt));
    }

    // 3. Marker means: per group (or per sample without groups), plus the difference view.
    const opts = groups && C.group_markers ? [...groups.map(g => [`g:${g}`, g]), ...groups.filter(g => g !== C.reference).map(g => [`d:${g}`, `${g} − ${C.reference}`])]
      : C.files.map(f => [`f:${f.number}`, `F${f.number}`]);
    if (!st.markers || !opts.some(o => o[0] === st.markers)) st.markers = opts[opts.length - 1][0];
    const mheat = T => {
      const m = st.markers, chans = C.channels;
      let z, title, scale = T.seq, zmid;
      const diff = m.startsWith('d:');
      if (diff || m.startsWith('g:')) {
        const g = m.slice(2);
        const look = new Map(C.group_markers.filter(r => r.group === g).map(r => [`${r.cluster}|${r.channel}`, r]));
        z = ks.map(c => chans.map(ch => { const r = look.get(`${c}|${ch}`); return r ? (diff ? r.diff_vs_ref : r.mean) : null; }));
        title = diff ? `${g} − ${C.reference}` : `${g} mean`;
        if (diff) { scale = T.div; zmid = 0; }
      } else {
        const fno = +m.slice(2);
        z = ks.map(c => { const r = C.cluster_markers.find(x => x.file_number === fno && x.cluster === c); return r ? r.means : chans.map(() => null); });
        title = `F${fno} mean`;
      }
      const short = chans.map(ch => ch.split(' (')[0]), units = chanUnits(man, chans.length);
      return {
        data: [{ type: 'heatmap', z, x: short, y: ks.map(c => `C${c}`), colorscale: scale, zmid, xgap: 1, ygap: 1, customdata: z.map((row, i) => row.map(() => ks[i])),
          text: z.map((row, i) => row.map((v, j) => `Cluster ${ks[i]} · ${chans[j]}<br>${title}: ${fmtNum(v)}${units[j]}`)), hovertemplate: '%{text}<extra></extra>',
          colorbar: { title: { text: title, side: 'right' }, thickness: 10, outlinewidth: 0, tickfont: { size: 9.5, color: T.fg3 } } }],
        layout: { margin: { l: 10, r: 10, t: 8, b: 90 }, xaxis: axis(T, '', { tickangle: -50, type: 'category' }), yaxis: axis(T, 'Cluster', { autorange: 'reversed', type: 'category' }) },
      };
    };
    const mSeg = seg('Marker means', opts.map(([v, t]) => [v, t]), st.markers, v => { st.markers = v; mSeg.querySelectorAll('button').forEach((b, i) => b.setAttribute('aria-pressed', String(opts[i][0] === v))); drawCharts(); });
    out.push(el('div', { class: 'section' }, el('div', { class: 'chart-head' }, el('h3', { text: `Marker means by cluster${unitsOf(man)}` }), mSeg),
      chart('tall', mheat),
      el('div', { class: 'note', text: groups ? 'A group mean is the unweighted mean of its samples\' cluster means; the difference view subtracts the reference group. Descriptive only: no significance test.' : 'Means per channel of one sample\'s cells in each cluster.' })));

    // 4. Downloads.
    const names = ['cluster_summary.csv', 'group_summary.csv', 'group_markers.csv', 'cluster_markers.csv'];
    const links = el('div', { class: 'links' });
    out.push(el('div', { class: 'section' }, el('h3', { text: 'Download the tables' }), links));
    Promise.all(names.map(n => api.fileUrl(rid, n))).then(urls => {
      if (dead) return;
      links.replaceChildren(...names.map((n, i) => (urls[i]
        ? el('a', { class: 'btn sm', href: urls[i], download: n, html: svg('download') + `<span></span>` })
        : el('button', { type: 'button', class: 'btn sm', disabled: true, title: 'Not part of the fixture set', html: svg('download') + '<span></span>' }))));
      links.querySelectorAll('span').forEach((s, i) => { s.textContent = names[i]; });
    });
    return out;
  }

  body.append(el('div', { class: 'doc muted', text: 'Loading the comparison…' }));
  Promise.all([getCompare(rid), getManifest(rid).catch(() => null)]).then(([C, man]) => {
    if (dead) return;
    body.replaceChildren(el('div', { class: 'doc' }, ...page(C, man)));
    requestAnimationFrame(() => {
      if (dead) return;
      drawCharts();
      ro = new ResizeObserver(() => charts.forEach(c => { if (window.Plotly && c.host._fullLayout) window.Plotly.Plots.resize(c.host); }));
      charts.forEach(c => ro.observe(c.host.parentElement));
    });
  }, e => { if (!dead) body.replaceChildren(el('div', { class: 'doc' }, docHead(`Compare samples · ${rid}`, null), el('div', { class: 'callout', text: e.message }))); });

  const offTheme = subscribe(EV.themeChange, () => { if (!dead && charts.length) drawCharts(); });
  return () => { dead = true; offTheme(); if (ro) ro.disconnect(); if (window.Plotly) charts.forEach(c => window.Plotly.purge(c.host)); };
}

export function mount() {
  registerView('compare', {
    title: key => ({ name: `Compare ${idOf(key)}`, icon: 'compare' }),
    crumbs: key => ['Runs', idOf(key), 'Compare samples'],
    render,
  });
}
