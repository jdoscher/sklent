// The detail overlay for one design.

import { api } from './api.js';
import { $, esc } from './dom.js';
import { CUBE, VARIANT_LABEL, fmtBytes } from './format.js';
import { activeJobFor, refresh, schedule, state } from './store.js';
import { toast } from './toast.js';

export function openDetail(d, keepFile = false) {
  state.detail = d;
  if (!keepFile || !d.files.some((f) => f.file === state.detailFile)) {
    state.detailFile = (d.files.find((f) => f.style === 'shaded' && f.variant === '1080p') || d.files[0] || {}).file || null;
  }
  const file = d.files.find((f) => f.file === state.detailFile);
  const viewer = $('#viewer');
  const current = viewer.dataset.file;
  if (current !== (file ? file.file : '')) {
    viewer.dataset.file = file ? file.file : '';
    viewer.innerHTML = !file ? `<div class="placeholder dim">${CUBE}<p>${esc(d.status)}</p></div>`
      : file.file.endsWith('.mp4') ? `<video src="${esc(file.url)}" controls autoplay loop muted playsinline></video>`
        : `<img src="${esc(file.url)}" alt="" />`;
  }
  const kist = state.status.kist;
  const job = activeJobFor(d.id);
  const groups = ['shaded', 'wireframe'].map((style) => {
    const fs = d.files.filter((f) => f.style === style);
    if (!fs.length) return '';
    return `<h3>${style}</h3>${fs.map((f) => `
      <div class="file ${f.file === state.detailFile ? 'active' : ''}" data-file="${esc(f.file)}">
        <span class="label">${esc(VARIANT_LABEL[f.variant] || f.variant)} <span class="dim">${f.width}×${f.height}</span></span>
        <span class="size">${fmtBytes(f.bytes)}</span>
        <a href="${esc(f.url)}" download="${esc(f.file)}" title="Download" onclick="event.stopPropagation()">↓</a>
      </div>`).join('')}`;
  }).join('');
  $('#detail-side').innerHTML = `
    <h2>${esc(d.name)}</h2>
    <div class="meta">
      <a href="${esc(d.html_url)}" target="_blank" rel="noopener">${esc(d.repo)}/${esc(d.path)}</a><br />
      ${esc(d.ref)} @ ${esc(d.commit)} · ${esc(d.stale ? 'changed since last render' : d.status)}
      ${d.rendered_at ? `<br />rendered ${esc(new Date(d.rendered_at).toLocaleString())}` : ''}
      ${d.kist_items.length && kist.url ? `<br />filed in <a href="${esc(kist.url)}" target="_blank" rel="noopener">Kist</a>: ${esc(kist.root_folder)}/${esc(d.repo)}/${esc(d.name.replace(/\.[^.]+$/, ''))}` : ''}
    </div>
    ${d.error ? `<p class="error">${esc(d.error)}</p>` : ''}
    ${job ? `<p class="dim">${esc(job.status)}: ${esc(job.message || '')}</p><div class="bar"><i style="width:${Math.round(job.progress * 100)}%"></i></div>` : ''}
    <div class="actions">
      <button class="primary" data-render="${esc(d.id)}" ${job ? 'disabled' : ''}>${d.status === 'rendered' && !d.stale ? 'Re-render' : 'Render'}</button>
    </div>
    ${groups || '<p class="dim">No files yet.</p>'}`;
  $('#detail').hidden = false;
}

/** After a poll: redraw the open design if its data changed. */
export function refreshDetail() {
  if (!state.detail) return;
  const fresh = state.designs.find((d) => d.id === state.detail.id);
  if (fresh && JSON.stringify(fresh) !== JSON.stringify(state.detail)) openDetail(fresh, true);
}

export function closeDetail() {
  $('#detail').hidden = true;
  state.detail = null;
  $('#viewer').innerHTML = '';
  $('#viewer').dataset.file = '';
}

export function initDetail() {
  $('#detail').addEventListener('click', async (e) => {
    if (e.target === e.currentTarget || e.target.closest('[data-close]')) { closeDetail(); return; }
    const f = e.target.closest('[data-file]');
    if (f) { state.detailFile = f.dataset.file; openDetail(state.detail, true); return; }
    const r = e.target.closest('[data-render]');
    if (r) {
      try {
        await api(`/designs/${r.dataset.render}/render`, { method: 'POST', body: { force: true } });
        toast('Render queued');
        await refresh(); schedule();
      } catch (err) { toast(err.message, true); }
    }
  });
}
