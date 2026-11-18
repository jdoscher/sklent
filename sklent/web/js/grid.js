// The canvas: the grid header (serif view title, count, scope, filter) and the tiles,
// or an empty state (U1-12 words) when there is nothing to show.

import { openDetail } from './detail.js';
import { $, esc } from './dom.js';
import { OUTLINE_MARK, isoTime } from './format.js';
import { emit, isBusy, state, visibleDesigns } from './store.js';
import { tile } from './tiles.js';

const TITLES = { all: 'All designs', rendered: 'Rendered', active: 'In progress', failed: 'Failed' };
const EXAMPLES = [
  'https://github.com/owner',
  'https://github.com/owner/repo/tree/main/designs',
  'https://forgejo.example.com/owner/repo/src/branch/main/part.sc',
];

function emptyState() {
  const words = !state.designs.length
    ? ['Point sklent at a repo.', 'Paste a GitHub or Forgejo address above and press Render. Every SolidCraft design in it becomes a turntable, a reel, stills and a GIF.',
      `<div class="examples">${EXAMPLES.map((u) => `<button type="button" data-example="${esc(u)}">${esc(u)}</button>`).join('')}</div>`]
    : state.query.trim() ? ['Nothing matches.', 'Try fewer words, or clear the filter.', '<button type="button" class="action" data-clear-query>Clear the filter</button>']
      : state.filter === 'failed' ? ['Nothing failed.', 'A design that can’t be rendered shows here with SolidCraft’s reason and a Render again button.', '']
        : state.filter === 'active' ? ['Nothing rendering.', 'Queued and running renders show here with their progress.', '']
          : state.filter === 'rendered' ? ['No renders yet.', 'Finished designs gather here as their renders complete.', '']
            : ['Nothing here yet.', 'This source has no designs in this view.', '<button type="button" class="action" data-show-all>Show all designs</button>'];
  return `<div class="empty-state">${OUTLINE_MARK}<h2>${words[0]}</h2><p>${words[1]}</p>${words[2]}</div>`;
}

export function renderGrid() {
  const list = visibleDesigns();
  const src = state.sources.find((s) => s.id === state.sourceId);
  $('#view-title').textContent = src ? src.label.split('/').pop() : TITLES[state.filter];
  const busy = state.designs.filter(isBusy).length;
  $('#title-count').textContent = `${list.length} design${list.length === 1 ? '' : 's'}${busy && state.filter === 'all' && !src ? ` · ${busy} in progress` : ''}`;
  const latest = state.designs.map((d) => d.rendered_at).filter(Boolean).sort().pop();
  $('#grid-scope').textContent = src ? src.label : latest ? `last render ${isoTime(latest)}` : '';
  $('#grid-scope').title = src ? src.url : '';
  $('.grid-area').classList.toggle('empty', !state.designs.length);
  // keep hover state (a playing GIF) and focus across polls when nothing changed
  const html = list.length ? list.map(tile).join('') : emptyState();
  const grid = $('#grid');
  if (grid.dataset.html !== html) {
    const focused = document.activeElement?.closest?.('[data-design]')?.dataset.design;
    grid.innerHTML = html;
    grid.dataset.html = html;
    if (focused) grid.querySelector(`[data-design="${CSS.escape(focused)}"]`)?.focus({ preventScroll: true });
  }
}

function openTile(el) {
  const d = state.designs.find((x) => x.id === el.dataset.design);
  if (d) openDetail(d, false, el);
}

export function initGrid() {
  const grid = $('#grid');
  // hover plays the turntable GIF, as Kist's grid does
  grid.addEventListener('mouseover', (e) => {
    const img = e.target.closest('.tile')?.querySelector('img[data-gif]');
    if (img && img.dataset.gif && !img.src.endsWith(img.dataset.gif)) img.src = img.dataset.gif;
  });
  grid.addEventListener('mouseout', (e) => {
    const t = e.target.closest('.tile');
    const img = t?.querySelector('img[data-still]');
    if (img && !t.contains(e.relatedTarget)) img.src = img.dataset.still;
  });
  grid.addEventListener('click', (e) => {
    const ex = e.target.closest('[data-example]');
    if (ex) { $('#url').value = ex.dataset.example; $('#url').focus(); return; }
    if (e.target.closest('[data-clear-query]')) { state.query = ''; $('#search').value = ''; emit(); return; }
    if (e.target.closest('[data-show-all]')) { state.sourceId = null; state.filter = 'all'; emit(); return; }
    const t = e.target.closest('[data-design]');
    if (t) openTile(t);
  });
  grid.addEventListener('keydown', (e) => {
    const t = e.target.closest('[data-design]');
    if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openTile(t); }
  });
  $('#search').addEventListener('input', (e) => { state.query = e.target.value; emit(); });
}
