// The REST client. `api(path, opts)` is the seam every module (and phase-2
// feature code) uses: JSON in and out, the bearer token attached, a 401 sends
// the user back to the token gate.

const TOKEN_KEY = 'sk_token';
let token = '';
let onUnauthorized = () => {};

export function readToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}

export function saveToken(t) {
  token = t;
  try { localStorage.setItem(TOKEN_KEY, t); } catch { /* private mode */ }
  document.cookie = `${TOKEN_KEY}=${encodeURIComponent(t)}; path=/; SameSite=Strict; max-age=31536000`;
}

export function setToken(t) { token = t; }

/** Called with a message when the server refuses the token. */
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    ...opts,
    headers: { Authorization: `Bearer ${token}`, ...(opts.body ? { 'Content-Type': 'application/json' } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) { onUnauthorized('That token was not accepted.'); throw new Error('unauthorized'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`);
  return data;
}
