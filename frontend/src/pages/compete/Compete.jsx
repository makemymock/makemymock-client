import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import Podium from '../../components/compete/Podium/Podium';
import { contestService } from '../../services/contestService';
import { battleService } from '../../services/battleService';
import { tokenStorage } from '../../utils/token';
import { parseApiError } from '../../utils/validators';
import InviteModal from '../battle/InviteModal';
import styles from './compete.module.css';

const TABS = [
  { key: 'battle',      label: 'Battle',      hint: '1-vs-1, live match' },
  { key: 'contest',     label: 'Contest',     hint: 'Scheduled events' },
  { key: 'leaderboard', label: 'Leaderboard', hint: 'Top performers' },
];

const useLiveNow = () => {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
};

const fmtDateTime = (iso) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

const fmtCountdown = (ms) => {
  if (ms <= 0) return '00:00:00';
  const total = Math.floor(ms / 1000);
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, '0');
  if (d > 0) return `${d}d ${pad(h)}:${pad(m)}:${pad(s)}`;
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
};

// ---------- Battle tab ----------
const BattleTab = () => {
  const navigate = useNavigate();
  const [history, setHistory] = useState(null);
  const [error, setError] = useState('');
  // Battle-a-friend modal. Lives at the Compete level (not inside an
  // anchored "open invite" handler) so the modal overlays the whole
  // tab body.
  const [inviteOpen, setInviteOpen] = useState(false);
  useEffect(() => {
    battleService
      .fetchHistory()
      .then((d) => setHistory(d.items || []))
      .catch((err) => setError(parseApiError(err, 'Could not load battle history.')));
  }, []);

  return (
    <div className={styles.tabBody}>
      <section className={styles.heroCard}>
        <div className={styles.heroCopy}>
          <p className={styles.eyebrow}>Live · 1-vs-1</p>
          <h2 className={styles.heroTitle}>Find an opponent.</h2>
          <p className={styles.heroLede}>
            Press Play to enter the queue. The next student to hit Play
            within 15 seconds is your opponent — same questions, same
            timer. Speed bonuses reward fast correct answers.
          </p>
          <div className={styles.heroActions}>
            <button
              type="button"
              className={styles.primaryCta}
              onClick={() => navigate('/battle/play')}
            >
              Play
              <span className={styles.ctaSub}>find me an opponent</span>
            </button>
            <button
              type="button"
              className={styles.friendCta}
              onClick={() => setInviteOpen(true)}
            >
              Battle a friend
              <span className={styles.ctaSub}>share a link & play together</span>
            </button>
            <button
              type="button"
              className={styles.ghostCta}
              onClick={() => navigate('/battle/history')}
            >
              View full history
            </button>
          </div>
        </div>
        <div className={styles.heroBadge} aria-hidden="true">
          <span className={styles.badgeIcon}>⚔</span>
          <span className={styles.badgeText}>BATTLE</span>
        </div>
      </section>

      {inviteOpen ? (
        <InviteModal
          onClose={() => setInviteOpen(false)}
          onStart={(code) => navigate(`/battle/play?invite=${encodeURIComponent(code)}`)}
        />
      ) : null}

      <section className={styles.card}>
        <header className={styles.cardHeader}>
          <h3 className={styles.cardTitle}>Recent battles</h3>
          <Link to="/battle/history" className={styles.cardLink}>See all →</Link>
        </header>
        {error ? <ErrorMessage message={error} /> : null}
        {history === null ? (
          <Loader />
        ) : history.length === 0 ? (
          <p className={styles.muted}>No battles yet — your wins will show up here.</p>
        ) : (
          <ul className={styles.battleList}>
            {history.slice(0, 4).map((b) => (
              <li key={b._id} className={styles.battleRow}>
                <span className={`${styles.resultBadge} ${styles[`result_${b.result}`]}`}>
                  {b.result}
                </span>
                <div>
                  <p className={styles.battleVs}>
                    {b.you.username} {b.you.score} <span className={styles.muted}>vs</span> {b.opponent.score} {b.opponent.username}
                  </p>
                  <p className={styles.muted}>{fmtDateTime(b.completed_at)}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
};

// ---------- Contest tab ----------
const ContestCard = ({ contest, now, onEnter }) => {
  const start = new Date(contest.start_time);
  const lobbyAt = new Date(contest.lobby_opens_at);
  const end = new Date(contest.end_time);

  let cta = null;
  let countdown = null;
  if (contest.status === 'scheduled') {
    const msToLobby = lobbyAt - now;
    countdown = (
      <div className={styles.countdown}>
        <span className={styles.countdownLabel}>
          {msToLobby > 0 ? 'Lobby opens in' : 'Starts in'}
        </span>
        <span className={styles.countdownValue}>
          {fmtCountdown(msToLobby > 0 ? msToLobby : start - now)}
        </span>
      </div>
    );
    if (contest.user_state === 'entered') {
      cta = (
        <button type="button" className={styles.cardCta} disabled>
          You're in the lobby
        </button>
      );
    } else if (contest.lobby_open) {
      cta = (
        <button
          type="button"
          className={styles.cardCtaPrimary}
          onClick={() => onEnter(contest.id)}
        >
          Enter lobby →
        </button>
      );
    } else {
      cta = (
        <button type="button" className={styles.cardCta} disabled>
          Doors open {fmtDateTime(lobbyAt)}
        </button>
      );
    }
  } else if (contest.status === 'live') {
    countdown = (
      <div className={styles.countdown}>
        <span className={styles.countdownLabel}>Live · ends in</span>
        <span className={styles.countdownValue}>{fmtCountdown(end - now)}</span>
      </div>
    );
    if (contest.user_state === 'submitted') {
      cta = (
        <button
          type="button"
          className={styles.cardCtaPrimary}
          onClick={() => onEnter(contest.id, 'result')}
        >
          View your result →
        </button>
      );
    } else if (contest.user_state === 'in_progress') {
      cta = (
        <button
          type="button"
          className={styles.cardCtaPrimary}
          onClick={() => onEnter(contest.id, 'play')}
        >
          Resume contest →
        </button>
      );
    } else if (contest.user_state === 'entered') {
      cta = (
        <button
          type="button"
          className={styles.cardCtaPrimary}
          onClick={() => onEnter(contest.id, 'play')}
        >
          Start contest →
        </button>
      );
    } else {
      cta = (
        <button
          type="button"
          className={styles.cardCtaPrimary}
          onClick={() => onEnter(contest.id)}
        >
          Enter contest →
        </button>
      );
    }
  } else {
    countdown = (
      <div className={styles.countdown}>
        <span className={styles.countdownLabel}>Ended</span>
        <span className={styles.countdownValue}>{fmtDateTime(end)}</span>
      </div>
    );
    if (contest.user_state === 'submitted') {
      cta = (
        <button
          type="button"
          className={styles.cardCtaPrimary}
          onClick={() => onEnter(contest.id, 'result')}
        >
          View your result →
        </button>
      );
    } else {
      cta = (
        <Link to={`/contest/${contest.id}/result`} className={styles.cardCta}>
          View leaderboard →
        </Link>
      );
    }
  }

  return (
    <article className={`${styles.contestCard} ${styles[`status_${contest.status}`]}`}>
      <header className={styles.contestHead}>
        <span className={`${styles.statusPill} ${styles[`pill_${contest.status}`]}`}>
          {contest.status}
        </span>
        <h3 className={styles.contestTitle}>{contest.title}</h3>
        {contest.description ? (
          <p className={styles.contestDesc}>{contest.description}</p>
        ) : null}
      </header>

      <dl className={styles.contestMeta}>
        <div>
          <dt>Starts</dt>
          <dd>{fmtDateTime(start)}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd>{Math.round(contest.duration_seconds / 60)} min</dd>
        </div>
        <div>
          <dt>Questions</dt>
          <dd>{contest.question_count}</dd>
        </div>
        <div>
          <dt>Marking</dt>
          <dd>
            +{contest.marking.correct} / {contest.marking.wrong} / {contest.marking.unattempted}
          </dd>
        </div>
      </dl>

      <footer className={styles.contestFooter}>
        {countdown}
        <div className={styles.cardActions}>{cta}</div>
      </footer>
    </article>
  );
};

const ContestTab = () => {
  const navigate = useNavigate();
  const now = useLiveNow();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const res = await contestService.list();
      setData(res);
    } catch (err) {
      setError(parseApiError(err, 'Could not load contests.'));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh once a minute so transitions (scheduled → live → done)
  // surface without the student having to reload manually.
  useEffect(() => {
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const onEnter = (id, dest) => {
    if (dest === 'result') navigate(`/contest/${id}/result`);
    else if (dest === 'play') navigate(`/contest/${id}/play`);
    else navigate(`/contest/${id}`);
  };

  if (data === null) return <Loader />;

  const { upcoming = [], live = [], past = [] } = data;
  const isEmpty = !upcoming.length && !live.length && !past.length;

  return (
    <div className={styles.tabBody}>
      {error ? <ErrorMessage message={error} /> : null}

      {isEmpty ? (
        <div className={styles.empty}>
          <h3>No contests yet.</h3>
          <p>Watch this space — new contests will appear here automatically.</p>
        </div>
      ) : null}

      {live.length ? (
        <section>
          <h2 className={styles.sectionTitle}>
            <span className={styles.liveDot} aria-hidden="true" />
            Live now
          </h2>
          <div className={styles.contestGrid}>
            {live.map((c) => (
              <ContestCard key={c.id} contest={c} now={now} onEnter={onEnter} />
            ))}
          </div>
        </section>
      ) : null}

      {upcoming.length ? (
        <section>
          <h2 className={styles.sectionTitle}>Upcoming</h2>
          <div className={styles.contestGrid}>
            {upcoming.map((c) => (
              <ContestCard key={c.id} contest={c} now={now} onEnter={onEnter} />
            ))}
          </div>
        </section>
      ) : null}

      {past.length ? (
        <section>
          <h2 className={styles.sectionTitle}>Past contests</h2>
          <div className={styles.contestGrid}>
            {past.map((c) => (
              <ContestCard key={c.id} contest={c} now={now} onEnter={onEnter} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
};

// ---------- Leaderboard tab ----------
const LeaderboardTab = () => {
  const [contests, setContests] = useState(null);
  const [selectedId, setSelectedId] = useState('');
  const [board, setBoard] = useState(null);
  const [error, setError] = useState('');
  const me = tokenStorage.getUser();

  useEffect(() => {
    contestService
      .list()
      .then((d) => {
        // Show past + live contests; scheduled have no leaderboard yet.
        const items = [...(d.live || []), ...(d.past || [])];
        setContests(items);
        if (items.length) setSelectedId(items[0].id);
      })
      .catch((err) => setError(parseApiError(err, 'Could not load contests.')));
  }, []);

  useEffect(() => {
    if (!selectedId) { setBoard(null); return; }
    setBoard(null);
    contestService
      .getLeaderboard(selectedId)
      .then(setBoard)
      .catch((err) => setError(parseApiError(err, 'Could not load leaderboard.')));
  }, [selectedId]);

  if (contests === null) return <Loader />;

  return (
    <div className={styles.tabBody}>
      <section className={styles.card}>
        <div className={styles.leaderboardHeader}>
          <div>
            <h3 className={styles.cardTitle}>Contest leaderboard</h3>
            <p className={styles.muted}>
              Ranked by score, ties broken by time taken.
            </p>
          </div>
          <select
            className={styles.contestSelect}
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            disabled={!contests.length}
          >
            {contests.length === 0 ? (
              <option value="">No completed contests yet</option>
            ) : null}
            {contests.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title} · {fmtDateTime(c.start_time)}
              </option>
            ))}
          </select>
        </div>

        {error ? <ErrorMessage message={error} /> : null}

        {!selectedId ? (
          <p className={styles.muted}>Select a contest to see its leaderboard.</p>
        ) : board === null ? (
          <Loader />
        ) : board.rows.length === 0 ? (
          <p className={styles.muted}>No participants have submitted yet.</p>
        ) : (
          <>
            {/* Top 3 podium — vertical bars; the rest live in the table
                below so the visual hierarchy makes the medallists pop. */}
            <Podium rows={board.rows.slice(0, 3)} youUserId={me?.id} />

            {board.rows.length > 3 ? (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Student</th>
                      <th>Score</th>
                      <th>Correct</th>
                      <th>Wrong</th>
                      <th>Skipped</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {board.rows.slice(3).map((r) => {
                      const meRow = r.is_you || (me && r.user_id === me.id);
                      return (
                        <tr key={r.user_id} className={meRow ? styles.meRow : ''}>
                          <td className={styles.rankCell}>{r.rank}</td>
                          <td>
                            {r.username}
                            {meRow ? <span className={styles.youTag}>You</span> : null}
                          </td>
                          <td><strong>{r.score.toFixed(1)}</strong></td>
                          <td>{r.correct_count}</td>
                          <td>{r.wrong_count}</td>
                          <td>{r.unattempted_count}</td>
                          <td>{Math.round(r.time_taken_seconds / 60)}m {r.time_taken_seconds % 60}s</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}

            <p className={styles.leaderboardFooter}>
              {board.total_participants} total participants
              {board.your_rank ? ` · you ranked #${board.your_rank}` : ''}
            </p>
          </>
        )}
      </section>
    </div>
  );
};

// ---------- shell ----------
const Compete = () => {
  const [params, setParams] = useSearchParams();
  const initial = params.get('tab');
  const [tab, setTab] = useState(
    TABS.find((t) => t.key === initial) ? initial : 'contest',
  );

  // Keep `?tab=` in sync so battle / contest links from elsewhere land
  // on the right tab and back/forward works correctly.
  useEffect(() => {
    const current = params.get('tab');
    if (current !== tab) {
      const next = new URLSearchParams(params);
      next.set('tab', tab);
      setParams(next, { replace: true });
    }
  }, [tab, params, setParams]);

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Compete</p>
        <h1 className={styles.pageTitle}>Test yourself. Beat the field.</h1>
        <p className={styles.pageSub}>
          1-vs-1 battles for fast practice, scheduled contests for the real thing.
        </p>
      </header>

      <div role="tablist" aria-label="Compete view" className={styles.tabStrip}>
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`${styles.tabBtn} ${tab === t.key ? styles.tabBtnOn : ''}`}
            title={t.hint}
          >
            <span className={styles.tabLabel}>{t.label}</span>
          </button>
        ))}
      </div>

      {tab === 'battle' ? <BattleTab /> : null}
      {tab === 'contest' ? <ContestTab /> : null}
      {tab === 'leaderboard' ? <LeaderboardTab /> : null}
    </div>
  );
};

export default Compete;
