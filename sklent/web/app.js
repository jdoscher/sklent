'use strict';

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const TOKEN_KEY = 'sk_token';

const state = {
  token: '',
  filter: 'all',
  sourceId: null,
  query: '',
  designs: [],
  sources: [],
  jobs: [],
  status: null,
  detail: null,
  detailFile: null,
};

const VARIANT_LABEL = {
  '1080p': '1080p movie', reel: 'Instagram reel', discord: 'Discord 640p',
  gif: 'GIF', social: 'Social still', hires: 'High-res still',
};
const CUBE = '<svg viewBox="0 0 64 64"><path d="M32 6 55 19v26L32 58 9 45V19Z" fill="none" stroke="currentColor" stroke-width="4" stroke-linejoin="round"/><path d="M9 19l23 13 23-13M32 32v26" fill="none" stroke="currentColor" stroke-width="3"/></svg>';

// ------------------------------------------------------------ api

function readToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}
function saveToken(t) {
  try { localStorage.setItem(TOKEN_KEY, t); } catch { /* private mode */ }
  document.cookie = `${TOKEN_KEY}=${encodeURIComponent(t)}; path=/; SameSite=Strict; max-age=31536000`;
}

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    ...opts,
    headers: { Authorization: `Bearer ${state.token}`, ...(opts.body ? { 'Content-Type': 'application/json' } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) { showGate('That token was not accepted.'); throw new Error('unauthorized'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`);
  return data;
}

function toast(msg, bad = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = `toast${bad ? ' bad' : ''}`;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, bad ? 7000 : 3500);
}

// ------------------------------------------------------------ gate

function showGate(err = '') {
  $('#app').hidden = true;
  $('#gate').hidden = false;
  $('#gate-error').textContent = err;
}

$('#gate-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  state.token = $('#gate-token').value.trim();
  saveToken(state.token);
  start();
});

// ------------------------------------------------------------ loading

async function refresh() {
  const [designs, sources, jobs] = await Promise.all([
    api('/designs'), api('/sources'), api('/jobs?limit=25'),
  ]);
  state.designs = designs;
  state.sources = sources;
  state.jobs = jobs;
  render();
  if (state.detail) {
    const fresh = designs.find((d) => d.id === state.detail.id);
    if (fresh && JSON.stringify(fresh) !== JSON.stringify(state.detail)) openDetail(fresh, true);
  }
}

let pollTimer;
function schedule() {
  clearTimeout(pollTimer);
  const busy = state.jobs.some((j) => j.status === 'queued' || j.status === 'running');
  pollTimer = setTimeout(async () => {
    try { await refresh(); } catch { /* shown on next action */ }
    schedule();
  }, busy ? 2500 : 15000);
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
  const k = state.status.kist;
  const chip = $('#kist-chip');
  chip.textContent = k.url ? (k.reachable ? 'Kist connected' : 'Kist unreachable') : 'Kist off';
  chip.className = `chip ${k.url ? (k.reachable ? 'ok' : 'bad') : ''}`;
  chip.title = k.url ? `${k.url} → ${k.root_folder}/…` : 'Set SK_KIST_URL to file renders into Kist';
  await refresh();
  schedule();
}

// ------------------------------------------------------------ rendering

function activeJobFor(designId) {
  return state.jobs.find((j) => j.design_id === designId && (j.status === 'running' || j.status === 'queued'));
}

function visibleDesigns() {
  const q = state.query.toLowerCase();
  return state.designs.filter((d) => {
    if (state.sourceId && d.source_id !== state.sourceId) return false;
    if (state.filter === 'rendered' && d.status !== 'rendered') return false;
    if (state.filter === 'failed' && d.status !== 'failed') return false;
    if (state.filter === 'active' && !['queued', 'rendering'].includes(d.status)) return false;
    return !q || `${d.name} ${d.repo} ${d.path}`.toLowerCase().includes(q);
  });
}

function render() {
  const c = (f) => state.designs.filter(f).length;
  $('#count-all').textContent = state.designs.length;
  $('#count-rendered').textContent = c((d) => d.status === 'rendered');
  $('#count-active').textContent = c((d) => ['queued', 'rendering'].includes(d.status)) || '';
  $('#count-failed').textContent = c((d) => d.status === 'failed') || '';
  $$('.sidebar [data-filter]').forEach((el) => el.classList.toggle('active', !state.sourceId && el.dataset.filter === state.filter));

  $('#sources').innerHTML = state.sources.length ? state.sources.map((s) => `
    <div class="row ${state.sourceId === s.id ? 'active' : ''}" data-source="${esc(s.id)}" title="${esc(s.url)}${s.last_error ? `\n\n${esc(s.last_error)}` : ''}">
      <span class="name">${s.last_error ? '<span class="warn">⚠</span> ' : ''}${esc(s.label)}</span>
      <span class="count">${s.designs}</span>
      <span class="row-actions">
        <button class="icon" data-scan="${esc(s.id)}" title="Scan now">⟳</button>
        <button class="icon" data-remove="${esc(s.id)}" title="Remove source">✕</button>
      </span>
    </div>`).join('') : '<div class="empty">Paste a GitHub or Forgejo URL above.</div>';

  $('#jobs').innerHTML = state.jobs.length ? state.jobs.slice(0, 12).map((j) => {
    const what = j.kind === 'scan' ? `Scan ${(j.source_url || '').replace(/^https?:\/\//, '')}` : (j.design_path || '').split('/').pop();
    const msg = j.error || j.message || '';
    return `<div class="job">
      <div class="line"><span class="what" title="${esc(what)}">${esc(what)}</span><span class="state ${esc(j.status)}">${esc(j.status)}</span></div>
      ${msg ? `<div class="msg" title="${esc(msg)}">${esc(msg)}</div>` : ''}
      ${j.status === 'running' ? `<div class="bar"><i style="width:${Math.round(j.progress * 100)}%"></i></div>` : ''}
    </div>`;
  }).join('') : '<div class="empty">No jobs yet.</div>';

  const list = visibleDesigns();
  const src = state.sources.find((s) => s.id === state.sourceId);
  $('#grid-meta').textContent = `${list.length} design${list.length === 1 ? '' : 's'}${src ? ` in ${src.label}` : ''}`;
  $('#grid').innerHTML = list.length ? list.map(tile).join('') : `<div class="empty-grid">${state.designs.length ? 'Nothing matches.' : 'No designs yet. Paste a repo URL above and press Render.'}</div>`;
}

function tile(d) {
  const job = activeJobFor(d.id);
  const badge = d.stale ? 'stale' : d.status === 'rendered' ? '' : d.status;
  const body = d.thumb_url
    ? `<img src="${esc(d.thumb_url)}" data-still="${esc(d.thumb_url)}" data-gif="${esc(d.gif_url || '')}" loading="lazy" alt="" />`
    : `<div class="placeholder">${CUBE}<span>${esc(d.status === 'failed' ? (d.error || 'failed').slice(0, 120) : d.status)}</span></div>`;
  return `<div class="tile" data-design="${esc(d.id)}">
    ${body}
    ${badge ? `<span class="badge ${esc(badge)}">${esc(badge)}</span>` : ''}
    <div class="tile-caption"><div class="n">${esc(d.name)}</div><div class="r">${esc(d.repo)}</div></div>
    ${job && job.status === 'running' ? `<div class="bar"><i style="width:${Math.round(job.progress * 100)}%"></i></div>` : ''}
  </div>`;
}

// hover plays the turntable GIF, as Kist's grid will
$('#grid').addEventListener('mouseover', (e) => {
  const img = e.target.closest('img[data-gif]');
  if (img && img.dataset.gif && img.src.indexOf(img.dataset.gif) < 0) img.src = img.dataset.gif;
});
$('#grid').addEventListener('mouseout', (e) => {
  const img = e.target.closest('img[data-still]');
  if (img && !img.contains(e.relatedTarget)) img.src = img.dataset.still;
});

// ------------------------------------------------------------ detail

function fmtBytes(n) {
  if (n == null) return '';
  return n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.round(n / 1e3)} KB`;
}

function openDetail(d, keepFile = false) {
  state.detail = d;
  if (!keepFile || !d.files.some((f) => f.file === state.detailFile)) {
    state.detailFile = (d.files.find((f) => f.style === 'shaded' && f.variant === '1080p') || d.files[0] || {}).file || null;
  }
  const file = d.files.find((f) => f.file === state.detailFile);
  const viewer = $('#viewer');
  const current = viewer.dataset.file;
  if (current !== (file ? file.file : '')) {
    viewer.dataset.file = file ? file.file : '';
    viewer.innerHTML = !file ? `<div class="placeholder dim">${CUBE}<p>${esc(d.status)}</p></div>`
      : file.file.endsWith('.mp4') ? `<video src="${esc(file.url)}" controls autoplay loop muted playsinline></video>`
        : `<img src="${esc(file.url)}" alt="" />`;
  }
  const kist = state.status.kist;
  const job = activeJobFor(d.id);
  const groups = ['shaded', 'wireframe'].map((style) => {
    const fs = d.files.filter((f) => f.style === style);
    if (!fs.length) return '';
    return `<h3>${style}</h3>${fs.map((f) => `
      <div class="file ${f.file === state.detailFile ? 'active' : ''}" data-file="${esc(f.file)}">
        <span class="label">${esc(VARIANT_LABEL[f.variant] || f.variant)} <span class="dim">${f.width}×${f.height}</span></span>
        <span class="size">${fmtBytes(f.bytes)}</span>
        <a href="${esc(f.url)}" download="${esc(f.file)}" title="Download" onclick="event.stopPropagation()">↓</a>
      </div>`).join('')}`;
  }).join('');
  $('#detail-side').innerHTML = `
    <h2>${esc(d.name)}</h2>
    <div class="meta">
      <a href="${esc(d.html_url)}" target="_blank" rel="noopener">${esc(d.repo)}/${esc(d.path)}</a><br />
      ${esc(d.ref)} @ ${esc(d.commit)} · ${esc(d.stale ? 'changed since last render' : d.status)}
      ${d.rendered_at ? `<br />rendered ${esc(new Date(d.rendered_at).toLocaleString())}` : ''}
      ${d.kist_items.length && kist.url ? `<br />filed in <a href="${esc(kist.url)}" target="_blank" rel="noopener">Kist</a>: ${esc(kist.root_folder)}/${esc(d.repo)}/${esc(d.name.replace(/\.[^.]+$/, ''))}` : ''}
    </div>
    ${d.error ? `<p class="error">${esc(d.error)}</p>` : ''}
    ${job ? `<p class="dim">${esc(job.status)}: ${esc(job.message || '')}</p><div class="bar"><i style="width:${Math.round(job.progress * 100)}%"></i></div>` : ''}
    <div class="actions">
      <button class="primary" data-render="${esc(d.id)}" ${job ? 'disabled' : ''}>${d.status === 'rendered' && !d.stale ? 'Re-render' : 'Render'}</button>
    </div>
    ${groups || '<p class="dim">No files yet.</p>'}`;
  $('#detail').hidden = false;
}

$('#detail').addEventListener('click', async (e) => {
  if (e.target === e.currentTarget || e.target.closest('[data-close]')) {
    $('#detail').hidden = true;
    state.detail = null;
    $('#viewer').innerHTML = '';
    $('#viewer').dataset.file = '';
    return;
  }
  const f = e.target.closest('[data-file]');
  if (f) { state.detailFile = f.dataset.file; openDetail(state.detail, true); return; }
  const r = e.target.closest('[data-render]');
  if (r) {
    try {
      await api(`/designs/${r.dataset.render}/render`, { method: 'POST', body: { force: true } });
      toast('Render queued');
      await refresh(); schedule();
    } catch (err) { toast(err.message, true); }
  }
});

// ------------------------------------------------------------ actions

$('.sidebar').addEventListener('click', async (e) => {
  const scan = e.target.closest('[data-scan]');
  const remove = e.target.closest('[data-remove]');
  try {
    if (scan) {
      await api(`/sources/${scan.dataset.scan}/scan`, { method: 'POST' });
      toast('Scan queued');
    } else if (remove) {
      const s = state.sources.find((x) => x.id === remove.dataset.remove);
      if (!confirm(`Remove ${s.label}? Its local renders are deleted; items already in Kist stay.`)) return;
      await api(`/sources/${remove.dataset.remove}`, { method: 'DELETE' });
      if (state.sourceId === remove.dataset.remove) state.sourceId = null;
    } else {
      const row = e.target.closest('[data-source], [data-filter]');
      if (!row) return;
      if (row.dataset.source) { state.sourceId = state.sourceId === row.dataset.source ? null : row.dataset.source; }
      else { state.sourceId = null; state.filter = row.dataset.filter; }
      render();
      return;
    }
    await refresh(); schedule();
  } catch (err) { toast(err.message, true); }
});

$('#grid').addEventListener('click', (e) => {
  const t = e.target.closest('[data-design]');
  if (t) openDetail(state.designs.find((d) => d.id === t.dataset.design));
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

$('#search').addEventListener('input', (e) => { state.query = e.target.value; render(); });

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') $$('.overlay').forEach((o) => { if (!o.hidden) o.click(); });
});

// ------------------------------------------------------------ settings

$('#open-settings').addEventListener('click', async () => {
  const s = await api('/settings');
  $('#palettes').innerHTML = state.status.palettes.map((p) => `
    <label><input type="radio" name="palette" value="${esc(p.name)}" ${p.name === s.palette ? 'checked' : ''} hidden />
    <span class="swatch" style="background:${esc(p.shaded)}"></span>${esc(p.label)}</label>`).join('');
  const form = $('#settings-form');
  for (const k of ['seconds', 'fps', 'pitch_deg', 'social_size', 'hires_width', 'hires_height', 'gif_width', 'gif_fps']) form.elements[k].value = s[k];
  $$('input[name=style]', form).forEach((cb) => { cb.checked = s.styles.includes(cb.value); });
  $('#settings-error').textContent = '';
  $('#settings').hidden = false;
});

$('#settings').addEventListener('click', (e) => {
  if (e.target === e.currentTarget || e.target.closest('[data-close]')) $('#settings').hidden = true;
});

$('#settings-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const num = (k) => Number(f[k].value);
  try {
    await api('/settings', {
      method: 'PUT',
      body: {
        palette: $('input[name=palette]:checked', e.target).value,
        seconds: num('seconds'), fps: num('fps'), pitch_deg: num('pitch_deg'),
        social_size: num('social_size'), hires_width: num('hires_width'), hires_height: num('hires_height'),
        gif_width: num('gif_width'), gif_fps: num('gif_fps'),
        styles: $$('input[name=style]:checked', e.target).map((c) => c.value),
      },
    });
    $('#settings').hidden = true;
    toast('Settings saved; they apply to the next renders');
  } catch (err) { $('#settings-error').textContent = err.message; }
});

// ------------------------------------------------------------ boot

state.token = readToken();
if (state.token) { saveToken(state.token); start(); } else showGate();
