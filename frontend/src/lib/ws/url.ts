/**
 * WebSocket URL construction.
 *
 * Two env vars, in precedence order:
 *
 * - `VITE_WS_BASE_URL` — an explicit WebSocket origin + prefix
 *   (`ws://localhost:8000/api/v1`). Needed when the socket does not live where
 *   the HTTP API lives: a separate host, or a dev server whose proxy handles
 *   `/api` but not upgrades.
 * - `VITE_API_BASE_URL` — the HTTP base, with its scheme swapped to `ws`.
 *
 * With neither set it falls back to the page's own origin and the default
 * `/api/v1` prefix, which is what the Vite dev proxy and the production Nginx
 * build both serve.
 *
 * Both socket hooks build their URLs here, so there is one answer to "where is
 * the WebSocket" rather than one per hook.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
const WS_BASE = import.meta.env.VITE_WS_BASE_URL;

export function buildWsUrl(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;

  if (WS_BASE) {
    return `${WS_BASE.replace(/\/$/, '')}${suffix}`;
  }
  if (/^https?:\/\//.test(API_BASE)) {
    return `${API_BASE.replace(/^http/, 'ws')}${suffix}`;
  }
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}${API_BASE}${suffix}`;
}
