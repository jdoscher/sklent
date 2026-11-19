// Area O: the "Output presets and brand" dialog. Edits the outputs_presets list (saved
// through PUT /api/settings like any setting) and the brand mark, with previews of the
// watermark and the cards as they will be burned into exported copies.

import { api, esc, sendFile } from './outputs-common.js';

const FORMATS = ['jpg', 'png', 'webp', 'pdf', 'mp4', 'gif'];
const ANCHORS = ['center', 'left', 'right'];

function host() {
  let el = document.getElementById('sk-outputs-dialog');
  if (!el) {
    el = document.createElement('div');
    el.id = 'sk-outputs-dialog';
    el.className = 'overlay';
    el.hidden = true;
    document.body.append(el);
  }
  return el;
}

const rowHtml = (p) => `<tr data-row>
  <td><input type="checkbox" name="enabled" ${p.enabled !== false ? 'checked' : ''} aria-label="On" /></td>
  <td><input name="name" value="${esc(p.name || '')}" aria-label="Name" required pattern="[a-z0-9][a-z0-9-]{0,39}" /></td>
  <td><input name="label" value="${esc(p.label || '')}" aria-label="Label" /></td>
  <td><input class="num" name="width" type="number" min="64" max="8192" value="${esc(p.width ?? 1200)}" aria-label="Width" /></td>
  <td><input class="num" name="height" type="number" min="64" max="8192" value="${esc(p.height ?? 900)}" aria-label="Height" /></td>
  <td><select name="format" aria-label="Format">${FORMATS.map((f) => `<option ${f === p.format ? 'selected' : ''}>${f}</option>`).join('')}</select></td>
  <td><input class="num" name="max_mb" type="number" min="0.05" step="0.05" value="${esc(p.max_mb ?? '')}" aria-label="Cap in MB" /></td>
  <td><input class="num" name="fill" type="number" min="0.2" max="1" step="0.01" value="${esc(p.fill ?? 0.8)}" aria-label="Fill" /></td>
  <td><select name="anchor" aria-label="Anchor">${ANCHORS.map((a) => `<option ${a === (p.anchor || 'center') ? 'selected' : ''}>${a}</option>`).join('')}</select></td>
  <td><button type="button" class="icon-btn" data-remove aria-label="Remove preset">×</button></td>
</tr>`;

function readRows(form) {
  return [...form.querySelectorAll('[data-row]')].map((tr) => {
    const v = (n) => tr.querySelector(`[name=${n}]`);
    return {
      enabled: v('enabled').checked, name: v('name').value.trim(), label: v('label').value.trim(),
      width: Number(v('width').value), height: Number(v('height').value), format: v('format').value,
      max_mb: v('max_mb').value === '' ? null : Number(v('max_mb').value), fill: Number(v('fill').value || 0.8),
      anchor: v('anchor').value, seconds: null,
    };
  });
}

export async function openPresetsDialog(ctx, design, onSaved = () => {}) {
  const el = host();
  const [settings, brand] = await Promise.all([api('/settings'), api('/outputs/brand')]);
  const q = design ? `&design_id=${encodeURIComponent(design.id)}` : '';
  const previews = () => ['watermark', 'title', 'end'].map((k) => `<figure><img alt="${k} preview" src="/api/outputs/brand/preview?kind=${k}${q}&t=${Date.now()}" />
      <figcaption>${k === 'watermark' ? 'Watermark' : k === 'title' ? 'Title card (videos)' : 'End card (videos)'}</figcaption></figure>`).join('');
  el.innerHTML = `<form class="dialog spec-sheet sk-outputs-dialog" role="dialog" aria-modal="true" aria-labelledby="sk-outputs-dlg-title">
    <div class="sk-sh"><h2 id="sk-outputs-dlg-title">Output presets and brand</h2>
      <p>Presets are sizes cut from a render set on demand (fill: how much of the frame the part may take; anchor
        left/right keeps it on a third for thumbnail text). The brand goes on exported copies only, never on the set.</p></div>
    <div class="sk-body">
      <div class="sk-grp">Presets</div>
      <div class="sk-outputs-pad"><table class="sk-outputs-table">
        <thead><tr><th>On</th><th>Name</th><th>Label</th><th>W px</th><th>H px</th><th>Format</th><th>≤ MB</th><th>Fill</th><th>Anchor</th><th></th></tr></thead>
        <tbody data-rows>${(settings.outputs_presets || []).map(rowHtml).join('')}</tbody>
      </table>
      <div class="sk-outputs-actions"><button type="button" class="outline" data-add>Add preset</button><button type="button" data-reset>Reset to defaults</button></div></div>
      <div class="sk-grp">Brand</div>
      <div class="sk-outputs-pad"><p>Watermark text, position, opacity and the cards are in Settings → Brand.
        Mark: ${brand.mark ? `${brand.mark.width}×${brand.mark.height} PNG` : 'none uploaded'}${brand.mark && !settings.outputs_brand_mark ? ' (not in use: turn on "Use the mark")' : ''}.</p>
        <div class="sk-outputs-actions"><button type="button" class="outline" data-mark>Upload mark (PNG)…</button>
          ${brand.mark ? '<button type="button" data-unmark>Remove mark</button>' : ''}
          <input type="file" accept="image/png,image/webp,image/jpeg" hidden data-markfile /></div></div>
      <div class="sk-outputs-brand" data-previews>${previews()}</div>
    </div>
    <p class="error" data-error role="alert"></p>
    <div class="sk-foot"><span class="sum"></span><button type="button" data-close>Cancel</button><button type="submit" class="primary">Save</button></div>
  </form>`;
  el.hidden = false;
  const form = el.querySelector('form');
  const close = () => { el.hidden = true; el.innerHTML = ''; };
  form.querySelector('input')?.focus();
  el.onclick = async (e) => {
    if (e.target === el || e.target.closest('[data-close]')) { close(); return; }
    if (e.target.closest('[data-add]')) {
      form.querySelector('[data-rows]').insertAdjacentHTML('beforeend', rowHtml({ name: `preset-${Date.now() % 10000}`, label: 'New preset', width: 1200, height: 900, format: 'jpg', fill: 0.8 }));
    }
    if (e.target.closest('[data-remove]')) e.target.closest('[data-row]').remove();
    if (e.target.closest('[data-reset]')) {
      const ok = await ctx.confirm({ title: 'Reset presets?', body: 'The list goes back to the built-in presets when you save.', confirm: 'Reset' });
      if (ok) {
        const defaults = await api('/outputs/presets/defaults');
        form.querySelector('[data-rows]').innerHTML = defaults.map(rowHtml).join('');
      }
    }
    if (e.target.closest('[data-mark]')) form.querySelector('[data-markfile]').click();
    if (e.target.closest('[data-unmark]')) {
      await api('/outputs/brand/mark', { method: 'DELETE' });
      ctx.toast('Mark removed');
      openPresetsDialog(ctx, design, onSaved);
    }
  };
  form.querySelector('[data-markfile]').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      await sendFile('/outputs/brand/mark', f, 'PUT');
      ctx.toast('Mark uploaded');
      openPresetsDialog(ctx, design, onSaved);
    } catch (err) { form.querySelector('[data-error]').textContent = err.message; }
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const rows = readRows(form);
    try {
      await api('/settings', { method: 'PUT', body: { outputs_presets: rows } });
      close();
      ctx.toast('Presets saved');
      onSaved();
    } catch (err) { form.querySelector('[data-error]').textContent = err.message; }
  });
}
