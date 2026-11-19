// Revisions (F1): every rendered version of a design keeps its set. Two sheets in the
// drawing sheet's schedule, under "Revisions":
//   Compare   — two versions side by side, as a slider, or as a pixel diff (changed
//               pixels in the sheet's ink colour, never a hue), the same still or the
//               same turntable frame, plus the commits in between (from the forge).
//   Filmstrip — one still per version along a hairline timeline, mono commit and date.
// A tile badge counts kept versions, the title block names the version's git tags, and
// a settings group holds the keep policy and the build-history timelapse (F29).

import { registerDetailSection, registerTitleBlockField } from '../detail.js';
import { registerSettingsGroup } from '../settings.js';
import { registerTileBadge } from '../tiles.js';
import { VARIANT_LABEL } from '../format.js';

// schedule labels for the timelapse files (F29); VARIANT_LABEL is the shared lookup
Object.assign(VARIANT_LABEL, { timelapse: 'Timelapse movie', 'timelapse-gif': 'Timelapse GIF' });

const VIEW = { slider: 'Slider', side: 'Side by side', diff: 'Changes' };
const PICK_LABEL = {
  hires: 'High-res still', social: 'Social still', '1080p': '1080p frame', reel: 'Reel frame',
  discord: 'Discord frame', gif: 'GIF frame', timelapse: 'Timelapse frame', 'timelapse-gif': 'Timelapse GIF frame',
};

// per design: the sets list (refetched when the design's data changes) and the view state
const cache = new Map();
const view = new Map();

const kept = (d) => (d.revisions && d.revisions.count) || 0;
const short = (s) => (s.commit || s.blob || s.id || '').slice(0, 7);
const day = (t) => (t ? String(t).slice(0, 10) : '—');

async function setsOf(d, ctx) {
  const key = `${d.id}|${d.rendered_at}|${kept(d)}`;
  const hit = cache.get(d.id);
  if (hit && hit.key === key) return hit.promise;
  const promise = ctx.api(`/designs/${d.id}/sets`);
  cache.set(d.id, { key, promise });
  promise.catch(() => cache.delete(d.id));
  return promise;
}

function stateFor(d, sets) {
  const v = view.get(d.id) || { mode: 'slider', style: 'shaded', variant: 'hires', frame: 0, pos: 50 };
  const ids = sets.map((s) => s.id);
  const current = sets.find((s) => s.current) || sets[0];
  if (!ids.includes(v.b)) v.b = current.id;
  if (!ids.includes(v.a) || v.a === v.b) v.a = (sets[sets.indexOf(sets.find((s) => s.id === v.b)) + 1] || sets.find((s) => s.id !== v.b)).id;
  view.set(d.id, v);
  return v;
}

function setLabel(s) {
  const tags = s.tags.length ? ` · ${s.tags.join(', ')}` : '';
  return `${short(s)} · ${day(s.date || s.rendered_at)}${tags}${s.current ? ' · current' : ''}${s.message ? ` · ${s.message}` : ''}`;
}

function caption(s, ctx) {
  return `<figcaption><span class="sk-data">${ctx.esc(short(s))}</span><span class="sk-data dim">${ctx.esc(day(s.date || s.rendered_at))}</span>${s.tags.map((t) => `<span class="sk-rev-tag sk-data">${ctx.esc(t)}</span>`).join('')}<span class="msg">${ctx.esc(s.message || '')}</span></figcaption>`;
}

// ---------------------------------------------------------------- compare

async function renderCompare(el, d, ctx) {
  el.classList.add('sk-rev');
  el.innerHTML = '<p class="sk-rev-note">Loading versions…</p>';
  let sets;
  try { sets = await setsOf(d, ctx); } catch (err) { el.innerHTML = `<p class="sk-rev-note">${ctx.esc(err.message)}</p>`; return; }
  if (sets.length < 2) { el.innerHTML = '<p class="sk-rev-note">Only one version is kept so far. Compare appears once a newer version renders.</p>'; return; }
  const v = stateFor(d, sets);
  const q = new URLSearchParams({ a: v.a, b: v.b, style: v.style, variant: v.variant });
  let cmp;
  try {
    const video = !['hires', 'social'].includes(v.variant);
    if (video) q.set('frame', String(v.frame));
    cmp = await ctx.api(`/designs/${d.id}/compare?${q}`);
  } catch (err) {
    if (v.variant !== 'hires') { v.variant = 'hires'; v.style = 'shaded'; renderCompare(el, d, ctx); return; }
    el.innerHTML = `<p class="sk-rev-note">${ctx.esc(err.message)}</p>`;
    return;
  }
  const opt = (s, sel) => `<option value="${ctx.esc(s.id)}" ${s.id === sel ? 'selected' : ''}>${ctx.esc(setLabel(s))}</option>`;
  const picks = cmp.choices.map((c) => {
    const k = `${c.style}|${c.variant}`;
    return `<option value="${ctx.esc(k)}" ${c.style === v.style && c.variant === v.variant ? 'selected' : ''}>${ctx.esc(`${PICK_LABEL[c.variant] || c.variant}, ${c.style}`)}</option>`;
  }).join('');
  const frames = cmp.frames || 0;
  const pct = cmp.changed_pct;
  const pctText = pct === 0 ? 'no pixels changed' : `${pct < 0.01 ? '<0.01' : pct.toFixed(pct < 1 ? 2 : 1)} % of pixels changed`;
  el.innerHTML = `
    <div class="sk-rev-bar">
      <label><span class="k">Older</span><select data-rev="a">${sets.map((s) => opt(s, v.a)).join('')}</select></label>
      <label><span class="k">Newer</span><select data-rev="b">${sets.map((s) => opt(s, v.b)).join('')}</select></label>
      <label><span class="k">Picture</span><select data-rev="pick">${picks}</select></label>
      ${frames ? `<label class="fr"><span class="k">Frame <b class="sk-data">${v.frame + 1}/${frames}</b></span><input type="range" data-rev="frame" min="0" max="${frames - 1}" value="${v.frame}" /></label>` : ''}
      <div class="seg" role="group" aria-label="View">${Object.entries(VIEW).map(([m, label]) => `<button type="button" data-rev-mode="${m}" aria-pressed="${v.mode === m}">${label}</button>`).join('')}</div>
    </div>
    <p class="sk-rev-facts"><span class="sk-data">${ctx.esc(pctText)}</span>${cmp.reframed ? '<span class="dim">The envelope changed between these versions, so each still is framed to its own size: part of the difference is framing.</span>' : ''}</p>
    <div class="sk-rev-stage mode-${v.mode}" style="--sk-rev-rw:${Number(cmp.width) || 16};--sk-rev-rh:${Number(cmp.height) || 9}">${stage(cmp, v, ctx)}</div>
    <section class="sk-rev-log" aria-label="Changes between the versions"><div class="lbl">Changelog</div><div class="body"><p class="sk-rev-note">Loading commits…</p></div></section>`;
  wireCompare(el, d, ctx, v, cmp);
  loadLog(el.querySelector('.sk-rev-log .body'), d, cmp, ctx);
}

function stage(cmp, v, ctx) {
  const img = (url, s, cls = '') => `<img class="${cls}" src="${ctx.esc(url)}" alt="${ctx.esc(`version ${short(s)}`)}" draggable="false" />`;
  if (v.mode === 'side') {
    return `<figure>${img(cmp.a_url, cmp.a)}${caption(cmp.a, ctx)}</figure><figure>${img(cmp.b_url, cmp.b)}${caption(cmp.b, ctx)}</figure>`;
  }
  if (v.mode === 'diff') {
    return `<figure><div class="pane">${img(cmp.b_url, cmp.b, 'faded')}<div class="ink" style="--sk-rev-mask:url('${ctx.esc(cmp.diff_url)}')"></div></div>
      <figcaption><span class="sk-data">${ctx.esc(short(cmp.a))} → ${ctx.esc(short(cmp.b))}</span><span class="dim">changed pixels in ink over the newer version</span></figcaption></figure>`;
  }
  return `<figure><div class="pane slider" style="--sk-rev-pos:${v.pos}%">${img(cmp.a_url, cmp.a)}${img(cmp.b_url, cmp.b, 'top')}<i class="handle" aria-hidden="true"></i>
      <input type="range" class="wipe" data-rev="pos" min="0" max="100" value="${v.pos}" aria-label="Wipe between the older and the newer version" /></div>
      <figcaption class="split"><span><span class="sk-data">${ctx.esc(short(cmp.a))}</span> <span class="dim">older, left</span></span><span><span class="dim">newer, right</span> <span class="sk-data">${ctx.esc(short(cmp.b))}</span></span></figcaption></figure>`;
}

function wireCompare(el, d, ctx, v, cmp) {
  const again = () => renderCompare(el, d, ctx);
  el.querySelectorAll('select[data-rev]').forEach((s) => s.addEventListener('change', () => {
    if (s.dataset.rev === 'pick') { [v.style, v.variant] = s.value.split('|'); v.frame = 0; } else v[s.dataset.rev] = s.value;
    if (v.a === v.b) {
      // the same version on both sides: move the other side to its neighbour
      const ids = [...el.querySelectorAll('select[data-rev="a"] option')].map((o) => o.value);
      const keep = s.dataset.rev === 'a' ? 'a' : 'b';
      const other = keep === 'a' ? 'b' : 'a';
      v[other] = ids[ids.indexOf(v[keep]) + (other === 'a' ? 1 : -1)] || ids.find((x) => x !== v[keep]);
    }
    again();
  }));
  const fr = el.querySelector('input[data-rev="frame"]');
  if (fr) {
    fr.addEventListener('input', () => { el.querySelector('.fr b').textContent = `${Number(fr.value) + 1}/${fr.max * 1 + 1}`; });
    fr.addEventListener('change', () => { v.frame = Number(fr.value); again(); });
  }
  const wipe = el.querySelector('input[data-rev="pos"]');
  if (wipe) {
    const pane = wipe.parentElement;
    const set = (pos) => { v.pos = Math.round(Math.min(100, Math.max(0, pos))); wipe.value = String(v.pos); pane.style.setProperty('--sk-rev-pos', `${v.pos}%`); };
    wipe.addEventListener('input', () => set(Number(wipe.value)));
    // drag anywhere on the picture, with a finger or a mouse (the range keeps the keyboard)
    const at = (e) => { const r = pane.getBoundingClientRect(); set(((e.clientX - r.left) / r.width) * 100); };
    let drag = null;
    pane.addEventListener('pointerdown', (e) => {
      drag = e.pointerId; at(e); e.preventDefault();
      try { pane.setPointerCapture(e.pointerId); } catch { /* a synthetic pointer */ }
    });
    pane.addEventListener('pointermove', (e) => { if (drag === e.pointerId) at(e); });
    const stop = () => { drag = null; };
    pane.addEventListener('pointerup', stop);
    pane.addEventListener('pointercancel', stop);
  }
  el.querySelectorAll('[data-rev-mode]').forEach((b) => b.addEventListener('click', () => { v.mode = b.dataset.revMode; again(); }));
}

async function loadLog(body, d, cmp, ctx) {
  let log;
  try { log = await ctx.api(`/designs/${d.id}/changelog?base=${encodeURIComponent(cmp.a.id)}&head=${encodeURIComponent(cmp.b.id)}`); } catch (err) { body.innerHTML = `<p class="sk-rev-note">${ctx.esc(err.message)}</p>`; return; }
  if (!body.isConnected) return;
  if (log.error) { body.innerHTML = `<p class="sk-rev-note">Changelog unavailable: ${ctx.esc(log.error)}</p>`; return; }
  if (!log.commits.length) { body.innerHTML = '<p class="sk-rev-note">No commits changed this file between these versions.</p>'; return; }
  body.innerHTML = `<ol class="sk-rev-commits">${log.commits.map((c) => `<li><span class="sk-data">${ctx.esc((c.sha || '').slice(0, 7))}</span><span class="msg">${ctx.esc((c.message || '').split('\n')[0])}</span><span class="sk-data dim">${ctx.esc(day(c.date))}${c.author ? ` · ${ctx.esc(c.author)}` : ''}</span></li>`).join('')}</ol>
    ${log.complete ? '' : '<p class="sk-rev-note">Older commits not shown: the forge listed only the newest ones, or the older version’s commit isn’t known.</p>'}`;
}

// ---------------------------------------------------------------- filmstrip

async function renderFilmstrip(el, d, ctx) {
  el.classList.add('sk-rev');
  el.innerHTML = '<p class="sk-rev-note">Loading versions…</p>';
  let sets;
  try { sets = await setsOf(d, ctx); } catch (err) { el.innerHTML = `<p class="sk-rev-note">${ctx.esc(err.message)}</p>`; return; }
  const oldestFirst = [...sets].reverse();
  el.innerHTML = `<p class="sk-rev-facts"><span class="sk-data">${ctx.format.plural(sets.length, 'version')} kept</span><span class="dim">oldest on the left; choose one to compare it with the current version</span></p>
    <ol class="sk-rev-strip">${oldestFirst.map((s) => `
      <li class="${s.current ? 'current' : ''}">
        <button type="button" class="frame" data-rev-set="${ctx.esc(s.id)}" data-sheet="section:revisions-compare" ${s.current ? 'disabled' : ''} title="${ctx.esc(s.current ? 'The current version' : `Compare ${short(s)} with the current version`)}">
          ${s.thumb_url ? `<img src="${ctx.esc(s.thumb_url)}" alt="${ctx.esc(`version ${short(s)}`)}" />` : '<span class="none">no still</span>'}
        </button>
        <i class="tick" aria-hidden="true"></i>
        <span class="sk-data">${ctx.esc(short(s))}</span>
        <span class="sk-data dim">${ctx.esc(day(s.date || s.rendered_at))}</span>
        ${s.tags.map((t) => `<span class="sk-rev-tag sk-data">${ctx.esc(t)}</span>`).join('')}
        ${s.current ? '<span class="dim">current</span>' : ''}
        ${s.message ? `<span class="msg" title="${ctx.esc(s.message)}">${ctx.esc(s.message)}</span>` : ''}
      </li>`).join('')}</ol>`;
  el.querySelectorAll('[data-rev-set]').forEach((b) => b.addEventListener('click', () => {
    // the sheet's own handler then opens Compare (data-sheet); choose the pair first
    const cur = sets.find((s) => s.current) || sets[0];
    const v = view.get(d.id) || { mode: 'slider', style: 'shaded', variant: 'hires', frame: 0, pos: 50 };
    view.set(d.id, { ...v, a: b.dataset.revSet, b: cur.id });
  }));
}

// ---------------------------------------------------------------- registrations

registerDetailSection({
  id: 'revisions-compare', title: 'Compare', group: 'Revisions', order: 40, sheet: true,
  when: (d) => kept(d) > 1,
  render: (el, d, ctx) => { renderCompare(el, d, ctx); },
});

registerDetailSection({
  id: 'revisions-filmstrip', title: 'Filmstrip', group: 'Revisions', order: 41, sheet: true,
  when: (d) => kept(d) > 1,
  render: (el, d, ctx) => { renderFilmstrip(el, d, ctx); },
});

registerTitleBlockField({
  id: 'revisions-tags', label: 'Tags', order: 30,
  value: (d) => (d.revisions && d.revisions.tags && d.revisions.tags.length ? d.revisions.tags.join(', ') : null),
});

registerTitleBlockField({
  id: 'revisions-kept', label: 'Versions', order: 31,
  value: (d) => (kept(d) > 1 ? `${kept(d)} kept` : null),
});

registerTileBadge((d) => (kept(d) > 1
  ? { text: `${kept(d)} rev`, title: `${kept(d)} versions kept${d.revisions.tagged ? `, ${d.revisions.tagged} tagged` : ''}` }
  : null));

registerSettingsGroup({
  id: 'revisions', title: 'Revisions', order: 60, fields: [
    { name: 'revisions_keep', label: 'Untagged versions kept', type: 'number', unit: 'sets', min: 0, max: 10000,
      hint: 'on disk, besides every tagged version; 0 keeps all' },
    { name: 'revisions_prune_kist', label: 'Prune Kist too', type: 'checkbox',
      hint: 'off: pruned versions stay in Kist, so links to them keep working' },
    { name: 'revisions_timelapse', label: 'Build-history timelapse', type: 'checkbox',
      hint: 'MP4 and GIF of the part building feature by feature' },
    { name: 'revisions_timelapse_max_features', label: 'Timelapse: most features', type: 'number', min: 2, max: 10000,
      hint: 'skipped above this; every step is a rebuild' },
    { name: 'revisions_timelapse_max_bodies', label: 'Timelapse: most bodies', type: 'number', min: 1, max: 100000,
      hint: 'skipped above this' },
  ],
});
