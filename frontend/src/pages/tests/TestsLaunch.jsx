import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Button from '../../components/common/Button/Button';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './testsLaunch.module.css';

const TEST_SIZES = [10, 20, 30, 50];

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function flattenChapterTopicIds(chapter) {
  return chapter.topics.map((t) => t.id);
}

const TestsLaunch = () => {
  const navigate = useNavigate();
  const [tab, setTab] = useState('launch'); // 'launch' | 'history'
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedTopics, setSelectedTopics] = useState(() => new Set());
  const [size, setSize] = useState(20);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await mockTestService.getCatalog();
        if (!cancelled) setCatalog(data);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load the topic catalog.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleTopic = (id) => {
    setSelectedTopics((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const setTopics = (ids, value) => {
    setSelectedTopics((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (value) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  };

  const chapterState = (chapter) => {
    const ids = flattenChapterTopicIds(chapter);
    if (ids.length === 0) return 'empty';
    let inCount = 0;
    for (const id of ids) if (selectedTopics.has(id)) inCount += 1;
    if (inCount === 0) return 'none';
    if (inCount === ids.length) return 'all';
    return 'some';
  };

  const onChapterToggle = (chapter) => {
    const state = chapterState(chapter);
    const ids = flattenChapterTopicIds(chapter);
    setTopics(ids, state !== 'all'); // any state other than all → select all
  };

  const totalTopics = useMemo(() => {
    if (!catalog) return 0;
    let n = 0;
    for (const s of catalog.subjects)
      for (const c of s.chapters)
        n += c.topics.length;
    return n;
  }, [catalog]);

  const onCreate = async () => {
    setCreateError('');
    if (selectedTopics.size === 0) {
      setCreateError('Pick at least one topic to get started.');
      return;
    }
    setCreating(true);
    try {
      const data = await mockTestService.createTest({
        topic_ids: Array.from(selectedTopics),
        total_questions: size,
      });
      navigate(`/tests/${data.session_id}`, { replace: true });
    } catch (err) {
      setCreateError(parseApiError(err, 'Could not generate the test.'));
    } finally {
      setCreating(false);
    }
  };

  return (
    <ExamShell
      chromeless
      title={tab === 'history' ? 'Your test history' : 'Launch a personalised mock test'}
      subtitle={
        tab === 'history'
          ? 'Every test you start lives here — resume an in-progress one or open a finished test’s analytics.'
          : 'Pick the topics you want to drill. The recommender picks how many questions per topic, the right difficulty mix, and the rotation between fresh and recyclable items.'
      }
    >
      {/* Tab strip — launch vs. history. History is embedded here per
          product brief; the /history route still works for deep links. */}
      <div role="tablist" aria-label="Tests view" className={styles.tabStrip}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'launch'}
          className={`${styles.tabBtn} ${tab === 'launch' ? styles.tabBtnOn : ''}`}
          onClick={() => setTab('launch')}
        >
          Launch a test
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'history'}
          className={`${styles.tabBtn} ${tab === 'history' ? styles.tabBtnOn : ''}`}
          onClick={() => setTab('history')}
        >
          Past tests
        </button>
      </div>

      {tab === 'history' ? <TestHistoryPanel /> : null}

      {tab === 'launch' ? (
      <>
      {loading ? <Loader /> : null}
      {error ? <ErrorMessage message={error} /> : null}

      {catalog && (
        <>
          <div className={styles.summaryBar}>
            <div className={styles.summary}>
              <span className={styles.summaryNum}>{selectedTopics.size}</span>
              <span className={styles.summaryLabel}>topics selected</span>
              <span className={styles.summaryDot} aria-hidden="true" />
              <span className={styles.summaryLabel}>of {totalTopics}</span>
            </div>

            <div className={styles.sizeRow}>
              <span className={styles.sizeLabel}>Questions</span>
              <div role="radiogroup" aria-label="Total questions" className={styles.sizeChips}>
                {TEST_SIZES.map((n) => (
                  <button
                    key={n}
                    type="button"
                    role="radio"
                    aria-checked={size === n}
                    className={`${styles.sizeChip} ${size === n ? styles.sizeChipOn : ''}`}
                    onClick={() => setSize(n)}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {createError ? <ErrorMessage message={createError} /> : null}

          {catalog.subjects.length === 0 ? (
            <div className={styles.emptyState}>
              <h3>No questions in the catalog yet.</h3>
              <p>Once questions are added to the <code>questions</code> collection (bbd_db schema),
              this catalog will populate automatically.</p>
            </div>
          ) : (
            <div className={styles.subjects}>
              {catalog.subjects.map((subject) => (
                <section key={subject.id} className={styles.subjectCard}>
                  <header className={styles.subjectHead}>
                    <h2 className={styles.subjectName}>{subject.name}</h2>
                    <span className={styles.subjectCount}>
                      {subject.chapters.length} chapters
                    </span>
                  </header>
                  <div className={styles.chapters}>
                    {subject.chapters.map((chapter) => {
                      const state = chapterState(chapter);
                      return (
                        <div key={chapter.id} className={styles.chapter}>
                          <label className={styles.chapterHead}>
                            <input
                              type="checkbox"
                              className={styles.chapterCheck}
                              aria-label={`Select all topics in ${chapter.name}`}
                              checked={state === 'all'}
                              ref={(el) => {
                                if (el) el.indeterminate = state === 'some';
                              }}
                              onChange={() => onChapterToggle(chapter)}
                            />
                            <span className={styles.chapterName}>{chapter.name}</span>
                            <span className={styles.chapterCount}>
                              {chapter.topics.length} topics
                            </span>
                          </label>
                          <div className={styles.topics}>
                            {chapter.topics.map((topic) => (
                              <label key={topic.id} className={`${styles.topic} ${selectedTopics.has(topic.id) ? styles.topicOn : ''}`}>
                                <input
                                  type="checkbox"
                                  className={styles.topicCheck}
                                  checked={selectedTopics.has(topic.id)}
                                  onChange={() => toggleTopic(topic.id)}
                                />
                                <span className={styles.topicName}>{topic.name}</span>
                                <span className={styles.topicQs}>{topic.question_count}</span>
                              </label>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}

          <div className={styles.actions}>
            <Button
              variant="primary"
              fullWidth={false}
              loading={creating}
              disabled={selectedTopics.size === 0 || creating}
              onClick={onCreate}
            >
              Generate {size}-question test
            </Button>
            <button
              type="button"
              className={styles.linkBtn}
              onClick={() => setSelectedTopics(new Set())}
              disabled={selectedTopics.size === 0}
            >
              Clear selection
            </button>
          </div>
        </>
      )}
      </>
      ) : null}
    </ExamShell>
  );
};

// ---------------------------------------------------------------------------
// History panel — embedded below the tab strip. Mirrors the layout of the
// standalone /history page (kept for deep-link compatibility) but lives
// inline so students can flip between launching and reviewing in one place.
// ---------------------------------------------------------------------------

const TestHistoryPanel = () => {
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
    return () => { cancelled = true; };
  }, []);

  if (loading) return <Loader />;
  if (error) return <ErrorMessage message={error} />;

  if (items.length === 0) {
    return (
      <section className={styles.historyEmpty}>
        <h3>No tests yet</h3>
        <p>Launch your first test from the <strong>Launch a test</strong> tab — it'll show up here.</p>
      </section>
    );
  }

  return (
    <ul className={styles.historyList}>
      {items.map((it) => {
        const completed = it.status === 'completed';
        return (
          <li key={it.session_id} className={styles.historyItem}>
            <div className={styles.historyMain}>
              <div className={styles.historyHead}>
                <span className={styles.historyId}>#{it.session_id}</span>
                <span
                  className={`${styles.historyStatus} ${
                    completed ? styles.historyStatusOk : styles.historyStatusPending
                  }`}
                >
                  {it.status}
                </span>
              </div>
              <div className={styles.historyMeta}>
                {it.total_questions} questions · started {formatDate(it.created_at)}
                {completed && it.completed_at ? ` · finished ${formatDate(it.completed_at)}` : ''}
              </div>
            </div>

            {completed ? (
              <div className={styles.historyScoreCol}>
                <div className={styles.historyScore}>
                  {it.score != null ? Number(it.score).toFixed(2) : '—'}
                </div>
                <div className={styles.historyScoreSub}>
                  {it.correct ?? 0}✓ · {it.partial ?? 0}~ · {it.incorrect ?? 0}✗
                </div>
              </div>
            ) : null}

            <div className={styles.historyActions}>
              {completed ? (
                <Link
                  to={`/tests/${it.session_id}/result`}
                  className={styles.historyAction}
                >
                  View result
                </Link>
              ) : (
                <Link
                  to={`/tests/${it.session_id}`}
                  className={`${styles.historyAction} ${styles.historyActionPrimary}`}
                >
                  Resume
                </Link>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
};

export default TestsLaunch;
