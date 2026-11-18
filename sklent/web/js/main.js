// Boot: theme, token gate, first load, top-bar actions, keyboard.

import { api, readToken, saveToken, setToken, setUnauthorizedHandler } from './api.js';
import { closeDetail, initDetail, refreshDetail } from './detail.js';
import { $, $$ } from './dom.js';
import './features.js';
import { initGrid, renderGrid } from './grid.js';
import { icon } from './icons.js';
import { closeSettings, initSettings } from './settings.js';
import { closeDrawer, initSidebar, renderSidebar } from './sidebar.js';
import { onChange, refresh, schedule, state } from './store.js';
import { closeMenu, initTheme } from './theme.js';
import { toast } from './toast.js';

// static icons in the markup: data-icon="name" or "name:size"
$$('[data-icon]').forEach((el) => {
  const [name, size] = el.dataset.icon.split(':');
  el.insertAdjacentHTML('afterbegin', icon(name, Number(size) || 16));
});

function showGate(err = '') {
  $('#app').hidden = true;
  $('#gate').hidden = false;
  $('#gate-error').textContent = err;
  $('#gate-host').textContent = location.host;
  fetch('/api/health').then((r) => r.json()).then((h) => { $('#gate-version').textContent = `sklent ${h.version}`; }).catch(() => {});
  $('#gate-token').focus();
}
setUnauthorizedHandler(showGate);

function showKist(k) {
  const chip = $('#kist-chip');
  chip.className = `kist-status ${k.url ? (k.reachable ? 'ok' : 'bad') : 'off'}`;
  $('.kist-word', chip).textContent = k.url ? (k.reachable ? 'Kist' : 'Kist unreachable') : 'Kist off';
  chip.title = k.url ? `${k.reachable ? 'Connected to' : 'Can’t reach'} ${k.url}; sets are filed under ${k.root_folder}/…` : 'Set SK_KIST_URL to file renders into Kist';
}

async function start() {
  try {
    state.status = await api('/status');
  } catch (e) {
    if (e.message !== 'unauthorized') showGate(e.message);
    return;
  }
  $('#gate').hidden = true;
  $('#app').hidden = false;
  showKist(state.status.kist);
  await refresh();
  schedule();
}

initTheme();
// the phone's pill field is narrow: a shorter hint
const narrow = window.matchMedia('(max-width: 760px)');
const hint = () => { $('#url').placeholder = narrow.matches ? 'Repo, folder or .sc URL' : 'Paste a GitHub or Forgejo URL: account, repo, folder or .sc file'; };
narrow.addEventListener('change', hint);
hint();
onChange(renderSidebar);
onChange(renderGrid);
onChange(refreshDetail);
initSidebar();
initGrid();
initDetail();
initSettings();

$('#gate-form').addEventListener('submit', (e) => {
  e.preventDefault();
  saveToken($('#gate-token').value.trim());
  start();
});

$('#url-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const url = $('#url').value.trim();
  if (!url) { $('#url').focus(); return; }
  const btn = $('#url-form .primary');
  btn.disabled = true;
  try {
    const r = await api('/render-url', { method: 'POST', body: { url } });
    toast(r.scan);
    $('#url').value = '';
    state.sourceId = r.source.id;
    await refresh(); schedule();
  } catch (err) { toast(err.message, { bad: true }); } finally { btn.disabled = false; }
});

$('#add-only').addEventListener('click', async () => {
  const url = $('#url').value.trim();
  if (!url) { $('#url').focus(); return; }
  try {
    await api('/sources', { method: 'POST', body: { url, auto_render: false } });
    toast('Source added; scanning without rendering');
    $('#url').value = '';
    await refresh(); schedule();
  } catch (err) { toast(err.message, { bad: true }); }
});

// Escape closes the topmost float: menu, confirm (its own handler), settings, sheet, drawer
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !$('#confirm').hidden) return;
  if (closeMenu() || closeSettings() || closeDetail() || closeDrawer()) e.preventDefault();
});

const saved = readToken();
if (saved) { saveToken(saved); start(); } else { setToken(''); showGate(); }
