import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import StatCard from '../../components/common/StatCard/StatCard';
import LineChart from '../../components/common/LineChart/LineChart';
import BarChart from '../../components/common/BarChart/BarChart';
import DonutChart from '../../components/common/DonutChart/DonutChart';
import Heatmap from '../../components/common/Heatmap/Heatmap';
import ConfidenceTrophy from '../../components/common/ConfidenceTrophy/ConfidenceTrophy';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import Tour from '../../components/common/Tour/Tour';
import { useTour } from '../../hooks/useTour';
import { analyticsTourSteps } from '../../components/tours/analyticsSteps';
import {
  DUMMY_OVERVIEW,
  DUMMY_CHAPTERS,
  DUMMY_TOPICS,
  DUMMY_HEATMAP,
  DUMMY_CONFIDENCE,
} from '../../components/tours/analyticsDummyData';
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
  const tour = useTour('analytics', analyticsTourSteps);

  const [overview, setOverview] = useState(null);
  const [chapters, setChapters] = useState(null);
  const [topics, setTopics] = useState(null);
  const [heatmap, setHeatmap] = useState(null);
  const [confidence, setConfidence] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [ov, ch, tp, hm, conf] = await Promise.all([
          mockTestService.getOverview(),
          mockTestService.getChapterAnalytics(),
          mockTestService.getTopicAnalytics(),
          mockTestService.getActivityHeatmap().catch(() => null),
          mockTestService.getConfidence().catch(() => null),
        ]);
        if (cancelled) return;
        setOverview(ov);
        setChapters(ch);
        setTopics(tp);
        setHeatmap(hm);
        setConfidence(conf);
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

  // While the Analytics tour is running, swap in dummy data so brand-new
  // users (with no test history yet) see the page in action. The page
  // reverts to its real state the moment the tour closes.
  const showcase = tour.open;
  const overviewV   = showcase ? DUMMY_OVERVIEW   : overview;
  const chaptersV   = showcase ? DUMMY_CHAPTERS   : chapters;
  const topicsV     = showcase ? DUMMY_TOPICS     : topics;
  const heatmapV    = showcase ? DUMMY_HEATMAP    : heatmap;
  const confidenceV = showcase ? DUMMY_CONFIDENCE : confidence;

  const accuracyTrendSeries = useMemo(() => {
    if (!overviewV) return [];
    return [{
      name: 'Accuracy %',
      points: overviewV.trend.map((t) => ({
        x: t.completed_at,
        y: t.accuracy_pct,
      })),
    }];
  }, [overviewV]);

  const scoreTrendSeries = useMemo(() => {
    if (!overviewV) return [];
    return [{
      name: 'Score',
      points: overviewV.trend.map((t) => ({
        x: t.completed_at,
        y: t.score,
      })),
      color: 'var(--color-brand-grad-from)',
    }];
  }, [overviewV]);

  const masteredCount = useMemo(() => {
    if (!topicsV) return 0;
    return topicsV.topics.filter(
      (t) => t.attempts >= 3 && t.accuracy_pct >= 75,
    ).length;
  }, [topicsV]);

  const needsWorkCount = useMemo(() => {
    if (!topicsV) return 0;
    return topicsV.topics.filter(
      (t) => t.attempts >= 1 && t.accuracy_pct < 50,
    ).length;
  }, [topicsV]);

  if (loading && !showcase) {
    return (
      <ExamShell chromeless title="Loading analytics…">
        <Loader />
      </ExamShell>
    );
  }

  if (error && !showcase) {
    return (
      <ExamShell chromeless title="Analytics">
        <ErrorMessage message={error} />
      </ExamShell>
    );
  }

  const empty = !showcase && (overviewV?.total_tests || 0) === 0;

  return (
    <ExamShell chromeless
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
          {/* ----- Confidence trophy ----- */}
          {confidenceV ? (
            <section className={styles.trophySection} data-tour="analytics.trophy">
              <ConfidenceTrophy data={confidenceV} />
            </section>
          ) : null}

          {/* ----- Headline stats + activity heatmap (side-by-side on laptop) -----
              On phones/tablets the inner sections stack normally. On laptop
              (≥ 1080px) the stat grid sits on the left in a 3×2 layout
              and the heatmap card sits on the right at a compact size. */}
          <section className={styles.heroRow}>
            <section
              className={`${styles.overviewGrid} ${styles.overviewGridInHero}`}
              data-tour="analytics.overview"
            >
              <StatCard label="Tests submitted" value={overviewV.total_tests} />
              <StatCard
                label="Questions attempted"
                value={overviewV.total_questions}
              />
              <StatCard
                label="Overall accuracy"
                value={`${overviewV.overall_accuracy_pct.toFixed(1)}%`}
                tone={
                  overviewV.overall_accuracy_pct >= 70
                    ? 'good'
                    : overviewV.overall_accuracy_pct >= 50
                    ? 'warn'
                    : 'bad'
                }
              />
              <StatCard
                label="Total score"
                value={overviewV.total_score.toFixed(1)}
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

            <section className={styles.heatmapSection} data-tour="analytics.heatmap">
              <Heatmap
                days={heatmapV?.days || []}
                maxCount={heatmapV?.max_count || 0}
                defaultRange="month"
              />
            </section>
          </section>

          {/* ----- Trend charts ----- */}
          <div className={styles.twoCol} data-tour="analytics.trends">
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Accuracy over time</h2>
                <span className={styles.cardSub}>
                  {overviewV.trend.length} sessions
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
          <div className={styles.twoCol} data-tour="analytics.breakdown">
            <section className={styles.card}>
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Difficulty breakdown</h2>
                <span className={styles.cardSub}>Accuracy per difficulty</span>
              </header>
              <BarChart
                rows={overviewV.by_difficulty.map((d) => ({
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
                segments={overviewV.by_type.map((d) => ({
                  label: prettyType(d.question_type),
                  value: d.attempts,
                }))}
                centerLabel={overviewV.total_questions}
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
            {chaptersV && chaptersV.chapters.length > 0 ? (
              <ul className={styles.chapterGrid} data-tour="analytics.chapter-grid">
                {chaptersV.chapters.map((c) => {
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
            <section className={styles.card} data-tour="analytics.weakest">
              <header className={styles.cardHead}>
                <h2 className={styles.cardTitle}>Top 5 weakest topics</h2>
                <span className={styles.cardSub}>Get more questions next</span>
              </header>
              <ul className={styles.miniList}>
                {overviewV.weakest_topics.map((t) => (
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
                {overviewV.strongest_topics.map((t) => (
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
      <Tour {...tour} />
    </ExamShell>
  );
};

export default Analytics;
