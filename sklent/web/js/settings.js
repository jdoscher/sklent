// Render settings as a spec sheet (U2-8 = UI 14): grouped rows, mono values with
// their units, and the live cost of a change (`240 frames a view · 960 a set`).
//
// Seam: registerSettingsGroup({ id, title, order, fields: [{ name, label, type, unit,
// min, max, step, options, hint }], render? }). render(container, ctx), when given, draws
// extra rows the group manages itself (they are not sent with Save). type is number (default) | select | checkbox |
// text; options are values or { value, label }. Fields load from GET /api/settings
// by name and are sent with the built-in ones in the same PUT /api/settings, so a
// group's keys must be ones the server accepts (add them server-side first).

import { api } from './api.js';
import { ctx } from './ctx.js';
import { $, $$, esc } from './dom.js';
import { state } from './store.js';
import { toast } from './toast.js';

const groups = [];

export function registerSettingsGroup(group) {
  if (!group || !group.id || !Array.isArray(group.fields)) throw new Error('registerSettingsGroup needs an id and fields');
  const i = groups.findIndex((g) => g.id === group.id);
  if (i >= 0) groups.splice(i, 1);
  groups.push({ order: 100, title: group.id, ...group });
  groups.sort((a, b) => a.order - b.order);
}

// the built-in groups, in the same registry (their keys are RenderOptions')
registerSettingsGroup({ id: 'palette', title: 'Palette', order: 0, fields: [], custom: 'palette' });
registerSettingsGroup({
  id: 'turntable', title: 'Turntable', order: 10, fields: [
    { name: 'seconds', label: 'Length', type: 'number', unit: 's', min: 2, max: 30, step: 0.5 },
    { name: 'fps', label: 'Frame rate', type: 'select', unit: 'fps', options: [24, 25, 30, 60] },
    { name: 'pitch_deg', label: 'Camera pitch', type: 'number', unit: '°', min: 0, max: 80, hint: 'above the horizon' },
  ],
});
registerSettingsGroup({
  id: 'stills', title: 'Stills', order: 20, fields: [
    { name: 'social_size', label: 'Social still', type: 'number', unit: 'px', min: 256, max: 8192, hint: 'square' },
    { name: 'hires', label: 'High-res still', type: 'pair', unit: 'px', pair: ['hires_width', 'hires_height'], min: 256, max: 8192 },
  ],
});
registerSettingsGroup({
  id: 'gif', title: 'GIF', order: 30, fields: [
    { name: 'gif_width', label: 'GIF width', type: 'number', unit: 'px', min: 160, max: 1280 },
    { name: 'gif_fps', label: 'GIF frame rate', type: 'number', unit: 'fps', min: 5, max: 30 },
  ],
});
registerSettingsGroup({ id: 'output', title: 'Output', order: 40, fields: [], custom: 'styles' });

const optValue = (o) => (o && typeof o === 'object' ? o.value : o);
const optLabel = (o) => (o && typeof o === 'object' ? o.label ?? o.value : o);

function inputHtml(f, v) {
  const lim = `${f.min != null ? ` min="${f.min}"` : ''}${f.max != null ? ` max="${f.max}"` : ''}${f.step != null ? ` step="${f.step}"` : ''}`;
  switch (f.type) {
    case 'select':
      return `<select name="${esc(f.name)}" aria-label="${esc(f.label)}">${(f.options || []).map((o, i) => `<option value="${i}" ${String(optValue(o)) === String(v) ? 'selected' : ''}>${esc(optLabel(o))}</option>`).join('')}</select>`;
    case 'checkbox':
      return `<input type="checkbox" name="${esc(f.name)}" aria-label="${esc(f.label)}" ${v ? 'checked' : ''} />`;
    case 'text':
      return `<input type="text" name="${esc(f.name)}" aria-label="${esc(f.label)}" value="${esc(v ?? '')}" />`;
    case 'pair':
      return `<input type="number" name="${esc(f.pair[0])}" aria-label="${esc(f.label)} width"${lim} value="${esc(v?.[0] ?? '')}" required /><span class="x">×</span><input type="number" name="${esc(f.pair[1])}" aria-label="${esc(f.label)} height"${lim} value="${esc(v?.[1] ?? '')}" required />`;
    default:
      return `<input type="number" name="${esc(f.name)}" aria-label="${esc(f.label)}"${lim} value="${esc(v ?? '')}" inputmode="decimal" required />`;
  }
}

function rowHtml(f, s) {
  const v = f.type === 'pair' ? f.pair.map((k) => s[k]) : s[f.name];
  return `<div class="sk-row" data-field="${esc(f.name)}">
    <span class="lab">${esc(f.label)}${f.hint || f.name === 'seconds' ? `<span class="h">${esc(f.hint || '')}</span>` : ''}</span>
    <span class="sk-val">${inputHtml(f, v)}${f.unit ? `<span class="u">${esc(f.unit)}</span>` : ''}</span>
  </div>`;
}

function paletteHtml(s) {
  return `<fieldset class="sk-pal" id="palettes"><legend class="visually-hidden">Part colour</legend>${state.status.palettes.map((p) => `
    <label><input type="radio" name="palette" value="${esc(p.name)}" ${p.name === s.palette ? 'checked' : ''} />
      <span class="swatch" style="background:${esc(p.shaded)}"></span>${esc(p.label)}<span class="hex">${esc(p.shaded.toLowerCase())}</span></label>`).join('')}
  </fieldset>`;
}

function stylesHtml(s) {
  return `<div class="sk-row"><span class="lab">Styles</span><span class="sk-val checks">
    <label><input type="checkbox" name="style" value="shaded" ${s.styles.includes('shaded') ? 'checked' : ''} /> Shaded</label>
    <label><input type="checkbox" name="style" value="wireframe" ${s.styles.includes('wireframe') ? 'checked' : ''} /> Wireframe (x-ray)</label>
  </span></div>`;
}

function updateTotals() {
  const form = $('#settings-form');
  const n = Math.round(Number(form.elements.seconds?.value || 0) * Number(fieldValue(form, findField('fps')) || 0));
  const styles = $$('input[name=style]:checked', form).length;
  const per = Number.isFinite(n) ? n : 0;
  $('#settings-sum').textContent = `${per} frames a view · ${per * 2 * styles} a set`;
  const h = $('[data-field=seconds] .h', form);
  if (h) h.textContent = `${per} frames a view`;
}

function findField(name) {
  for (const g of groups) for (const f of g.fields) if (f.name === name) return f;
  return null;
}

function fieldValue(form, f) {
  if (!f) return undefined;
  const el = form.elements[f.name];
  if (f.type === 'select') return el ? optValue(f.options[Number(el.value)]) : undefined;
  if (f.type === 'checkbox') return el ? el.checked : undefined;
  if (f.type === 'text') return el ? el.value : undefined;
  return el && el.value !== '' ? Number(el.value) : undefined;
}

export async function openSettings() {
  const s = await api('/settings');
  $('#settings-body').innerHTML = groups.map((g) => `<div class="sk-grp">${esc(g.title)}</div>${
    g.custom === 'palette' ? paletteHtml(s) : g.custom === 'styles' ? stylesHtml(s) : g.fields.map((f) => rowHtml(f, s)).join('')}${
    g.render ? `<div class="sk-grp-body" data-group="${esc(g.id)}"></div>` : ''}`).join('');
  // a group may also draw its own rows (render(container, ctx)), e.g. a list it manages itself
  for (const g of groups) {
    if (!g.render) continue;
    try { g.render($(`#settings-body [data-group="${CSS.escape(g.id)}"]`), ctx); } catch (err) { console.error(`settings group ${g.id}`, err); }
  }
  $('#settings-error').textContent = '';
  $('#settings').hidden = false;
  updateTotals();
  ($('#settings-form input[name=palette]:checked') || $('#settings-form input')).focus({ preventScroll: true });
}

export function closeSettings() {
  if ($('#settings').hidden) return false;
  $('#settings').hidden = true;
  $('#open-settings').focus({ preventScroll: true });
  return true;
}

export function initSettings() {
  $$('#open-settings, [data-open=settings]').forEach((b) => b.addEventListener('click', () => openSettings().catch((err) => toast(err.message, { bad: true }))));
  $('#settings').addEventListener('click', (e) => {
    if (e.target === e.currentTarget || e.target.closest('[data-close]')) closeSettings();
  });
  $('#settings-form').addEventListener('input', updateTotals);
  $('#settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const body = {
      palette: $('input[name=palette]:checked', form)?.value,
      styles: $$('input[name=style]:checked', form).map((c) => c.value),
    };
    for (const g of groups) {
      for (const f of g.fields) {
        if (f.type === 'pair') f.pair.forEach((k) => { body[k] = Number(form.elements[k].value); });
        else { const v = fieldValue(form, f); if (v !== undefined) body[f.name] = v; }
      }
    }
    try {
      await api('/settings', { method: 'PUT', body });
      closeSettings();
      toast('Settings saved; they apply to the next renders');
    } catch (err) { $('#settings-error').textContent = err.message; }
  });
}
