import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import MarkdownText from '../../components/common/MarkdownText/MarkdownText';
import { contestService } from '../../services/contestService';
import { parseApiError } from '../../utils/validators';
import styles from './contestLobby.module.css';

const fmtCountdown = (ms) => {
  if (ms <= 0) return '00:00:00';
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
};

const ContestLobby = () => {
  const { contestId } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [entering, setEntering] = useState(false);
  const [starting, setStarting] = useState(false);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const load = useCallback(async () => {
    try {
      const res = await contestService.get(contestId);
      setData(res);
    } catch (err) {
      setError(parseApiError(err, 'Could not load contest.'));
    }
  }, [contestId]);

  useEffect(() => { load(); }, [load]);

  // Refresh once a minute so contest state transitions (scheduled →
  // live → completed) surface without the student having to reload.
  useEffect(() => {
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const start = useMemo(() => (data ? new Date(data.start_time) : null), [data]);
  const end = useMemo(() => (data ? new Date(data.end_time) : null), [data]);
  const lobbyOpensAt = useMemo(
    () => (data ? new Date(data.lobby_opens_at) : null), [data],
  );

  const onEnter = async () => {
    setEntering(true);
    setError('');
    try {
      await contestService.enterLobby(contestId);
      await load();
    } catch (err) {
      setError(parseApiError(err, 'Could not enter the lobby.'));
    } finally {
      setEntering(false);
    }
  };

  const onStart = async () => {
    setStarting(true);
    setError('');
    try {
      await contestService.start(contestId);
      navigate(`/contest/${contestId}/play`, { replace: true });
    } catch (err) {
      setError(parseApiError(err, 'Could not start the contest.'));
      setStarting(false);
    }
  };

  if (!data) {
    return (
      <ExamShell chromeless title="Contest" subtitle="Loading details…">
        <Loader />
      </ExamShell>
    );
  }

  const status = data.status;
  const userState = data.user_state;
  const submitted = userState === 'submitted';
  const inProgress = userState === 'in_progress';
  const inLobby = userState === 'entered';

  // Decide the headline CTA + countdown context.
  let ctaBlock = null;
  let countdownLabel = '';
  let countdownTarget = null;

  if (submitted) {
    countdownLabel = 'Contest finished';
    countdownTarget = end;
    ctaBlock = (
      <button
        type="button"
        className={styles.primaryBtn}
        onClick={() => navigate(`/contest/${contestId}/result`)}
      >
        View your result →
      </button>
    );
  } else if (status === 'completed') {
    countdownLabel = 'Contest ended';
    countdownTarget = end;
    ctaBlock = (
      <button type="button" className={styles.secondaryBtn} disabled>
        Contest is over
      </button>
    );
  } else if (status === 'live') {
    countdownLabel = 'Ends in';
    countdownTarget = end;
    ctaBlock = inProgress ? (
      <button
        type="button"
        className={styles.primaryBtn}
        onClick={() => navigate(`/contest/${contestId}/play`)}
      >
        Resume contest →
      </button>
    ) : inLobby ? (
      <button
        type="button"
        className={styles.primaryBtn}
        onClick={onStart}
        disabled={starting}
      >
        {starting ? 'Starting…' : 'Start contest →'}
      </button>
    ) : (
      <button
        type="button"
        className={styles.primaryBtn}
        onClick={onEnter}
        disabled={entering}
      >
        {entering ? 'Entering…' : 'Enter & start →'}
      </button>
    );
  } else {
    // Scheduled — gate by lobby + start window.
    const msToStart = start - now;
    const msToLobby = lobbyOpensAt - now;
    if (msToLobby > 0) {
      countdownLabel = 'Doors open in';
      countdownTarget = lobbyOpensAt;
      ctaBlock = (
        <button type="button" className={styles.secondaryBtn} disabled>
          Lobby opens at {lobbyOpensAt.toLocaleTimeString()}
        </button>
      );
    } else if (msToStart > 0) {
      countdownLabel = 'Starts in';
      countdownTarget = start;
      if (inLobby) {
        ctaBlock = (
          <button type="button" className={styles.secondaryBtn} disabled>
            You're in the lobby — waiting for start
          </button>
        );
      } else {
        ctaBlock = (
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={onEnter}
            disabled={entering}
          >
            {entering ? 'Entering…' : 'Enter the lobby →'}
          </button>
        );
      }
    } else {
      // Race window — start time has passed but our snapshot hasn't
      // refreshed; one more refresh nudge fixes it.
      countdownLabel = 'Starting now';
      countdownTarget = start;
      ctaBlock = (
        <button
          type="button"
          className={styles.primaryBtn}
          onClick={async () => { await load(); onStart(); }}
          disabled={starting}
        >
          {starting ? 'Starting…' : 'Refresh & start →'}
        </button>
      );
    }
  }

  const msRemaining = countdownTarget ? countdownTarget - now : 0;

  return (
    <ExamShell
      chromeless
      eyebrow="Contest"
      title={data.title}
      subtitle={data.description || undefined}
    >
      <div className={styles.layout}>
        <section className={styles.heroPanel}>
          <div className={styles.heroLeft}>
            <p className={styles.statusEyebrow}>
              <span className={`${styles.statusDot} ${styles[`dot_${status}`]}`} />
              {status === 'live' ? 'Live now' : status === 'scheduled' ? 'Scheduled' : 'Completed'}
            </p>
            <div className={styles.countdownBig}>
              <span className={styles.countdownLabel}>{countdownLabel}</span>
              <span className={styles.countdownValue}>{fmtCountdown(msRemaining)}</span>
            </div>
            <p className={styles.heroMuted}>
              {countdownTarget ? countdownTarget.toLocaleString() : ''}
            </p>
          </div>

          <dl className={styles.heroFacts}>
            <div>
              <dt>Questions</dt>
              <dd>{data.question_count}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{Math.round(data.duration_seconds / 60)} min</dd>
            </div>
            <div>
              <dt>Marking</dt>
              <dd>+{data.marking.correct} / {data.marking.wrong} / {data.marking.unattempted}</dd>
            </div>
          </dl>
        </section>

        {error ? <ErrorMessage message={error} /> : null}

        <div className={styles.ctaRow}>
          {ctaBlock}
          <Link to="/compete?tab=contest" className={styles.backLink}>
            ← All contests
          </Link>
        </div>

        <section className={styles.rulesCard}>
          <h2 className={styles.rulesTitle}>Rules & regulations</h2>
          <div className={styles.rulesBody}>
            <MarkdownText text={data.rules || ''} />
          </div>
        </section>
      </div>
    </ExamShell>
  );
};

export default ContestLobby;
