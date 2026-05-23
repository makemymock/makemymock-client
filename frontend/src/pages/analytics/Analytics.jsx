import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import StatCard from '../../components/common/StatCard/StatCard';
import LineChart from '../../components/common/LineChart/LineChart';
import BarChart from '../../components/common/BarChart/BarChart';
import DonutChart from '../../components/common/DonutChart/DonutChart';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './analytics.module.css';

const prettyType = (t) => {
  switch (t) {
    case 'single_correct':
      return 'Single correct';
    case 'multi_correct':
      return 'Multiple correct';
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

const Analytics = () => {
  const [overview, setOverview] = useState(null);
  const [chapters, setChapters] = useState(null);
  const [topics, setTopics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [ov, ch, tp] = await Promise.all([
          mockTestService.getOverview(),
          mockTestService.getChapterAnalytics(),
          mockTestService.getTopicAnalytics(),
        ]);
        if (cancelled) return;
        setOverview(ov);
        setChapters(ch);
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

  const accuracyTrendSeries = useMemo(() => {
    if (!overview) return [];
    return [{
      name: 'Accuracy %',
      points: overview.trend.map((t) => ({
        x: t.completed_at,
        y: t.accuracy_pct,
      })),
    }];
  }, [overview]);

  const scoreTrendSeries = useMemo(() => {
    if (!overview) return [];
    return [{
      name: 'Score',
      points: overview.trend.map((t) => ({
        x: t.completed_at,
        y: t.score,
      })),
      color: 'var(--color-brand-grad-from)',
    }];
  }, [overview]);

  const masteredCount = useMemo(() => {
    if (!topics) return 0;
    return topics.topics.filter(
      (t) => t.attempts >= 3 && t.accuracy_pct >= 75,
    ).length;
  }, [topics]);

  const needsWorkCount = useMemo(() => {
    if (!topics) return 0;
    return topics.topics.filter(
      (t) => t.attempts >= 1 && t.accuracy_pct < 50,
    ).length;
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
      subtitle="Every submitted test feeds the recommender. Higher priority means more questions next time."
    >
      {empty ? (
        <section className={styles.emptyState}>
          <h3>No completed tests yet</h3>
          <p>
            Once you submit a mock test from <Link to="/tests">/tests</Link>, this
            page will populate with score history, chapter rollups, and topic
            deep-dives.
          </p>
        </section>
      ) : (
        <>
          {/* ----- Headline stats ----- */}
          <section className={styles.overviewGrid}>
            <StatCard label="Tests submitted" value={overview.total_tests} />
            <StatCard
              label="Questions attempted"
              value={overview.total_questions}
            />
            <StatCard
              label="Overall accuracy"
              value={`${overview.overall_accuracy_pct.toFixed(1)}%`}
              tone={
                overview.overall_accuracy_pct >= 70
                  ? 'good'
                  : overview.overall_accuracy_pct >= 50
                  ? 'warn'
                  : 'bad'
              }
            />
            <StatCard
              label="Total score"
              value={overview.total_score.toFixed(1)}
            />
            <StatCard
              label="Topics mastered"
              value={masteredCount}
              sub="3+ attempts · 75%+ accuracy"
              tone="good"
            />
            <StatCard
              label="Topics needing work"
              value={needsWorkCount}
              sub="Below 50% accuracy"
              tone={needsWorkCount > 0 ? 'bad' : undefined}
            />
          </section>

          {/* ----- Trend charts ----- */}
          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Accuracy over time</h2>
                <span className={styles.cardSub}>
                  {overview.trend.length} sessions
                </span>
              </header>
              <LineChart
                series={accuracyTrendSeries}
                yMin={0}
                yMax={100}
                yTickFormat={(v) => `${v.toFixed(0)}%`}
                yLabel="Accuracy"
                ariaLabel="Accuracy trend across sessions"
              />
            </section>

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Score per test</h2>
                <span className={styles.cardSub}>Raw points earned</span>
              </header>
              <LineChart
                series={scoreTrendSeries}
                yMin={0}
                yTickFormat={(v) => v.toFixed(1)}
                yLabel="Score"
                ariaLabel="Score trend across sessions"
              />
            </section>
          </div>

          {/* ----- Difficulty / Type distributions ----- */}
          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Difficulty breakdown</h2>
                <span className={styles.cardSub}>Accuracy per difficulty</span>
              </header>
              <BarChart
                rows={overview.by_difficulty.map((d) => ({
                  label: d.difficulty,
                  meta: `${d.attempts} qns`,
                  value: d.accuracy_pct,
                }))}
                valueSuffix="%"
                format={(v) => v.toFixed(1)}
              />
            </section>

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Question type mix</h2>
              </header>
              <DonutChart
                segments={overview.by_type.map((d) => ({
                  label: prettyType(d.question_type),
                  value: d.attempts,
                }))}
                centerLabel={overview.total_questions}
                centerSub="attempts"
              />
            </section>
          </div>

          {/* ----- Chapter cards (entry into drill-down) ----- */}
          <section className={styles.card}>
            <header className={styles.cardHead}>
              <h2 className={styles.cardTitle}>Chapters you've practised</h2>
              <span className={styles.cardSub}>
                Sorted by recommender priority — weakest first
              </span>
            </header>
            {chapters && chapters.chapters.length > 0 ? (
              <ul className={styles.chapterGrid}>
                {chapters.chapters.map((c) => {
                  const coverage = c.total_topic_count
                    ? Math.round(
                        (c.attempted_topic_count / c.total_topic_count) * 100,
                      )
                    : 0;
                  return (
                    <li key={c.chapter_id}>
                      <Link
                        to={`/analytics/chapter/${c.chapter_id}`}
                        className={styles.chapterCard}
                      >
                        <span className={styles.chapterSubject}>
                          {c.subject_name}
                        </span>
                        <span className={styles.chapterName}>
                          {c.chapter_name}
                        </span>
                        <div className={styles.chapterMetrics}>
                          <div>
                            <span className={styles.metricNum}>
                              {c.accuracy_pct.toFixed(0)}%
                            </span>
                            <span className={styles.metricLabel}>
                              accuracy
                            </span>
                          </div>
                          <div>
                            <span className={styles.metricNum}>
                              {c.avg_priority_score.toFixed(1)}
                            </span>
                            <span className={styles.metricLabel}>
                              priority
                            </span>
                          </div>
                          <div>
                            <span className={styles.metricNum}>
                              {c.attempts}
                            </span>
                            <span className={styles.metricLabel}>
                              attempts
                            </span>
                          </div>
                        </div>
                        <div className={styles.coverageRow}>
                          <span className={styles.coverageLabel}>
                            {c.attempted_topic_count}/{c.total_topic_count} topics
                          </span>
                          <div className={styles.coverageTrack}>
                            <div
                              className={styles.coverageFill}
                              style={{ width: `${coverage}%` }}
                            />
                          </div>
                        </div>
                        <span className={styles.deepDive}>
                          Open deep-dive →
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className={styles.tableEmpty}>
                Practise a few topics to see chapter rollups here.
              </p>
            )}
          </section>

          {/* ----- Weakest / strongest topics shortcuts ----- */}
          <div className={styles.twoCol}>
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Top 5 weakest topics</h2>
                <span className={styles.cardSub}>Get more questions next</span>
              </header>
              <ul className={styles.miniList}>
                {overview.weakest_topics.map((t) => (
                  <li key={t.topic_id}>
                    <Link to={`/analytics/topic/${t.topic_id}`}>
                      <strong>{t.topic_name}</strong>
                      <span>
                        {t.subject_name} · {t.chapter_name}
                      </span>
                      <em>priority {t.priority_score.toFixed(2)}</em>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>

            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Top 5 strongest topics</h2>
                <span className={styles.cardSub}>Reliably right</span>
              </header>
              <ul className={styles.miniList}>
                {overview.strongest_topics.map((t) => (
                  <li key={t.topic_id}>
                    <Link to={`/analytics/topic/${t.topic_id}`}>
                      <strong>{t.topic_name}</strong>
                      <span>
                        {t.subject_name} · {t.chapter_name}
                      </span>
                      <em>{t.accuracy_pct.toFixed(0)}% accuracy</em>
                    </Link>
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

export default Analytics;
