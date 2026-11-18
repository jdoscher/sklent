// One grid tile per design (UI 9a): a clean figure (the render, never drawn over)
// and a label strip under it: the name, then a mono spec line
// (`95 × 66 × 32 mm · 1 body · 1258878`), or the job while one runs.
//
// Seam: registerTileBadge(fn) where fn(design) -> { text, title } | null. Badges sit
// at the right of the name line as small neutral chips (e.g. a revision count).

import { esc } from './dom.js';
import { envelope, plural, splitExt } from './format.js';
import { icon } from './icons.js';
import { activeJobFor, state } from './store.js';

const badgeFns = [];

/** Add a tile badge: fn(design) -> { text, title } | null. */
export function registerTileBadge(fn) {
  if (typeof fn !== 'function') throw new Error('registerTileBadge needs a function');
  badgeFns.push(fn);
}

function badges(d) {
  const out = [];
  for (const fn of badgeFns) {
    try {
      const b = fn(d);
      if (b && b.text) out.push(`<span class="badge" title="${esc(b.title || '')}">${esc(b.text)}</span>`);
    } catch (err) { console.error('tile badge', err); }
  }
  return out.length ? `<span class="badges">${out.join('')}</span>` : '';
}

const SEP = '<span class="sep">·</span>';

/** The spec line: the job while it works, the failure, else envelope · bodies · revision. */
export function specLine(d) {
  const job = activeJobFor(d.id);
  if (job && job.status === 'running') {
    const m = (job.message || '').match(/frame (\d+)\/(\d+)/);
    return `rendering${SEP}${m ? `frame ${m[1]}/${m[2]}` : esc(job.message || 'starting')}`;
  }
  if (job && job.status === 'queued') {
    const line = state.jobs.filter((j) => j.status === 'queued' && j.kind === 'render').sort((a, b) => a.id - b.id);
    const n = line.findIndex((j) => j.id === job.id) + 1;
    return `queued${n ? `${SEP}${n} of ${line.length} in line` : ''}`;
  }
  if (d.status === 'failed') {
    return `<span class="bad">failed</span>${SEP}<span class="bad" title="${esc(d.error || '')}">${esc((d.error || 'no reason given').slice(0, 120))}</span>`;
  }
  const r = d.report || {};
  const spec = d.spec || {};
  const parts = [];
  if (d.stale) parts.push('<span class="warn">changed</span>');
  const env = envelope(spec.bounds_mm || r.bounds_mm);
  if (env) parts.push(`${env} mm`);
  const bodies = spec.bodies ?? r.bodies;
  if (bodies != null) parts.push(`<span class="opt">${plural(bodies, 'body', 'bodies')}</span>`);
  const rev = (d.blob || d.commit || '').slice(0, 7);
  if (rev) parts.push(`<span class="opt">${esc(rev)}</span>`);
  if (!parts.length) return esc(d.status);
  // the separator before an optional part hides with it on the phone
  return parts.map((p, i) => (i === 0 ? p : p.startsWith('<span class="opt">') ? p.replace('<span class="opt">', `<span class="opt">${SEP}`) : SEP + p)).join('');
}

function placeholder(d, job) {
  if (d.status === 'failed') return `${icon('triangle-alert', 20)}<span class="w">Failed</span>`;
  if (job && job.status === 'running') return `${icon('loader-circle', 20, 'spin')}<span class="w">Rendering</span>`;
  if (job || d.status === 'queued') return `${icon('clock', 20)}<span class="w">Queued</span>`;
  return `${icon('clock', 20)}<span class="w">${esc(d.status[0].toUpperCase() + d.status.slice(1))}</span>`;
}

export function tile(d) {
  const job = activeJobFor(d.id);
  const [stem, ext] = splitExt(d.name);
  const fig = d.thumb_url
    ? `<img src="${esc(d.thumb_url)}" data-still="${esc(d.thumb_url)}" data-gif="${esc(d.gif_url || '')}" loading="lazy" decoding="async" alt="" />`
    : `<div class="placeholder">${placeholder(d, job)}</div>`;
  const pct = job && job.status === 'running' ? Math.round(job.progress * 100) : null;
  const rule = pct != null
    ? `<div class="rule"><i style="width:${pct}%"></i><b style="left:${Math.min(96, Math.max(4, pct))}%">${pct}%</b></div>` : '';
  return `<div class="tile" data-design="${esc(d.id)}" role="button" tabindex="0" aria-label="${esc(d.name)}, ${esc(d.stale ? 'changed' : d.status)}">
    <div class="fig">${fig}${rule}</div>
    <div class="label">
      <div class="n"><span class="stem">${esc(stem)}<span class="ext sk-data">${esc(ext)}</span></span>${badges(d)}</div>
      <span class="spec sk-data">${specLine(d)}</span>
    </div>
  </div>`;
}
