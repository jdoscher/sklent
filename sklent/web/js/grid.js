// The design grid and its header.

import { $ } from './dom.js';
import { openDetail } from './detail.js';
import { state, visibleDesigns } from './store.js';
import { tile } from './tiles.js';

export function renderGrid() {
  const list = visibleDesigns();
  const src = state.sources.find((s) => s.id === state.sourceId);
  $('#grid-meta').textContent = `${list.length} design${list.length === 1 ? '' : 's'}${src ? ` in ${src.label}` : ''}`;
  $('#grid').innerHTML = list.length ? list.map(tile).join('') : `<div class="empty-grid">${state.designs.length ? 'Nothing matches.' : 'No designs yet. Paste a repo URL above and press Render.'}</div>`;
}

export function initGrid() {
  // hover plays the turntable GIF, as Kist's grid will
  $('#grid').addEventListener('mouseover', (e) => {
    const img = e.target.closest('img[data-gif]');
    if (img && img.dataset.gif && img.src.indexOf(img.dataset.gif) < 0) img.src = img.dataset.gif;
  });
  $('#grid').addEventListener('mouseout', (e) => {
    const img = e.target.closest('img[data-still]');
    if (img && !img.contains(e.relatedTarget)) img.src = img.dataset.still;
  });
  $('#grid').addEventListener('click', (e) => {
    const t = e.target.closest('[data-design]');
    if (t) openDetail(state.designs.find((d) => d.id === t.dataset.design));
  });
}
