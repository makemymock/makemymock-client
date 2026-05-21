import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './analytics.module.css';

const Analytics = () => {
  const [overview, setOverview] = useState(null);
  const [topics, setTopics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [ov, tp] = await Promise.all([
          mockTestService.getOverview(),
          mockTestService.getTopicAnalytics(),
        ]);
        if (cancelled) return;
        setOverview(ov);
        setTopics(tp);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load analytics.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const maxPriority = useMemo(() => {
    if (!topics) return 1;
    return topics.topics.reduce((m, t) => Math.max(m, t.priority_score), 1);
  }, [topics]);

  if (loading) {
    return (
      <ExamShell title="Loading analytics…">
        <Loader />
      </ExamShell>
    );
  }

  if (error) {
    return (
      <ExamShell title="Analytics">
        <ErrorMessage message={error} />
      </ExamShell>
    );
  }

  const empty = (overview?.total_tests || 0) === 0;

  return (
    <ExamShell
      eyebrow="Personal analytics"
      title="How your practice is shaping your priority profile"
      subtitle="Every submitted test feeds the recommender. Topics with higher priority get more questions next time; topics with the lowest priority get fewer."
    >
      {empty ? (
        <section className={styles.emptyState}>
          <h3>No completed tests yet</h3>
          <p>Once you submit a mock test from <Link to="/tests">/tests</Link>, this page will populate with your score history, weak topics, and difficulty breakdown.</p>
        </section>
      ) : (
        <>
          <section className={styles.overview}>
            <Stat label="Tests" value={overview.total_tests} />
            <Stat label="Questions attempted" value={overview.total_questions} />
            <Stat label="Total score" value={overview.total_score.toFixed(2)} />
            <Stat label="Overall accuracy" value={`${overview.overall_accuracy_pct.toFixed(1)}%`} />
          </section>

          <section className={styles.card}>
            <header className={styles.cardHead}>
              <h2 className={styles.cardTitle}>Accuracy trend</h2>
              <span className={styles.cardSub}>{overview.trend.length} tests</span>
            </header>
            <Sparkline points={overview.trend.map((p) => p.accuracy_pct)} />
          </section>

          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>By difficulty</h2>
              </header>
              <BarTable
                rows={overview.by_difficulty.map((d) => ({
                  label: d.difficulty,
                  meta: `${d.attempts} qns`,
                  value: d.accuracy_pct,
                  suffix: '%',
                }))}
              />
            </section>

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>By question type</h2>
              </header>
              <BarTable
                rows={overview.by_type.map((d) => ({
                  label: prettyType(d.question_type),
                  meta: `${d.attempts} qns`,
                  value: d.accuracy_pct,
                  suffix: '%',
                }))}
              />
            </section>
          </div>

          <section className={styles.card}>
            <header className={styles.cardHead}>
              <h2 className={styles.cardTitle}>Topics by recommender priority</h2>
              <span className={styles.cardSub}>Higher score = more questions next test</span>
            </header>
            <ul className={styles.topicList}>
              {topics.topics.map((t) => {
                const w = Math.min(100, (t.priority_score / maxPriority) * 100);
                return (
                  <li key={t.topic_id} className={styles.topicRow}>
                    <div className={styles.topicHead}>
                      <span className={styles.topicSubject}>{t.subject_name}</span>
                      <span className={styles.topicSep}>·</span>
                      <span className={styles.topicChapter}>{t.chapter_name}</span>
                    </div>
                    <div className={styles.topicName}>{t.topic_name}</div>
                    <div className={styles.topicBar}>
                      <div className={styles.topicBarFill} style={{ width: `${w}%` }} />
                    </div>
                    <div className={styles.topicMeta}>
                      <span>{t.attempts} attempts</span>
                      <span>{t.accuracy_pct.toFixed(0)}% accuracy</span>
                      <span>priority {t.priority_score.toFixed(2)}</span>
                      <span>decay ×{t.decay_factor.toFixed(2)}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>

          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Weakest topics</h2>
                <span className={styles.cardSub}>Need the most practice</span>
              </header>
              <ul className={styles.miniList}>
                {overview.weakest_topics.map((t) => (
                  <li key={t.topic_id}>
                    <strong>{t.topic_name}</strong>
                    <span>{t.subject_name} · {t.chapter_name}</span>
                    <em>priority {t.priority_score.toFixed(2)}</em>
                  </li>
                ))}
              </ul>
            </section>

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Strongest topics</h2>
                <span className={styles.cardSub}>Reliable signal — recycled less</span>
              </header>
              <ul className={styles.miniList}>
                {overview.strongest_topics.map((t) => (
                  <li key={t.topic_id}>
                    <strong>{t.topic_name}</strong>
                    <span>{t.subject_name} · {t.chapter_name}</span>
                    <em>{t.accuracy_pct.toFixed(0)}% accuracy</em>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </>
      )}
    </ExamShell>
  );
};

const Stat = ({ label, value }) => (
  <div className={styles.stat}>
    <span className={styles.statLabel}>{label}</span>
    <span className={styles.statValue}>{value}</span>
  </div>
);

const BarTable = ({ rows }) => {
  if (!rows.length) {
    return <p className={styles.tableEmpty}>No data yet.</p>;
  }
  const maxV = rows.reduce((m, r) => Math.max(m, r.value), 1);
  return (
    <ul className={styles.barTable}>
      {rows.map((r) => {
        const w = Math.min(100, (r.value / maxV) * 100);
        return (
          <li key={r.label}>
            <div className={styles.barRow}>
              <span className={styles.barLabel}>{r.label}</span>
              <span className={styles.barMeta}>{r.meta}</span>
              <span className={styles.barValue}>{r.value.toFixed(1)}{r.suffix || ''}</span>
            </div>
            <div className={styles.barTrack}>
              <div className={styles.barFill} style={{ width: `${w}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
};

const Sparkline = ({ points }) => {
  if (!points || points.length === 0) {
    return <p className={styles.tableEmpty}>No completed tests yet.</p>;
  }
  if (points.length === 1) {
    return <p className={styles.tableEmpty}>Take one more test to see a trend.</p>;
  }
  const w = 600;
  const h = 120;
  const pad = 8;
  const max = Math.max(...points, 100);
  const min = Math.min(...points, 0);
  const span = max - min || 1;
  const stepX = (w - pad * 2) / (points.length - 1);
  const path = points.map((p, i) => {
    const x = pad + i * stepX;
    const y = pad + (h - pad * 2) * (1 - (p - min) / span);
    return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg className={styles.sparkline} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Accuracy trend">
      <defs>
        <linearGradient id="spark" x1="0" x2="1">
          <stop offset="0" stopColor="var(--color-brand-grad-from)" />
          <stop offset="1" stopColor="var(--color-brand-grad-to)" />
        </linearGradient>
      </defs>
      <path d={path} fill="none" stroke="url(#spark)" strokeWidth="3" strokeLinecap="round" />
      {points.map((p, i) => {
        const x = pad + i * stepX;
        const y = pad + (h - pad * 2) * (1 - (p - min) / span);
        return <circle key={i} cx={x} cy={y} r="3" fill="var(--color-accent)" />;
      })}
    </svg>
  );
};

function prettyType(t) {
  switch (t) {
    case 'single_correct': return 'Single correct';
    case 'multi_correct': return 'Multiple correct';
    case 'integer': return 'Integer';
    case 'matching': return 'Matching';
    case 'passage': return 'Passage';
    default: return t;
  }
}

export default Analytics;
