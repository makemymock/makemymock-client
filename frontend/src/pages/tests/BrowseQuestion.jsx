import { useEffect, useMemo, useState } from 'react';
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
    search: sp.get('q') || '',
  };
}

// Fetch the full ordered filtered list (paged at the API cap of 100) so the
// navigation panel and prev/next have the complete neighbour sequence.
async function fetchFilteredList(filters) {
  const all = [];
  let page = 1;
  while (page <= 20) {
    const res = await mockTestService.browseQuestions({ ...filters, page, page_size: 100 });
    all.push(...res.items);
    if (all.length >= res.total || res.items.length === 0) break;
    page += 1;
  }
  return all;
}

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

const BrowseQuestion = () => {
  const { questionId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Standalone answer (QuestionViewer shape) or passage answers keyed by sub.
  const [answer, setAnswer] = useState(null);
  const [subAnswers, setSubAnswers] = useState({});

  // Result of a submit (or a prior attempt loaded from the detail).
  const [graded, setGraded] = useState(null); // { fromPrior, status, correctAnswer, recorded, subResults }
  const [submitting, setSubmitting] = useState(false);

  const [solution, setSolution] = useState(null); // { text, correct }
  const [solutionViewed, setSolutionViewed] = useState(false);
  const [listOpen, setListOpen] = useState(false);

  const [marked, setMarked] = useState(false);
  const [markBusy, setMarkBusy] = useState(false);

  const [navList, setNavList] = useState([]);

  const filterKey = searchParams.toString();
  const backHref = `/tests?${filterKey}`;

  // Load the filtered navigation list once per filter set.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const items = await fetchFilteredList(buildFilters(searchParams));
        if (!cancelled) setNavList(items);
      } catch {
        if (!cancelled) setNavList([]);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  // Load the question detail whenever the id changes.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      setAnswer(null);
      setSubAnswers({});
      setGraded(null);
      setSolution(null);
      setSolutionViewed(false);
      setMarked(false);
      try {
        const d = await mockTestService.getBrowseQuestion(questionId);
        if (cancelled) return;
        setDetail(d);
        setSolutionViewed(Boolean(d.solution_viewed));
        setMarked(Boolean(d.marked));
        // A previously-attempted question opens in graded (review) mode — we
        // know the outcome + correct answer, though not the exact past pick.
        if (d.attempted && d.performance) {
          setGraded({
            fromPrior: true,
            status: d.performance.status,
            correctAnswer: d.correct_answer,
            recorded: true,
            subResults: d.question_type === 'passage' ? d.sub_questions : null,
          });
        }
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

  const qtype = detail?.question_type;
  const isPassage = qtype === 'passage';
  const isGraded = graded != null;
  // The question is in review mode (read-only, correct answer shown) once it's
  // graded OR the solution has been revealed this session.
  const revealed = isGraded || solution != null;

  const submitDisabled = useMemo(() => {
    if (!detail || submitting || isGraded) return true;
    if (isPassage) {
      return !Object.values(subAnswers).some((a) => a && a.selected_option);
    }
    return isAnswerEmpty(qtype, answer);
  }, [detail, submitting, isGraded, isPassage, subAnswers, qtype, answer]);

  const onSubmit = async () => {
    if (submitDisabled) return;
    setSubmitting(true);
    setError('');
    try {
      let body;
      if (isPassage) {
        const answers = {};
        Object.entries(subAnswers).forEach(([i, a]) => {
          if (a && a.selected_option) answers[i] = a.selected_option;
        });
        body = { answers };
      } else if (qtype === 'single_correct') {
        body = { selected_option: answer?.selected_option };
      } else if (qtype === 'multi_correct') {
        body = { selected_options: answer?.selected_options || [] };
      } else if (qtype === 'integer') {
        body = { integer_answer: answer?.integer_answer };
      } else if (qtype === 'matching') {
        body = { matching: answer?.matching || {} };
      }
      const res = await mockTestService.submitBrowseAttempt(questionId, body);
      setGraded({
        fromPrior: false,
        status: res.performance.status,
        correctAnswer: res.correct_answer,
        recorded: res.recorded,
        subResults: res.sub_results && res.sub_results.length ? res.sub_results : null,
      });
      // Auto-reveal the worked solution right after grading. The attempt was
      // already recorded above (it checks the viewed-marker server-side before
      // this call), so showing it now doesn't retract a genuine attempt — it
      // only stops further retries on this question from re-feeding.
      try {
        const sol = await mockTestService.viewBrowseSolution(questionId);
        setSolution({ text: sol.solution, correct: sol.correct_answer });
        setSolutionViewed(true);
      } catch {
        /* non-fatal — the grade + correct-answer highlights already show */
      }
    } catch (err) {
      setError(parseApiError(err, 'Could not grade your answer.'));
    } finally {
      setSubmitting(false);
    }
  };

  const onViewSolution = async () => {
    try {
      const res = await mockTestService.viewBrowseSolution(questionId);
      setSolution({ text: res.solution, correct: res.correct_answer });
      setSolutionViewed(true);
    } catch (err) {
      setError(parseApiError(err, 'Could not load the solution.'));
    }
  };

  const onTryAgain = () => {
    setGraded(null);
    setAnswer(null);
    setSubAnswers({});
    // Drop the revealed solution so the viewer goes interactive again. The
    // server still knows it was viewed, so a fresh submit stays uncounted.
    setSolution(null);
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

  const statusBadge = (() => {
    if (isGraded) {
      const cls = graded.status === 'correct' ? styles.bCorrect
        : graded.status === 'partial' ? styles.bPartial : styles.bWrong;
      const label = graded.fromPrior
        ? `Attempted before · ${STATUS_LABEL[graded.status]}`
        : STATUS_LABEL[graded.status];
      return <span className={`${styles.badge} ${cls}`}>{label}</span>;
    }
    if (detail.attempted) return <span className={`${styles.badge} ${styles.bWrong}`}>Attempted</span>;
    if (solutionViewed || detail.solution_viewed) return <span className={`${styles.badge} ${styles.bViewed}`}>Viewed</span>;
    return <span className={`${styles.badge} ${styles.bTodo}`}>Not attempted</span>;
  })();

  return (
    <div className={styles.page}>
      {/* Top toolbar */}
      <div className={styles.toolbar}>
        <Link to={backHref} className={styles.back}>‹ Back to browse</Link>
        <div className={styles.nav}>
          <button type="button" className={styles.navBtn} disabled={!prevId} onClick={() => go(prevId)}>‹ Prev</button>
          <span className={styles.navPos}>
            {navIndex >= 0 ? `${navIndex + 1} / ${navList.length}` : '—'}
          </span>
          <button type="button" className={styles.navBtn} disabled={!nextId} onClick={() => go(nextId)}>Next ›</button>
          <button
            type="button"
            className={`${styles.navBtn} ${listOpen ? styles.navBtnOn : ''}`}
            aria-expanded={listOpen}
            onClick={() => setListOpen((v) => !v)}
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

          {isPassage ? (
            <>
              {detail.passage_text ? (
                <section className={styles.passage}>
                  <p className={styles.passageEyebrow}>Passage</p>
                  <MarkdownText text={detail.passage_text} />
                </section>
              ) : null}
              {detail.sub_questions.map((sub, i) => {
                const gradedSub = graded?.subResults?.[i];
                const correctOpt = gradedSub?.correct_option
                  ?? sub.correct_option
                  ?? solution?.correct?.[String(i)]
                  ?? null;
                const subStatus = gradedSub?.performance?.status ?? sub.performance?.status;
                return (
                  <div key={i} className={styles.subWrap}>
                    <QuestionViewer
                      question={{
                        question_type: 'single_correct',
                        difficulty: detail.difficulty,
                        question_text: sub.question_text,
                        options: sub.options,
                        passage_sub_index: i,
                        passage_sub_total: detail.sub_questions.length,
                      }}
                      index={i}
                      total={detail.sub_questions.length}
                      answer={subAnswers[i] || null}
                      onChange={(a) => setSubAnswers((prev) => ({ ...prev, [i]: a }))}
                      readOnly={revealed}
                      correctAnswer={revealed ? correctOpt : null}
                      isCorrect={subStatus ? subStatus === 'correct' : true}
                    />
                  </div>
                );
              })}
            </>
          ) : (
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
              total={navList.length || 1}
              answer={answer}
              onChange={setAnswer}
              readOnly={revealed}
              correctAnswer={revealed ? (graded?.correctAnswer ?? solution?.correct ?? detail.correct_answer) : null}
              isCorrect={graded ? graded.status === 'correct' : true}
            />
          )}

          {error ? <ErrorMessage message={error} /> : null}

          {/* Result banner */}
          {isGraded && !graded.fromPrior ? (
            <div className={`${styles.resultBanner} ${graded.status === 'correct' ? styles.rbOk : graded.status === 'partial' ? styles.rbPartial : styles.rbBad}`}>
              <strong>{STATUS_LABEL[graded.status]}.</strong>{' '}
              {graded.recorded
                ? 'This attempt counts toward your recommendations.'
                : 'You’d viewed the solution, so this doesn’t count toward your recommendations.'}
            </div>
          ) : null}

          {/* Actions */}
          <div className={styles.actions}>
            {!revealed ? (
              <Button variant="primary" fullWidth={false} loading={submitting} disabled={submitDisabled} onClick={onSubmit}>
                Check answer
              </Button>
            ) : (
              <Button variant="outline" fullWidth={false} onClick={onTryAgain}>
                Try again
              </Button>
            )}
            <button type="button" className={styles.linkBtn} onClick={onViewSolution}>
              {solution ? 'Solution shown below' : 'View solution'}
            </button>
            {!solution && !solutionViewed ? (
              <span className={styles.peekNote}>Viewing the solution means this question won’t count toward your recommendations.</span>
            ) : null}
          </div>

          {/* Solution */}
          {solution ? (
            <section className={styles.solution}>
              <p className={styles.solutionEyebrow}>Worked solution</p>
              {solution.text ? <MarkdownText text={solution.text} /> : <p className={styles.muted}>No written solution is available for this question.</p>}
            </section>
          ) : null}
        </div>

        {/* Navigation drawer */}
        {listOpen ? (
          <aside className={styles.drawer}>
            <div className={styles.drawerHead}>
              <span>{navList.length} in this filter</span>
              <button type="button" className={styles.drawerClose} onClick={() => setListOpen(false)} aria-label="Close list">×</button>
            </div>
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
            </ul>
          </aside>
        ) : null}
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
