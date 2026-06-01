import { useEffect, useRef, useState } from 'react';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { battleService, inviteUrlFor } from '../../services/battleService';
import { parseApiError } from '../../utils/validators';
import styles from './inviteModal.module.css';

/**
 * Invite-a-friend modal. Lifecycle:
 *   1. mount → POST /battle/invites → render code + shareable URL
 *   2. user copies the URL (or the bare code) and shares it
 *   3. user clicks "Start waiting" → parent navigates to
 *      /battle/play?invite=CODE which is where the WS pair-up actually
 *      happens. The friend's accept-flow lands on the same path.
 *   4. if user closes the modal without starting, we cancel the invite
 *      so we don't leave orphan rows.
 */
const InviteModal = ({ onClose, onStart }) => {
  const [code, setCode] = useState('');
  const [expiresAt, setExpiresAt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(null); // 'link' | 'code' | null

  // Refs power the unmount cleanup so it reads live state instead of a
  // stale closure. Previous bug: a state-dep effect's cleanup fired
  // when `started` flipped true (clicking "Start waiting →"), cancelling
  // the invite right as the user was about to use it.
  const codeRef = useRef('');
  const shouldCancelRef = useRef(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await battleService.createInvite();
        if (cancelled) return;
        setCode(data.code);
        codeRef.current = data.code;
        setExpiresAt(data.expires_at);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not create an invite.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Unmount cleanup — cancels the invite ONLY if the user closes the
  // modal without clicking "Start waiting". Reads `shouldCancelRef` at
  // teardown time so we don't accidentally cancel a session the user
  // actually wants to use. Empty deps so it never re-fires mid-life.
  useEffect(() => {
    return () => {
      if (shouldCancelRef.current && codeRef.current) {
        battleService.cancelInvite(codeRef.current).catch(() => {});
      }
    };
  }, []);

  const url = inviteUrlFor(code);

  const copy = async (text, which) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      setTimeout(() => setCopied(null), 1800);
    } catch {
      // Clipboard API blocked (insecure context, browser denied, etc.).
      // Falls back to letting the user select manually.
    }
  };

  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true" aria-label="Invite a friend to battle">
      <div className={styles.card}>
        <header className={styles.head}>
          <h2 className={styles.title}>Battle a friend</h2>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        {loading ? <Loader /> : null}
        {error ? <ErrorMessage message={error} /> : null}

        {!loading && !error && code ? (
          <>
            <p className={styles.subtitle}>
              Share the link below. The moment your friend opens it and
              taps Accept, you'll both jump into the arena.
            </p>

            {/* Primary CTA — the link. Most shares happen through
                WhatsApp / chat, so this is the big-button option. */}
            <label className={styles.fieldLabel}>Shareable link</label>
            <div className={styles.row}>
              <input
                type="text"
                readOnly
                value={url}
                className={styles.input}
                onClick={(e) => e.target.select()}
              />
              <button
                type="button"
                className={styles.copyBtn}
                onClick={() => copy(url, 'link')}
              >
                {copied === 'link' ? 'Copied!' : 'Copy link'}
              </button>
            </div>

            {/* Fallback — the bare code, for voice calls / in-person /
                someone already inside the app. */}
            <label className={styles.fieldLabel}>or share code</label>
            <div className={styles.row}>
              <span className={styles.codeBig}>{code}</span>
              <button
                type="button"
                className={styles.copyBtn}
                onClick={() => copy(code, 'code')}
              >
                {copied === 'code' ? 'Copied!' : 'Copy code'}
              </button>
            </div>

            {expiresAt ? (
              <p className={styles.meta}>
                Expires {new Date(expiresAt).toLocaleTimeString()} —
                ~10 minutes. After that you'll need a new code.
              </p>
            ) : null}

            <div className={styles.actions}>
              <button
                type="button"
                className={styles.secondary}
                onClick={onClose}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.primary}
                onClick={() => {
                  // Mark the invite as in-use BEFORE navigating so the
                  // unmount cleanup leaves it alive. Otherwise the
                  // friend who clicks the link gets a "cancelled"
                  // banner.
                  shouldCancelRef.current = false;
                  onStart(code);
                }}
              >
                Start waiting →
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
};

export default InviteModal;
