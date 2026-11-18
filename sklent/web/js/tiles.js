// One grid tile per design.

import { esc } from './dom.js';
import { CUBE } from './format.js';
import { activeJobFor } from './store.js';

export function tile(d) {
  const job = activeJobFor(d.id);
  const badge = d.stale ? 'stale' : d.status === 'rendered' ? '' : d.status;
  const body = d.thumb_url
    ? `<img src="${esc(d.thumb_url)}" data-still="${esc(d.thumb_url)}" data-gif="${esc(d.gif_url || '')}" loading="lazy" alt="" />`
    : `<div class="placeholder">${CUBE}<span>${esc(d.status === 'failed' ? (d.error || 'failed').slice(0, 120) : d.status)}</span></div>`;
  return `<div class="tile" data-design="${esc(d.id)}">
    ${body}
    ${badge ? `<span class="badge ${esc(badge)}">${esc(badge)}</span>` : ''}
    <div class="tile-caption"><div class="n">${esc(d.name)}</div><div class="r">${esc(d.repo)}</div></div>
    ${job && job.status === 'running' ? `<div class="bar"><i style="width:${Math.round(job.progress * 100)}%"></i></div>` : ''}
  </div>`;
}
