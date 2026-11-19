// Area O (outputs and publishing), the UI entry: registers the drawing-sheet pages, a
// side-column summary, a sidebar section for the selected source, a tile badge for
// real photos and the settings groups. Uses only the D seams (docs/design.md).
//
//   F19 photos · F6 presets (+ F23 brand) · F13 listing packs · F7 print files ·
//   F5 project page · F26 Kist review

import { ctx } from '../ctx.js';
import { registerDetailSection } from '../detail.js';
import { registerSettingsGroup } from '../settings.js';
import { registerSidebarSection } from '../sidebar.js';
import { registerTileBadge } from '../tiles.js';
import { api, esc, go, mark } from './outputs-common.js';
import { openPresetsDialog } from './outputs-dialog.js';
import { filesSheet, listingSheet, pageSheet, photosSheet, presetsSheet, reviewHtml, reviewSheet, wireReview } from './outputs-sheets.js';

const rendered = (d) => d.status === 'rendered' || (d.files && d.files.length > 0);
const SHEETS = [
  ['outputs-photos', 'Real photos', photosSheet],
  ['outputs-presets', 'Output presets', presetsSheet],
  ['outputs-listing', 'Listing packs', listingSheet],
  ['outputs-files', 'Print files', filesSheet],
  ['outputs-page', 'Project page', pageSheet],
  ['outputs-review', 'Review in Kist', reviewSheet],
];
SHEETS.forEach(([id, title, render], i) => registerDetailSection({
  id, title, order: 60 + i, sheet: true, group: 'Publish', when: rendered, render,
}));

// ---------------------------------------------------------------- side column: a summary

registerDetailSection({
  id: 'outputs-summary', title: 'Publish', order: 60, when: rendered,
  async render(el, d, ctx) {
    el.innerHTML = '<div class="sk-outputs-side"><span class="line">Loading…</span></div>';
    let o;
    try { o = await api(`/designs/${encodeURIComponent(d.id)}/outputs`); } catch (err) { el.textContent = err.message; return; }
    const markets = Object.entries(o.readiness);
    el.innerHTML = `<div class="sk-outputs-side">
      ${markets.map(([, r]) => {
        const miss = r.checks.filter((c) => c.required && !c.ok);
        return `<span class="line"><span>${mark(r.ready)}</span><b>${esc(r.label)}</b><span>${r.ready ? 'ready to list' : esc(miss.map((c) => c.rule).join(' · '))}</span></span>`;
      }).join('')}
      <span class="line">${o.photos.length} real photo${o.photos.length === 1 ? '' : 's'} · print files ${o.filepack?.made ? 'exported' : 'off'}${o.review?.share?.active ? ' · shared in Kist' : ''}</span>
      <span class="sk-outputs-go">${SHEETS.map(([id, title]) => `<button type="button" data-go="${id}">${esc(title)}</button>`).join('')}</span>
    </div>`;
    el.onclick = (e) => { const b = e.target.closest('[data-go]'); if (b) go(b.dataset.go); };
    void ctx;
  },
});

// ---------------------------------------------------------------- sidebar: the selected source

registerSidebarSection({
  id: 'outputs-source', title: 'Publish', order: 15,
  render(el, ctx) {
    const src = ctx.state.sourceId && ctx.state.sources.find((s) => s.id === ctx.state.sourceId);
    if (!src) {
      el.innerHTML = '<div class="sk-outputs-src"><span class="sk-outputs-note">Pick a source to export a project page of all its designs, or lay them out on a Kist board.</span></div>';
      el.onclick = null;
      return;
    }
    const key = `${src.id}:${src.rendered}`;
    if (el.dataset.key === key) return;  // runs after every poll: keep it cheap
    el.dataset.key = key;
    el.innerHTML = `<div class="sk-outputs-src">
      <button type="button" data-src-page ${src.rendered ? '' : 'disabled'}>Project page (.zip)</button>
      <button type="button" data-src-review ${src.rendered && ctx.state.status.kist?.url ? '' : 'disabled'}>Kist board…</button>
      <span class="sk-outputs-note">${esc(src.label)}: ${src.rendered} rendered design${src.rendered === 1 ? '' : 's'}. Downloads only; nothing is posted.</span>
    </div>`;
    el.onclick = async (e) => {
      try {
        if (e.target.closest('[data-src-page]')) {
          const r = await api(`/sources/${encodeURIComponent(src.id)}/outputs/page`, { method: 'POST', body: { include_files: false } });
          const a = document.createElement('a'); a.href = r.url; a.download = ''; document.body.append(a); a.click(); a.remove();
        }
        if (e.target.closest('[data-src-review]')) openSourceReview(ctx, src);
      } catch (err) { ctx.toast(err.message, { bad: true }); }
    };
  },
});

async function openSourceReview(ctx, src) {
  let el = document.getElementById('sk-outputs-review');
  if (!el) { el = document.createElement('div'); el.id = 'sk-outputs-review'; el.className = 'overlay'; document.body.append(el); }
  const base = `/sources/${encodeURIComponent(src.id)}`;
  const draw = async () => {
    const r = await api(`${base}/outputs/review`);
    el.innerHTML = `<div class="dialog spec-sheet sk-outputs-dialog sheet" role="dialog" aria-modal="true" aria-labelledby="sk-outputs-rv-title">
      <div class="sk-sh"><h2 id="sk-outputs-rv-title">Review ${esc(src.label)} in Kist</h2>
        <p>One still per rendered design, laid out as a Kist board; a share link only if you ask.</p></div>
      <div class="sk-body sk-outputs-page">${reviewHtml(r, 'every design in this source')}</div>
      <div class="sk-foot"><span class="sum"></span><button type="button" data-close>Close</button></div></div>`;
    el.hidden = false;
    const body = el.querySelector('.sk-body');
    wireReview(body, base, r, ctx, draw);
  };
  el.onclick = (e) => { if (e.target === el || e.target.closest('[data-close]')) { el.hidden = true; el.innerHTML = ''; } };
  try { await draw(); } catch (err) { ctx.toast(err.message, { bad: true }); }
}

// ---------------------------------------------------------------- tile badge: real photos

let photoCounts = {};
let badgesStarted = false;
async function refreshBadges(ctx) {
  try { photoCounts = await api('/outputs/readiness'); } catch { return; }
  ctx.emit();  // redraw the tiles with the counts
}
registerTileBadge((d) => {
  if (!badgesStarted) {
    // first tile drawn: the token is set by now (never call the API at import time)
    badgesStarted = true;
    setTimeout(() => refreshBadges(ctx), 0);
    setInterval(() => refreshBadges(ctx), 60_000);
  }
  const c = photoCounts[d.id];
  if (!c || !c.needed) return null;  // only for designs someone is listing (it has photos)
  return { text: `photos ${Math.min(c.photos, c.needed)}/${c.needed}`, title: `${c.site} asks for ${c.needed} real print photos; this design has ${c.photos}` };
});

// ---------------------------------------------------------------- settings

registerSettingsGroup({
  id: 'outputs-files', title: 'Print files', order: 60, fields: [
    { name: 'outputs_filepack', label: 'Export print files', type: 'checkbox', hint: 'STEP, 3MF, STL from the same commit' },
    { name: 'outputs_filepack_formats', label: 'Formats', type: 'text', hint: 'some of step, 3mf, stl' },
    { name: 'outputs_filepack_body_budget', label: 'Whole-design mesh up to', type: 'number', unit: 'bodies', min: 1, max: 5000, hint: 'above: STL per body, no 3MF' },
    { name: 'outputs_filepack_per_body', label: 'Also one STL per body', type: 'checkbox' },
    { name: 'outputs_filepack_quality', label: 'Mesh quality', type: 'select', options: ['standard', 'fine', 'finest'] },
    { name: 'outputs_filepack_exclude', label: 'Leave out bodies', type: 'text', hint: 'patterns, e.g. M3*, insert*' },
  ],
});
registerSettingsGroup({
  id: 'outputs-brand', title: 'Brand (exported copies only)', order: 61, fields: [
    { name: 'outputs_brand_text', label: 'Watermark text', type: 'text', hint: 'empty: none' },
    { name: 'outputs_brand_mark', label: 'Use the uploaded mark', type: 'checkbox' },
    { name: 'outputs_brand_position', label: 'Position', type: 'select', options: ['bottom-right', 'bottom-left', 'top-right', 'top-left', 'center'] },
    { name: 'outputs_brand_opacity', label: 'Opacity', type: 'number', min: 0.1, max: 1, step: 0.05 },
    { name: 'outputs_brand_size', label: 'Size', type: 'number', unit: '%', min: 3, max: 40, hint: 'of the image width' },
    { name: 'outputs_brand_photos', label: 'Mark real photos too', type: 'checkbox' },
    { name: 'outputs_brand_title_card', label: 'Title card on clips', type: 'checkbox' },
    { name: 'outputs_brand_end_card', label: 'End card on clips', type: 'checkbox' },
    { name: 'outputs_brand_card_text', label: 'End card line', type: 'text' },
    { name: 'outputs_brand_card_seconds', label: 'Card length', type: 'number', unit: 's', min: 0.5, max: 5, step: 0.5 },
  ],
});
registerSettingsGroup({
  id: 'outputs-listing', title: 'Listing', order: 62, fields: [
    { name: 'outputs_marketplaces', label: 'Marketplaces', type: 'text', hint: 'printables, makerworld, thingiverse, cults, etsy' },
    { name: 'outputs_licence', label: 'Default licence', type: 'text', hint: 'e.g. CC-BY-4.0' },
  ],
});
registerSettingsGroup({
  id: 'outputs-review', title: 'Review (Kist)', order: 63, fields: [
    { name: 'outputs_review_share_links', label: 'Allow share links', type: 'checkbox', hint: 'public Kist pages, made only on click' },
    { name: 'outputs_review_proofing', label: 'Guest proofing', type: 'checkbox', hint: 'guests pick and comment' },
    { name: 'outputs_review_share_days', label: 'Links expire after', type: 'number', unit: 'days', min: 0, max: 365, hint: '0: never' },
    { name: 'outputs_review_allow_download', label: 'Guests may download', type: 'checkbox' },
  ],
});

export { openPresetsDialog };
