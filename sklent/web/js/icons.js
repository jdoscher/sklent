// Lucide icons (lucide-static v1.75.0, ISC licence: LICENSE-lucide.txt), inlined so
// there is no build step or icon font. One stroke width (1.5) everywhere, sizes
// 14 / 16 / 20 px, one meaning per glyph (Kist's icon rules).

const PATHS = {
  'menu': '<path d="M4 5h16"/> <path d="M4 12h16"/> <path d="M4 19h16"/>',
  'link-2': '<path d="M9 17H7A5 5 0 0 1 7 7h2"/> <path d="M15 7h2a5 5 0 1 1 0 10h-2"/> <line x1="8" x2="16" y1="12" y2="12"/>',
  'palette': '<path d="M12 22a1 1 0 0 1 0-20 10 9 0 0 1 10 9 5 5 0 0 1-5 5h-2.25a1.75 1.75 0 0 0-1.4 2.8l.3.4a1.75 1.75 0 0 1-1.4 2.8z"/> <circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/> <circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/> <circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/> <circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/>',
  'settings': '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/> <circle cx="12" cy="12" r="3"/>',
  'layout-grid': '<rect width="7" height="7" x="3" y="3" rx="1"/> <rect width="7" height="7" x="14" y="3" rx="1"/> <rect width="7" height="7" x="14" y="14" rx="1"/> <rect width="7" height="7" x="3" y="14" rx="1"/>',
  'circle-check': '<circle cx="12" cy="12" r="10"/> <path d="m16 9-5.5 5.5L8 12"/>',
  'loader-circle': '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
  'triangle-alert': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/> <path d="M12 9v4"/> <path d="M12 17h.01"/>',
  'folder-git-2': '<path d="M18 19a5 5 0 0 1-5-5v8"/> <path d="M9 20H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v5"/> <circle cx="13" cy="12" r="2"/> <circle cx="20" cy="19" r="2"/>',
  'refresh-cw': '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/> <path d="M21 3v5h-5"/> <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/> <path d="M8 16H3v5"/>',
  'x': '<path d="M18 6 6 18"/> <path d="m6 6 12 12"/>',
  'clock': '<circle cx="12" cy="12" r="10"/> <path d="M12 6v6l4 2"/>',
  'circle-x': '<circle cx="12" cy="12" r="10"/> <path d="m15 9-6 6"/> <path d="m9 9 6 6"/>',
  'circle-slash': '<circle cx="12" cy="12" r="10"/> <line x1="9" x2="15" y1="15" y2="9"/>',
  'download': '<path d="M12 15V3"/> <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/> <path d="m7 10 5 5 5-5"/>',
  'external-link': '<path d="M15 3h6v6"/> <path d="M10 14 21 3"/> <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  'plus': '<path d="M5 12h14"/> <path d="M12 5v14"/>',
  'sun-moon': '<path d="M12 2v2"/> <path d="M14.837 16.385a6 6 0 1 1-7.223-7.222c.624-.147.97.66.715 1.248a4 4 0 0 0 5.26 5.259c.589-.255 1.396.09 1.248.715"/> <path d="M16 12a4 4 0 0 0-4-4"/> <path d="m19 5-1.256 1.256"/> <path d="M20 12h2"/>',
};

/** `<svg>` markup for a Lucide icon: icon('x', 14). Decorative (aria-hidden); give the
 * button around it an aria-label. */
export function icon(name, size = 16, cls = '') {
  const body = PATHS[name];
  if (!body) throw new Error(`no icon ${name}`);
  return `<svg class="lucide i${size}${cls ? ` ${cls}` : ''}" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

export const ICONS = Object.keys(PATHS);
