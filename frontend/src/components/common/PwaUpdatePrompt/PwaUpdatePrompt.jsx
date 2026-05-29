import { useRegisterSW } from 'virtual:pwa-register/react';
import styles from './PwaUpdatePrompt.module.css';

// Surfaces two transient toasts driven by the service-worker lifecycle:
//   1. "App is ready offline" — fires once, after the first SW install
//      finishes precaching the shell. Lets the user know an offline view
//      is available without telling them how to use it.
//   2. "Update available" — fires whenever a new SW finishes installing
//      and is waiting to take control. Refresh applies the new bundle
//      immediately via skipWaiting + reload.
//
// `registerType: 'prompt'` in vite.config.js ensures these events do
// surface — with 'autoUpdate' the SW swaps in silently and the open
// tab stays on the old code until manual reload.
export default function PwaUpdatePrompt() {
  const {
    offlineReady: [offlineReady, setOfflineReady],
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisterError(error) {
      // Quiet in prod — the app still works without the SW, this just
      // means there's no offline cache and no update prompt.
      if (import.meta.env.DEV) console.warn('SW registration error:', error);
    },
  });

  if (!offlineReady && !needRefresh) return null;

  const close = () => {
    setOfflineReady(false);
    setNeedRefresh(false);
  };

  return (
    <div className={styles.wrap} role="status" aria-live="polite">
      <div className={styles.card}>
        <p className={styles.text}>
          {needRefresh
            ? 'A new version is available.'
            : 'App is ready to work offline.'}
        </p>
        <div className={styles.actions}>
          {needRefresh ? (
            <button
              type="button"
              className={styles.primary}
              onClick={() => updateServiceWorker(true)}
            >
              Refresh
            </button>
          ) : null}
          <button type="button" className={styles.secondary} onClick={close}>
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
