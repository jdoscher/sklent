// Formatting shared by the grid, the detail sheet and phase-2 sections.

export const VARIANT_LABEL = {
  '1080p': '1080p movie', reel: 'Instagram reel', discord: 'Discord 640p',
  gif: 'GIF', social: 'Social still', hires: 'High-res still',
};

export function fmtBytes(n) {
  if (n == null) return '';
  return n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.round(n / 1e3)} KB`;
}

export const CUBE = '<svg viewBox="0 0 64 64"><path d="M32 6 55 19v26L32 58 9 45V19Z" fill="none" stroke="currentColor" stroke-width="4" stroke-linejoin="round"/><path d="M9 19l23 13 23-13M32 32v26" fill="none" stroke="currentColor" stroke-width="3"/></svg>';
