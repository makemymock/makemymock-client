import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import Button from '../../components/common/Button/Button';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import BrowsePanel from './BrowsePanel';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './testsLaunch.module.css';

// Browse-only URL params, cleared when leaving the Browse tab so they don't
// linger on the Launch / Past-tests views.
const BROWSE_PARAMS = ['subject', 'chapter', 'topic', 'difficulty', 'qtype', 'attempted', 'marked', 'q', 'page'];

// Backend hard-caps total_questions at 1..100 (see schema.py); the UI
// validates the same range so a runaway value doesn't bounce off the API.
const MIN_SIZE = 1;
const MAX_SIZE = 100;
const DEFAULT_SIZE = 20;

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
  // Tab lives in the URL (?tab=) so Back from a Browse problem page restores
  // the right view. 'launch' is the default and carries no param.
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get('tab') || 'launch'; // 'launch' | 'history' | 'browse'
  const setTab = (next) => {
    setSearchParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next === 'launch') p.delete('tab');
      else p.set('tab', next);
      if (next !== 'browse') BROWSE_PARAMS.forEach((k) => p.delete(k));
      return p;
    });
  };
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedTopics, setSelectedTopics] = useState(() => new Set());
  const [expandedSubjects, setExpandedSubjects] = useState(() => new Set());
  const [expandedChapters, setExpandedChapters] = useState(() => new Set());

  const toggleSubject = (id) => {
    setExpandedSubjects((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const toggleChapter = (id) => {
    setExpandedChapters((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  // Kept as a string so the user can clear the field while typing without
  // jumping back to a number. Parsed to int at submit / validation time.
  const [sizeInput, setSizeInput] = useState(String(DEFAULT_SIZE));
  const sizeNum = parseInt(sizeInput, 10);
  const sizeValid =
    Number.isInteger(sizeNum) && sizeNum >= MIN_SIZE && sizeNum <= MAX_SIZE;
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await mockTestService.getCatalog();
        if (!cancelled) {
          setCatalog(data);
          // Subjects expanded by default — chapters stay collapsed so the
          // initial page is browsable without scrolling through every topic.
          setExpandedSubjects(new Set(data.subjects.map((s) => s.id)));
        }
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
    if (!sizeValid) {
      setCreateError(`Enter a number of questions between ${MIN_SIZE} and ${MAX_SIZE}.`);
      return;
    }
    setCreating(true);
    try {
      const data = await mockTestService.createTest({
        topic_ids: Array.from(selectedTopics),
        total_questions: sizeNum,
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
      title={
        tab === 'history'
          ? 'Your test history'
          : tab === 'browse'
            ? 'Browse the question bank'
            : tab === 'notebook'
              ? 'Your notebook'
              : 'Personalised mock test'
      }
      subtitle={
        tab === 'history'
          ? 'Every test you start lives here — resume an in-progress one or open a finished test’s analytics.'
          : tab === 'browse'
            ? 'Filter the full question bank, see what you’ve attempted, and practise any question on its own.'
            : tab === 'notebook'
              ? 'Questions you saved to revise later. Filter them just like Browse and practise any one on its own.'
              : 'Pick your topics — we set the question count, difficulty mix, and rotate fresh and recyclable items.'
      }
    >
      {/* Tab strip — launch / browse / notebook / past tests. On small
          screens the strip becomes a horizontal scroller that fills the
          viewport; edge shadows appear when there's more to scroll, so a
          visible scrollbar isn't needed to hint at the overflow. */}
      <TabStrip
        tabs={[
          { key: 'launch', label: 'Mock' },
          { key: 'browse', label: 'Browse' },
          { key: 'notebook', label: 'Notebook' },
          { key: 'history', label: 'History' },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === 'history' ? <TestHistoryPanel /> : null}
      {tab === 'browse' ? <BrowsePanel /> : null}
      {tab === 'notebook' ? <BrowsePanel notebookMode /> : null}

      {tab === 'launch' ? (
        <>
          {loading ? <Loader /> : null}
          {error ? <ErrorMessage message={error} /> : null}

          {catalog && (
            <>
              <div className={styles.summaryBar} data-tour="practice.summary">
                <div className={styles.summary}>
                  <span className={styles.summaryNum}>{selectedTopics.size}</span>
                  <span className={styles.summaryLabel}>topics selected</span>
                  <span className={styles.summaryDot} aria-hidden="true" />
                  <span className={styles.summaryLabel}>of {totalTopics}</span>
                </div>

                <div className={styles.sizeRow}>
                  <label className={styles.sizeLabel} htmlFor="totalQuestions">
                    Questions
                  </label>
                  <input
                    id="totalQuestions"
                    type="number"
                    inputMode="numeric"
                    min={MIN_SIZE}
                    max={MAX_SIZE}
                    step={1}
                    value={sizeInput}
                    // Strip anything that isn't a digit so the value stays a clean
                    // positive integer — no leading +, no decimals, no exponent.
                    onChange={(e) => setSizeInput(e.target.value.replace(/\D/g, ''))}
                    aria-invalid={!sizeValid}
                    className={`${styles.sizeInput} ${!sizeValid ? styles.sizeInputBad : ''}`}
                  />
                  <span className={styles.sizeHint}>
                    {MIN_SIZE}–{MAX_SIZE}
                  </span>
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
                <div className={styles.subjects} data-tour="practice.subjects">
                  {catalog.subjects.map((subject) => {
                    const subjOpen = expandedSubjects.has(subject.id);
                    return (
                      <section key={subject.id} className={styles.subjectCard}>
                        <button
                          type="button"
                          className={styles.subjectHead}
                          aria-expanded={subjOpen}
                          onClick={() => toggleSubject(subject.id)}
                        >
                          <span className={styles.chevron} aria-hidden="true">
                            {subjOpen ? '▾' : '▸'}
                          </span>
                          <h2 className={styles.subjectName}>{subject.name}</h2>
                          <span className={styles.subjectCount}>
                            {subject.chapters.length} chapters
                          </span>
                        </button>
                        {subjOpen ? (
                          <div className={styles.chapters}>
                            {subject.chapters.map((chapter) => {
                              const state = chapterState(chapter);
                              const chOpen = expandedChapters.has(chapter.id);
                              return (
                                <div key={chapter.id} className={styles.chapter}>
                                  {/* Header has TWO independent click targets: the
                              checkbox toggles selection of all topics in the
                              chapter, the rest of the row toggles expansion.
                              Keeping them as separate siblings avoids the
                              click-bubbling tangle of a nested checkbox. */}
                                  <div className={styles.chapterHead}>
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
                                    <button
                                      type="button"
                                      className={styles.chapterToggle}
                                      aria-expanded={chOpen}
                                      onClick={() => toggleChapter(chapter.id)}
                                    >
                                      <span className={styles.chevron} aria-hidden="true">
                                        {chOpen ? '▾' : '▸'}
                                      </span>
                                      <span className={styles.chapterName}>{chapter.name}</span>
                                      <span className={styles.chapterCount}>
                                        {chapter.topics.length} topics
                                      </span>
                                    </button>
                                  </div>
                                  {chOpen ? (
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
                                  ) : null}
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                      </section>
                    );
                  })}
                </div>
              )}

              <div className={styles.actions} data-tour="practice.generate">
                <Button
                  variant="primary"
                  fullWidth={false}
                  loading={creating}
                  disabled={selectedTopics.size === 0 || !sizeValid || creating}
                  onClick={onCreate}
                >
                  {sizeValid ? `Generate ${sizeNum}-question test` : 'Generate test'}
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
        <p>Launch your first test from the <strong>Mock</strong> tab — it'll show up here.</p>
      </section>
    );
  }

  return (
    <ul className={styles.historyList}>
      {items.map((it) => {
        const completed = it.status === 'completed';
        const href = completed ? `/tests/${it.session_id}/result` : `/tests/${it.session_id}`;
        return (
          <li key={it.session_id}>
            <Link to={href} className={styles.historyItem}>
              <div className={styles.historyMain}>
                <div className={styles.historyHead}>
                  <span className={styles.historyId}>#{it.session_id}</span>
                  <span
                    className={`${styles.historyStatus} ${completed ? styles.historyStatusOk : styles.historyStatusPending
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

              {/* Visual cue only — the whole row is the click target. */}
              <span className={styles.historyActions} aria-hidden="true">
                <span className={`${styles.historyAction} ${!completed ? styles.historyActionPrimary : ''}`}>
                  {completed ? 'View result' : 'Resume'}
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
};

// ---------------------------------------------------------------------------
// Tab strip with horizontal-scroll-on-overflow + edge shadow indicators.
//
// On narrow screens the pill can grow wider than the viewport — instead of
// wrapping (which doubles its height) or showing a scrollbar (which looks
// off on a pill), we let it scroll horizontally and surface "more content
// here" via subtle dark gradients on the appropriate edge. The JS keeps the
// shadow opacity in sync with the actual scroll position.
// ---------------------------------------------------------------------------

const TabStrip = ({ tabs, active, onChange }) => {
  const scrollRef = useRef(null);
  const [shadows, setShadows] = useState({ left: false, right: false });

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    const update = () => {
      setShadows({
        left: el.scrollLeft > 1,
        right: el.scrollLeft + el.clientWidth < el.scrollWidth - 1,
      });
    };
    update();
    el.addEventListener('scroll', update, { passive: true });
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', update);
      ro.disconnect();
    };
  }, []);

  return (
    <div
      className={`${styles.tabStripOuter} ${shadows.left ? styles.shadowLeft : ''} ${shadows.right ? styles.shadowRight : ''}`}
      data-tour="practice.tabs"
    >
      <div ref={scrollRef} className={styles.tabStripWrap}>
        <div role="tablist" aria-label="Tests view" className={styles.tabStrip}>
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={active === t.key}
              className={`${styles.tabBtn} ${active === t.key ? styles.tabBtnOn : ''}`}
              onClick={() => onChange(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default TestsLaunch;
