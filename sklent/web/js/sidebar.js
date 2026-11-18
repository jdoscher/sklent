// The sidebar: filter counts, sources, jobs.

import { api } from './api.js';
import { $, $$, esc } from './dom.js';
import { emit, refresh, schedule, state } from './store.js';
import { toast } from './toast.js';

export function renderSidebar() {
  const c = (f) => state.designs.filter(f).length;
  $('#count-all').textContent = state.designs.length;
  $('#count-rendered').textContent = c((d) => d.status === 'rendered');
  $('#count-active').textContent = c((d) => ['queued', 'rendering'].includes(d.status)) || '';
  $('#count-failed').textContent = c((d) => d.status === 'failed') || '';
  $$('.sidebar [data-filter]').forEach((el) => el.classList.toggle('active', !state.sourceId && el.dataset.filter === state.filter));

  $('#sources').innerHTML = state.sources.length ? state.sources.map((s) => `
    <div class="row ${state.sourceId === s.id ? 'active' : ''}" data-source="${esc(s.id)}" title="${esc(s.url)}${s.last_error ? `\n\n${esc(s.last_error)}` : ''}">
      <span class="name">${s.last_error ? '<span class="warn">⚠</span> ' : ''}${esc(s.label)}</span>
      <span class="count">${s.designs}</span>
      <span class="row-actions">
        <button class="icon" data-scan="${esc(s.id)}" title="Scan now">⟳</button>
        <button class="icon" data-remove="${esc(s.id)}" title="Remove source">✕</button>
      </span>
    </div>`).join('') : '<div class="empty">Paste a GitHub or Forgejo URL above.</div>';

  $('#jobs').innerHTML = state.jobs.length ? state.jobs.slice(0, 12).map((j) => {
    const what = j.kind === 'scan' ? `Scan ${(j.source_url || '').replace(/^https?:\/\//, '')}` : (j.design_path || '').split('/').pop();
    const msg = j.error || j.message || '';
    return `<div class="job">
      <div class="line"><span class="what" title="${esc(what)}">${esc(what)}</span><span class="state ${esc(j.status)}">${esc(j.status)}</span></div>
      ${msg ? `<div class="msg" title="${esc(msg)}">${esc(msg)}</div>` : ''}
      ${j.status === 'running' ? `<div class="bar"><i style="width:${Math.round(j.progress * 100)}%"></i></div>` : ''}
    </div>`;
  }).join('') : '<div class="empty">No jobs yet.</div>';
}

export function initSidebar() {
  $('.sidebar').addEventListener('click', async (e) => {
    const scan = e.target.closest('[data-scan]');
    const remove = e.target.closest('[data-remove]');
    try {
      if (scan) {
        await api(`/sources/${scan.dataset.scan}/scan`, { method: 'POST' });
        toast('Scan queued');
      } else if (remove) {
        const s = state.sources.find((x) => x.id === remove.dataset.remove);
        if (!confirm(`Remove ${s.label}? Its local renders are deleted; items already in Kist stay.`)) return;
        await api(`/sources/${remove.dataset.remove}`, { method: 'DELETE' });
        if (state.sourceId === remove.dataset.remove) state.sourceId = null;
      } else {
        const row = e.target.closest('[data-source], [data-filter]');
        if (!row) return;
        if (row.dataset.source) { state.sourceId = state.sourceId === row.dataset.source ? null : row.dataset.source; }
        else { state.sourceId = null; state.filter = row.dataset.filter; }
        emit();
        return;
      }
      await refresh(); schedule();
    } catch (err) { toast(err.message, true); }
  });
}
