import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import { patternLearningService } from '../../services/patternLearningService';
import { parseApiError } from '../../utils/validators';
import styles from './QuestionPath.module.css';

// Duolingo-style path of a single pattern's questions. Header shows the
// pattern name; nodes unlock one at a time as each is answered.
const QuestionPath = () => {
  const { patternId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await patternLearningService.questionRoadmap(patternId);
        if (alive) setData(res);
      } catch (err) {
        if (alive) setError(parseApiError(err, 'Could not load this pattern.'));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [patternId]);

  if (loading) return <Loader />;
  if (error) return <div className={styles.page}><div className={styles.error}>{error}</div></div>;
  if (!data) return null;

  const open = (node) => {
    if (node.state === 'locked') return;
    navigate(`/learn/questions/${encodeURIComponent(node.question_id)}`);
  };

  const backTo = `/learn/chapters/${encodeURIComponent(data.chapter)}`;
  const solved = data.items.filter((q) => q.state === 'solved').length;

  return (
    <div className={styles.page}>
      <button className={styles.back} onClick={() => navigate(backTo)}>← Back to patterns</button>
      <header className={styles.head}>
        <span className={styles.kicker}>PATTERN</span>
        <h1 className={styles.title}>{data.pattern_name}</h1>
        <p className={styles.subtitle}>{solved}/{data.items.length} questions solved</p>
      </header>

      <ol className={styles.path}>
        {data.items.map((node, i) => (
          <li key={node.question_id} className={`${styles.row} ${styles[`pos${i % 3}`]}`}>
            <button
              type="button"
              className={`${styles.node} ${styles[node.state]}`}
              onClick={() => open(node)}
              disabled={node.state === 'locked'}
              aria-label={`Question ${node.sequence} — ${node.state}`}
            >
              <span>{node.state === 'solved' ? '✓' : node.state === 'locked' ? '🔒' : node.sequence}</span>
            </button>
          </li>
        ))}
        {data.items.length === 0 && (
          <p className={styles.empty}>No questions in this pattern.</p>
        )}
      </ol>
    </div>
  );
};

export default QuestionPath;
