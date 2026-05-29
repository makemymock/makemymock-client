import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { battleService } from '../../services/battleService';
import { parseApiError } from '../../utils/validators';
import styles from './battleJoin.module.css';

/**
 * Landing page when a friend opens an invite link
 * (`/battle/join/:code`). Resolves the invite info, shows the inviter's
 * name, and on Accept it navigates to /battle/play?invite=CODE — where
 * the WS pair-up actually happens.
 *
 * If the invite is the user's own (e.g. they clicked their own copied
 * link to test), we bounce them straight to the play page so the WS
 * picks up the parked host slot.
 */
const BattleJoin = () => {
  const { code } = useParams();
  const navigate = useNavigate();
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    if (!code) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const data = await battleService.getInvite(code);
        if (cancelled) return;
        setInfo(data);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load this invite.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [code]);

  const handleAccept = async () => {
    setAccepting(true);
    setError('');
    try {
      // Pre-check verifies the invite is still claimable BEFORE we
      // open the WS — saves the user from a confusing
      // "queue_timeout" if the inviter cancelled in the meantime.
      await battleService.precheckInvite(code);
      navigate(`/battle/play?invite=${encodeURIComponent(code)}`);
    } catch (err) {
      setError(parseApiError(err, 'Could not accept this invite.'));
      setAccepting(false);
    }
  };

  if (loading) return <div className={styles.page}><Loader /></div>;

  if (error) {
    return (
      <div className={styles.page}>
        <ErrorMessage message={error} />
        <button
          type="button"
          className={styles.secondary}
          onClick={() => navigate('/battle')}
        >
          ← Back to battle
        </button>
      </div>
    );
  }

  if (!info) return null;

  // Inviter clicked their own link — bounce into the arena to claim
  // their host slot. The WS will park them as expected.
  if (info.is_own_invite) {
    navigate(`/battle/play?invite=${encodeURIComponent(code)}`, { replace: true });
    return null;
  }

  if (info.status !== 'pending') {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <h1 className={styles.title}>This invite isn't active.</h1>
          <p className={styles.subtitle}>
            {info.status === 'expired' && 'The link expired before you could join — invites last 10 minutes.'}
            {info.status === 'accepted' && 'Someone already accepted this invite.'}
            {info.status === 'cancelled' && 'The inviter cancelled this invite.'}
          </p>
          <button
            type="button"
            className={styles.primary}
            onClick={() => navigate('/battle')}
          >
            Find a random opponent
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <p className={styles.eyebrow}>1-vs-1 battle invite</p>
        <h1 className={styles.title}>
          <span className={styles.inviter}>{info.inviter_username}</span>
          <br />
          invited you to battle.
        </h1>
        <p className={styles.subtitle}>
          5 questions · 15s each · same questions for both of you.
          Whoever scores higher wins.
        </p>

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            onClick={handleAccept}
            disabled={accepting}
          >
            {accepting ? 'Joining…' : 'Accept & battle'}
          </button>
          <button
            type="button"
            className={styles.secondary}
            onClick={() => navigate('/battle')}
            disabled={accepting}
          >
            Not now
          </button>
        </div>

        <p className={styles.codeLine}>
          Invite code: <strong>{info.code}</strong>
        </p>
      </div>
    </div>
  );
};

export default BattleJoin;
