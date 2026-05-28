import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import Button from '../../components/common/Button/Button';
import MarkdownText from '../../components/common/MarkdownText/MarkdownText';
import QuestionViewer from '../../components/mockTest/QuestionViewer/QuestionViewer';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './browseQuestion.module.css';

// Translate the URL filter params into the browse API's filter shape so the
// problem page's prev/next + list panel walk the SAME filtered set the user
// came from.
function buildFilters(sp) {
  return {
    subject: sp.get('subject') || '',
    chapter: sp.get('chapter') || '',
    topic: sp.get('topic') || '',
    difficulty: sp.get('difficulty') || '',
    question_type: sp.get('qtype') || '',
    attempted: sp.get('attempted') || '',
    marked: sp.get('marked') || '',
    search: sp.get('q') || '',
  };
}

// Page size for the navigation drawer. The list paginates on scroll so the
// drawer can open instantly with page 1 instead of waiting on the whole
// filtered set.
const NAV_PAGE_SIZE = 50;

function isAnswerEmpty(qtype, answer) {
  if (!answer) return true;
  switch (qtype) {
    case 'single_correct': return !answer.selected_option;
    case 'multi_correct': return !(answer.selected_options && answer.selected_options.length);
    case 'integer': return answer.integer_answer == null || answer.integer_answer === '';
    case 'matching': return !answer.matching || Object.keys(answer.matching).length === 0;
    default: return true;
  }
}

const STATUS_LABEL = {
  correct: 'Correct',
  partial: 'Partial credit',
  incorrect: 'Incorrect',
};

// Map a recorded attempt status into the muted "you attempted this before"
// badge on the page header. Mirrors the symbols used in the browse list.
const ATTEMPTED_BADGE = {
  correct: { cls: 'bCorrect', label: 'Attempted ✓' },
  partial: { cls: 'bPartial', label: 'Attempted ◐' },
  incorrect: { cls: 'bWrong', label: 'Attempted ✗' },
};

const BrowseQuestion = () => {
  const { questionId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // The current attempt input — QuestionViewer-shape answer dict.
  const [answer, setAnswer] = useState(null);
  // Outcome of the most recent submit on this page. `correctAnswer` and
  // `solution` are populated only when the user got it right; a wrong
  // attempt leaves them null so the prompt stays a re-attemptable mystery.
  const [attemptResult, setAttemptResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Worked solution shown either after a correct attempt or after the
  // user explicitly clicks "View solution".
  const [solution, setSolution] = useState(null); // { text, correct }

  const [listOpen, setListOpen] = useState(false);
  const [marked, setMarked] = useState(false);
  const [markBusy, setMarkBusy] = useState(false);
  // Navigation list — paginated. Page 1 fetches eagerly so prev/next have
  // immediate context; further pages load on scroll inside the drawer (or
  // when the user presses Next at the boundary).
  const [navList, setNavList] = useState([]);
  const [navTotal, setNavTotal] = useState(0);
  const [navPage, setNavPage] = useState(0);
  const [navHasMore, setNavHasMore] = useState(false);
  const [navLoading, setNavLoading] = useState(true);
  const [navLoadingMore, setNavLoadingMore] = useState(false);

  // The side panel chrome is always mounted so CSS transitions cover both
  // the slide-in and slide-out smoothly. Its item list (one MarkdownText
  // per filtered question) is deferred until the first open to keep the
  // initial page render light.
  const drawerRef = useRef(null);
  const listButtonRef = useRef(null);
  const [listEverOpened, setListEverOpened] = useState(false);
  // Items render is held back by one paint after the first open. Mounting
  // 50 MarkdownText items (markdown + KaTeX parsing) blocks the main
  // thread; without this defer the panel can't slide in until that work
  // finishes, making the click feel unresponsive.
  const [drawerItemsReady, setDrawerItemsReady] = useState(false);
  useEffect(() => {
    if (!listEverOpened || drawerItemsReady) return undefined;
    const raf = requestAnimationFrame(() => setDrawerItemsReady(true));
    return () => cancelAnimationFrame(raf);
  }, [listEverOpened, drawerItemsReady]);
  useEffect(() => {
    if (!listOpen) return undefined;
    const handler = (e) => {
      if (drawerRef.current?.contains(e.target)) return;
      if (listButtonRef.current?.contains(e.target)) return;
      setListOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [listOpen]);

  const filterKey = searchParams.toString();
  const backHref = `/tests?${filterKey}`;

  // Load page 1 of the filtered nav list immediately on filter change. The
  // drawer can open before this finishes — it shows a loader inside until
  // the first page arrives.
  useEffect(() => {
    let cancelled = false;
    setNavList([]);
    setNavTotal(0);
    setNavPage(0);
    setNavHasMore(false);
    setNavLoading(true);
    (async () => {
      try {
        const res = await mockTestService.browseQuestions({
          ...buildFilters(searchParams),
          page: 1,
          page_size: NAV_PAGE_SIZE,
        });
        if (cancelled) return;
        setNavList(res.items);
        setNavTotal(res.total);
        setNavPage(1);
        setNavHasMore(res.items.length > 0 && res.items.length < res.total);
      } catch {
        if (!cancelled) {
          setNavList([]);
          setNavHasMore(false);
        }
      } finally {
        if (!cancelled) setNavLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  // Fetch the next nav page and append. Returns the newly fetched items so
  // callers (e.g. the Next button at boundary) can act on them immediately
  // instead of waiting for the state update to flush.
  const loadMoreNav = useCallback(async () => {
    if (navLoading || navLoadingMore || !navHasMore) return [];
    setNavLoadingMore(true);
    try {
      const nextPage = navPage + 1;
      const res = await mockTestService.browseQuestions({
        ...buildFilters(searchParams),
        page: nextPage,
        page_size: NAV_PAGE_SIZE,
      });
      setNavList((prev) => {
        const merged = [...prev, ...res.items];
        setNavHasMore(merged.length < res.total);
        return merged;
      });
      setNavTotal(res.total);
      setNavPage(nextPage);
      return res.items;
    } catch {
      // Stay on the current page — the sentinel will retry on the next
      // intersection if the user keeps scrolling.
      return [];
    } finally {
      setNavLoadingMore(false);
    }
  }, [navLoading, navLoadingMore, navHasMore, navPage, searchParams]);

  // IntersectionObserver on a sentinel at the end of the drawer list.
  // Only attached when the drawer is open, items are mounted, and there's
  // more to load. `drawerItemsReady` is critical here — the sentinel <li>
  // doesn't exist until items mount one frame after open, so without it
  // in the deps the effect would run too early (sentinelRef.current=null)
  // and never re-run to attach the observer.
  const sentinelRef = useRef(null);
  useEffect(() => {
    if (!listOpen || !drawerItemsReady || !navHasMore) return undefined;
    const node = sentinelRef.current;
    if (!node) return undefined;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadMoreNav();
      },
      // root is the scrolling element (.drawerList), not the outer drawer
      // (which is overflow:hidden and doesn't scroll itself).
      { root: node.parentElement, rootMargin: '160px' },
    );
    obs.observe(node);
    return () => obs.disconnect();
  }, [listOpen, drawerItemsReady, navHasMore, loadMoreNav]);

  // Load the question detail whenever the id changes. The page always opens
  // fresh — the prior outcome shows only as a small badge so the student can
  // try again, no auto-revealed answer / solution.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      setAnswer(null);
      setAttemptResult(null);
      setSolution(null);
      setMarked(false);
      try {
        const d = await mockTestService.getBrowseQuestion(questionId);
        if (cancelled) return;
        setDetail(d);
        setMarked(Boolean(d.marked));
        // Keep the load effect tidy — fields not used here.
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load this question.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [questionId]);

  const navIndex = useMemo(
    () => navList.findIndex((x) => x.question_id === questionId),
    [navList, questionId],
  );
  const prevId = navIndex > 0 ? navList[navIndex - 1]?.question_id : null;
  const nextId = navIndex >= 0 && navIndex < navList.length - 1 ? navList[navIndex + 1]?.question_id : null;

  const go = (id) => { if (id) navigate(`/tests/browse/${id}?${filterKey}`); };

  // At the boundary of what's loaded, auto-fetch the next page and jump to
  // its first item so prev/next keeps working past page-size without
  // forcing the user to open the drawer and scroll.
  const onNext = async () => {
    if (nextId) { go(nextId); return; }
    if (!navHasMore || navLoadingMore || navLoading) return;
    const fresh = await loadMoreNav();
    if (fresh.length > 0) go(fresh[0].question_id);
  };
  // If the current question isn't in the loaded page (navIndex == -1), we
  // can't meaningfully step prev/next — the user opens the drawer to seek.
  const nextDisabled = navIndex < 0 || ((!nextId && !navHasMore) || navLoadingMore);

  const qtype = detail?.question_type;
  // The page is "revealed" once the user has either answered correctly OR
  // explicitly clicked View Solution. While unrevealed (including after a
  // wrong submit), the prompt stays editable so the student can try again.
  const isCorrect = attemptResult?.status === 'correct';
  const revealed = isCorrect || solution != null;

  const submitDisabled = useMemo(() => {
    if (!detail || submitting || revealed) return true;
    return isAnswerEmpty(qtype, answer);
  }, [detail, submitting, revealed, qtype, answer]);

  const onSubmit = async () => {
    if (submitDisabled) return;
    setSubmitting(true);
    setError('');
    try {
      let body;
      if (qtype === 'single_correct') {
        body = { selected_option: answer?.selected_option };
      } else if (qtype === 'multi_correct') {
        body = { selected_options: answer?.selected_options || [] };
      } else if (qtype === 'integer') {
        body = { integer_answer: answer?.integer_answer };
      } else if (qtype === 'matching') {
        body = { matching: answer?.matching || {} };
      }
      const res = await mockTestService.submitBrowseAttempt(questionId, body);
      setAttemptResult({
        status: res.performance.status,
        correctAnswer: res.correct_answer ?? null,
        solution: res.solution ?? null,
      });
      // Correct → backend already returned the worked solution + the
      // correct answer. Surface them so the page locks into review mode.
      if (res.performance.status === 'correct') {
        setSolution({
          text: res.solution || '',
          correct: res.correct_answer ?? null,
        });
      }
    } catch (err) {
      setError(parseApiError(err, 'Could not grade your answer.'));
    } finally {
      setSubmitting(false);
    }
  };

  const onTryAgain = () => {
    setAttemptResult(null);
    setAnswer(null);
  };

  const onViewSolution = async () => {
    try {
      const res = await mockTestService.viewBrowseSolution(questionId);
      setSolution({ text: res.solution, correct: res.correct_answer });
    } catch (err) {
      setError(parseApiError(err, 'Could not load the solution.'));
    }
  };

  const onToggleMark = async () => {
    if (markBusy) return;
    setMarkBusy(true);
    const next = !marked;
    setMarked(next); // optimistic
    try {
      if (next) await mockTestService.addToNotebook(questionId);
      else await mockTestService.removeFromNotebook(questionId);
    } catch (err) {
      setMarked(!next); // revert on failure
      setError(parseApiError(err, 'Could not update the notebook.'));
    } finally {
      setMarkBusy(false);
    }
  };

  if (loading) return <div className={styles.page}><Loader /></div>;
  if (error && !detail) {
    return (
      <div className={styles.page}>
        <Link to={backHref} className={styles.back}>‹ Back to browse</Link>
        <ErrorMessage message={error} />
      </div>
    );
  }
  if (!detail) return null;

  // Badge logic — prefer the current session's result if there is one,
  // otherwise the previously-recorded outcome carried by the detail.
  const statusBadge = (() => {
    if (attemptResult) {
      const cfg = ATTEMPTED_BADGE[attemptResult.status] || ATTEMPTED_BADGE.incorrect;
      const label = STATUS_LABEL[attemptResult.status];
      return <span className={`${styles.badge} ${styles[cfg.cls]}`}>{label}</span>;
    }
    if (detail.attempted && detail.performance) {
      const cfg = ATTEMPTED_BADGE[detail.performance.status] || ATTEMPTED_BADGE.incorrect;
      return <span className={`${styles.badge} ${styles[cfg.cls]}`}>{cfg.label}</span>;
    }
    return <span className={`${styles.badge} ${styles.bTodo}`}>Not attempted</span>;
  })();

  // The correct-answer overlay on the QuestionViewer is only set once the
  // page is "revealed" (correct attempt or explicit view). A wrong-attempt
  // state never leaks the right answer back into the viewer.
  const correctAnswerToShow = revealed
    ? (attemptResult?.correctAnswer ?? solution?.correct ?? null)
    : null;

  return (
    <div className={styles.page}>
      {/* Top toolbar */}
      <div className={styles.toolbar}>
        <Link to={backHref} className={styles.back}>‹ Back to browse</Link>
        <div className={styles.nav}>
          <button type="button" className={styles.navBtn} disabled={!prevId} onClick={() => go(prevId)}>‹ Prev</button>
          <span className={styles.navPos}>
            {navIndex >= 0 ? `${navIndex + 1} / ${navTotal || navList.length}` : '—'}
          </span>
          <button type="button" className={styles.navBtn} disabled={nextDisabled} onClick={onNext}>Next ›</button>
          <button
            ref={listButtonRef}
            type="button"
            className={`${styles.navBtn} ${listOpen ? styles.navBtnOn : ''}`}
            aria-expanded={listOpen}
            onClick={() => {
              if (!listOpen) setListEverOpened(true);
              setListOpen((v) => !v);
            }}
          >
            ☰ List
          </button>
        </div>
      </div>

      <div className={styles.body}>
        <div className={styles.main}>
          <div className={styles.metaCard}>
            <span className={styles.crumb}>
              {detail.subject} <span className={styles.sep}>›</span> {detail.chapter} <span className={styles.sep}>›</span> {detail.topic}
            </span>
            <div className={styles.metaRight}>
              <button
                type="button"
                className={`${styles.markBtn} ${marked ? styles.markBtnOn : ''}`}
                onClick={onToggleMark}
                disabled={markBusy}
                aria-pressed={marked}
                title={marked ? 'Remove from notebook' : 'Save to notebook'}
              >
                <span aria-hidden="true">{marked ? '🔖' : '🏷️'}</span>
                {marked ? 'Saved' : 'Save to notebook'}
              </button>
              {statusBadge}
            </div>
          </div>

          {/* Passage stem (only when this is a sub-question of a passage). */}
          {detail.is_passage_sub && detail.passage_text ? (
            <section className={styles.passage}>
              <p className={styles.passageEyebrow}>Passage</p>
              <MarkdownText text={detail.passage_text} />
            </section>
          ) : null}

          <QuestionViewer
            question={{
              question_type: qtype,
              difficulty: detail.difficulty,
              question_text: detail.question_text,
              options: detail.options,
              left_column: detail.left_column,
              right_column: detail.right_column,
            }}
            index={navIndex >= 0 ? navIndex : 0}
            total={navTotal || navList.length || 1}
            answer={answer}
            onChange={setAnswer}
            readOnly={revealed}
            correctAnswer={correctAnswerToShow}
            isCorrect={attemptResult ? isCorrect : true}
          />

          {error ? <ErrorMessage message={error} /> : null}

          {/* Result banner — wrong attempts say "try again" without
              revealing anything; correct attempts celebrate the win
              alongside the auto-revealed worked solution. */}
          {attemptResult ? (
            <div className={`${styles.resultBanner} ${
              attemptResult.status === 'correct' ? styles.rbOk
                : attemptResult.status === 'partial' ? styles.rbPartial
                : styles.rbBad
            }`}>
              {attemptResult.status === 'correct' ? (
                <strong>Correct! Solution shown below.</strong>
              ) : attemptResult.status === 'partial' ? (
                <strong>Partial credit — try again or view the solution.</strong>
              ) : (
                <strong>Not quite. Try again, or view the solution if you’re stuck.</strong>
              )}
            </div>
          ) : null}

          {/* Actions */}
          <div className={styles.actions}>
            {!revealed ? (
              <Button
                variant="primary"
                fullWidth={false}
                loading={submitting}
                disabled={submitDisabled}
                onClick={onSubmit}
              >
                Check answer
              </Button>
            ) : null}
            {attemptResult && !revealed ? (
              <button type="button" className={styles.linkBtn} onClick={onTryAgain}>
                Try again
              </button>
            ) : null}
            {!solution ? (
              <button type="button" className={styles.linkBtn} onClick={onViewSolution}>
                View solution
              </button>
            ) : (
              <span className={styles.peekNote}>Solution shown below.</span>
            )}
          </div>

          {/* Solution */}
          {solution ? (
            <section className={styles.solution}>
              <p className={styles.solutionEyebrow}>Worked solution</p>
              {solution.text ? <MarkdownText text={solution.text} /> : <p className={styles.muted}>No written solution is available for this question.</p>}
            </section>
          ) : null}
        </div>

        {/* Navigation side panel — slides in from the right; outside-click
            closes. The shell is always mounted so the slide transitions
            work in both directions; the heavy item list mounts on first
            open. */}
        <aside
          ref={drawerRef}
          className={`${styles.drawer} ${listOpen ? styles.drawerOpen : ''}`}
          aria-hidden={!listOpen}
        >
          <div className={styles.drawerHead}>
            <span>
              {navTotal > 0
                ? `${navList.length} of ${navTotal} loaded`
                : navLoading ? 'Loading…' : '0 in this filter'}
            </span>
            <button type="button" className={styles.drawerClose} onClick={() => setListOpen(false)} aria-label="Close list">×</button>
          </div>
          {listEverOpened ? (
            !drawerItemsReady || (navLoading && navList.length === 0) ? (
              <div className={styles.drawerLoading}>
                <Loader compact />
              </div>
            ) : navList.length === 0 ? (
              <div className={styles.drawerEmpty}>No questions match these filters.</div>
            ) : (
              <ul className={styles.drawerList}>
                {navList.map((it, i) => (
                  <li key={it.question_id}>
                    <button
                      type="button"
                      className={`${styles.drawerItem} ${it.question_id === questionId ? styles.drawerItemOn : ''}`}
                      onClick={() => { go(it.question_id); setListOpen(false); }}
                    >
                      <span className={styles.drawerNum}>{i + 1}</span>
                      <span className={styles.drawerText}>
                        <MarkdownText text={it.question_text} inline />
                      </span>
                      <span className={styles.drawerDot} data-status={drawerStatus(it)} />
                    </button>
                  </li>
                ))}
                {navHasMore ? (
                  <li ref={sentinelRef} className={styles.drawerSentinel}>
                    {navLoadingMore ? <Loader compact /> : null}
                  </li>
                ) : null}
              </ul>
            )
          ) : null}
        </aside>
      </div>
    </div>
  );
};

function drawerStatus(it) {
  if (it.attempted && it.performance) return it.performance.status;
  if (it.viewed) return 'viewed';
  return 'todo';
}

export default BrowseQuestion;
