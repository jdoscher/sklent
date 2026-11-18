// App state, the poll loop and a redraw signal. Modules subscribe with onChange()
// and redraw their part after every poll and every change of view.

import { api } from './api.js';

export const state = {
  filter: 'all',        // all | rendered | active | failed
  sourceId: null,       // a source's id narrows the grid to it
  query: '',
  designs: [],
  sources: [],
  jobs: [],
  status: null,         // /api/status: kist, palettes, ...
  detail: null,         // the design open in the drawing sheet
  detailFile: null,     // its open sheet: a file name, or `section:<id>`
};

const listeners = [];

/** Register a redraw: fn(state), called after every poll and view change. */
export function onChange(fn) { listeners.push(fn); }

/** Redraw everything from the current state. */
export function emit() { for (const fn of listeners) fn(state); }

const ACTIVE = new Set(['queued', 'running']);

/** The queued or running job of a design, if any. */
export function activeJobFor(designId) {
  return state.jobs.find((j) => j.design_id === designId && ACTIVE.has(j.status));
}

export function isBusy(d) { return d.status === 'queued' || d.status === 'rendering'; }

export function visibleDesigns() {
  const q = state.query.trim().toLowerCase();
  return state.designs.filter((d) => {
    if (state.sourceId && d.source_id !== state.sourceId) return false;
    if (state.filter === 'rendered' && d.status !== 'rendered') return false;
    if (state.filter === 'failed' && d.status !== 'failed') return false;
    if (state.filter === 'active' && !isBusy(d)) return false;
    return !q || `${d.name} ${d.repo} ${d.path}`.toLowerCase().includes(q);
  });
}

export async function refresh() {
  const [designs, sources, jobs] = await Promise.all([
    api('/designs'), api('/sources'), api('/jobs?limit=25'),
  ]);
  state.designs = designs;
  state.sources = sources;
  state.jobs = jobs;
  emit();
}

let pollTimer;
/** Poll again soon: every 2.5 s while anything is queued or running, else 15 s. */
export function schedule() {
  clearTimeout(pollTimer);
  const busy = state.jobs.some((j) => ACTIVE.has(j.status));
  pollTimer = setTimeout(async () => {
    try { await refresh(); } catch { /* shown on the next action */ }
    schedule();
  }, busy ? 2500 : 15000);
}
