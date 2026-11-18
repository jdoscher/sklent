// App state, the poll loop, and a render signal: modules subscribe to
// `onChange` and redraw their part when data or the view changes.

import { api } from './api.js';

export const state = {
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

const listeners = [];

/** Register a redraw; called after every poll and every view change. */
export function onChange(fn) { listeners.push(fn); }

/** Redraw everything from the current state. */
export function emit() { for (const fn of listeners) fn(state); }

export function activeJobFor(designId) {
  return state.jobs.find((j) => j.design_id === designId && (j.status === 'running' || j.status === 'queued'));
}

export function visibleDesigns() {
  const q = state.query.toLowerCase();
  return state.designs.filter((d) => {
    if (state.sourceId && d.source_id !== state.sourceId) return false;
    if (state.filter === 'rendered' && d.status !== 'rendered') return false;
    if (state.filter === 'failed' && d.status !== 'failed') return false;
    if (state.filter === 'active' && !['queued', 'rendering'].includes(d.status)) return false;
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
export function schedule() {
  clearTimeout(pollTimer);
  const busy = state.jobs.some((j) => j.status === 'queued' || j.status === 'running');
  pollTimer = setTimeout(async () => {
    try { await refresh(); } catch { /* shown on next action */ }
    schedule();
  }, busy ? 2500 : 15000);
}
