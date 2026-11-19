// Render control and render helpers (0.2.1).
// - Settings → Rendering: where this server renders (GPU / Software / Off), the GPU process
//   cap, quiet hours and what happens during them, and the helper fallback. A line under
//   the fields says what the server does right now (GET /api/render-state).
// - Settings → Helpers: every helper with its last contact, SolidCraft version, renderer,
//   current job and done count; "Create helper token" makes a helper-scoped token and shows
//   the .env.helper lines for docker-compose.helper.yml once.
// - The sidebar shows "Quiet hours: helpers only" (or why this server holds renders back)
//   above the jobs; the job log shows "on <helper>"; the title block says where a set was
//   rendered (host and renderer, from report.json). The job log's "on <helper>" is drawn
//   by sidebar.js from the job's `helper`.

import { api } from '../api.js';
import { registerTitleBlockField } from '../detail.js';
import { registerSettingsGroup } from '../settings.js';
import { registerSidebarSection } from '../sidebar.js';
import { emit, onChange } from '../store.js';

const DEVICE = [
  { value: 'gpu', label: 'GPU' },
  { value: 'software', label: 'Software (CPU)' },
  { value: 'off', label: 'Off: helpers only' },
];

// ---------- what the server does now (polled with the app's own poll) ----------

let renderState = null;
let asked = 0;
onChange(async (state) => {
  if (!state.status || Date.now() - asked < 10000) return;
  asked = Date.now();
  try {
    renderState = await api('/render-state');
    emit();
  } catch { /* a viewer without access, or offline: no notice */ }
});

function stateLine(s) {
  if (!s) return '';
  if (s.reason) return s.reason;
  const dev = s.renderer === 'software' ? 'software (CPU)' : 'the GPU';
  return `Renders here on ${dev}, up to ${s.processes} process${s.processes === 1 ? '' : 'es'} at once`;
}

registerSidebarSection({
  id: 'render-state', title: '', order: 19, render(el, ctx) {
    const reason = renderState && renderState.reason;
    const sec = el.closest('section');
    if (sec) sec.hidden = !reason;
    el.innerHTML = reason ? `<div class="sk-helpers-notice" role="status">${ctx.icon(renderState.quiet ? 'sun-moon' : 'clock', 14)}<span>${ctx.esc(reason)}</span>${
      renderState.helpers_active ? `<span class="sk-helpers-n sk-data">${renderState.helpers_active} helper${renderState.helpers_active === 1 ? '' : 's'}</span>` : ''}</div>` : '';
  },
});

// ---------- title block: where the set was rendered ----------

registerTitleBlockField({
  id: 'rendered-on', label: 'Rendered on', order: 5, wide: true,
  value: (d) => {
    const r = d.report || {};
    if (!r.host && !r.renderer) return null;
    const dev = r.renderer === 'software' ? 'software' : r.renderer === 'gpu' ? 'GPU' : r.renderer;
    return [r.host, dev].filter(Boolean).join(' · ');
  },
});

// ---------- Settings → Rendering ----------

registerSettingsGroup({
  id: 'rendering', title: 'Rendering', order: 50, fields: [
    { name: 'render_device', label: 'Renderer', type: 'select', options: DEVICE, hint: 'where this server renders' },
    { name: 'render_gpu_processes', label: 'GPU processes', type: 'number', min: 1, max: 16, hint: 'at once, in GPU mode' },
    { name: 'render_quiet_hours', label: 'Quiet hours', type: 'text', hint: 'e.g. 22:00-07:00, server time; empty for none' },
    { name: 'render_quiet_mode', label: 'In quiet hours', type: 'select', options: [
      { value: 'wait', label: 'Wait: helpers only' }, { value: 'software', label: 'Render in software' }] },
    { name: 'helpers_fallback_minutes', label: 'Helper fallback', type: 'number', unit: 'min', min: 0, max: 10080,
      hint: 'with a helper around, render here after; 0 never' },
  ],
  render: async (el, ctx) => {
    el.innerHTML = '<p class="sk-helpers-now" data-render-now></p>';
    try {
      const s = await ctx.api('/render-state');
      el.querySelector('[data-render-now]').textContent = `Now: ${stateLine(s)}.`;
    } catch (err) { el.querySelector('[data-render-now]').textContent = err.message; }
  },
});

// ---------- Settings → Helpers ----------

const pad = (n) => String(n).padStart(2, '0');
function ago(t) {
  if (!t) return 'never';
  const s = Math.max(0, (Date.now() - new Date(t).getTime()) / 1000);
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  const d = new Date(t);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function envSnippet(url, name, token) {
  return [
    '# .env.helper beside docker-compose.helper.yml on the helper machine, then:',
    '#   docker compose -f docker-compose.helper.yml up -d',
    `SK_HELPER_URL=${url}`,
    `SK_HELPER_NAME=${name}`,
    `SK_HELPER_TOKEN=${token}`,
    'SK_RENDERER=gpu',
    'SK_RENDER_PROCESSES=2',
    'SK_RENDER_GID=992',
  ].join('\n');
}

async function drawHelpers(el, ctx, fresh = null) {
  const { esc } = ctx;
  let list = [];
  let base = location.origin;
  try {
    [list] = await Promise.all([ctx.api('/helpers')]);
    const s = await ctx.api('/settings');
    if (s.inputs_public_url) base = s.inputs_public_url;
  } catch (err) { el.innerHTML = `<p class="sk-helpers-note">${esc(err.message)}</p>`; return; }
  const row = (h) => {
    const facts = [
      `seen ${ago(h.last_seen)}`,
      h.version ? `SolidCraft ${h.version}` : null,
      h.renderer ? `${h.renderer === 'software' ? 'software' : 'GPU'}${h.gpu ? ` (${h.gpu})` : ''}` : null,
      h.mem_gb ? `${h.mem_gb} GB` : null,
      `${h.jobs_done} done${h.jobs_failed ? `, ${h.jobs_failed} failed` : ''}`,
    ].filter(Boolean).join(' · ');
    const cur = h.current ? `rendering ${(h.current.path || '').split('/').pop()} ${Math.round((h.current.progress || 0) * 100)}%` : '';
    const trouble = h.refused || h.last_error;
    return `<div class="sk-row sk-helpers-row${h.active ? '' : ' idle'}" data-helper="${esc(h.name)}">
      <span class="lab">${esc(h.name)}<span class="h">${esc(facts)}</span>${trouble ? `<span class="h sk-helpers-trouble">${esc(trouble)}</span>` : ''}</span>
      <span class="sk-val"><span class="sk-helpers-chip${h.active ? ' on' : ''}">${h.active ? (cur ? esc(cur) : 'ready') : 'away'}</span></span>
    </div>`;
  };
  el.innerHTML = `
    <p class="sk-helpers-note">A helper is another machine with SolidCraft that renders for this server: it takes every render
      (scans and filing stay here). Its token can only claim and report render jobs.</p>
    ${fresh ? `<div class="sk-helpers-fresh" role="status"><span class="lab">For ${esc(fresh.name)}, shown once: put these lines in <span class="sk-data">.env.helper</span> on the helper.</span>
      <textarea readonly rows="8" class="sk-data" aria-label="Helper settings for ${esc(fresh.name)}">${esc(envSnippet(base, fresh.name, fresh.token))}</textarea>
      <button type="button" data-helper-copy>Copy</button></div>` : ''}
    <div class="sk-row"><span class="lab">New helper<span class="h">its name in this list, e.g. the machine’s</span></span>
      <span class="sk-val"><input type="text" data-helper-name placeholder="Name" aria-label="Helper name" maxlength="64" />
      <button type="button" data-helper-make>Create helper token</button></span></div>
    ${list.length ? list.map(row).join('') : '<div class="sk-row"><span class="lab sk-helpers-dim">No helper has asked for work yet.</span></div>'}`;
  const name = el.querySelector('[data-helper-name]');
  const make = async () => {
    const n = name.value.trim();
    if (!n || /[/\\]/.test(n)) { name.focus(); return; }
    try {
      const t = await ctx.api('/tokens', { method: 'POST', body: { name: n, scope: 'helper' } });
      await drawHelpers(el, ctx, { name: n, token: t.token });
    } catch (err) { ctx.toast(err.message, { bad: true }); }
  };
  el.querySelector('[data-helper-make]').addEventListener('click', make);
  name.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); make(); } });
  el.querySelector('[data-helper-copy]')?.addEventListener('click', async (e) => {
    const t = el.querySelector('.sk-helpers-fresh textarea');
    t.select();
    try { await navigator.clipboard.writeText(t.value); } catch { document.execCommand('copy'); }
    e.target.textContent = 'Copied';
  });
}

registerSettingsGroup({ id: 'helpers', title: 'Helpers', order: 60, fields: [], render: (el, ctx) => drawHelpers(el, ctx) });
