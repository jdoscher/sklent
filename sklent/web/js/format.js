// Formatting shared by the grid, the drawing sheet and phase-2 sections. Spec values
// (sizes, hashes, envelopes, dates) are set in mono by the caller (.sk-data).

export const VARIANT_LABEL = {
  '1080p': '1080p movie', reel: 'Reel', discord: 'Discord',
  gif: 'GIF', social: 'Social still', hires: 'High-res still',
};

/** Discord's free upload cap, shown as the discord file's budget. */
export const DISCORD_MB = 10;

export function fmtBytes(n) {
  if (n == null) return '—';
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`;
}

/** `1 body`, `2 bodies`, `1,418 bodies`. */
export function plural(n, one, many = `${one}s`) {
  return `${Number(n).toLocaleString('en-US')} ${n === 1 ? one : many}`;
}

/** [stem, ext]: 'pi-case.sc' -> ['pi-case', '.sc']. */
export function splitExt(name) {
  const m = String(name).match(/^(.*?)(\.[^.]+)$/);
  return m ? [m[1], m[2]] : [String(name), ''];
}

/** An axis-aligned box [[x,y,z] min, [x,y,z] max] in mm -> '95 × 66 × 32' (null if none). */
export function envelope(bounds) {
  if (!bounds || bounds.length !== 2) return null;
  const f = (v) => (v >= 100 ? v.toFixed(0) : v.toFixed(1).replace(/\.0$/, ''));
  return bounds[1].map((v, i) => f(Math.abs(v - bounds[0][i]))).join(' × ');
}

/** Local time in ISO order to the minute: a drawing's date field. */
export function isoTime(t) {
  if (!t) return '—';
  const d = new Date(t);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** Mass in grams -> '84 g' / '1.25 kg'. */
export function fmtMass(g) {
  if (g == null || Number.isNaN(Number(g))) return null;
  const n = Number(g);
  return n >= 1000 ? `${(n / 1000).toFixed(2).replace(/\.?0+$/, '')} kg` : `${n < 10 ? n.toFixed(1) : Math.round(n)} g`;
}

/** The job log's message, tidied: '12 files (1 body) · filed 12 in Kist'. */
export function jobMessage(j) {
  const m = j.error || j.message || '';
  return m.replace(/\b1 bodies\b/, '1 body').replace(/^rendered (\d[\d,]* files?)/, '$1').replace(/ and filed (\d+) in Kist/, ' · filed $1 in Kist');
}

/** The S-in-a-ring mark as a 1.5 px outline with a solid ink square: empty states. */
export const OUTLINE_MARK = '<svg class="outline" viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="22" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M40 23.5c-1.5-3-4.5-4.5-8-4.5-4.5 0-7.5 2.6-7.5 6.2 0 8.3 15.5 4.6 15.5 13.3 0 3.6-3.3 6.5-8 6.5-3.7 0-6.8-1.8-8.3-4.8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><rect class="dot" x="48" y="48" width="6" height="6" rx="1"/></svg>';
