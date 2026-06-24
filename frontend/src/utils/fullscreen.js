// Thin wrapper over the browser Fullscreen API with the older webkit
// prefixes folded in, so callers don't repeat the vendor dance. Used by
// the drill's FullscreenGate to keep a student in full screen while they
// take a test, and by the launch screen to enter full screen up front on
// the "Generate" click (while the user gesture is still live).

const docEl = () => document.documentElement;

export const isFullscreen = () =>
  !!(document.fullscreenElement || document.webkitFullscreenElement);

// Some browsers (notably a few iOS Safari builds) expose no Fullscreen API
// on regular elements. Callers use this to avoid trapping the student
// behind a button that can never succeed.
export const fullscreenSupported = () =>
  !!(docEl().requestFullscreen || docEl().webkitRequestFullscreen);

export const requestFullscreen = (el = docEl()) => {
  const fn = el.requestFullscreen || el.webkitRequestFullscreen;
  if (!fn) return Promise.reject(new Error('Fullscreen API unavailable'));
  try {
    const out = fn.call(el);
    return out && typeof out.then === 'function' ? out : Promise.resolve();
  } catch (err) {
    return Promise.reject(err);
  }
};

export const exitFullscreen = () => {
  const fn = document.exitFullscreen || document.webkitExitFullscreen;
  if (!fn || !isFullscreen()) return Promise.resolve();
  try {
    const out = fn.call(document);
    return out && typeof out.then === 'function' ? out : Promise.resolve();
  } catch {
    return Promise.resolve();
  }
};

// Subscribe to full-screen enter/exit. Returns an unsubscribe fn so it
// drops straight into a useEffect cleanup.
export const onFullscreenChange = (handler) => {
  document.addEventListener('fullscreenchange', handler);
  document.addEventListener('webkitfullscreenchange', handler);
  return () => {
    document.removeEventListener('fullscreenchange', handler);
    document.removeEventListener('webkitfullscreenchange', handler);
  };
};
