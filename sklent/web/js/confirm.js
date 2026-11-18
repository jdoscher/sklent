// A small float dialog in place of the browser's confirm() (U1-11).

import { $, esc } from './dom.js';

/** Resolves true when confirmed. { title, body, confirm: 'Remove', danger: true } */
export function confirmDialog({ title, body = '', confirm = 'OK', cancel = 'Cancel', danger = false }) {
  const host = $('#confirm');
  const before = document.activeElement;
  host.innerHTML = `<div class="dialog confirm" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-body">
      <h2 id="confirm-title">${esc(title)}</h2>
      <p id="confirm-body">${esc(body)}</p>
      <div class="actions">
        <button type="button" data-answer="no">${esc(cancel)}</button>
        <button type="button" data-answer="yes" class="${danger ? 'danger' : 'primary'}">${esc(confirm)}</button>
      </div>
    </div>`;
  host.hidden = false;
  host.querySelector('[data-answer=no]').focus();
  return new Promise((resolve) => {
    const done = (yes) => {
      host.hidden = true;
      host.innerHTML = '';
      host.removeEventListener('click', onClick);
      host.removeEventListener('keydown', onKey);
      if (before && before.focus) before.focus();
      resolve(yes);
    };
    const onClick = (e) => {
      if (e.target === host) return done(false);
      const b = e.target.closest('[data-answer]');
      if (b) done(b.dataset.answer === 'yes');
    };
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); done(false); } };
    host.addEventListener('click', onClick);
    host.addEventListener('keydown', onKey);
  });
}
