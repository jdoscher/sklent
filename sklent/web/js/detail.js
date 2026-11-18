// The detail view as a drawing sheet (UI 12a): the viewer with dimension lines on the
// media's edge (U2-7), and a side column with the head row, the sheet schedule
// (U2-6: numbered files with pixel size, file size and the Discord budget) and the
// title block (U2-5: ISO 7200 fields from design.report, and design.spec if present).
//
// Seams (phase 2):
//   registerDetailSection({ id, title, order, render(container, design, ctx), sheet?, when? })
//     sheet: false (default) — a ruled section in the side column, between the
//       schedule and the title block (spec card, BOM, files pack, ...).
//     sheet: true — a numbered row in the schedule; choosing it renders the section
//       into the viewer instead of a media file (compare, filmstrip, ...).
//     when(design) -> bool hides it for designs it doesn't apply to.
//     render() runs when the sheet opens and whenever the design's data changes.
//   registerTitleBlockField({ id, label, order, wide, value(design, ctx) -> string | null })
//     an extra title-block cell; null hides it (the block shows only fields with data).

import { ctx } from './ctx.js';
import { $, $$, esc } from './dom.js';
import { DISCORD_MB, OUTLINE_MARK, VARIANT_LABEL, envelope, fmtBytes, fmtMass, isoTime, jobMessage, splitExt } from './format.js';
import { icon } from './icons.js';
import { jobState } from './sidebar.js';
import { activeJobFor, refresh, schedule, state } from './store.js';
import { toast } from './toast.js';

const sections = [];
const tbFields = [];
const byOrder = (a, b) => (a.order ?? 100) - (b.order ?? 100);

export function registerDetailSection(sec) {
  if (!sec || !sec.id || typeof sec.render !== 'function') throw new Error('registerDetailSection needs an id and render()');
  const i = sections.findIndex((s) => s.id === sec.id);
  if (i >= 0) sections.splice(i, 1);
  sections.push({ order: 100, title: sec.id, sheet: false, ...sec });
  sections.sort(byOrder);
}

export function registerTitleBlockField(field) {
  if (!field || !field.id || typeof field.value !== 'function') throw new Error('registerTitleBlockField needs an id and value()');
  const i = tbFields.findIndex((f) => f.id === field.id);
  if (i >= 0) tbFields.splice(i, 1);
  tbFields.push({ order: 100, label: field.id, wide: false, ...field });
  tbFields.sort(byOrder);
}

const applies = (s, d) => { try { return !s.when || s.when(d); } catch { return false; } };

/** Every sheet of a design in schedule order: its files, then registered sheet sections. */
function sheetsOf(d) {
  const files = ['shaded', 'wireframe'].flatMap((style) => d.files.filter((f) => f.style === style))
    .concat(d.files.filter((f) => !['shaded', 'wireframe'].includes(f.style)));
  const extra = sections.filter((s) => s.sheet && applies(s, d));
  return [
    ...files.map((f) => ({ key: f.file, file: f, group: f.style })),
    ...extra.map((s) => ({ key: `section:${s.id}`, section: s, group: s.group || 'More' })),
  ];
}

// ---------------------------------------------------------------- viewer

function drawDims() {
  const v = $('#viewer');
  v.querySelectorAll('.dims').forEach((n) => n.remove());
  const m = v.querySelector('.media');
  const sheet = sheetsOf(state.detail || { files: [] }).find((s) => s.key === state.detailFile);
  if (!m || !sheet || !sheet.file) return;
  const f = sheet.file;
  const vr = v.getBoundingClientRect();
  const r = m.getBoundingClientRect();
  if (!r.width || !r.height) return;
  const cs = getComputedStyle(document.documentElement);
  const px = (n, fb) => parseFloat(cs.getPropertyValue(n)) || fb;
  const off = px('--sk-dim-offset', 16), gap = px('--sk-dim-gap', 4), over = px('--sk-dim-over', 8), tk = px('--sk-dim-tick', 4.5);
  const L = r.left - vr.left, T = r.top - vr.top, W = r.width, H = r.height;
  const y = T - off, x = L - off;
  v.insertAdjacentHTML('beforeend', `<svg class="dims" width="${vr.width}" height="${vr.height}" aria-hidden="true">
    <line x1="${L + 0.5}" y1="${T - gap}" x2="${L + 0.5}" y2="${y - over}"/>
    <line x1="${L + W - 0.5}" y1="${T - gap}" x2="${L + W - 0.5}" y2="${y - over}"/>
    <line x1="${L - over}" y1="${y + 0.5}" x2="${L + W + over}" y2="${y + 0.5}"/>
    <line class="t" x1="${L - tk}" y1="${y + tk}" x2="${L + tk}" y2="${y - tk}"/>
    <line class="t" x1="${L + W - tk}" y1="${y + tk}" x2="${L + W + tk}" y2="${y - tk}"/>
    <text x="${L + W / 2}" y="${y - 5}" text-anchor="middle">${f.width} px</text>
    <line x1="${L - gap}" y1="${T + 0.5}" x2="${x - over}" y2="${T + 0.5}"/>
    <line x1="${L - gap}" y1="${T + H - 0.5}" x2="${x - over}" y2="${T + H - 0.5}"/>
    <line x1="${x + 0.5}" y1="${T - over}" x2="${x + 0.5}" y2="${T + H + over}"/>
    <line class="t" x1="${x - tk}" y1="${T + tk}" x2="${x + tk}" y2="${T - tk}"/>
    <line class="t" x1="${x - tk}" y1="${T + H + tk}" x2="${x + tk}" y2="${T + H - tk}"/>
    <text transform="translate(${x - 5} ${T + H / 2}) rotate(-90)" text-anchor="middle">${f.height} px</text>
  </svg>`);
}

function drawViewer(d, sheets, current) {
  const viewer = $('#viewer');
  const idx = sheets.indexOf(current) + 1;
  if (viewer.dataset.key !== (current ? current.key : '') || viewer.dataset.design !== d.id) {
    viewer.dataset.key = current ? current.key : '';
    viewer.dataset.design = d.id;
    if (!current) {
      viewer.innerHTML = `<div class="placeholder">${OUTLINE_MARK}<span>${esc(d.status === 'failed' ? 'Not rendered' : 'No files yet')}</span></div>`;
    } else if (current.section) {
      viewer.innerHTML = '<div class="section-sheet"></div>';
      try { current.section.render(viewer.firstChild, d, ctx); } catch (err) { console.error(`detail sheet ${current.section.id}`, err); }
    } else {
      const f = current.file;
      // width/height give the box its true aspect before the media arrives (and when a
      // browser can't decode it), so the dimension lines are right from the start
      const size = `width="${f.width}" height="${f.height}"`;
      viewer.innerHTML = f.file.endsWith('.mp4')
        ? `<video class="media" ${size} src="${esc(f.url)}" autoplay loop muted playsinline></video>`
        : `<img class="media" ${size} src="${esc(f.url)}" alt="${esc(`${d.name}: ${VARIANT_LABEL[f.variant] || f.variant}, ${f.style}`)}" />`;
      const m = viewer.querySelector('.media');
      m.addEventListener(m.tagName === 'VIDEO' ? 'loadedmetadata' : 'load', () => requestAnimationFrame(drawDims));
    }
  }
  viewer.querySelectorAll('.cap').forEach((n) => n.remove());
  if (current) {
    const facts = current.file
      ? `${current.file.width} × ${current.file.height} · ${fmtBytes(current.file.bytes)} · ${idx} of ${sheets.length}`
      : `${idx} of ${sheets.length}`;
    viewer.insertAdjacentHTML('beforeend', `<div class="cap"><span class="file-name">${esc(current.file ? current.file.file : current.section.title)}</span><span class="sk-data">${facts}</span></div>`);
  }
}

// ---------------------------------------------------------------- side column

function headHtml(d, job) {
  const kist = state.status.kist;
  const verb = d.status === 'rendered' && !d.stale ? 'Re-render' : d.status === 'failed' ? 'Render again' : 'Render';
  return `<button type="button" class="primary" data-render="${esc(d.id)}" ${job ? 'disabled' : ''}>${verb}</button>
    ${job ? `<button type="button" data-cancel="${job.id}">Cancel</button>` : ''}
    <a class="q" href="${esc(d.html_url)}" target="_blank" rel="noopener">Source ${icon('external-link', 14)}</a>
    ${d.kist_items.length && kist.url ? `<a class="q" href="${esc(kist.url)}" target="_blank" rel="noopener">Kist ${icon('external-link', 14)}</a>` : ''}
    <span class="spacer"></span>
    <button type="button" class="icon-btn close" data-close aria-label="Close">${icon('x', 20)}</button>`;
}

function jobHtml(job) {
  if (!job) return '';
  return `<div class="line">${jobState(job)}<span class="sk-data">${esc(jobMessage(job))}</span></div>
    ${job.status === 'running' ? `<div class="rule"><i style="width:${Math.round(job.progress * 100)}%"></i></div>` : ''}`;
}

function schedHtml(sheets) {
  if (!sheets.length) return '<div class="lbl">Sheets</div><p class="empty">No files yet.</p>';
  let group = null;
  let html = `<div class="lbl">Sheets <span class="sk-data">${sheets.length}</span></div>`;
  sheets.forEach((s, i) => {
    if (s.group !== group) { group = s.group; html += `<div class="lbl">${esc(group)}</div>`; }
    const active = s.key === state.detailFile ? ' active' : '';
    const no = String(i + 1).padStart(2, '0');
    if (s.section) {
      html += `<div class="srow${active}" data-sheet="${esc(s.key)}" role="button" tabindex="0" aria-current="${!!active}">
        <span class="no sk-data">${no}</span><span class="nm">${esc(s.section.title)}</span><span></span><span></span><span></span></div>`;
      return;
    }
    const f = s.file;
    const size = f.variant === 'discord' && f.bytes != null ? `${(f.bytes / 1e6).toFixed(1)}/${DISCORD_MB} MB` : fmtBytes(f.bytes);
    html += `<div class="srow${active}" data-sheet="${esc(s.key)}" role="button" tabindex="0" aria-current="${!!active}">
      <span class="no sk-data">${no}</span>
      <span class="nm">${esc(VARIANT_LABEL[f.variant] || f.variant)}</span>
      <span class="px sk-data">${f.width}×${f.height}</span>
      <span class="size sk-data"${f.variant === 'discord' ? ` title="Discord's upload limit is ${DISCORD_MB} MB"` : ''}>${size}</span>
      <a href="${esc(f.url)}" download="${esc(f.file)}" aria-label="Download ${esc(f.file)}" title="Download">${icon('download', 14)}</a>
    </div>`;
  });
  return html;
}

/** The title block's cells, data only: a field with no data shows "—" (truth rule). */
function titleCells(d, sheets, current) {
  const r = d.report || {};
  const spec = d.spec || {};
  const kist = state.status.kist;
  const [stem] = splitExt(d.name);
  const idx = sheets.indexOf(current) + 1;
  const pal = state.status.palettes.find((p) => p.name === (spec.palette || r.palette));
  const styles = [...new Set(d.files.map((f) => f.style))].join(' + ');
  const env = envelope(spec.bounds_mm || r.bounds_mm);
  const bodies = spec.bodies ?? r.bodies;
  const mass = fmtMass(spec.mass_g ?? (spec.mass_kg != null ? spec.mass_kg * 1000 : null));
  const cells = [
    { id: 'title', wide: true, cls: 'title', label: `Title<span class="sh">Sheet <b>${String(idx || 0).padStart(2, '0')} / ${String(sheets.length).padStart(2, '0')}</b></span>`,
      html: `<span class="v" id="sheet-title">${esc(spec.title || stem)}</span><span class="sub" title="${esc(d.path)}">${esc(d.path)}</span>` },
    { id: 'source', wide: true, label: 'Source', value: `${esc(d.repo)} <span class="d">@</span> ${esc(d.ref)} <span class="d">·</span> ${esc((d.commit || '').slice(0, 7))}` },
    { id: 'rev', label: 'Rev', value: d.blob ? esc(d.blob.slice(0, 7)) : '—' },
    { id: 'date', label: 'Date', value: esc(isoTime(d.rendered_at)) },
    { id: 'palette', label: 'Palette', value: pal ? `<span class="sw" style="background:${esc(pal.shaded)}"></span>${esc(pal.label.toLowerCase())}` : '—' },
    { id: 'styles', label: 'Styles', value: esc(styles || '—') },
    { id: 'envelope', wide: true, label: 'Envelope', value: env ? `${esc(env)} <span class="u">mm</span>` : '—' },
    { id: 'bodies', label: 'Bodies', value: bodies != null ? Number(bodies).toLocaleString('en-US') : '—' },
    { id: 'status', label: 'Status', value: esc(d.stale ? 'changed' : d.status) },
  ];
  if (mass) cells.push({ id: 'mass', label: 'Mass', value: esc(mass) });
  if (spec.material) cells.push({ id: 'material', label: 'Material', value: esc(spec.material) });
  for (const f of tbFields) {
    let v = null;
    try { v = f.value(d, ctx); } catch (err) { console.error(`title block ${f.id}`, err); }
    if (v != null && v !== '') cells.push({ id: f.id, label: esc(f.label), wide: f.wide, value: esc(v) });
  }
  if (d.kist_items.length && kist.url) {
    cells.push({ id: 'filed', wide: true, label: 'Filed', value: esc(`${kist.root_folder}/${d.repo}/${stem}`), wrap: true });
  }
  return cells;
}

function titleBlockHtml(d, sheets, current) {
  const cells = titleCells(d, sheets, current);
  // lay out halves in pairs; a half left alone takes the whole row
  for (let i = 0; i < cells.length; i += 1) {
    if (cells[i].wide) continue;
    if (cells[i + 1] && !cells[i + 1].wide) { cells[i].left = true; i += 1; } else cells[i].wide = true;
  }
  return cells.map((c) => `<div class="${[c.wide ? 'w2' : '', c.left ? 'l' : '', c.cls || ''].join(' ').trim()}" data-cell="${c.id}">
    <span class="k">${c.label}</span>${c.html || `<span class="v${c.wrap ? ' wrap' : ''}">${c.value}</span>`}</div>`).join('');
}

function drawSections(d) {
  const host = $('#detail-side .sheet-sections');
  const list = sections.filter((s) => !s.sheet && applies(s, d));
  host.innerHTML = list.map((s) => `<section class="sheet-section" data-section="${esc(s.id)}"><div class="lbl">${esc(s.title)}</div><div class="body"></div></section>`).join('');
  for (const s of list) {
    try { s.render(host.querySelector(`[data-section="${CSS.escape(s.id)}"] .body`), d, ctx); } catch (err) { console.error(`detail section ${s.id}`, err); }
  }
}

// ---------------------------------------------------------------- open / refresh / close

let opener = null;
let drawnData = '';

function draw(d, keepFile) {
  const changed = !state.detail || state.detail.id !== d.id || JSON.stringify(d) !== drawnData;
  state.detail = d;
  const sheets = sheetsOf(d);
  if (!keepFile || !sheets.some((s) => s.key === state.detailFile)) {
    const first = sheets.find((s) => s.file && s.file.style === 'shaded' && s.file.variant === '1080p') || sheets[0];
    state.detailFile = first ? first.key : null;
  }
  const current = sheets.find((s) => s.key === state.detailFile) || null;
  const job = activeJobFor(d.id);

  const side = $('#detail-side');
  if (side.dataset.design !== d.id) {
    side.dataset.design = d.id;
    side.innerHTML = '<div class="sheet-head"></div><div class="sheet-job"></div><p class="sheet-error"></p><div class="sched"></div><div class="sheet-sections"></div><section class="tb" aria-label="Title block"></section>';
  }
  $('.sheet-head', side).innerHTML = headHtml(d, job);
  $('.sheet-job', side).innerHTML = jobHtml(job);
  $('.sheet-job', side).hidden = !job;
  $('.sheet-error', side).textContent = d.status === 'failed' ? (d.error || 'The render failed.') : '';
  $('.sheet-error', side).hidden = d.status !== 'failed';
  const sched = $('.sched', side);
  const scroll = sched.scrollTop;
  sched.innerHTML = schedHtml(sheets);
  sched.scrollTop = scroll;
  $('.tb', side).innerHTML = titleBlockHtml(d, sheets, current);
  if (changed) { drawSections(d); drawnData = JSON.stringify(d); }
  drawViewer(d, sheets, current);
  requestAnimationFrame(drawDims);
  $('#detail').hidden = false;
}

const reducedMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Open (or redraw) the drawing sheet for a design. */
export function openDetail(d, keepFile = false, fromEl = null) {
  const opening = $('#detail').hidden;
  if (opening) opener = fromEl || document.activeElement;
  const go = () => {
    draw(d, keepFile);
    if (opening) $('#detail-side .close')?.focus({ preventScroll: true });
  };
  if (opening && document.startViewTransition && !reducedMotion()) document.startViewTransition(go);
  else go();
}

/** After a poll: redraw the open design if its data or its job changed. */
export function refreshDetail() {
  if (!state.detail || $('#detail').hidden) return;
  const fresh = state.designs.find((d) => d.id === state.detail.id);
  if (!fresh) { closeDetail(); return; }
  const job = activeJobFor(fresh.id);
  const key = JSON.stringify([fresh, job]);
  if (key !== refreshDetail.last) { refreshDetail.last = key; draw(fresh, true); }
}

export function closeDetail() {
  if ($('#detail').hidden) return false;
  $('#detail').hidden = true;
  state.detail = null;
  const viewer = $('#viewer');
  viewer.innerHTML = '';
  viewer.dataset.key = '';
  viewer.dataset.design = '';
  $('#detail-side').dataset.design = '';
  drawnData = '';
  refreshDetail.last = '';
  if (opener && opener.isConnected) opener.focus({ preventScroll: true });
  opener = null;
  return true;
}

async function rerender(id) {
  const d = state.designs.find((x) => x.id === id) || state.detail;
  const job = await ctx.api(`/designs/${id}/render`, { method: 'POST', body: { force: true } });
  toast(`Render queued for ${splitExt(d.name)[0]}`, {
    action: { label: 'Cancel', run: async () => { await ctx.api(`/jobs/${job.id}/cancel`, { method: 'POST' }); toast('Render cancelled'); await refresh(); } },
  });
  await refresh(); schedule();
}

export function initDetail() {
  const overlay = $('#detail');
  overlay.addEventListener('click', async (e) => {
    if (e.target === overlay || e.target.closest('[data-close]')) { closeDetail(); return; }
    if (e.target.closest('a[download]')) return;
    const row = e.target.closest('[data-sheet]');
    if (row) { state.detailFile = row.dataset.sheet; draw(state.detail, true); return; }
    try {
      const r = e.target.closest('[data-render]');
      if (r) await rerender(r.dataset.render);
      const c = e.target.closest('[data-cancel]');
      if (c) {
        await ctx.api(`/jobs/${c.dataset.cancel}/cancel`, { method: 'POST' });
        toast('Render cancelled');
        await refresh(); schedule();
      }
    } catch (err) { toast(err.message, { bad: true }); }
  });
  overlay.addEventListener('keydown', (e) => {
    const row = e.target.closest('[data-sheet]');
    if (row && e.target === row && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); row.click(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const rows = $$('#detail [data-sheet]');
      const i = rows.findIndex((x) => x.dataset.sheet === state.detailFile);
      const next = rows[i + (e.key === 'ArrowDown' ? 1 : -1)];
      if (next && (row || e.target === overlay || e.target.closest('.viewer'))) { e.preventDefault(); next.click(); $(`#detail [data-sheet="${CSS.escape(next.dataset.sheet)}"]`)?.focus(); }
    }
  });
  if (window.ResizeObserver) new ResizeObserver(() => requestAnimationFrame(drawDims)).observe($('#viewer'));
  else window.addEventListener('resize', () => requestAnimationFrame(drawDims));
}
