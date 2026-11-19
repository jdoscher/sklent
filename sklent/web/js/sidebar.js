// The sidebar as a schedule (UI 11a): views with Lucide icons, sources as the file or
// folder name over its path, the job log. On the phone it is the drawer (A1).
//
// Seam: registerSidebarSection({ id, title, order, render(container, ctx) }) adds a
// section; built-ins are views (0), sources (10) and jobs (20). render() runs after
// every poll and view change, into the section's own container.
// Seam: registerSourceAction({ id, icon, label, order, when(source), run(source, ctx) })
// adds an icon button to each source row's actions (before Scan and Remove).

import { ctx } from './ctx.js';
import { $, $$, esc } from './dom.js';
import { jobMessage } from './format.js';
import { icon } from './icons.js';
import { emit, refresh, schedule, state } from './store.js';
import { toast } from './toast.js';

const sections = [];
let mounted = false;

/** Add a sidebar section. `title` '' renders no heading. Re-registering an id replaces it. */
export function registerSidebarSection({ id, title = '', order = 100, render, grow = false }) {
  if (!id || typeof render !== 'function') throw new Error('registerSidebarSection needs an id and render()');
  const i = sections.findIndex((s) => s.id === id);
  if (i >= 0) sections.splice(i, 1);
  sections.push({ id, title, order, render, grow });
  sections.sort((a, b) => a.order - b.order);
  mounted = false;
}

const sourceActions = [];

/** An icon button on every source row (when(source) hides it); run() may be async. */
export function registerSourceAction({ id, icon: ic = 'plus', label, order = 100, when, run }) {
  if (!id || !label || typeof run !== 'function') throw new Error('registerSourceAction needs an id, label and run()');
  const i = sourceActions.findIndex((a) => a.id === id);
  if (i >= 0) sourceActions.splice(i, 1);
  sourceActions.push({ id, icon: ic, label, order, when, run });
  sourceActions.sort((a, b) => a.order - b.order);
}

function sourceActionsHtml(s, leaf) {
  return sourceActions.filter((a) => { try { return !a.when || a.when(s); } catch { return false; } })
    .map((a) => `<button type="button" class="icon-btn s24" data-source-action="${esc(a.id)}" data-sid="${esc(s.id)}" aria-label="${esc(a.label)}: ${esc(leaf)}" title="${esc(a.label)}">${icon(a.icon, 14)}</button>`).join('');
}

export const VIEWS = [
  ['all', 'All designs', 'layout-grid'],
  ['rendered', 'Rendered', 'circle-check'],
  ['active', 'In progress', 'loader-circle'],
  ['failed', 'Failed', 'triangle-alert'],
];

function counts() {
  const c = (f) => state.designs.filter(f).length;
  return {
    all: state.designs.length,
    rendered: c((d) => d.status === 'rendered'),
    active: c((d) => d.status === 'queued' || d.status === 'rendering'),
    failed: c((d) => d.status === 'failed'),
  };
}

function renderViews(el) {
  const n = counts();
  el.innerHTML = VIEWS.map(([f, label, ic]) => `
    <div class="row ${!state.sourceId && state.filter === f ? 'active' : ''}" data-filter="${f}" role="button" tabindex="0">
      ${icon(ic)}<span class="name">${label}</span><span class="count">${n[f] || (f === 'all' || f === 'rendered' ? n[f] : '')}</span>
    </div>`).join('');
}

function renderSources(el) {
  el.innerHTML = state.sources.length ? state.sources.map((s) => {
    const parts = s.label.split('/');
    const leaf = parts.pop();
    const tip = `${s.url}${s.last_error ? `\n\n${s.last_error}` : ''}`;
    return `<div class="row ${state.sourceId === s.id ? 'active' : ''}" data-source="${esc(s.id)}" role="button" tabindex="0" title="${esc(tip)}">
      ${icon('folder-git-2')}
      <span class="src"><b>${s.last_error ? `<span class="warn" title="${esc(s.last_error)}">${icon('triangle-alert', 14)}</span>` : ''}<span>${esc(leaf)}</span></b><i>${esc(parts.length ? parts.join('/') : s.provider)}</i></span>
      <span class="count">${s.designs}</span>
      <span class="row-actions">
        ${sourceActionsHtml(s, leaf)}
        <button type="button" class="icon-btn s24" data-scan="${esc(s.id)}" aria-label="Scan ${esc(leaf)} now" title="Scan now">${icon('refresh-cw', 14)}</button>
        <button type="button" class="icon-btn s24" data-remove="${esc(s.id)}" aria-label="Remove ${esc(leaf)}" title="Remove source">${icon('x', 14)}</button>
      </span>
    </div>`;
  }).join('') : '<div class="empty">Paste a GitHub or Forgejo URL above.</div>';
}

const JOB_STATE = {
  queued: ['clock', 'Queued'],
  running: ['loader-circle', 'Rendering'],
  done: ['circle-check', 'Done'],
  failed: ['circle-x', 'Failed'],
  cancelled: ['circle-slash', 'Cancelled'],
};

export function jobState(j) {
  const [ic, word] = JOB_STATE[j.status] || ['clock', j.status];
  const label = j.status === 'running' && j.kind === 'scan' ? 'Scanning' : word;
  return `${icon(ic, 14, j.status === 'running' ? 'spin' : '')}${label}`;
}

function renderJobs(el) {
  el.innerHTML = state.jobs.length ? state.jobs.slice(0, 12).map((j) => {
    const what = j.kind === 'scan' ? `Scan ${(j.source_url || '').replace(/^https?:\/\/[^/]+\//, '')}` : (j.design_path || '').split('/').pop();
    const msg = jobMessage(j);
    const live = j.status === 'queued' || j.status === 'running';
    return `<div class="job" data-job="${j.id}">
      <div class="line"><span class="what" title="${esc(what)}">${esc(what)}</span><span class="state ${esc(j.status)}">${jobState(j)}</span>
        ${live ? `<button type="button" class="icon-btn s24 cancel" data-cancel="${j.id}" aria-label="Cancel ${esc(what)}" title="Cancel">${icon('x', 14)}</button>` : ''}</div>
      ${msg ? `<div class="msg" title="${esc(msg)}">${esc(msg)}</div>` : ''}
      ${j.status === 'running' ? `<div class="rule"><i style="width:${Math.round(j.progress * 100)}%"></i></div>` : ''}
    </div>`;
  }).join('') : '<div class="empty">No jobs yet.</div>';
}

registerSidebarSection({ id: 'views', title: '', order: 0, render: renderViews });
registerSidebarSection({ id: 'sources', title: 'Sources', order: 10, render: renderSources });
registerSidebarSection({ id: 'jobs', title: 'Jobs', order: 20, render: renderJobs, grow: true });

function mount() {
  $('#sidebar-sections').innerHTML = sections.map((s) => `
    <section class="section${s.grow ? ' grow' : ''}" data-section="${esc(s.id)}" id="section-${esc(s.id)}">
      ${s.title ? `<h2 class="section-title">${esc(s.title)}</h2>` : ''}<div class="section-body"></div>
    </section>`).join('');
  mounted = true;
}

export function renderSidebar() {
  if (!mounted) mount();
  for (const s of sections) {
    const el = $(`#section-${CSS.escape(s.id)} .section-body`);
    try { s.render(el, ctx); } catch (err) { console.error(`sidebar section ${s.id}`, err); }
  }
  renderFilterRow();
}

// ---------- phone: the filter pills and the drawer ----------

function renderFilterRow() {
  const n = counts();
  $('#filter-row').innerHTML = VIEWS.map(([f, label]) => `
    <button type="button" data-pf="${f}" class="${!state.sourceId && state.filter === f ? 'on' : ''}">${label === 'All designs' ? 'All' : label}${f !== 'all' && n[f] ? ` ${n[f]}` : ''}</button>`).join('')
    + `<button type="button" data-pf="sources" class="${state.sourceId ? 'on' : ''}">Sources</button><button type="button" data-pf="jobs">Jobs</button>`;
}

export function openDrawer(sectionId) {
  document.body.classList.add('drawer-open');
  $('#drawer-scrim').hidden = false;
  $('#menu-btn').setAttribute('aria-expanded', 'true');
  $('#drawer-close').focus({ preventScroll: true });
  if (sectionId) $(`#section-${sectionId}`)?.scrollIntoView({ block: 'start' });
}

export function closeDrawer() {
  if (!document.body.classList.contains('drawer-open')) return false;
  document.body.classList.remove('drawer-open');
  $('#drawer-scrim').hidden = true;
  $('#menu-btn').setAttribute('aria-expanded', 'false');
  $('#menu-btn').focus({ preventScroll: true });
  return true;
}

function choose(row) {
  if (row.dataset.source) state.sourceId = state.sourceId === row.dataset.source ? null : row.dataset.source;
  else { state.sourceId = null; state.filter = row.dataset.filter; }
  emit();
  closeDrawer();
}

export function initSidebar() {
  const bar = $('.sidebar');
  bar.addEventListener('click', async (e) => {
    const scan = e.target.closest('[data-scan]');
    const remove = e.target.closest('[data-remove]');
    const cancel = e.target.closest('[data-cancel]');
    const action = e.target.closest('[data-source-action]');
    try {
      if (action) {
        const a = sourceActions.find((x) => x.id === action.dataset.sourceAction);
        const s = state.sources.find((x) => x.id === action.dataset.sid);
        if (a && s) await a.run(s, ctx);
        return;
      }
      if (scan) {
        await ctx.api(`/sources/${scan.dataset.scan}/scan`, { method: 'POST' });
        toast('Scan queued');
      } else if (remove) {
        const s = state.sources.find((x) => x.id === remove.dataset.remove);
        const ok = await ctx.confirm({
          title: `Remove ${s.label.split('/').pop()}?`,
          body: 'Its designs and local renders are deleted from Sklent. Items already filed in Kist stay.',
          confirm: 'Remove', danger: true,
        });
        if (!ok) return;
        await ctx.api(`/sources/${remove.dataset.remove}`, { method: 'DELETE' });
        if (state.sourceId === remove.dataset.remove) state.sourceId = null;
        toast('Source removed');
      } else if (cancel) {
        await ctx.api(`/jobs/${cancel.dataset.cancel}/cancel`, { method: 'POST' });
        toast('Job cancelled');
      } else {
        const row = e.target.closest('[data-source], [data-filter]');
        if (row) choose(row);
        return;
      }
      await refresh(); schedule();
    } catch (err) { toast(err.message, { bad: true }); }
  });
  bar.addEventListener('keydown', (e) => {
    const row = e.target.closest('[data-source], [data-filter]');
    if (row && e.target === row && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); choose(row); }
  });
  $('#filter-row').addEventListener('click', (e) => {
    const b = e.target.closest('[data-pf]');
    if (!b) return;
    if (b.dataset.pf === 'sources' || b.dataset.pf === 'jobs') { openDrawer(b.dataset.pf); return; }
    state.sourceId = null; state.filter = b.dataset.pf; emit();
  });
  $('#menu-btn').addEventListener('click', () => (document.body.classList.contains('drawer-open') ? closeDrawer() : openDrawer()));
  $('#drawer-close').addEventListener('click', closeDrawer);
  $('#drawer-scrim').addEventListener('click', closeDrawer);
  $$('[data-open=settings]').forEach((b) => b.addEventListener('click', () => closeDrawer()));
}
