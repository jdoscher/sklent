// Area O (outputs and publishing): shared bits for the outputs UI. See outputs-ui.js.

import { api, readToken } from '../api.js';
import { esc } from '../dom.js';
import { fmtBytes } from '../format.js';

export { api, esc, fmtBytes };

/** Everything the outputs sheets show for a design: GET /api/designs/{id}/outputs. */
export const load = (d) => api(`/designs/${encodeURIComponent(d.id)}/outputs`);

/** Switch the drawing sheet's viewer to one of our sheet sections. */
export function go(id) {
  const row = document.querySelector(`#detail [data-sheet="section:${CSS.escape(id)}"]`);
  if (row) row.click();
}

/** Start a download of an /api URL (GET; the cookie carries the token). */
export function download(url) {
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.append(a);
  a.click();
  a.remove();
}

/** POST a file as the raw request body (photos, the brand mark). */
export async function sendFile(path, file, method = 'POST') {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { Authorization: `Bearer ${readToken()}`, 'Content-Type': file.type || 'application/octet-stream' },
    body: file,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`);
  return data;
}

/** A size with its cap: `0.6/10 MB`, or just the size. */
export function budget(bytes, maxMb) {
  if (bytes == null) return '—';
  return maxMb ? `${(bytes / 1e6).toFixed(bytes < 1e6 ? 2 : 1)}/${maxMb} MB` : fmtBytes(bytes);
}

/** ✓ ✕ ? as text marks: no hue, so the state reads in any theme. */
export const mark = (ok) => (ok === true ? '✓' : ok === false ? '✕' : '?');

/** Run an async action from a button: disable it, show the error as a toast. */
export async function busy(btn, ctx, fn) {
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Working…'; }
  try { return await fn(); } catch (err) { ctx.toast(err.message, { bad: true }); return null; } finally {
    if (btn && btn.isConnected) { btn.disabled = false; btn.textContent = label; }
  }
}

export const LICENCES = ['CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', 'CC-BY-NC-4.0', 'CC-BY-NC-SA-4.0', 'CC-BY-ND-4.0',
  'CC-BY-NC-ND-4.0', 'MIT', 'Apache-2.0', 'GPL-3.0', 'CERN-OHL-S-2.0', 'CERN-OHL-W-2.0', 'CERN-OHL-P-2.0'];

export const isVideo = (f) => /\.(mp4|webm|mov)$/i.test(f || '');
export const isImage = (f) => /\.(png|jpe?g|webp|gif)$/i.test(f || '');
