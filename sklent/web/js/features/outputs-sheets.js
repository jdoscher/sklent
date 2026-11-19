// Area O: the sheet pages in the drawing sheet's viewer (registerDetailSection, sheet: true):
// real photos (F19), output presets (F6, F23), listing packs (F13), print files (F7),
// project page (F5) and the Kist review board (F26). Nothing here posts anywhere; the one
// outbound action, a Kist share link, is off by default and asks first.

import { LICENCES, api, budget, busy, download, esc, fmtBytes, isVideo, load, mark, sendFile } from './outputs-common.js';
import { openPresetsDialog } from './outputs-dialog.js';

const enc = encodeURIComponent;
const loading = (el) => { el.innerHTML = '<div class="sk-outputs-page"><p class="sk-outputs-lede">Loading…</p></div>'; };
const fail = (el, err) => { el.innerHTML = `<div class="sk-outputs-page"><p class="sk-outputs-lede">${esc(err.message)}</p></div>`; };

/** Wrap a sheet renderer: load the design's outputs, draw, and redraw after actions. */
function sheet(draw) {
  return async function render(el, d, ctx) {
    const again = () => render(el, d, ctx);
    loading(el);
    try {
      const o = await load(d);
      if (!el.isConnected) return;
      el.innerHTML = `<div class="sk-outputs-page">${draw.html(o, d, ctx)}</div>`;
      draw.wire?.(el, o, d, ctx, again);
    } catch (err) { fail(el, err); }
  };
}

// ---------------------------------------------------------------- F19 photos

export const photosSheet = sheet({
  html(o) {
    const n = o.photos.length;
    const need = Math.max(0, ...Object.values(o.readiness).map((m) => {
      const c = m.checks.find((x) => x.rule.startsWith('Real print photos'));
      return c ? Number(c.rule.match(/of (\d+)/)?.[1] || 0) : 0;
    }));
    return `<h3>Real print photos</h3>
      <p class="sk-outputs-lede">Photos of the printed part lead every listing pack and project page: Etsy wants a real
        photo first and MakerWorld at least three. They are never cropped or repainted, and location data (EXIF) is
        removed when they're stored.${o.review?.kist_on ? ' With Kist on, each is also filed in the design\'s Kist folder, tagged kind:photo.' : ''}</p>
      <div class="sk-outputs-actions">
        <button type="button" class="primary" data-act="add">Add photos…</button>
        <input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden data-file />
        <span class="sk-data sk-outputs-dim">${n} photo${n === 1 ? '' : 's'}${need ? ` · ${Math.min(n, need)} of ${need} the strictest site asks for` : ''}</span>
      </div>
      ${n ? `<div class="sk-outputs-gallery">${o.photos.map((p, i) => `
        <div class="sk-outputs-card" data-photo="${esc(p.id)}">
          <div class="fig"><img src="${esc(p.url)}" alt="${esc(p.caption || p.name)}" loading="lazy" /></div>
          <div class="sk-outputs-cap"><span class="nm">${String(i + 1).padStart(2, '0')} ${esc(p.caption || p.name)}</span><span class="sk-data sk-outputs-dim">${p.width}×${p.height}</span></div>
          <div class="tools">
            <button type="button" data-move="-1" ${i === 0 ? 'disabled' : ''} aria-label="Move earlier">←</button>
            <button type="button" data-move="1" ${i === n - 1 ? 'disabled' : ''} aria-label="Move later">→</button>
            <button type="button" data-caption>Caption</button>
            <button type="button" data-delete>Remove</button>
          </div>
        </div>`).join('')}</div>` : '<p class="sk-outputs-dim">No photos yet. Packs still build; the checklist says which sites want them.</p>'}`;
  },
  wire(el, o, d, ctx, again) {
    const input = el.querySelector('[data-file]');
    input.addEventListener('change', async () => {
      const files = [...input.files];
      await busy(el.querySelector('[data-act=add]'), ctx, async () => {
        for (const f of files) await sendFile(`/designs/${enc(d.id)}/outputs/photos?name=${enc(f.name)}`, f);
        ctx.toast(`${files.length} photo${files.length === 1 ? '' : 's'} added`);
      });
      again();
    });
    el.addEventListener('click', async (e) => {
      if (e.target.closest('[data-act=add]')) { input.click(); return; }
      const card = e.target.closest('[data-photo]');
      if (!card) return;
      const pid = card.dataset.photo;
      const i = o.photos.findIndex((p) => p.id === pid);
      const path = `/designs/${enc(d.id)}/outputs/photos/${enc(pid)}`;
      const mv = e.target.closest('[data-move]');
      if (mv) { await busy(mv, ctx, () => api(path, { method: 'PATCH', body: { position: i + Number(mv.dataset.move) } })); again(); }
      if (e.target.closest('[data-caption]')) {
        const caption = window.prompt('Caption', o.photos[i].caption || '');
        if (caption != null) { await busy(null, ctx, () => api(path, { method: 'PATCH', body: { caption } })); again(); }
      }
      if (e.target.closest('[data-delete]')) {
        const ok = await ctx.confirm({ title: 'Remove this photo?', body: 'It is deleted from Sklent (and moved to Kist\'s trash if it was filed there).', confirm: 'Remove', danger: true });
        if (ok) { await busy(null, ctx, () => api(path, { method: 'DELETE' })); again(); }
      }
    });
  },
});

// ---------------------------------------------------------------- F6 presets (+ F23 brand)

export const presetsSheet = sheet({
  html(o, d) {
    const all = `/api/designs/${enc(d.id)}/outputs/presets.zip`;
    return `<h3>Output presets</h3>
      <p class="sk-outputs-lede">Copies of this set cut to each site's size and cap, framed on the part. They are made on
        demand and kept with this set; the rendered files themselves never change.
        Brand: ${o.brand ? 'on (watermark or cards on these copies)' : 'none'}.</p>
      <div class="sk-outputs-actions">
        <button type="button" class="primary" data-act="all">Make all</button>
        <a class="sk-outputs-link" href="${esc(all)}" download>Download all (.zip)</a>
        <a class="sk-outputs-link" href="${esc(all)}?set=true" download>All + the set (.zip)</a>
        <button type="button" data-act="edit">Presets and brand…</button>
      </div>
      <div class="sk-outputs-gallery">${o.presets.filter((p) => p.enabled).map((p) => `
        <div class="sk-outputs-card" data-preset="${esc(p.name)}">
          <div class="fig">${p.made
            ? (isVideo(p.file) ? `<video src="${esc(p.url)}" muted loop autoplay playsinline></video>`
              : p.format === 'pdf' ? '<span class="sk-outputs-dim">PDF</span>'
                : `<img src="${esc(p.url)}" alt="${esc(p.label)}" loading="lazy" />`)
            : '<span class="sk-outputs-dim">not made yet</span>'}</div>
          <div class="sk-outputs-cap"><span class="nm">${esc(p.label)}</span><span class="sk-data sk-outputs-dim">${p.width}×${p.height}</span></div>
          <div class="sk-outputs-cap"><span class="sk-data sk-outputs-dim nm">${esc(p.format)} · ${p.made ? budget(p.bytes, p.max_mb) : (p.max_mb ? `≤ ${p.max_mb} MB` : 'no cap')}${p.made && p.fits === false ? ' · over the cap' : ''}</span></div>
          <div class="tools">${p.made ? `<a class="sk-outputs-link" href="${esc(p.url)}${p.url.includes('?') ? '&' : '?'}download=true" download>Download</a>` : `<button type="button" data-make>Make</button>`}</div>
        </div>`).join('')}</div>`;
  },
  wire(el, o, d, ctx, again) {
    el.addEventListener('click', async (e) => {
      const make = e.target.closest('[data-make]');
      if (make) {
        const name = make.closest('[data-preset]').dataset.preset;
        await busy(make, ctx, () => api(`/designs/${enc(d.id)}/outputs/presets/${enc(name)}`, { method: 'POST' }));
        again();
      }
      const all = e.target.closest('[data-act=all]');
      if (all) {
        await busy(all, ctx, async () => {
          for (const p of o.presets.filter((x) => x.enabled && !x.made)) {
            await api(`/designs/${enc(d.id)}/outputs/presets/${enc(p.name)}`, { method: 'POST' });
          }
        });
        again();
      }
      if (e.target.closest('[data-act=edit]')) openPresetsDialog(ctx, d, again);
    });
  },
});

// ---------------------------------------------------------------- F13 listing packs (+ F19 checklist)

const MARKET_ORDER = ['etsy', 'makerworld', 'printables', 'cults', 'thingiverse'];

export const listingSheet = sheet({
  html(o, d) {
    const m = o.meta;
    const from = (k) => (m.from[k] === 'default' ? '' : `<span class="from">from ${esc(m.from[k] === 'repo' ? '.sklent.yaml' : 'this design')}</span>`);
    const markets = MARKET_ORDER.filter((k) => o.readiness[k]);
    const built = Object.fromEntries((o.exports || []).map((x) => [x.file, x]));
    const stem = (d.name || '').replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9._-]+/g, '-');
    return `<h3>Listing packs</h3>
      <p class="sk-outputs-lede">One zip per marketplace: pictures in upload order (real photos first), the clips the site
        takes, the print files split to its limits, listing.md and pack.json with every rule checked. Sklent never posts:
        you upload the pack yourself.</p>
      <div class="lbl">Listing details</div>
      <form class="sk-outputs-form" data-meta>
        <label for="o-title">Title</label><span><input id="o-title" type="text" name="title" value="${esc(m.title)}" size="40" /> ${from('title')}</span>
        <label for="o-summary">Summary</label><span><textarea id="o-summary" name="summary">${esc(m.summary)}</textarea> ${from('summary')}</span>
        <label for="o-licence">Licence</label><span><input id="o-licence" type="text" name="licence" value="${esc(m.licence)}" list="o-licences" placeholder="e.g. CC-BY-4.0" /> ${from('licence')}
          <datalist id="o-licences">${LICENCES.map((l) => `<option value="${l}"></option>`).join('')}</datalist></span>
        <label for="o-notes">Print notes</label><span><textarea id="o-notes" name="print_notes" placeholder="material, layer height, supports, orientation">${esc(m.print_notes)}</textarea> ${from('print_notes')}</span>
        <label for="o-tags">Tags</label><span><input id="o-tags" type="text" name="tags" value="${esc((m.tags || []).join(', '))}" size="40" /> ${from('tags')}</span>
        <label>Source link</label><span><label class="sk-outputs-check"><input type="checkbox" name="hide_source" ${m.hide_source ? 'checked' : ''} /> Leave the repo URL out of packs and pages</label></span>
        <span></span><span><button type="submit">Save details</button></span>
      </form>
      ${markets.map((k) => {
        const r = o.readiness[k];
        const zip = built[`${stem}-${k}-listing.zip`];
        return `<div class="sk-outputs-market" data-market="${esc(k)}">
          <div class="head"><span class="title">${esc(r.label)}</span>
            <span class="sk-outputs-state${r.ready ? ' ok' : ''}">${r.ready ? 'ready to list' : 'not ready'}</span>
            <button type="button" data-build>Build pack</button>
            <button type="button" data-copy>Copy text</button>
            ${zip ? `<a class="sk-outputs-link" href="${esc(zip.url)}" download>Last pack · ${fmtBytes(zip.bytes)}</a>` : ''}
          </div>
          <ul class="sk-outputs-checks">${r.checks.map((c) => `<li class="${c.required ? '' : 'opt'}"><span class="m" aria-label="${c.ok === true ? 'met' : c.ok === false ? 'not met' : 'unknown'}">${mark(c.ok)}</span>
            <span>${esc(c.rule)}${c.required ? '' : ' <span class="d">(recommended)</span>'}${c.detail ? ` <span class="d">· ${esc(c.detail)}</span>` : ''}</span></li>`).join('')}</ul>
        </div>`;
      }).join('')}
      <p class="sk-outputs-dim">Rules come from each site's published guidance (the links are in each pack's pack.json). The check informs; it never blocks a pack.</p>`;
  },
  wire(el, o, d, ctx, again) {
    el.querySelector('[data-meta]').addEventListener('submit', async (e) => {
      e.preventDefault();
      const f = e.target;
      const v = (n) => f.elements.namedItem(n);
      const body = { title: v('title').value, summary: v('summary').value, licence: v('licence').value,
        print_notes: v('print_notes').value, tags: v('tags').value, hide_source: v('hide_source').checked };
      await busy(f.querySelector('[type=submit]'), ctx, async () => {
        await api(`/designs/${enc(d.id)}/outputs/meta`, { method: 'PUT', body });
        ctx.toast('Listing details saved');
      });
      again();
    });
    el.addEventListener('click', async (e) => {
      const market = e.target.closest('[data-market]')?.dataset.market;
      const b = e.target.closest('[data-build]');
      if (b) {
        const pack = await busy(b, ctx, () => api(`/designs/${enc(d.id)}/outputs/listing/${enc(market)}`, { method: 'POST' }));
        if (pack) {
          ctx.toast(`${pack.label} pack built${pack.all_fit ? '' : ': some files miss a rule, see pack.json'}`);
          download(pack.url);
          again();
        }
      }
      const c = e.target.closest('[data-copy]');
      if (c) {
        await busy(c, ctx, async () => {
          const res = await fetch(`/api/designs/${enc(d.id)}/outputs/listing/${enc(market)}/text`, { credentials: 'same-origin' });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          await navigator.clipboard.writeText(await res.text());
          ctx.toast('Listing text copied');
        });
      }
    });
  },
});

// ---------------------------------------------------------------- F7 print files

export const filesSheet = sheet({
  html(o) {
    const fp = o.filepack;
    if (!fp || !fp.made) {
      return `<h3>Print files</h3>
        <p class="sk-outputs-lede">STEP, 3MF and STL exported by SolidCraft from the same commit as the pictures, with a
          README, the licence and a manifest of sha256 sums.</p>
        <div class="sk-outputs-warn">${esc((fp && fp.skipped && fp.skipped[0]) || 'This set has no print files.')}
          ${fp && fp.setting_on ? '<br />Print files are on now: re-render this design to export them.' : ''}</div>
        <div class="sk-outputs-actions"><button type="button" data-act="settings">Open settings</button></div>`;
    }
    return `<h3>Print files</h3>
      <p class="sk-outputs-lede">Exported by SolidCraft from this set's commit: ${fp.bodies} part${fp.bodies === 1 ? '' : 's'}${fp.hidden_left_out ? `, ${fp.hidden_left_out} hidden bod${fp.hidden_left_out === 1 ? 'y' : 'ies'} left out` : ''}${fp.excluded?.length ? `, hardware left out: ${esc(fp.excluded.slice(0, 8).join(', '))}` : ''}.</p>
      ${fp.files.map((f) => `<div class="sk-outputs-row"><span class="nm">${esc(f.file)}</span><span class="sk-data sk-outputs-dim">${esc(f.variant)} · ${fmtBytes(f.bytes)}</span><a class="sk-outputs-link" href="${esc(f.url)}" download>Download</a></div>`).join('')}
      ${(fp.skipped || []).map((s) => `<p class="sk-outputs-dim">${esc(s)}</p>`).join('')}
      <div class="sk-outputs-actions">
        <button type="button" class="primary" data-pack="">Build pack (.zip)</button>
        <button type="button" data-pack="20">Split for Etsy (5 × 20 MB)</button>
      </div>
      <div data-parts></div>`;
  },
  wire(el, o, d, ctx) {
    el.addEventListener('click', async (e) => {
      if (e.target.closest('[data-act=settings]')) { document.getElementById('open-settings')?.click(); return; }
      const b = e.target.closest('[data-pack]');
      if (!b) return;
      const split = b.dataset.pack ? Number(b.dataset.pack) : null;
      const r = await busy(b, ctx, () => api(`/designs/${enc(d.id)}/outputs/filepack`, { method: 'POST', body: { split_mb: split } }));
      if (!r) return;
      el.querySelector('[data-parts]').innerHTML = `<div class="lbl">${r.parts.length} file${r.parts.length === 1 ? '' : 's'}${split ? ` · ≤ ${split} MB each${r.parts.length > 5 ? ' · more than Etsy\'s 5' : ''}` : ''}</div>
        ${r.parts.map((p) => `<div class="sk-outputs-row"><span class="nm">${esc(p.file)}</span><span class="sk-data sk-outputs-dim">${budget(p.bytes, split)}</span><a class="sk-outputs-link" href="${esc(p.url)}" download>Download</a></div>`).join('')}
        ${r.notes.map((n) => `<p class="sk-outputs-dim">${esc(n)}</p>`).join('')}`;
      if (r.parts.length === 1) download(r.parts[0].url);
    });
  },
});

// ---------------------------------------------------------------- F5 project page

export const pageSheet = sheet({
  html(o, d) {
    return `<h3>Project page</h3>
      <p class="sk-outputs-lede">A static HTML page in Sklent's drafting look: hero, pictures (real photos first),
        turntable, spec, parts, files, licence and commit. It works offline, with no scripts and nothing fetched. It is a
        download only: Sklent never hosts or posts it. Drop the folder on your own site or open index.html.</p>
      <div class="sk-outputs-actions">
        <label class="sk-outputs-check"><input type="checkbox" data-files ${o.filepack?.made ? 'checked' : 'disabled'} /> Include the print files</label>
        <label class="sk-outputs-check"><input type="checkbox" data-hide ${o.meta.hide_source ? 'checked' : ''} /> Leave out the source link</label>
      </div>
      <div class="sk-outputs-actions">
        <button type="button" class="primary" data-page>Download page (.zip)</button>
        <button type="button" data-source-page>Page for every design in ${esc(d.repo)} (.zip)</button>
      </div>`;
  },
  wire(el, o, d, ctx) {
    el.addEventListener('click', async (e) => {
      const files = el.querySelector('[data-files]').checked;
      const hide = el.querySelector('[data-hide]').checked;
      const b = e.target.closest('[data-page]');
      if (b) {
        const r = await busy(b, ctx, () => api(`/designs/${enc(d.id)}/outputs/page`, { method: 'POST', body: { include_files: files, hide_source: hide } }));
        if (r) download(r.url);
      }
      const s = e.target.closest('[data-source-page]');
      if (s) {
        const r = await busy(s, ctx, () => api(`/sources/${enc(d.source_id)}/outputs/page`, { method: 'POST', body: { include_files: false, hide_source: hide } }));
        if (r) download(r.url);
      }
    });
  },
});

// ---------------------------------------------------------------- F26 Kist review

export function reviewHtml(r, what) {
  if (!r || !r.kist_on) {
    return '<div class="sk-outputs-warn">Kist is off (no SK_KIST_URL), so there is no board to make. Everything else here works without it.</div>';
  }
  const b = r.board;
  const s = r.share && r.share.active ? r.share : null;
  const days = r.share_days ? `${r.share_days} days` : 'no expiry';
  return `<div class="lbl">Board</div>
    ${b ? `<div class="sk-outputs-row"><span class="nm">${esc(b.name)}</span><span class="sk-data sk-outputs-dim">${b.items} items</span>
        ${b.url ? `<a class="sk-outputs-link" href="${esc(b.url)}" target="_blank" rel="noopener">Open in Kist</a>` : ''}</div>
      <div class="sk-outputs-actions"><button type="button" data-board>Rebuild board</button><button type="button" data-unboard>Remove board</button></div>`
    : `<p class="sk-outputs-dim">Lays ${esc(what)} out as a board in your Kist, real photos first. It stays inside Kist; nothing is shared.</p>
      <div class="sk-outputs-actions"><button type="button" class="primary" data-board>Make Kist board</button></div>`}
    <div class="lbl">Share link</div>
    ${!r.share_links_allowed ? `<div class="sk-outputs-warn">Share links are off. A share link is a public page on ${esc(r.kist_url || 'your Kist')} that
        anyone with the URL can open. Turn it on in Settings → Review to make one here; it is still only made when you ask.</div>`
    : s ? `<p class="sk-outputs-url">${esc(s.url)}</p>
        <p class="sk-outputs-dim">Public until ${esc(s.expires_at ? String(s.expires_at).slice(0, 10) : 'revoked')}${s.proofing ? ' · guests can pick and comment (Kist proofing)' : ''}.</p>
        <div class="sk-outputs-actions"><button type="button" data-copy-share>Copy link</button><button type="button" data-revoke>Revoke</button></div>`
      : `<p class="sk-outputs-dim">Sends the board to your Kist's public share page: ${b ? `its ${b.items} items` : 'the board'}, for ${days}${r.proofing ? ', with guest proofing (picks and comments)' : ''}${r.allow_download ? ', downloads allowed' : ', no downloads'}.</p>
        <div class="sk-outputs-actions"><input type="password" data-password placeholder="Password (optional)" autocomplete="new-password" />
          <button type="button" data-share>Create share link…</button></div>`}`;
}

export function wireReview(el, base, r, ctx, again) {
  el.addEventListener('click', async (e) => {
    const t = e.target;
    if (t.closest('[data-board]')) { await busy(t.closest('button'), ctx, () => api(`${base}/outputs/review/board`, { method: 'POST' })); again(); }
    if (t.closest('[data-unboard]')) {
      const ok = await ctx.confirm({ title: 'Remove the Kist board?', body: 'The board moves to Kist\'s trash and its share link (if any) is revoked. The items stay in Kist.', confirm: 'Remove', danger: true });
      if (ok) { await busy(null, ctx, () => api(`${base}/outputs/review/board`, { method: 'DELETE' })); again(); }
    }
    if (t.closest('[data-share]')) {
      const ok = await ctx.confirm({
        title: 'Create a public share link?',
        body: `Kist will serve this board at a public /s/… address on ${r.kist_url || 'your Kist'}. Anyone with the link can view it for ${r.share_days ? `${r.share_days} days` : 'ever'} unless you revoke it${r.proofing ? '; guests can pick and comment' : ''}.`,
        confirm: 'Create link',
      });
      if (!ok) return;
      const password = el.querySelector('[data-password]')?.value || null;
      const res = await busy(t.closest('button'), ctx, () => api(`${base}/outputs/review/share`, { method: 'POST', body: { password } }));
      if (res?.share?.url) { try { await navigator.clipboard.writeText(res.share.url); ctx.toast('Share link created and copied'); } catch { ctx.toast('Share link created'); } }
      again();
    }
    if (t.closest('[data-copy-share]')) { await navigator.clipboard.writeText(r.share.url); ctx.toast('Link copied'); }
    if (t.closest('[data-revoke]')) { await busy(t.closest('button'), ctx, () => api(`${base}/outputs/review/share`, { method: 'DELETE' })); ctx.toast('Share link revoked'); again(); }
  });
}

export const reviewSheet = sheet({
  html(o) {
    return `<h3>Review in Kist</h3>
      <p class="sk-outputs-lede">This set as a Kist board, and, only if you ask, a Kist share link to it with guest proofing.</p>
      ${reviewHtml(o.review, 'this set')}`;
  },
  wire(el, o, d, ctx, again) { wireReview(el, `/designs/${enc(d.id)}`, o.review, ctx, again); },
});
