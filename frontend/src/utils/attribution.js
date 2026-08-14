// First-touch marketing attribution.
//
// UTM params only exist in the URL at the instant someone lands. Signup
// happens later (a different page, maybe a different day), so we capture the
// source once on the very first meaningful visit, persist it in localStorage,
// and attach it to the signup request. First-touch = never overwritten, so the
// *original* source that brought the user in is what gets recorded.
//
// Mirrors utils/token.js: this module owns the `mmm_attribution` key. Nothing
// else should read/write it directly.

const KEY = 'mmm_attribution';
const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];

// Read UTMs (and an external referrer) from the current URL and store them,
// unless something is already stored. Call once, as early as possible at boot.
export function captureAttribution() {
  try {
    if (localStorage.getItem(KEY)) return; // already have a first touch

    const params = new URLSearchParams(window.location.search);
    const utm = {};
    for (const k of UTM_KEYS) {
      const v = params.get(k);
      if (v) utm[k] = v.slice(0, 200);
    }

    let referrer = '';
    if (document.referrer) {
      try {
        // Only an *external* referrer is attribution; internal navigation isn't.
        if (new URL(document.referrer).host !== window.location.host) {
          referrer = document.referrer.slice(0, 500);
        }
      } catch { /* malformed referrer — ignore */ }
    }

    // Direct visit with nothing to attribute: store nothing, so a later UTM'd
    // visit becomes the first meaningful touch instead of "direct".
    if (Object.keys(utm).length === 0 && !referrer) return;

    localStorage.setItem(KEY, JSON.stringify({
      ...utm,
      ...(referrer ? { referrer } : {}),
      landing_path: window.location.pathname.slice(0, 300),
    }));
  } catch {
    /* localStorage blocked (private mode, etc.) — attribution is best-effort */
  }
}

// The stored attribution object, or null. Shape matches the backend
// Attribution schema (snake_case utm_* keys).
export function getAttribution() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
