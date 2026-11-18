// What every registered section, sheet and badge is handed: the live state and the
// app's verbs, so phase-2 code never reaches into another module's internals.

import { api } from './api.js';
import { confirmDialog } from './confirm.js';
import { $, $$, esc } from './dom.js';
import * as format from './format.js';
import { icon } from './icons.js';
import { activeJobFor, emit, refresh, schedule, state } from './store.js';
import { toast } from './toast.js';

export const ctx = {
  state,            // read-only by convention; change the view through emit()
  api,              // api(path, opts) -> JSON
  refresh,          // reload designs, sources and jobs, then redraw
  schedule,         // restart the poll loop (call after queueing work)
  emit,             // redraw from state
  toast,            // toast(msg, { bad, action })
  confirm: confirmDialog,
  activeJobFor,
  icon, esc, $, $$,
  format,
};
