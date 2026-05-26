import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import StatCard from '../../components/common/StatCard/StatCard';
import LineChart from '../../components/common/LineChart/LineChart';
import BarChart from '../../components/common/BarChart/BarChart';
import DonutChart from '../../components/common/DonutChart/DonutChart';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './topicAnalytics.module.css';

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

const formatDateTime = (d) => {
  if (!d) return '—';
  const dt = d instanceof Date ? d : new Date(d);
  return dt.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
};

const TopicAnalytics = () => {
  const { topicId } = useParams();
  const [state, setState] = useState({ id: null, data: null, error: '' });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await mockTestService.getTopicDetail(topicId);
        if (!cancelled) setState({ id: String(topicId), data: d, error: '' });
      } catch (err) {
        if (!cancelled) {
          setState({
            id: String(topicId),
            data: null,
            error: parseApiError(err, 'Could not load topic analytics.'),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [topicId]);

  const settled = state.id === String(topicId);
  const loading = !settled;
  const data = settled ? state.data : null;
  const error = settled ? state.error : '';

  const prioritySeries = useMemo(() => {
    if (!data) return [];
    return [{
      name: 'Priority',
      points: data.priority_trend.map((p) => ({
        x: p.completed_at,
        y: p.priority_score,
      })),
    }];
  }, [data]);

  const decaySeries = useMemo(() => {
    if (!data) return [];
    return [{
      name: 'Decay multiplier',
      color: 'var(--color-brand-grad-from)',
      points: data.priority_trend.map((p) => ({
        x: p.completed_at,
        y: p.decay_factor,
      })),
    }];
  }, [data]);

  const accuracySeries = useMemo(() => {
    if (!data) return [];
    return [{
      name: 'Accuracy %',
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
      color: 'var(--color-accent)',
      points: data.cumulative_attempts.map((p) => ({
        x: p.date,
        y: p.cumulative,
      })),
    }];
  }, [data]);

  if (loading) {
    return (
      <ExamShell chromeless title="Loading topic analytics…">
        <Loader />
      </ExamShell>
    );
  }

  if (error) {
    return (
      <ExamShell chromeless title="Topic analytics">
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
      eyebrow={`${data.subject_name} · ${data.chapter_name}`}
      title={data.topic_name}
      subtitle={
        noActivity
          ? 'You have not attempted this topic yet.'
          : 'Topic-level drill-down: priority, accuracy, and recent attempts.'
      }
    >
      <p className={styles.backRow}>
        <Link to="/analytics">← All analytics</Link>
        {data.chapter_id ? (
          <>
            {' '}
            ·{' '}
            <Link to={`/analytics/chapter/${data.chapter_id}`}>
              {data.chapter_name}
            </Link>
          </>
        ) : null}
      </p>

      {noActivity ? (
        <section className={styles.emptyState}>
          <h3>No attempts yet</h3>
          <p>
            Pick this topic on <Link to="/tests">/tests</Link> and come back to
            see priority history.
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
              label="Current priority"
              value={data.current_priority_score.toFixed(2)}
              sub="higher = more focus next test"
            />
            <StatCard
              label="Decay factor"
              value={`×${data.current_decay_factor.toFixed(2)}`}
              sub={
                data.current_decay_factor >= 2
                  ? 'likely forgotten'
                  : data.current_decay_factor >= 1.2
                  ? 'fading'
                  : 'fresh'
              }
            />
            <StatCard
              label="Last attempted"
              value={formatDateTime(data.last_attempted_at)}
              sub=""
            />
          </section>

          {/* ----- Priority + Accuracy trends ----- */}
          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Priority over time</h2>
                <span className={styles.cardSub}>
                  Recomputed at each completed test
                </span>
              </header>
              <LineChart
                series={prioritySeries}
                yMin={0}
                yTickFormat={(v) => v.toFixed(1)}
                yLabel="Priority"
                ariaLabel="Topic priority over time"
              />
            </section>

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Accuracy over time</h2>
                <span className={styles.cardSub}>
                  Per-session accuracy on this topic
                </span>
              </header>
              <LineChart
                series={accuracySeries}
                yMin={0}
                yMax={100}
                yTickFormat={(v) => `${v.toFixed(0)}%`}
                yLabel="Accuracy"
                ariaLabel="Topic accuracy over time"
              />
            </section>
          </div>

          {/* ----- Decay + cumulative ----- */}
          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Decay multiplier</h2>
                <span className={styles.cardSub}>
                  How much the engine boosts priority for staleness
                </span>
              </header>
              <LineChart
                series={decaySeries}
                yMin={1}
                yMax={2.5}
                yTickFormat={(v) => `×${v.toFixed(1)}`}
                yLabel="Decay"
                ariaLabel="Decay factor over time"
              />
            </section>

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Cumulative attempts</h2>
              </header>
              <LineChart
                series={cumulativeSeries}
                yMin={0}
                yTickFormat={(v) => v.toFixed(0)}
                yLabel="Attempts"
                ariaLabel="Cumulative attempts"
              />
            </section>
          </div>

          {/* ----- Difficulty + type breakdowns ----- */}
          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>By difficulty</h2>
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

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>By question type</h2>
              </header>
              {data.by_type.length === 0 ? (
                <p className={styles.muted}>No type data yet.</p>
              ) : (
                <BarChart
                  rows={data.by_type.map((d) => ({
                    label: prettyType(d.question_type),
                    meta: `${d.attempts} qns`,
                    value: d.accuracy_pct,
                  }))}
                  valueSuffix="%"
                />
              )}
            </section>
          </div>

          {/* ----- Recent attempts table ----- */}
          <section className={styles.card}>
            <header className={styles.cardHead}>
              <h2 className={styles.cardTitle}>Recent attempts</h2>
              <span className={styles.cardSub}>
                Last {data.recent_attempts.length} on this topic
              </span>
            </header>
            {data.recent_attempts.length === 0 ? (
              <p className={styles.muted}>No attempts yet.</p>
            ) : (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Difficulty</th>
                      <th>Result</th>
                      <th>Score Δ</th>
                      <th>Session</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_attempts.map((a) => {
                      const verdict =
                        a.correctness >= 1
                          ? 'Correct'
                          : a.correctness > 0
                          ? `Partial (${(a.correctness * 100).toFixed(0)}%)`
                          : 'Wrong';
                      const tone =
                        a.correctness >= 1
                          ? styles.good
                          : a.correctness > 0
                          ? styles.warn
                          : styles.bad;
                      return (
                        <tr key={`${a.session_id}-${a.question_id}`}>
                          <td>{formatDateTime(a.attempted_at)}</td>
                          <td className={styles.cap}>{a.difficulty}</td>
                          <td className={tone}>{verdict}</td>
                          <td>{a.score_contribution}</td>
                          <td>
                            <Link to={`/tests/${a.session_id}/result`}>
                              #{a.session_id}
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </ExamShell>
  );
};

export default TopicAnalytics;
