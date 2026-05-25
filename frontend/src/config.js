// Central app configuration. Every service should pull values from here
// instead of reading `import.meta.env` directly — that way switching
// between local and hosted backends is a single edit (in `.env`).

// Vite exposes env vars at build time. Anything you want available in
// the client MUST be prefixed `VITE_` (other prefixes are silently
// stripped). To switch backends, edit `frontend/.env` and restart
// `npm run dev` — Vite only re-reads env files on server start.
const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1';

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;

// WebSocket base — derived from the HTTP base by swapping the scheme.
// http://  → ws://    (local dev)
// https:// → wss://   (Railway, Vercel, any TLS-terminated host)
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws');
