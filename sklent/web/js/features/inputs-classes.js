// Inputs and access, F28: class sets and due-date snapshots.
// Sidebar section "Class sets": each class (an account + repo-name prefix, a deadline,
// a roster) with "n/m submitted" and who has no submission; choosing it narrows the
// grid to its designs. "Add class set" (admins only) makes one.

import { registerSidebarSection } from '../sidebar.js';

let classes = [];
let fetchedAt = 0;
let sourcesKey = '';
let busy = false;
const open = new Set();
let adding = false;

const pad = (n) => String(n).padStart(2, '0');
// the deadline in this browser's time zone: the one the class works in
const due = (t) => {
  if (!t) return 'no deadline';
  const d = new Date(t);
  return `due ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const STATUS = { submitted: 'in', empty: 'no design', late: 'nothing by due', missing: 'no repo' };

async function load(ctx, el) {
  if (busy) return;
  busy = true;
  try { classes = await ctx.api('/classes'); fetchedAt = Date.now(); if (!adding) draw(el, ctx); }
  catch { /* shown on the next poll */ } finally { busy = false; }
}

function formHtml() {
  return `<form class="sk-inputs-form" data-class-form>
    <label>Account or org URL<input name="url" required placeholder="https://github.com/your-school" class="sk-data" /></label>
    <label>Repo prefix<input name="prefix" placeholder="bracket-hw-" class="sk-data" /></label>
    <label>Deadline<input name="deadline" type="datetime-local" /></label>
    <label>Roster <span class="sk-inputs-dim">one per line: username, Display name</span><textarea name="roster" rows="3" class="sk-data"></textarea></label>
    <label>Title<input name="title" placeholder="Bracket HW · P3" /></label>
    <div class="sk-inputs-actions"><button type="submit" class="primary">Add class set</button><button type="button" data-class-cancel>Cancel</button></div>
  </form>`;
}

function draw(el, ctx) {
  const { esc, state } = ctx;
  el.innerHTML = `${classes.map((c) => `
    <div class="row sk-inputs-classrow ${state.sourceId === c.source_id ? 'active' : ''}" data-class="${esc(c.source_id)}" role="button" tabindex="0" title="${esc(c.missing.length ? `No submission: ${c.missing.join(', ')}` : 'Everyone handed in')}">
      ${ctx.icon('folder-git-2')}
      <span class="src"><b><span>${esc(c.title)}</span></b><i class="sk-inputs-due">${esc(due(c.deadline))}</i></span>
      <span class="count">${c.submitted}/${c.expected}</span>
    </div>
    ${open.has(c.source_id) ? `<ul class="sk-inputs-roster">${c.students.map((s) => `<li class="sk-inputs-st-${esc(s.status)}"><span>${esc(s.display)}</span><span class="sk-data">${esc(STATUS[s.status] || s.status)}${s.after_due ? ' · after due' : ''}</span></li>`).join('')}</ul>` : ''}`).join('')}
    ${adding ? formHtml() : `<button type="button" class="sk-inputs-add sk-inputs-write" data-class-add>${ctx.icon('plus', 14)} Add class set</button>`}`;

  el.querySelectorAll('[data-class]').forEach((row) => {
    const pick = () => {
      const id = row.dataset.class;
      if (open.has(id) && state.sourceId === id) { open.delete(id); state.sourceId = null; }
      else { open.add(id); state.sourceId = id; }
      ctx.emit();
    };
    row.addEventListener('click', pick);
    row.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
  });
  el.querySelector('[data-class-add]')?.addEventListener('click', () => { adding = true; draw(el, ctx); el.querySelector('input[name=url]').focus(); });
  el.querySelector('[data-class-cancel]')?.addEventListener('click', () => { adding = false; draw(el, ctx); });
  el.querySelector('[data-class-form]')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    const local = f.deadline.value;
    const body = {
      url: f.url.value.trim(), prefix: f.prefix.value.trim() || null, title: f.title.value.trim() || null,
      deadline: local ? new Date(local).toISOString() : null,
      roster: f.roster.value.split('\n').map((x) => x.trim()).filter(Boolean),
    };
    try {
      const r = await ctx.api('/classes', { method: 'POST', body });
      adding = false; open.add(r.source.id); state.sourceId = r.source.id;
      ctx.toast(`Class set added; scanning ${r.source.url.replace(/^https?:\/\//, '')}`);
      await ctx.refresh(); ctx.schedule(); fetchedAt = 0;
    } catch (err) { ctx.toast(err.message, { bad: true }); }
  });
}

registerSidebarSection({
  id: 'inputs-classes', title: 'Class sets', order: 15,
  render(el, ctx) {
    const key = ctx.state.sources.map((s) => `${s.id}:${s.scanned_at}:${s.rendered}`).join(',');
    if (!el.dataset.drawn || key !== sourcesKey || Date.now() - fetchedAt > 30000) {
      sourcesKey = key; el.dataset.drawn = '1';
      load(ctx, el);
    }
    if (!adding) draw(el, ctx);
    el.closest('.section').hidden = !classes.length && !adding && document.body.dataset.skRole === 'viewer';
  },
});
