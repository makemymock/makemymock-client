import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { battleService } from '../../services/battleService';
import { parseApiError } from '../../utils/validators';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import styles from './battleHistory.module.css';

const formatDate = (d) => {
  try {
    return new Date(d).toLocaleString();
  } catch {
    return d;
  }
};

const BattleHistory = () => {
  const navigate = useNavigate();
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
    return () => {
      cancelled = true;
    };
  }, []);

  const winCount = items.filter((i) => i.result === 'win').length;
  const lossCount = items.filter((i) => i.result === 'loss').length;
  const drawCount = items.filter((i) => i.result === 'draw').length;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <button
          type="button"
          className={styles.back}
          onClick={() => navigate('/battle')}
        >
          ← Arena
        </button>
        <h1 className={styles.title}>Battle history</h1>
        <button
          type="button"
          className={styles.playAgain}
          onClick={() => navigate('/battle/play')}
        >
          Play
        </button>
      </header>

      <main className={styles.main}>
        {loading ? <Loader /> : null}
        {error ? <ErrorMessage message={error} /> : null}

        {!loading && !error ? (
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
        ) : null}
      </main>
    </div>
  );
};

export default BattleHistory;
