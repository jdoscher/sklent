// The render settings dialog.

import { api } from './api.js';
import { $, $$, esc } from './dom.js';
import { state } from './store.js';
import { toast } from './toast.js';

export function initSettings() {
  $('#open-settings').addEventListener('click', async () => {
    const s = await api('/settings');
    $('#palettes').innerHTML = state.status.palettes.map((p) => `
      <label><input type="radio" name="palette" value="${esc(p.name)}" ${p.name === s.palette ? 'checked' : ''} hidden />
      <span class="swatch" style="background:${esc(p.shaded)}"></span>${esc(p.label)}</label>`).join('');
    const form = $('#settings-form');
    for (const k of ['seconds', 'fps', 'pitch_deg', 'social_size', 'hires_width', 'hires_height', 'gif_width', 'gif_fps']) form.elements[k].value = s[k];
    $$('input[name=style]', form).forEach((cb) => { cb.checked = s.styles.includes(cb.value); });
    $('#settings-error').textContent = '';
    $('#settings').hidden = false;
  });

  $('#settings').addEventListener('click', (e) => {
    if (e.target === e.currentTarget || e.target.closest('[data-close]')) $('#settings').hidden = true;
  });

  $('#settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target.elements;
    const num = (k) => Number(f[k].value);
    try {
      await api('/settings', {
        method: 'PUT',
        body: {
          palette: $('input[name=palette]:checked', e.target).value,
          seconds: num('seconds'), fps: num('fps'), pitch_deg: num('pitch_deg'),
          social_size: num('social_size'), hires_width: num('hires_width'), hires_height: num('hires_height'),
          gif_width: num('gif_width'), gif_fps: num('gif_fps'),
          styles: $$('input[name=style]:checked', e.target).map((c) => c.value),
        },
      });
      $('#settings').hidden = true;
      toast('Settings saved; they apply to the next renders');
    } catch (err) { $('#settings-error').textContent = err.message; }
  });
}
