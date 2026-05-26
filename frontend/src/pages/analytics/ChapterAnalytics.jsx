import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import StatCard from '../../components/common/StatCard/StatCard';
import LineChart from '../../components/common/LineChart/LineChart';
import BarChart from '../../components/common/BarChart/BarChart';
import DonutChart from '../../components/common/DonutChart/DonutChart';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './chapterAnalytics.module.css';

const TOPIC_COLORS = [
  '#14b8a6',
  '#f59e0b',
  '#6366f1',
  '#ef4444',
  '#22c55e',
  '#0ea5e9',
  '#a855f7',
  '#eab308',
];

const prettyType = (t) => {
  switch (t) {
    case 'single_correct':
      return 'Single correct';
    case 'multi_correct':
      return 'Multi correct';
    case 'integer':
      return 'Integer';
    case 'matching':
      return 'Matching';
    case 'passage':
      return 'Passage';
    default:
      return t;
  }
};

const ChapterAnalytics = () => {
  const { chapterId } = useParams();
  const navigate = useNavigate();
  const [state, setState] = useState({ id: null, data: null, error: '' });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await mockTestService.getChapterDetail(chapterId);
        if (!cancelled) setState({ id: String(chapterId), data: d, error: '' });
      } catch (err) {
        if (!cancelled) {
          setState({
            id: String(chapterId),
            data: null,
            error: parseApiError(err, 'Could not load chapter analytics.'),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chapterId]);

  const settled = state.id === String(chapterId);
  const loading = !settled;
  const data = settled ? state.data : null;
  const error = settled ? state.error : '';

  const priorityTrendSeries = useMemo(() => {
    if (!data) return [];
    return [{
      name: 'Avg priority',
      points: data.priority_trend.map((p) => ({
        x: p.completed_at,
        y: p.priority_score,
      })),
    }];
  }, [data]);

  const accuracyTrendSeries = useMemo(() => {
    if (!data) return [];
    return [{
      name: 'Chapter accuracy %',
      points: data.accuracy_trend.map((p) => ({
        x: p.completed_at,
        y: p.accuracy_pct,
      })),
    }];
  }, [data]);

  const cumulativeSeries = useMemo(() => {
    if (!data) return [];
    return [{
      name: 'Cumulative attempts',
      points: data.cumulative_attempts.map((p) => ({
        x: p.date,
        y: p.cumulative,
      })),
      color: 'var(--color-accent)',
    }];
  }, [data]);

  const perTopicPrioritySeries = useMemo(() => {
    if (!data) return [];
    return data.per_topic_priority
      .filter((t) => t.points.length > 0)
      .map((t, i) => ({
        name: t.topic_name,
        color: TOPIC_COLORS[i % TOPIC_COLORS.length],
        dotColor: TOPIC_COLORS[i % TOPIC_COLORS.length],
        points: t.points.map((p) => ({ x: p.completed_at, y: p.priority_score })),
      }));
  }, [data]);

  const perTopicAccuracySeries = useMemo(() => {
    if (!data) return [];
    return data.per_topic_accuracy
      .filter((t) => t.points.length > 0)
      .map((t, i) => ({
        name: t.topic_name,
        color: TOPIC_COLORS[i % TOPIC_COLORS.length],
        dotColor: TOPIC_COLORS[i % TOPIC_COLORS.length],
        points: t.points.map((p) => ({ x: p.completed_at, y: p.accuracy_pct })),
      }));
  }, [data]);

  if (loading) {
    return (
      <ExamShell chromeless title="Loading chapter analytics…">
        <Loader />
      </ExamShell>
    );
  }

  if (error) {
    return (
      <ExamShell chromeless title="Chapter analytics">
        <ErrorMessage message={error} />
        <p className={styles.backRow}>
          <Link to="/analytics">← Back to analytics</Link>
        </p>
      </ExamShell>
    );
  }

  if (!data) return null;

  const noActivity = data.attempts === 0;

  return (
    <ExamShell chromeless
      eyebrow={data.subject_name || 'Chapter'}
      title={data.chapter_name || 'Chapter analytics'}
      subtitle={
        noActivity
          ? 'You have not attempted any topics from this chapter yet.'
          : `Per-chapter rollup across your sessions in ${data.subject_name}.`
      }
    >
      <p className={styles.backRow}>
        <Link to="/analytics">← Back to analytics</Link>
      </p>

      {noActivity ? (
        <section className={styles.emptyState}>
          <h3>No attempts yet</h3>
          <p>
            Pick topics from this chapter on <Link to="/tests">/tests</Link> and
            come back to see the drill-down.
          </p>
        </section>
      ) : (
        <>
          {/* ----- Headline ----- */}
          <section className={styles.overviewGrid}>
            <StatCard
              label="Attempts"
              value={data.attempts}
              sub={`${data.correct} correct`}
            />
            <StatCard
              label="Accuracy"
              value={`${data.accuracy_pct.toFixed(1)}%`}
              tone={
                data.accuracy_pct >= 70
                  ? 'good'
                  : data.accuracy_pct >= 50
                  ? 'warn'
                  : 'bad'
              }
            />
            <StatCard
              label="Avg priority"
              value={data.avg_priority_score.toFixed(2)}
              sub={`max ${data.max_priority_score.toFixed(1)}`}
            />
            <StatCard
              label="Topics practised"
              value={`${data.topics.length}`}
            />
            <StatCard
              label="Decay factor"
              value={`×${data.avg_decay_factor.toFixed(2)}`}
              sub="recall pressure"
            />
            <StatCard
              label="Total score"
              value={data.total_score.toFixed(1)}
            />
          </section>

          {/* ----- Priority + accuracy trends (chapter rollup) ----- */}
          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>
                  Priority score over time
                </h2>
                <span className={styles.cardSub}>
                  Average across topics in this chapter
                </span>
              </header>
              <LineChart
                series={priorityTrendSeries}
                yMin={0}
                yTickFormat={(v) => v.toFixed(1)}
                yLabel="Priority"
                ariaLabel="Chapter priority over time"
              />
            </section>

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Accuracy over time</h2>
                <span className={styles.cardSub}>
                  Per-session accuracy on this chapter
                </span>
              </header>
              <LineChart
                series={accuracyTrendSeries}
                yMin={0}
                yMax={100}
                yTickFormat={(v) => `${v.toFixed(0)}%`}
                yLabel="Accuracy"
                ariaLabel="Chapter accuracy over time"
              />
            </section>
          </div>

          {/* ----- Cumulative attempts + difficulty ----- */}
          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Cumulative attempts</h2>
                <span className={styles.cardSub}>Questions practised over time</span>
              </header>
              <LineChart
                series={cumulativeSeries}
                yMin={0}
                yTickFormat={(v) => v.toFixed(0)}
                yLabel="Attempts"
                ariaLabel="Cumulative attempts"
              />
            </section>

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Difficulty mix</h2>
              </header>
              <DonutChart
                segments={data.by_difficulty.map((d) => ({
                  label: d.difficulty,
                  value: d.attempts,
                }))}
                centerLabel={data.attempts}
                centerSub="attempts"
              />
              <BarChart
                rows={data.by_difficulty.map((d) => ({
                  label: d.difficulty,
                  meta: `${d.attempts} qns`,
                  value: d.accuracy_pct,
                }))}
                valueSuffix="%"
              />
            </section>
          </div>

          {/* ----- Per-topic priority trends ----- */}
          {perTopicPrioritySeries.length > 0 ? (
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>
                  Priority score per topic
                </h2>
                <span className={styles.cardSub}>
                  How each topic's priority moved across sessions
                </span>
              </header>
              <LineChart
                series={perTopicPrioritySeries}
                yMin={0}
                yTickFormat={(v) => v.toFixed(1)}
                yLabel="Priority"
                ariaLabel="Per-topic priority trend"
              />
            </section>
          ) : null}

          {/* ----- Per-topic accuracy trends ----- */}
          {perTopicAccuracySeries.length > 0 ? (
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Accuracy per topic</h2>
                <span className={styles.cardSub}>
                  Per-session accuracy by topic in this chapter
                </span>
              </header>
              <LineChart
                series={perTopicAccuracySeries}
                yMin={0}
                yMax={100}
                yTickFormat={(v) => `${v.toFixed(0)}%`}
                yLabel="Accuracy"
                ariaLabel="Per-topic accuracy trend"
              />
            </section>
          ) : null}

          {/* ----- Question types ----- */}
          {data.by_type.length > 0 ? (
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>By question type</h2>
              </header>
              <BarChart
                rows={data.by_type.map((d) => ({
                  label: prettyType(d.question_type),
                  meta: `${d.attempts} qns`,
                  value: d.accuracy_pct,
                }))}
                valueSuffix="%"
              />
            </section>
          ) : null}

          {/* ----- Topic deep-dive entry ----- */}
          <section className={styles.card}>
            <header className={styles.cardHead}>
              <h2 className={styles.cardTitle}>Topics in this chapter</h2>
              <span className={styles.cardSub}>
                Sorted by priority — open one to drill in
              </span>
            </header>
            <ul className={styles.topicList}>
              {data.topics.map((t) => (
                <li key={t.topic_id}>
                  <button
                    type="button"
                    className={styles.topicRow}
                    onClick={() =>
                      navigate(`/analytics/topic/${t.topic_id}`)
                    }
                  >
                    <span className={styles.topicName}>{t.topic_name}</span>
                    <span className={styles.topicMeta}>
                      <span>{t.attempts} attempts</span>
                      <span>{t.accuracy_pct.toFixed(0)}% acc</span>
                      <span>priority {t.priority_score.toFixed(2)}</span>
                      <span>×{t.decay_factor.toFixed(2)} decay</span>
                    </span>
                    <span className={styles.topicArrow} aria-hidden="true">
                      →
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </ExamShell>
  );
};

export default ChapterAnalytics;
