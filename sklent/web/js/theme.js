// Themes (U1-1): Kist's three, gallery by default, plus System. The Appearance menu
// is a float of theme chips; each swatch carries its theme's own tokens.

import { $, $$ } from './dom.js';

const KEY = 'sk.theme';
const CHOICES = [
  ['gallery', 'Gallery grey'],
  ['dark', 'Dark'],
  ['light', 'Light'],
  ['system', 'System'],
];
const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

export function storedTheme() {
  try { return localStorage.getItem(KEY) || 'gallery'; } catch { return 'gallery'; }
}

function resolve(choice) {
  if (choice === 'system') return media && media.matches ? 'light' : 'dark';
  return ['dark', 'light'].includes(choice) ? choice : 'gallery';
}

export function applyTheme(choice = storedTheme()) {
  const root = document.documentElement;
  const theme = resolve(choice);
  root.dataset.theme = theme;
  root.style.colorScheme = theme === 'light' ? 'light' : 'dark';
  root.style.backgroundColor = '';
  const chrome = getComputedStyle(root).getPropertyValue('--chrome').trim();
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta && chrome) meta.setAttribute('content', chrome);
}

function setTheme(choice) {
  try { localStorage.setItem(KEY, choice); } catch { /* private mode */ }
  applyTheme(choice);
  renderMenu();
}

function renderMenu() {
  const current = storedTheme();
  $('#menu-appearance').innerHTML = `<span class="caps">Theme</span>${CHOICES.map(([id, label]) => `
    <button type="button" role="menuitemradio" aria-checked="${id === current}" data-theme-choice="${id}">
      <span class="theme-sw ${id === 'system' ? 'system' : ''}" ${id === 'system' ? '' : `data-theme="${id}"`}></span>${label}
    </button>`).join('')}`;
}

let opener = null;
function openMenu(btn) {
  const menu = $('#menu-appearance');
  renderMenu();
  menu.hidden = false;
  const r = btn.getBoundingClientRect();
  const w = menu.offsetWidth;
  menu.style.top = `${Math.round(r.bottom + 6)}px`;
  menu.style.left = `${Math.round(Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w)))}px`;
  opener = btn;
  btn.setAttribute('aria-expanded', 'true');
  (menu.querySelector('[aria-checked=true]') || menu.querySelector('button')).focus();
}

export function closeMenu() {
  const menu = $('#menu-appearance');
  if (menu.hidden) return false;
  menu.hidden = true;
  if (opener) { opener.setAttribute('aria-expanded', 'false'); opener.focus(); }
  opener = null;
  return true;
}

export function initTheme() {
  applyTheme();
  if (media) media.addEventListener('change', () => { if (storedTheme() === 'system') applyTheme('system'); });
  $$('#open-appearance, [data-open=appearance]').forEach((b) => b.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!$('#menu-appearance').hidden) closeMenu(); else openMenu(b);
  }));
  $('#menu-appearance').addEventListener('click', (e) => {
    const b = e.target.closest('[data-theme-choice]');
    if (b) setTheme(b.dataset.themeChoice);
  });
  $('#menu-appearance').addEventListener('keydown', (e) => {
    const items = $$('#menu-appearance [role=menuitemradio]');
    const i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus();
    }
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#menu-appearance')) closeMenu();
  });
}
