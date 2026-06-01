import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import QuestionViewer from '../../components/mockTest/QuestionViewer/QuestionViewer';
import QuestionPalette from '../../components/mockTest/QuestionPalette/QuestionPalette';
import Timer from '../../components/mockTest/Timer/Timer';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { contestService } from '../../services/contestService';
import { parseApiError } from '../../utils/validators';
import styles from './contestPlay.module.css';

// Map our per-question answer object to the palette's `status` field.
const paletteStatus = (answer) => {
  if (!answer) return 'unanswered';
  const hasSingle = !!answer.selected_option;
  const hasMulti = (answer.selected_options || []).length > 0;
  const hasInt = answer.integer_answer != null && String(answer.integer_answer).trim() !== '';
  const hasMatch = answer.matching
    ? Object.values(answer.matching).some((v) => (v || []).length > 0)
    : false;
  return (hasSingle || hasMulti || hasInt || hasMatch) ? 'answered' : 'unanswered';
};

const draftKey = (contestId) => `mmm_contest_draft_${contestId}`;

const ContestPlay = () => {
  const { contestId } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState(null);
  const [answers, setAnswers] = useState({});
  const [idx, setIdx] = useState(0);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const submitInFlight = useRef(false);

  // ---- load + start the contest ----
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await contestService.start(contestId);
        if (cancelled) return;
        setData(res);
        // Restore in-flight draft answers if a refresh happened mid-test.
        try {
          const raw = sessionStorage.getItem(draftKey(contestId));
          if (raw) setAnswers(JSON.parse(raw));
        } catch { /* ignore */ }
      } catch (err) {
        if (cancelled) return;
        setError(parseApiError(err, 'Could not start the contest.'));
      }
    })();
    return () => { cancelled = true; };
  }, [contestId]);

  // ---- persist draft on every change ----
  useEffect(() => {
    if (!data) return;
    try {
      sessionStorage.setItem(draftKey(contestId), JSON.stringify(answers));
    } catch { /* ignore quota */ }
  }, [answers, contestId, data]);

  const questions = data?.questions || [];
  const current = questions[idx];

  const onChange = useCallback((newAnswer) => {
    if (!current) return;
    setAnswers((cur) => ({ ...cur, [current.question_id]: newAnswer }));
  }, [current]);

  const onSubmit = useCallback(async (auto = false) => {
    if (submitInFlight.current) return;
    submitInFlight.current = true;
    setSubmitting(true);
    setError('');
    try {
      const payload = questions.map((q) => {
        const a = answers[q.question_id] || {};
        return { question_id: q.question_id, ...a };
      });
      await contestService.submit(contestId, payload);
      sessionStorage.removeItem(draftKey(contestId));
      navigate(`/contest/${contestId}/result`, { replace: true });
    } catch (err) {
      submitInFlight.current = false;
      setSubmitting(false);
      setError(parseApiError(err, 'Submission failed. Try again.'));
      if (!auto) setConfirmOpen(false);
    }
  }, [answers, contestId, navigate, questions]);

  const startedAtMs = useMemo(() => {
    if (!data?.started_at) return Date.now();
    return new Date(data.started_at).getTime();
  }, [data]);

  // Tally for the submit dialog.
  const tally = useMemo(() => {
    let answered = 0;
    for (const q of questions) {
      if (paletteStatus(answers[q.question_id]) === 'answered') answered += 1;
    }
    return { answered, total: questions.length };
  }, [questions, answers]);

  if (error && !data) {
    return (
      <div className={styles.fatal}>
        <ErrorMessage message={error} />
        <button
          type="button"
          className={styles.secondaryBtn}
          onClick={() => navigate(`/contest/${contestId}`, { replace: true })}
        >
          ← Back to lobby
        </button>
      </div>
    );
  }
  if (!data) return <Loader fullscreen />;

  return (
    <div className={styles.shell}>
      {/* Top bar — title, timer, submit. Sticky so the timer stays
          visible as the question scrolls. */}
      <header className={styles.topBar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>CT</span>
          {/* Full title visible from ≥640px; mobile shows the compact
              qChip below instead so the top bar stays one row tall. */}
          <div className={styles.brandText}>
            <p className={styles.brandTitle}>Contest in progress</p>
            <p className={styles.brandSub}>Q{idx + 1} of {questions.length}</p>
          </div>
          <span className={styles.qChip} aria-label={`Question ${idx + 1} of ${questions.length}`}>
            Q{idx + 1}<span className={styles.qChipSlash}>/</span>{questions.length}
          </span>
        </div>
        <div className={styles.center}>
          <Timer
            startedAtMs={startedAtMs}
            totalSeconds={data.duration_seconds}
            onExpire={() => onSubmit(true)}
          />
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.submitBtn}
            disabled={submitting}
            onClick={() => setConfirmOpen(true)}
          >
            Submit
          </button>
        </div>
      </header>

      {error ? (
        <div className={styles.errorRow}>
          <ErrorMessage message={error} />
        </div>
      ) : null}

      <div className={styles.body}>
        <main className={styles.main}>
          {current ? (
            <QuestionViewer
              question={current}
              index={idx}
              total={questions.length}
              answer={answers[current.question_id]}
              onChange={onChange}
            />
          ) : null}

          <nav className={styles.qNav} aria-label="Question navigation">
            <button
              type="button"
              className={styles.secondaryBtn}
              disabled={idx === 0}
              onClick={() => setIdx((i) => Math.max(0, i - 1))}
            >
              ← Previous
            </button>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => onChange({})}
            >
              Clear answer
            </button>
            <button
              type="button"
              className={styles.primaryBtn}
              disabled={idx >= questions.length - 1}
              onClick={() => setIdx((i) => Math.min(questions.length - 1, i + 1))}
            >
              Save & next →
            </button>
          </nav>
        </main>

        <aside className={styles.side}>
          <QuestionPalette
            items={questions.map((q, i) => ({
              question_id: q.question_id,
              display_order: i,
              status: paletteStatus(answers[q.question_id]),
              isActive: i === idx,
            }))}
            onJump={setIdx}
            legend
          />
        </aside>
      </div>

      {confirmOpen ? (
        <div
          className={styles.dialogBackdrop}
          role="dialog"
          aria-modal="true"
          aria-labelledby="contestSubmitTitle"
          onClick={() => !submitting && setConfirmOpen(false)}
        >
          <div className={styles.dialog} onClick={(e) => e.stopPropagation()}>
            <h2 id="contestSubmitTitle" className={styles.dialogTitle}>Submit contest?</h2>
            <p className={styles.dialogBody}>
              You've answered <strong>{tally.answered}</strong> of{' '}
              <strong>{tally.total}</strong> questions. Once submitted you
              cannot reopen the contest.
            </p>
            <div className={styles.dialogActions}>
              <button
                type="button"
                className={styles.secondaryBtn}
                disabled={submitting}
                onClick={() => setConfirmOpen(false)}
              >
                Keep working
              </button>
              <button
                type="button"
                className={styles.primaryBtn}
                disabled={submitting}
                onClick={() => onSubmit(false)}
              >
                {submitting ? 'Submitting…' : 'Submit contest'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default ContestPlay;
