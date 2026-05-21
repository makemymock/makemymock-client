import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import Timer from '../../components/mockTest/Timer/Timer';
import QuestionPalette from '../../components/mockTest/QuestionPalette/QuestionPalette';
import QuestionViewer from '../../components/mockTest/QuestionViewer/QuestionViewer';
import SubmitDialog from '../../components/mockTest/SubmitDialog/SubmitDialog';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import Button from '../../components/common/Button/Button';
import { mockTestService } from '../../services/mockTestService';
import { examDraft } from '../../utils/examDraft';
import { parseApiError } from '../../utils/validators';
import styles from './takeTest.module.css';

// UX rule: single → multi → passage → matching → integer.
const TYPE_RANK = {
  single_correct: 0,
  multi_correct: 1,
  passage: 2,
  matching: 3,
  integer: 4,
};

function typeRankFor(q) {
  if (q.passage_id != null) return TYPE_RANK.passage;
  return TYPE_RANK[q.question_type] ?? 99;
}

function isAnswerNonEmpty(a) {
  if (!a) return false;
  if (typeof a.selected_option === 'string' && a.selected_option) return true;
  if (Array.isArray(a.selected_options) && a.selected_options.length > 0) return true;
  if (a.integer_answer != null && String(a.integer_answer).trim() !== '') return true;
  if (a.matching && typeof a.matching === 'object' && Object.values(a.matching).some((v) => v)) return true;
  return false;
}

function buildPayload(answers, questionIds) {
  return questionIds
    .filter((id) => isAnswerNonEmpty(answers[id]))
    .map((id) => ({ question_id: Number(id), ...answers[id] }));
}

const TakeTest = () => {
  const { sessionId: routeId } = useParams();
  const navigate = useNavigate();
  const sessionId = Number(routeId);

  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [answers, setAnswers] = useState({});
  const [marks, setMarks] = useState({});
  const [visited, setVisited] = useState({});
  const [startedAtMs, setStartedAtMs] = useState(null);
  const [submitDialogOpen, setSubmitDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const submitGuardRef = useRef(false);

  // Sort questions for display per UX rule. Stable secondary key:
  // passage_id / question_id so a passage's siblings stay clustered.
  const orderedQuestions = useMemo(() => {
    if (!session) return [];
    const list = [...session.questions];
    list.sort((a, b) => {
      const ra = typeRankFor(a);
      const rb = typeRankFor(b);
      if (ra !== rb) return ra - rb;
      const ga = a.passage_id != null ? a.passage_id : a.question_id;
      const gb = b.passage_id != null ? b.passage_id : b.question_id;
      if (ga !== gb) return ga - gb;
      return a.question_id - b.question_id;
    });
    return list;
  }, [session]);

  // Load session
  useEffect(() => {
    if (!Number.isFinite(sessionId)) {
      setError('Invalid session id.');
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await mockTestService.getSession(sessionId);
        if (cancelled) return;
        if (data.status === 'completed') {
          navigate(`/tests/${sessionId}/result`, { replace: true });
          return;
        }
        setSession(data);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load this session.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, navigate]);

  // Hydrate drafts from sessionStorage once we know the question list.
  // `startedAtMs` is captured on the CLIENT the first time this test is
  // opened, then frozen for the lifetime of the session. That keeps the
  // timer independent of server clock skew / timezone serialization.
  useEffect(() => {
    if (!session) return;
    const draft = examDraft.ensure(sessionId, {
      answers: {},
      marks: {},
      visited: {},
      activeIndex: 0,
      startedAtMs: Date.now(),
    });
    setAnswers(draft.answers || {});
    setMarks(draft.marks || {});
    setVisited(draft.visited || {});
    setStartedAtMs(Number.isFinite(draft.startedAtMs) ? draft.startedAtMs : Date.now());
    setActiveIndex(Math.min(draft.activeIndex || 0, Math.max(0, orderedQuestions.length - 1)));
  }, [session, sessionId, orderedQuestions.length]);

  // Persist drafts on every change.
  useEffect(() => {
    if (!session || startedAtMs === null) return;
    examDraft.save(sessionId, {
      answers, marks, visited, activeIndex, startedAtMs,
    });
  }, [session, sessionId, answers, marks, visited, activeIndex, startedAtMs]);

  // Mark current as visited
  useEffect(() => {
    if (!session || orderedQuestions.length === 0) return;
    const q = orderedQuestions[activeIndex];
    if (!q) return;
    setVisited((prev) => (prev[q.question_id] ? prev : { ...prev, [q.question_id]: true }));
  }, [session, orderedQuestions, activeIndex]);

  const currentQ = orderedQuestions[activeIndex];

  const paletteItems = useMemo(() => {
    return orderedQuestions.map((q, i) => {
      const isAnswered = isAnswerNonEmpty(answers[q.question_id]);
      const isMarked = !!marks[q.question_id];
      let status = 'unanswered';
      if (isAnswered && isMarked) status = 'answered_marked';
      else if (isAnswered) status = 'answered';
      else if (isMarked) status = 'marked';
      return {
        question_id: q.question_id,
        display_order: i,
        status,
        isActive: i === activeIndex,
      };
    });
  }, [orderedQuestions, answers, marks, activeIndex]);

  const stats = useMemo(() => {
    const total = orderedQuestions.length;
    let answered = 0;
    let markedCount = 0;
    orderedQuestions.forEach((q) => {
      if (isAnswerNonEmpty(answers[q.question_id])) answered += 1;
      if (marks[q.question_id]) markedCount += 1;
    });
    return { total, answered, marked: markedCount, unanswered: total - answered };
  }, [orderedQuestions, answers, marks]);

  const handleAnswerChange = (next) => {
    if (!currentQ) return;
    setAnswers((prev) => ({ ...prev, [currentQ.question_id]: next }));
  };

  const toggleMark = () => {
    if (!currentQ) return;
    setMarks((prev) => ({ ...prev, [currentQ.question_id]: !prev[currentQ.question_id] }));
  };

  const clearResponse = () => {
    if (!currentQ) return;
    setAnswers((prev) => {
      const next = { ...prev };
      delete next[currentQ.question_id];
      return next;
    });
  };

  const goPrev = useCallback(() => {
    setActiveIndex((i) => Math.max(0, i - 1));
  }, []);
  const goNext = useCallback(() => {
    setActiveIndex((i) => Math.min(orderedQuestions.length - 1, i + 1));
  }, [orderedQuestions.length]);

  const submit = useCallback(async () => {
    if (submitGuardRef.current) return;
    submitGuardRef.current = true;
    setSubmitting(true);
    try {
      const payload = buildPayload(answers, orderedQuestions.map((q) => q.question_id));
      await mockTestService.submitTest(sessionId, payload);
      examDraft.clear(sessionId);
      navigate(`/tests/${sessionId}/result`, { replace: true });
    } catch (err) {
      setError(parseApiError(err, 'Could not submit the test.'));
      setSubmitting(false);
      setSubmitDialogOpen(false);
      submitGuardRef.current = false;
    }
  }, [answers, orderedQuestions, sessionId, navigate]);

  // Auto-submit on timer expiry.
  const onTimerExpire = useCallback(() => {
    if (!session) return;
    setSubmitDialogOpen(false);
    submit();
  }, [session, submit]);

  if (loading) {
    return (
      <ExamShell title="Loading test…">
        <Loader />
      </ExamShell>
    );
  }

  if (error && !session) {
    return (
      <ExamShell title="Couldn't open this test">
        <ErrorMessage message={error} />
        <button type="button" className={styles.linkBtn} onClick={() => navigate('/tests')}>
          ← Back to test selection
        </button>
      </ExamShell>
    );
  }

  if (!session || !currentQ) {
    return null;
  }

  return (
    <ExamShell
      eyebrow={`Test #${sessionId}`}
      sticky={
        <>
          <span className={styles.metaPill}>
            {stats.answered}/{stats.total} answered
          </span>
          <Timer
            startedAtMs={startedAtMs}
            totalSeconds={session.total_seconds}
            onExpire={onTimerExpire}
          />
          <Button
            variant="primary"
            fullWidth={false}
            onClick={() => setSubmitDialogOpen(true)}
            className={styles.submitBtn}
          >
            Submit
          </Button>
        </>
      }
    >
      {error ? <ErrorMessage message={error} /> : null}

      <div className={styles.layout}>
        <div className={styles.questionColumn}>
          <QuestionViewer
            question={currentQ}
            index={activeIndex}
            total={orderedQuestions.length}
            answer={answers[currentQ.question_id]}
            onChange={handleAnswerChange}
          />

          <div className={styles.controlsBar}>
            <button
              type="button"
              className={styles.ctrlBtn}
              onClick={goPrev}
              disabled={activeIndex === 0}
            >
              ← Previous
            </button>
            <button
              type="button"
              className={`${styles.ctrlBtn} ${marks[currentQ.question_id] ? styles.ctrlBtnOn : ''}`}
              onClick={toggleMark}
            >
              {marks[currentQ.question_id] ? 'Unmark review' : 'Mark for review'}
            </button>
            <button
              type="button"
              className={styles.ctrlBtn}
              onClick={clearResponse}
              disabled={!isAnswerNonEmpty(answers[currentQ.question_id])}
            >
              Clear response
            </button>
            <button
              type="button"
              className={`${styles.ctrlBtn} ${styles.ctrlBtnPrimary}`}
              onClick={goNext}
              disabled={activeIndex >= orderedQuestions.length - 1}
            >
              Save &amp; next →
            </button>
          </div>
        </div>

        <div className={styles.paletteColumn}>
          <QuestionPalette
            items={paletteItems}
            onJump={(i) => setActiveIndex(i)}
          />
        </div>
      </div>

      <SubmitDialog
        open={submitDialogOpen}
        onClose={() => setSubmitDialogOpen(false)}
        onConfirm={submit}
        stats={stats}
        submitting={submitting}
      />
    </ExamShell>
  );
};

export default TakeTest;
