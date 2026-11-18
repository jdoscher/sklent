// The toast: one line, at most one quiet action (e.g. Cancel on "Render queued").

import { $, esc } from './dom.js';

let timer;

/**
 * toast('Saved') · toast(err.message, { bad: true }) ·
 * toast('Render queued for pi-case', { action: { label: 'Cancel', run: () => ... } })
 * The second argument may also be a boolean (bad), as in 0.1.
 */
export function toast(msg, opts = {}) {
  if (typeof opts === 'boolean') opts = { bad: opts };
  const { bad = false, action = null, ms = bad ? 7000 : action ? 6000 : 3500 } = opts;
  const t = $('#toast');
  t.className = `toast${bad ? ' bad' : ''}`;
  t.innerHTML = `<span class="msg">${esc(msg)}</span>${action ? `<button type="button">${esc(action.label)}</button>` : ''}`;
  if (action) {
    t.querySelector('button').addEventListener('click', async () => {
      t.hidden = true;
      try { await action.run(); } catch (err) { toast(err.message, { bad: true }); }
    }, { once: true });
  }
  t.hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => { t.hidden = true; }, ms);
}
