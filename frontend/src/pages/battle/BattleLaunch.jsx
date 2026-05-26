import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { battleService } from '../../services/battleService';
import { parseApiError } from '../../utils/validators';
import styles from './battleLaunch.module.css';

const PERKS = [
  { title: '5 Questions', body: 'Speed-round style. Be sharp, be quick.' },
  { title: '15 seconds each', body: 'Lock your answer before the bar runs out.' },
  { title: 'Same questions', body: 'Both players see the exact same set — fair fight.' },
  { title: 'Speed bonus', body: 'Faster correct answers earn more points.' },
];

const formatDate = (d) => {
  try {
    return new Date(d).toLocaleString();
  } catch {
    return d;
  }
};

const BattleLaunch = () => {
  const navigate = useNavigate();
  const [tab, setTab] = useState('arena'); // 'arena' | 'history'

  return (
    <div className={styles.page}>
      {/* Tab strip — sidebar navigation handles cross-feature moves;
          this strip switches between launching and reviewing battles. */}
      <div role="tablist" aria-label="Battle view" className={styles.tabStrip}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'arena'}
          className={`${styles.tabBtn} ${tab === 'arena' ? styles.tabBtnOn : ''}`}
          onClick={() => setTab('arena')}
        >
          Find an opponent
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'history'}
          className={`${styles.tabBtn} ${tab === 'history' ? styles.tabBtnOn : ''}`}
          onClick={() => setTab('history')}
        >
          Battle history
        </button>
      </div>

      <main className={styles.main}>
        {tab === 'arena' ? (
          <>
            <section className={styles.hero}>
              <p className={styles.eyebrow}>Live match. Real opponent.</p>
              <h2 className={styles.title}>
                Pick up the gauntlet.
                <br />
                <span className={styles.titleAccent}>Out-think. Out-pace.</span>
              </h2>
              <p className={styles.lede}>
                Press <strong>Play</strong> to enter the queue. The next student who hits
                Play within 15&nbsp;seconds is your opponent. Same questions, same timer
                — the winner is whoever scores the most.
              </p>

              <button
                type="button"
                className={styles.playButton}
                onClick={() => navigate('/battle/play')}
              >
                <span className={styles.playLabel}>PLAY</span>
                <span className={styles.playSub}>find me an opponent</span>
              </button>

              <button
                type="button"
                className={styles.secondaryButton}
                onClick={() => setTab('history')}
              >
                View past battles →
              </button>
            </section>

            <section className={styles.perks}>
              {PERKS.map((perk) => (
                <article key={perk.title} className={styles.perk}>
                  <h3>{perk.title}</h3>
                  <p>{perk.body}</p>
                </article>
              ))}
            </section>
          </>
        ) : (
          <BattleHistoryPanel onPlay={() => navigate('/battle/play')} />
        )}
      </main>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Embedded history panel — formerly the dedicated /battle/history page.
// The standalone route still works for deep links.
// ---------------------------------------------------------------------------

const BattleHistoryPanel = ({ onPlay }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await battleService.fetchHistory();
        if (!cancelled) setItems(data.items || []);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load your battles.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <Loader />;
  if (error) return <ErrorMessage message={error} />;

  const winCount = items.filter((i) => i.result === 'win').length;
  const lossCount = items.filter((i) => i.result === 'loss').length;
  const drawCount = items.filter((i) => i.result === 'draw').length;

  return (
    <>
      <section className={styles.summary}>
        <div className={styles.summaryStat}>
          <p className={styles.statLabel}>Wins</p>
          <p className={styles.statValue}>{winCount}</p>
        </div>
        <div className={styles.summaryStat}>
          <p className={styles.statLabel}>Losses</p>
          <p className={styles.statValue}>{lossCount}</p>
        </div>
        <div className={styles.summaryStat}>
          <p className={styles.statLabel}>Draws</p>
          <p className={styles.statValue}>{drawCount}</p>
        </div>
      </section>

      {items.length === 0 ? (
        <div className={styles.emptyCard}>
          <p className={styles.emptyTitle}>No battles yet.</p>
          <p className={styles.emptySub}>
            Hit Play to enter the arena and fight your first round.
          </p>
          <button type="button" className={styles.secondaryButton} onClick={onPlay}>
            Play now →
          </button>
        </div>
      ) : (
        <ul className={styles.list}>
          {items.map((it) => (
            <li
              key={it.battle_id}
              className={[
                styles.row,
                it.result === 'win' ? styles.rowWin : '',
                it.result === 'loss' ? styles.rowLoss : '',
                it.result === 'draw' ? styles.rowDraw : '',
              ].join(' ')}
            >
              <div className={styles.rowResult}>{it.result.toUpperCase()}</div>
              <div className={styles.rowMid}>
                <p className={styles.rowOpponent}>
                  vs <strong>{it.opponent.username}</strong>
                </p>
                <p className={styles.rowDate}>{formatDate(it.completed_at)}</p>
              </div>
              <div className={styles.rowScore}>
                <span>{it.you.score}</span>
                <span className={styles.rowDash}>—</span>
                <span>{it.opponent.score}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
};

export default BattleLaunch;
