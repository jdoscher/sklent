// Boot: token gate, first load, top-bar actions, keyboard.

import { api, readToken, saveToken, setToken, setUnauthorizedHandler } from './api.js';
import { initDetail, refreshDetail } from './detail.js';
import { $, $$ } from './dom.js';
import { initGrid, renderGrid } from './grid.js';
import { initSettings } from './settings.js';
import { initSidebar, renderSidebar } from './sidebar.js';
import { emit, onChange, refresh, schedule, state } from './store.js';
import { toast } from './toast.js';

function showGate(err = '') {
  $('#app').hidden = true;
  $('#gate').hidden = false;
  $('#gate-error').textContent = err;
}
setUnauthorizedHandler(showGate);

async function start() {
  try {
    state.status = await api('/status');
  } catch (e) {
    if (e.message !== 'unauthorized') showGate(e.message);
    return;
  }
  $('#gate').hidden = true;
  $('#app').hidden = false;
  const k = state.status.kist;
  const chip = $('#kist-chip');
  chip.textContent = k.url ? (k.reachable ? 'Kist connected' : 'Kist unreachable') : 'Kist off';
  chip.className = `chip ${k.url ? (k.reachable ? 'ok' : 'bad') : ''}`;
  chip.title = k.url ? `${k.url} → ${k.root_folder}/…` : 'Set SK_KIST_URL to file renders into Kist';
  await refresh();
  schedule();
}

onChange(renderSidebar);
onChange(renderGrid);
onChange(refreshDetail);
initSidebar();
initGrid();
initDetail();
initSettings();

$('#gate-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  saveToken($('#gate-token').value.trim());
  start();
});

$('#url-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const url = $('#url').value.trim();
  if (!url) return;
  const btn = $('#url-form .primary');
  btn.disabled = true;
  try {
    const r = await api('/render-url', { method: 'POST', body: { url } });
    toast(`${r.scan}`);
    $('#url').value = '';
    state.sourceId = r.source.id;
    await refresh(); schedule();
  } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
});

$('#add-only').addEventListener('click', async () => {
  const url = $('#url').value.trim();
  if (!url) return;
  try {
    await api('/sources', { method: 'POST', body: { url, auto_render: false } });
    toast('Source added; scanning without rendering');
    $('#url').value = '';
    await refresh(); schedule();
  } catch (err) { toast(err.message, true); }
});

$('#search').addEventListener('input', (e) => { state.query = e.target.value; emit(); });

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') $$('.overlay').forEach((o) => { if (!o.hidden) o.click(); });
});

const saved = readToken();
if (saved) { saveToken(saved); start(); } else { setToken(''); showGate(); }
