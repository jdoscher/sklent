// Inputs and access, F18: read-only viewer tokens.
// - Asks the server who this token is (GET /api/whoami) and marks <body data-sk-role>;
//   css/features/inputs.css hides every write control for a viewer (Render, Add source,
//   scan/remove/cancel, settings), and the server refuses them anyway.
// - Settings → Tokens: make a named viewer token (shown once), list them, revoke one.

import { api } from '../api.js';
import { registerSettingsGroup } from '../settings.js';
import { onChange } from '../store.js';

let asked = false;
onChange(async (state) => {
  if (asked || !state.status) return;
  asked = true;
  try {
    const me = await api('/whoami');
    document.body.dataset.skRole = me.role;
    if (me.role === 'viewer') document.body.dataset.skViewer = me.name || '';
  } catch { asked = false; }
});

const pad = (n) => String(n).padStart(2, '0');
function when(t) {
  if (!t) return 'never';
  const d = new Date(t);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function drawTokens(el, ctx, fresh = null) {
  const { esc } = ctx;
  let list = [];
  try { list = await ctx.api('/tokens'); } catch (err) { el.innerHTML = `<p class="sk-inputs-note">${esc(err.message)}</p>`; return; }
  el.innerHTML = `
    <p class="sk-inputs-note">A viewer token can browse, view and download renders. It can’t render, add sources,
      change settings or call MCP tools that change things. Give one to a team or a class instead of the admin token.</p>
    ${fresh ? `<div class="sk-inputs-fresh" role="status"><span class="lab">New token for ${esc(fresh.name)}, shown once:</span>
      <input type="text" readonly value="${esc(fresh.token)}" aria-label="New viewer token" class="sk-data" />
      <button type="button" data-tok-copy>Copy</button></div>` : ''}
    <div class="sk-row"><span class="lab">New viewer token<span class="h">a name you’ll recognise: a team, a class</span></span>
      <span class="sk-val"><input type="text" data-tok-name placeholder="Name" aria-label="Token name" maxlength="80" />
      <button type="button" data-tok-make>Create</button></span></div>
    ${list.length ? list.map((t) => `<div class="sk-row sk-inputs-token${t.revoked_at ? ' revoked' : ''}">
      <span class="lab">${esc(t.name)}<span class="h">${esc(t.hint)} · made ${esc(when(t.created_at))} · used ${esc(when(t.last_used_at))}${t.revoked_at ? ` · revoked ${esc(when(t.revoked_at))}` : ''}</span></span>
      <span class="sk-val">${t.revoked_at ? '<span class="sk-inputs-chip">revoked</span>' : `<button type="button" data-tok-revoke="${esc(t.id)}">Revoke</button>`}</span>
    </div>`).join('') : '<div class="sk-row"><span class="lab sk-inputs-dim">No viewer tokens yet.</span></div>'}`;
  const name = el.querySelector('[data-tok-name]');
  const make = async () => {
    if (!name.value.trim()) { name.focus(); return; }
    try { await drawTokens(el, ctx, await ctx.api('/tokens', { method: 'POST', body: { name: name.value.trim() } })); }
    catch (err) { ctx.toast(err.message, { bad: true }); }
  };
  el.querySelector('[data-tok-make]').addEventListener('click', make);
  // Enter in the name field makes a token instead of saving the settings form
  name.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); make(); } });
  el.querySelector('[data-tok-copy]')?.addEventListener('click', async (e) => {
    const input = el.querySelector('.sk-inputs-fresh input');
    input.select();
    try { await navigator.clipboard.writeText(input.value); } catch { document.execCommand('copy'); }
    e.target.textContent = 'Copied';
  });
  el.querySelectorAll('[data-tok-revoke]').forEach((b) => b.addEventListener('click', async () => {
    const t = list.find((x) => x.id === b.dataset.tokRevoke);
    const ok = await ctx.confirm({ title: `Revoke ${t.name}?`, body: 'Anyone using it loses access at once. This can’t be undone; make a new token instead.', confirm: 'Revoke', danger: true });
    if (!ok) return;
    try { await ctx.api(`/tokens/${t.id}`, { method: 'DELETE' }); await drawTokens(el, ctx); }
    catch (err) { ctx.toast(err.message, { bad: true }); }
  }));
}

registerSettingsGroup({ id: 'inputs-tokens', title: 'Tokens', order: 95, fields: [], render: (el, ctx) => drawTokens(el, ctx) });
