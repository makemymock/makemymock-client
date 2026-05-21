import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './history.module.css';

function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

const History = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await mockTestService.getHistory();
        if (!cancelled) setItems(data.items || []);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load history.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <ExamShell title="Loading history…">
        <Loader />
      </ExamShell>
    );
  }

  if (error) {
    return (
      <ExamShell title="Test history">
        <ErrorMessage message={error} />
      </ExamShell>
    );
  }

  return (
    <ExamShell
      eyebrow="Past performance"
      title="Your test history"
      subtitle="Every test you start lives here — whether you submitted it or not. Resume an in-progress test or open a finished one's analytics."
    >
      {items.length === 0 ? (
        <section className={styles.emptyState}>
          <h3>No tests yet</h3>
          <p>When you launch a mock test from <Link to="/tests">/tests</Link>, it'll appear here.</p>
        </section>
      ) : (
        <ul className={styles.list}>
          {items.map((it) => {
            const completed = it.status === 'completed';
            return (
              <li key={it.session_id} className={styles.item}>
                <div className={styles.itemMain}>
                  <div className={styles.itemHead}>
                    <span className={styles.itemId}>#{it.session_id}</span>
                    <span className={`${styles.statusPill} ${completed ? styles.completed : styles.pending}`}>
                      {it.status}
                    </span>
                  </div>
                  <div className={styles.itemMeta}>
                    {it.total_questions} questions · started {formatDate(it.created_at)}
                    {completed && it.completed_at ? ` · finished ${formatDate(it.completed_at)}` : ''}
                  </div>
                </div>

                {completed ? (
                  <div className={styles.itemScoreCol}>
                    <div className={styles.score}>{it.score != null ? Number(it.score).toFixed(2) : '—'}</div>
                    <div className={styles.scoreSub}>
                      {it.correct ?? 0}✓ · {it.partial ?? 0}~ · {it.incorrect ?? 0}✗
                    </div>
                  </div>
                ) : null}

                <div className={styles.itemActions}>
                  {completed ? (
                    <Link to={`/tests/${it.session_id}/result`} className={styles.actionBtn}>
                      View result
                    </Link>
                  ) : (
                    <Link to={`/tests/${it.session_id}`} className={`${styles.actionBtn} ${styles.actionPrimary}`}>
                      Resume
                    </Link>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </ExamShell>
  );
};

export default History;
