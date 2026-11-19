// Inputs and access, F3 / F14 / F25 / F12: what a design came from.
// - Tile badges: the input format (STEP, STL, 3MF), linked files (ASM n), the ref
//   (PR #n, a branch or tag), and "after due" for a class-set snapshot.
// - Title block: Ref, Inputs, Config (.sklent.yaml @ commit), Due.
// - Detail section "Inputs": linked files, notes, the repo config that applied.
// - Detail section "Review": the review comment to copy, and Post (only when the server
//   allows posting; it says where it posts).
// - Settings: which inputs a scan finds; review links and posting.

import { registerDetailSection, registerTitleBlockField } from '../detail.js';
import { registerSettingsGroup } from '../settings.js';
import { registerTileBadge } from '../tiles.js';

const FORMAT = { step: 'STEP', stl: 'STL', '3mf': '3MF' };
const short = (s) => (s || '').slice(0, 7);
const pad = (n) => String(n).padStart(2, '0');
const dueText = (t) => {
  if (!t) return '';
  const d = new Date(t);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

registerTileBadge((d) => (FORMAT[d.format] ? { text: FORMAT[d.format], title: `Imported from a ${FORMAT[d.format]} file` } : null));
registerTileBadge((d) => {
  const n = d.inputs?.links?.length;
  return n ? { text: `ASM ${n}`, title: `An assembly: ${n} linked file${n === 1 ? '' : 's'} fetched with it` } : null;
});
registerTileBadge((d) => {
  const r = d.ref_info;
  if (!r) return null;
  return r.kind === 'pull' ? { text: r.label, title: r.title ? `${r.label}: ${r.title}` : r.label } : { text: r.label, title: `Rendered from ${r.label}` };
});
registerTileBadge((d) => (d.due?.after_due ? { text: 'after due', title: 'Pushed again after the deadline; this is what was there at the deadline' } : null));

registerTitleBlockField({
  id: 'inputs-ref', label: 'Ref', order: 10, wide: true,
  value: (d) => (d.ref_info ? (d.ref_info.kind === 'pull' ? `${d.ref_info.label}${d.ref_info.title ? ` · ${d.ref_info.title}` : ''}` : d.ref_info.label) : null),
});
registerTitleBlockField({
  id: 'inputs-due', label: 'Due', order: 11, wide: true,
  value: (d) => (d.due ? `${dueText(d.due.deadline)}${d.due.committed_at ? ` · committed ${dueText(d.due.committed_at)}` : ''}` : null),
});
registerTitleBlockField({
  id: 'inputs-format', label: 'Input', order: 12,
  value: (d) => (FORMAT[d.format] ? `${FORMAT[d.format]}${d.format === 'stl' || d.format === '3mf' ? ' mesh' : ''}` : d.inputs?.links?.length ? `${d.inputs.links.length} linked` : null),
});
registerTitleBlockField({
  id: 'inputs-config', label: 'Config', order: 13,
  value: (d) => (d.config?.from?.length ? `${d.config.from[d.config.from.length - 1].path.split('/').pop()} @ ${short(d.config.commit)}` : null),
});

registerDetailSection({
  id: 'inputs', title: 'Inputs', order: 40,
  when: (d) => !!(d.inputs || d.config || FORMAT[d.format]),
  render(el, d, ctx) {
    const { esc } = ctx;
    const rows = [];
    if (FORMAT[d.format]) rows.push(['Format', `${FORMAT[d.format]}${d.format === 'stl' || d.format === '3mf' ? ' (a mesh: no volume or B-rep edges)' : ''}`]);
    for (const l of d.inputs?.links || []) rows.push(['Linked', `${l.path}${l.missing ? ' · not found, saved copy used' : ` · ${short(l.blob)}`}`]);
    for (const n of d.inputs?.notes || []) rows.push(['Note', n]);
    if (d.config) {
      for (const f of d.config.from || []) rows.push(['Config', `${f.path} @ ${short(d.config.commit)}`]);
      const s = Object.entries(d.config.settings || {}).map(([k, v]) => `${k} ${Array.isArray(v) ? v.join('+') : v}`).join(' · ');
      if (s) rows.push(['Overrides', s]);
      for (const k of ['title', 'licence', 'material', 'bom']) if (d.config[k]) rows.push([k[0].toUpperCase() + k.slice(1), d.config[k]]);
      for (const e of d.config.errors || []) rows.push(['Problem', e]);
    }
    el.innerHTML = `<dl class="sk-inputs-dl">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd class="sk-data">${esc(v)}</dd>`).join('')}</dl>`;
  },
});

function copyText(text, btn) {
  const done = () => { btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = 'Copy review comment'; }, 2000); };
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done);
  const ta = document.createElement('textarea');
  ta.value = text; ta.setAttribute('readonly', ''); ta.className = 'sk-inputs-offscreen';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); done(); } finally { ta.remove(); }
  return Promise.resolve();
}

registerDetailSection({
  id: 'inputs-review', title: 'Review comment', order: 41,
  when: (d) => !!d.ref_info && d.status === 'rendered',
  async render(el, d, ctx) {
    const { esc } = ctx;
    el.innerHTML = '<p class="sk-inputs-dim">Building…</p>';
    let r;
    try { r = await ctx.api(`/sources/${d.source_id}/review-comment`); } catch (err) { el.innerHTML = `<p class="sk-inputs-dim">${esc(err.message)}</p>`; return; }
    const pull = d.ref_info.kind === 'pull';
    el.innerHTML = `
      <p class="sk-inputs-note">Markdown for the ${pull ? 'pull request' : 'review'} thread: ${r.rendered} rendered design${r.rendered === 1 ? '' : 's'}${pull ? ', before and after' : ''}. Images link to this server (<span class="sk-data">${esc(r.base_url)}</span>), so readers need its token${r.markdown.includes('full set') ? '; the Kist share links work without it' : ''}.</p>
      <textarea class="sk-inputs-md sk-data" readonly rows="6" aria-label="Review comment Markdown">${esc(r.markdown)}</textarea>
      <div class="sk-inputs-actions">
        <button type="button" data-review-copy>Copy review comment</button>
        ${pull && r.post_enabled ? `<button type="button" class="sk-inputs-write" data-review-post>Post to PR #${d.ref_info.number}</button>` : ''}
      </div>
      ${pull ? `<p class="sk-inputs-note">${r.post_enabled
    ? `Post sends this Markdown as one comment on ${esc(d.ref_info.url || `PR #${d.ref_info.number}`)} with the server’s ${esc(d.repo.split('/')[0])} forge token.`
    : 'Posting to the forge is off (Settings → Review). Copy it and paste it yourself.'}</p>` : ''}`;
    el.querySelector('[data-review-copy]').addEventListener('click', (e) => copyText(r.markdown, e.currentTarget));
    el.querySelector('[data-review-post]')?.addEventListener('click', async () => {
      const ok = await ctx.confirm({ title: `Post to PR #${d.ref_info.number}?`, body: `One comment with these renders goes to ${d.ref_info.url || d.repo}, as the server’s forge token.`, confirm: 'Post' });
      if (!ok) return;
      try { const p = await ctx.api(`/sources/${d.source_id}/review-comment`, { method: 'POST' }); ctx.toast('Comment posted', p.url ? { action: { label: 'Open', run: () => window.open(p.url, '_blank', 'noopener') } } : {}); }
      catch (err) { ctx.toast(err.message, { bad: true }); }
    });
  },
});

registerSettingsGroup({
  id: 'inputs-formats', title: 'Inputs', order: 60, fields: [
    { name: 'inputs_step', label: 'STEP files', type: 'checkbox', hint: '.step, .stp: opened as B-rep' },
    { name: 'inputs_mesh', label: 'STL and 3MF meshes', type: 'checkbox', hint: 'exports next to a .sc design are skipped' },
  ],
});
registerSettingsGroup({
  id: 'inputs-review', title: 'Review', order: 61, fields: [
    { name: 'inputs_public_url', label: 'Server URL for links', type: 'text', hint: 'in review comments; empty: this page’s address' },
    { name: 'inputs_review_post', label: 'Post to the forge', type: 'checkbox', hint: 'off: copy only. On: a Post button comments on the PR with the server’s GitHub/Forgejo token' },
  ],
});
