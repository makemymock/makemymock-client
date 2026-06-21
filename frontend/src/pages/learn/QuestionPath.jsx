import { useEffect, useLayoutEffect, useRef, useState, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import { patternLearningService } from '../../services/patternLearningService';
import { parseApiError } from '../../utils/validators';
import styles from './QuestionPath.module.css';

// Duolingo-style path of a single pattern's questions. Header shows the
// pattern name; nodes unlock one at a time as each is answered.
// A zig-zag dashed line connects consecutive question nodes.
const QuestionPath = () => {
  const { patternId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const wrapRef = useRef(null);
  const nodeRefs = useRef([]);
  const [connectors, setConnectors] = useState([]);

  useEffect(() => {
    let alive = true;
    setConnectors([]);
    setLoading(true);
    setError('');
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

  // Calculate connector lines between consecutive nodes after render.
  const computeConnectors = useCallback(() => {
    if (!wrapRef.current || !data || data.items.length < 2) return;
    const wrapRect = wrapRef.current.getBoundingClientRect();
    const lines = [];
    for (let i = 0; i < data.items.length - 1; i++) {
      const elA = nodeRefs.current[i];
      const elB = nodeRefs.current[i + 1];
      if (!elA || !elB) continue;
      const rectA = elA.getBoundingClientRect();
      const rectB = elB.getBoundingClientRect();
      const x1 = rectA.left + rectA.width / 2 - wrapRect.left;
      const y1 = rectA.top + rectA.height / 2 - wrapRect.top;
      const x2 = rectB.left + rectB.width / 2 - wrapRect.left;
      const y2 = rectB.top + rectB.height / 2 - wrapRect.top;
      const active = data.items[i].state !== 'locked' && data.items[i + 1].state !== 'locked';
      lines.push({ x1, y1, x2, y2, active });
    }
    setConnectors(lines);
  }, [data]);

  // Use useLayoutEffect so we measure after DOM paint with all refs assigned.
  // Also use a small setTimeout as a fallback for CSS transforms to settle.
  useLayoutEffect(() => {
    if (!data || loading) return;
    // First attempt: immediate (layout is ready)
    computeConnectors();
    // Second attempt: after a short delay so CSS transforms/transitions settle
    const timer = setTimeout(computeConnectors, 100);
    window.addEventListener('resize', computeConnectors);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', computeConnectors);
    };
  }, [data, loading, computeConnectors]);

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

      {/* Wrapper holds both the SVG overlay and the node list */}
      <div className={styles.pathWrap} ref={wrapRef}>
        {/* SVG connector lines behind the nodes */}
        {connectors.length > 0 && (
          <svg className={styles.connectorSvg}>
            {connectors.map((c, i) => {
              // Smooth S-curve between consecutive nodes
              const cy1 = c.y1 + (c.y2 - c.y1) * 0.4;
              const cy2 = c.y1 + (c.y2 - c.y1) * 0.6;
              const d = `M ${c.x1} ${c.y1} C ${c.x1} ${cy1}, ${c.x2} ${cy2}, ${c.x2} ${c.y2}`;
              return (
                <path
                  key={i}
                  d={d}
                  className={`${styles.connectorLine} ${c.active ? styles.connectorLineActive : ''}`}
                />
              );
            })}
          </svg>
        )}

        <ol className={styles.path}>
          {data.items.map((node, i) => (
            <li key={node.question_id} className={`${styles.row} ${styles[`pos${i % 3}`]}`}>
              <button
                type="button"
                ref={(el) => { nodeRefs.current[i] = el; }}
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
    </div>
  );
};

export default QuestionPath;
