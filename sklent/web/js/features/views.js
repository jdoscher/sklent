// Views and render modes (Sklent 0.2, area V): the quick-check still, per-render outputs,
// shot presets and masters, exploded / section / configuration / motion / transparent /
// hero / plate views, the "my part" highlight and the bed-fit badge.
//
// Uses only the seams: registerSettingsGroup, registerDetailSection,
// registerTitleBlockField, registerTileBadge, registerTileFigure, api.

import { api } from '../api.js';
import { registerDetailSection, registerTitleBlockField } from '../detail.js';
import { VARIANT_LABEL } from '../format.js';
import { registerSettingsGroup } from '../settings.js';
import { registerTileBadge, registerTileFigure } from '../tiles.js';

const CORE = [
  { value: '1080p', label: '1080p' }, { value: 'reel', label: 'Reel' },
  { value: 'discord', label: 'Discord' }, { value: 'gif', label: 'GIF' },
  { value: 'social', label: 'Social still' }, { value: 'hires', label: 'High-res still' },
];
// feature outputs a single render can turn on (settings keys)
const EXTRA = [
  { value: 'views_exploded', label: 'Exploded' },
  { value: 'views_section', label: 'Section' },
  { value: 'views_transparent', label: 'Transparent' },
  { value: 'views_hero', label: 'Studio hero' },
  { value: 'views_plate', label: 'Plate' },
  { value: 'views_shot_half_orbit', label: 'Half orbit' },
  { value: 'views_shot_push_in', label: 'Push-in' },
  { value: 'views_shot_top_to_iso', label: 'Top to iso' },
  { value: 'views_shot_low_angle', label: 'Low angle' },
  { value: 'views_master_4k', label: '4K master' },
];

for (let i = 1; i <= 24; i += 1) VARIANT_LABEL[`config-${i}`] = `Configuration ${i}`;
Object.assign(VARIANT_LABEL, {
  preview: 'Quick check', exploded: 'Exploded', 'explode-anim': 'Explode', section: 'Section',
  'config-lineup': 'Configurations', highlight: 'My part', 'highlight-turntable': 'My part turntable',
  transparent: 'Transparent', hero: 'Studio hero', plate: 'Plate', 'master-4k': '4K master',
  'frames-zip': 'PNG sequence', prores: 'ProRes master', 'preset-half-orbit': 'Half orbit',
  'preset-push-in': 'Push-in', 'preset-top-to-iso': 'Top to iso', 'preset-low-angle': 'Low angle',
});

// ---------------------------------------------------------------- settings

registerSettingsGroup({
  id: 'views-outputs', title: 'Outputs', order: 45, fields: [
    { name: 'outputs', label: 'Make', type: 'checklist', options: CORE, hint: 'a quick-check still always comes first' },
  ],
});
registerSettingsGroup({
  id: 'views-shots', title: 'Shot presets', order: 50, fields: [
    { name: 'views_shot_half_orbit', label: 'Half orbit', type: 'checkbox', hint: 'eases onto the iso angle' },
    { name: 'views_shot_push_in', label: 'Push-in', type: 'checkbox', hint: 'slow dolly in' },
    { name: 'views_shot_top_to_iso', label: 'Top to iso', type: 'checkbox', hint: 'from straight down' },
    { name: 'views_shot_low_angle', label: 'Low angle', type: 'checkbox', hint: 'a low 60° pass' },
    { name: 'views_shot_seconds', label: 'Shot length', type: 'number', unit: 's', min: 2, max: 12, step: 0.5 },
  ],
});
registerSettingsGroup({
  id: 'views-masters', title: 'Masters', order: 55, fields: [
    { name: 'views_master_4k', label: '4K turntable', type: 'checkbox', hint: '3840 × 2160 H.264' },
    { name: 'views_master_prores', label: 'ProRes 422 HQ', type: 'checkbox', hint: '3840 × 2160 .mov, large' },
    { name: 'views_master_zip', label: 'PNG sequence', type: 'checkbox', hint: '3840 × 2160 frames, zipped, large' },
    { name: 'views_master_seconds', label: 'Master length', type: 'number', unit: 's', min: 0, max: 60, step: 1, hint: '0 = the turntable’s; loops exactly' },
  ],
});
registerSettingsGroup({
  id: 'views-extra', title: 'Extra views', order: 60, fields: [
    { name: 'views_exploded', label: 'Exploded', type: 'checkbox', hint: 'still + animation, 2+ components' },
    { name: 'views_explode_scale', label: 'Explode distance', type: 'number', unit: '×', min: 0.2, max: 3, step: 0.1 },
    { name: 'views_section', label: 'Section cut', type: 'checkbox', hint: 'through the centre, filled caps' },
    { name: 'views_configs', label: 'Configurations', type: 'checkbox', hint: 'a still each + a lineup' },
    { name: 'views_motion', label: 'Motion studies', type: 'checkbox', hint: 'a clip per study' },
    { name: 'views_transparent', label: 'Transparent stills', type: 'checkbox', hint: 'PNG with alpha' },
    { name: 'views_hero', label: 'Studio hero', type: 'checkbox', hint: 'path traced on the CPU: slow' },
    { name: 'views_plate', label: 'Plate view', type: 'checkbox', hint: 'parts laid flat, top-down' },
  ],
});
registerSettingsGroup({
  id: 'views-beds', title: 'Bed fit', order: 65, fields: [
    { name: 'views_bedfit', label: 'Badge on tiles', type: 'checkbox' },
    { name: 'views_bed', label: 'Check against', type: 'text', hint: 'a bed name from the list' },
    { name: 'views_beds', label: 'Beds', type: 'text', hint: 'Name XxYxZ; … in mm' },
  ],
});

// ---------------------------------------------------------------- tiles

registerTileFigure((d) => (d.views && d.views.preview_url) || null);

const mm = (v) => v.map((x) => Math.round(x)).join(' × ');

registerTileBadge((d) => {
  const b = d.views && d.views.bed_fit;
  if (!b || d.status === 'failed') return null;
  const largest = `largest part ${b.largest.name} ${mm(b.largest.size)} mm`;
  if (b.fits) {
    return { text: `fits ${b.label}`, title: `Fits the ${b.bed} (${b.label} mm): ${largest}. Fits: ${b.fits_beds.join(', ') || 'none'}` };
  }
  return { text: `> ${b.label}`, title: `${b.too_big.length} of ${b.parts} parts too big for the ${b.bed} (${b.label} mm): ${b.too_big.join(', ')}. ${b.fits_beds.length ? `Fits: ${b.fits_beds.join(', ')}` : 'Fits none of the beds'}` };
});

registerTitleBlockField({
  id: 'bed-fit', label: 'Bed fit', order: 40, wide: true,
  value: (d) => {
    const b = d.views && d.views.bed_fit;
    if (!b) return null;
    return `${b.fits ? 'fits' : 'too big for'} ${b.bed} ${b.label} · ${b.parts} ${b.parts === 1 ? 'part' : 'parts'}`;
  },
});

// ---------------------------------------------------------------- detail sheet

let settingsCache = null;
async function settings() {
  if (!settingsCache) settingsCache = api('/settings').catch((err) => { settingsCache = null; throw err; });
  return settingsCache;
}
document.addEventListener('submit', (e) => { if (e.target && e.target.id === 'settings-form') settingsCache = null; }, true);

const infoCache = new Map();
async function viewsInfo(id, fresh = false) {
  if (fresh || !infoCache.has(id)) infoCache.set(id, api(`/designs/${id}/views`).catch((err) => { infoCache.delete(id); throw err; }));
  return infoCache.get(id);
}

// The quick-check still while a render of this design runs (F17).
registerDetailSection({
  id: 'views-quick', title: 'Quick check', order: 5,
  when: (d) => !!(d.views && d.views.preview_url && (d.status === 'rendering' || d.status === 'queued')),
  render(el, d, ctx) {
    el.innerHTML = `<figure class="sk-views-quick"><img src="${ctx.esc(d.views.preview_url)}" alt="${ctx.esc(`${d.name}: quick check`)}" />
      <figcaption class="sk-data">shaded · iso · 1024 × 1024 · the rest is rendering</figcaption></figure>`;
  },
});

function checks(name, opts, on) {
  return opts.map((o) => `<label><input type="checkbox" name="${name}" value="${o.value}" ${on(o.value) ? 'checked' : ''} /> ${o.label}</label>`).join('');
}

// One compact section (the side column is shared): Quick check, and behind "Outputs and
// views…" this render's outputs and extra views (F17) and the design's "my part" (F20).
function highlightHtml(d, v, ctx) {
  const names = v.highlight.names || [];
  const from = v.highlight.source === '.sklent.yaml' ? ' (now from .sklent.yaml)' : '';
  const list = `sk-views-bodies-${d.id}`;
  return `<div class="sk-views-hl">
    <span class="sk-views-sub">My part</span>
    <input type="text" name="names" list="${ctx.esc(list)}" value="${ctx.esc(names.join(', '))}" placeholder="body names or globs, e.g. Arm*" aria-label="Bodies to highlight" />
    <datalist id="${ctx.esc(list)}">${(v.bodies || []).slice(0, 300).map((b) => `<option value="${ctx.esc(b)}"></option>`).join('')}</datalist>
    <button type="button" data-views-hl>Save</button>
    <p class="sk-views-dim sk-views-hint">Solid, the rest x-ray: a still and a turntable from the next render${ctx.esc(from)}.</p>
  </div>`;
}

registerDetailSection({
  id: 'views-render', title: 'Render', order: 20,
  render(el, d, ctx) {
    const token = `${d.id}:${Date.now()}`;
    el.dataset.token = token;
    const busy = !!ctx.activeJobFor(d.id);
    el.innerHTML = `<form class="sk-views-form">
      <div class="sk-views-actions">
        <button type="button" data-views-quick ${busy ? 'disabled' : ''} title="One shaded iso still, in seconds. It replaces this commit's set.">Quick check</button>
        <button type="button" data-views-more aria-expanded="false" aria-controls="sk-views-pick-${ctx.esc(d.id)}">Outputs and views…</button>
      </div>
      <div class="sk-views-pick" id="sk-views-pick-${ctx.esc(d.id)}" hidden><p class="sk-data sk-views-dim">loading…</p></div>
    </form>`;
    const form = el.querySelector('form');
    const pick = el.querySelector('.sk-views-pick');
    const more = el.querySelector('[data-views-more]');
    const send = async (body, msg) => {
      try {
        await ctx.api(`/designs/${d.id}/views/render`, { method: 'POST', body });
        ctx.toast(msg);
        await ctx.refresh(); ctx.schedule();
      } catch (err) { ctx.toast(err.message, { bad: true }); }
    };
    el.querySelector('[data-views-quick]').addEventListener('click', () => send({ preview_only: true }, 'Quick check queued'));
    let loaded = false;
    more.addEventListener('click', () => {
      pick.hidden = !pick.hidden;
      more.setAttribute('aria-expanded', String(!pick.hidden));
      if (loaded || pick.hidden) return;
      loaded = true;
      Promise.all([settings(), viewsInfo(d.id)]).then(([s, v]) => {
        if (el.dataset.token !== token) return;
        pick.innerHTML = `
          <div class="sk-views-checks">${checks('out', CORE, (x) => (s.outputs || []).includes(x))}</div>
          <div class="sk-views-checks sk-views-extra">${checks('extra', EXTRA, (k) => !!s[k])}</div>
          <div class="sk-views-actions"><button type="submit" ${busy ? 'disabled' : ''}>Render these</button>
            <span class="sk-views-dim sk-views-hint">this render only; Settings hold the defaults</span></div>
          ${highlightHtml(d, v, ctx)}`;
        pick.querySelector('[data-views-hl]').addEventListener('click', async () => {
          const raw = form.elements.names.value;
          try {
            const r = await ctx.api(`/designs/${d.id}/views/highlight`, { method: 'PUT', body: { names: raw.split(',').map((x) => x.trim()).filter(Boolean) } });
            infoCache.delete(d.id);
            ctx.toast(r.names.length ? `My part saved (${r.names.length}); re-render to see it` : 'My part cleared');
          } catch (err) { ctx.toast(err.message, { bad: true }); }
        });
      }).catch((err) => { pick.innerHTML = `<p class="sk-views-dim">${ctx.esc(err.message)}</p>`; loaded = false; });
    });
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const outputs = [...form.querySelectorAll('input[name=out]:checked')].map((c) => c.value);
      const extra = Object.fromEntries(EXTRA.map((o) => [o.value, !!form.querySelector(`input[name=extra][value="${o.value}"]`)?.checked]));
      send({ outputs, settings: extra }, outputs.length ? `Render queued: ${outputs.length} outputs` : 'Quick check queued');
    });
  },
});

// What the last render's views did, and why any were skipped ("report why"): a sheet.
const NOTE_LABEL = { exploded: 'Exploded', section: 'Section', motion: 'Motion studies', configs: 'Configurations', transparent: 'Transparent', hero: 'Studio hero', plate: 'Plate' };
registerDetailSection({
  id: 'views-report', title: 'Views report', order: 90, sheet: true, group: 'Views',
  when: (d) => d.status === 'rendered',
  render(el, d, ctx) {
    el.innerHTML = '<div class="sk-views-report"><p class="sk-data sk-views-dim">loading…</p></div>';
    viewsInfo(d.id, true).then((v) => {
      const notes = v.notes || {};
      const rows = Object.entries(notes).map(([k, n]) => {
        const what = n.skipped ? `skipped: ${n.skipped}` : [n.plane, n.method, n.source, n.rows && `${n.rows.length} configurations`,
          n.studies && `${n.studies.length} studies`, n.s != null && `${n.s} s`, n.cells && `${n.cells} parts`].filter(Boolean).join(' · ') || 'made';
        return `<div class="sk-views-note"><span>${ctx.esc(NOTE_LABEL[k] || k)}</span><span class="sk-data">${ctx.esc(what)}</span></div>`;
      });
      const f = v.facts || {};
      const fit = v.bed_fit;
      const facts = [
        `${(f.configurations || []).length} configurations`, `${(f.motion_studies || []).length} motion studies`,
        `${f.explode_views || 0} saved exploded views`,
      ];
      el.firstChild.innerHTML = `<h3 class="sk-views-h">Views report</h3>
        ${rows.join('') || '<p class="sk-views-dim">No extra views on the last render. Turn them on in Settings or under Outputs and views.</p>'}
        <p class="sk-views-dim sk-data">${ctx.esc(facts.join(' · '))}</p>
        ${fit ? `<div class="sk-views-note"><span>Bed fit</span><span class="sk-data">${ctx.esc(`${fit.fits ? 'fits' : 'too big for'} ${fit.bed} (${fit.label}) · largest ${fit.largest.name} ${mm(fit.largest.size)} mm · fits: ${fit.fits_beds.join(', ') || 'none'}`)}</span></div>` : ''}`;
    }).catch((err) => { el.firstChild.innerHTML = `<p class="sk-views-dim">${ctx.esc(err.message)}</p>`; });
  },
});
