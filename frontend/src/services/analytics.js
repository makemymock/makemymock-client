// Umami analytics loader.
//
// Injects the Umami tracker script only when a website id is configured
// (VITE_UMAMI_WEBSITE_ID). Production (Vercel) sets it and gets tracked; local
// dev leaves it unset, so `npm run dev` never pollutes your real stats.
//
// The website id is PUBLIC (it ships in the page source either way), so it is
// not a secret — it just lives in an env var so we can toggle tracking per
// environment. Umami's tracker auto-tracks SPA route changes via the History
// API, so no per-route wiring is needed here.

const WEBSITE_ID = import.meta.env.VITE_UMAMI_WEBSITE_ID;
const SRC = import.meta.env.VITE_UMAMI_SRC || 'https://cloud.umami.is/script.js';

export function initAnalytics() {
  if (!WEBSITE_ID) return;                                   // unset in dev → no tracking
  if (document.querySelector('script[data-website-id]')) return; // already injected
  const s = document.createElement('script');
  s.defer = true;
  s.src = SRC;
  s.setAttribute('data-website-id', WEBSITE_ID);
  document.head.appendChild(s);
}
