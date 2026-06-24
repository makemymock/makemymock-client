import { useEffect, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import { patternLearningService } from '../../services/patternLearningService';
import { parseApiError } from '../../utils/validators';
import styles from './PatternPath.module.css';

// Duolingo-style vertical path of a chapter's patterns. Each node shows the
// pattern NAME and its state (locked / unlocked / completed).
const PatternPath = () => {
  const { chapter } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await patternLearningService.patternRoadmap(chapter);
        if (alive) setData(res);
      } catch (err) {
        if (alive) setError(parseApiError(err, 'Could not load this chapter.'));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [chapter]);

  if (loading) return <Loader />;
  if (error) return <div className={styles.page}><div className={styles.error}>{error}</div></div>;
  if (!data) return null;

  const open = (node) => {
    if (node.state === 'locked') return;
    navigate(`/learn/patterns/${encodeURIComponent(node.pattern_id)}`);
  };

  return (
    <div className={styles.page}>
      <Link to="/tests?section=patterns" className={styles.back}>← All chapters</Link>
      <header className={styles.head}>
        <h1 className={styles.title}>{data.display_name}</h1>
        {data.unlocked ? (
          <p className={styles.subtitle}>{data.items.length} patterns on this path</p>
        ) : (
          <p className={styles.gateNote}>
            🔒 Reach {data.gate_required}% accuracy in this chapter's mock tests to
            start — you're at <strong>{data.gate_accuracy}%</strong>.
          </p>
        )}
      </header>

      <ol className={styles.path}>
        {data.items.map((node, i) => (
          <li
            key={node.pattern_id}
            className={`${styles.row} ${i % 2 === 0 ? styles.left : styles.right}`}
          >
            <button
              type="button"
              className={`${styles.node} ${styles[node.state]}`}
              onClick={() => open(node)}
              disabled={node.state === 'locked'}
              aria-label={`${node.name} — ${node.state}`}
            >
              <span className={styles.nodeIcon}>
                {node.state === 'completed' ? '★' : node.state === 'locked' ? '🔒' : node.sequence}
              </span>
            </button>
            <button
              type="button"
              className={`${styles.card} ${styles[`card_${node.state}`]}`}
              onClick={() => open(node)}
              disabled={node.state === 'locked'}
            >
              <span className={styles.cardStep}>Pattern {node.sequence}</span>
              <span className={styles.name}>{node.name}</span>
              {node.description && <span className={styles.desc}>{node.description}</span>}
              <span className={styles.count}>
                {node.solved_count} / {node.total_count} solved
              </span>
            </button>
          </li>
        ))}
        {data.items.length === 0 && (
          <p className={styles.empty}>No patterns mined for this chapter yet.</p>
        )}
      </ol>
    </div>
  );
};

export default PatternPath;
