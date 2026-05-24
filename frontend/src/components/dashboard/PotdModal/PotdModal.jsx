import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { mockTestService } from '../../../services/mockTestService';
import { parseApiError } from '../../../utils/validators';
import MarkdownText from '../../common/MarkdownText/MarkdownText';
import Loader from '../../common/Loader/Loader';
import styles from './PotdModal.module.css';

// ---------------------------------------------------------------------------
// Topic-selection algorithm (60 / 40):
//   - 60% of the time pull from the user's highest-priority topic
//     (weakest area — analytics endpoint already sorts by priority DESC).
//   - 40% from a random other topic the user has already attempted.
//
// `topics` only includes topics with attempts > 0 (that's how the backend
// builds the analytics list), so the "attempted" filter is implicit.
// ---------------------------------------------------------------------------
function chooseTopicId(topics) {
  if (!topics || topics.length === 0) return null;
  const top = topics[0];
  const others = topics.slice(1);
  if (others.length === 0) return top.topic_id;
  return Math.random() < 0.6
    ? top.topic_id
    : others[Math.floor(Math.random() * others.length)].topic_id;
}

const STORAGE_PREFIX = 'mmm_potd_';
const todayKey = () => {
  // Local date (not UTC) — the "day" boundary should match the user's
  // wall clock, otherwise a student in IST starting at 11pm and one
  // starting at 2am the next morning would race the same challenge.
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const storageKey = (userId) => `${STORAGE_PREFIX}${userId || 'anon'}_${todayKey()}`;

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

const PotdModal = ({ open, userId, onClose }) => {
  const navigate = useNavigate();
  // phases: loading | no-data | error | question | submitting | result | unsupported
  const [phase, setPhase] = useState('loading');
  const [error, setError] = useState('');
  const [question, setQuestion] = useState(null);    // from /mock-test/create or /session
  const [sessionId, setSessionId] = useState(null);
  const [topicMeta, setTopicMeta] = useState(null);  // {topic_name, ...} for display
  const [selectedOption, setSelectedOption] = useState(null);
  const [selectedOptions, setSelectedOptions] = useState([]);
  const [integerAnswer, setIntegerAnswer] = useState('');
  const [resultData, setResultData] = useState(null);  // per-question result with solution

  const dialogRef = useRef(null);

  // ---- ESC closes the modal ----
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // ---- Lock background scroll while open ----
  useEffect(() => {
    if (!open) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  // ---- Bootstrap the daily challenge whenever the modal opens ----
  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;

    (async () => {
      setPhase('loading');
      setError('');
      setSelectedOption(null);
      setSelectedOptions([]);
      setIntegerAnswer('');
      setResultData(null);

      try {
        const key = storageKey(userId);
        let sid = null;
        try {
          const raw = localStorage.getItem(key);
          if (raw) sid = JSON.parse(raw).sessionId ?? null;
        } catch { /* ignore corrupt storage */ }

        // Reuse today's session if we have one stored.
        if (sid != null) {
          try {
            const session = await mockTestService.getSession(sid);
            if (cancelled) return;
            const q = session.questions?.[0];
            if (!q) throw new Error('Session has no question');
            setSessionId(session.session_id);
            setQuestion(q);
            setTopicMeta(session.topics?.[0] || null);
            if (session.status === 'completed') {
              const res = await mockTestService.getResults(session.session_id);
              if (cancelled) return;
              setResultData(res.results?.[0] || null);
              setPhase('result');
            } else if (!isSupported(q.question_type, q.passage_id)) {
              setPhase('unsupported');
            } else {
              setPhase('question');
            }
            return;
          } catch {
            // Stored session is stale or unfetchable — fall through to fresh
            // creation. We do NOT clear the key here so we don't lose track
            // of a session that just had a transient API hiccup.
          }
        }

        // No usable session today — pick a topic and create one.
        const analytics = await mockTestService.getTopicAnalytics();
        if (cancelled) return;
        const topics = analytics.topics || [];
        const topicId = chooseTopicId(topics);
        if (topicId == null) {
          setPhase('no-data');
          return;
        }

        const created = await mockTestService.createTest({
          topic_ids: [topicId],
          total_questions: 1,
        });
        if (cancelled) return;

        try {
          localStorage.setItem(
            storageKey(userId),
            JSON.stringify({ sessionId: created.session_id }),
          );
        } catch { /* localStorage full or unavailable — non-fatal */ }

        const q = created.questions?.[0];
        if (!q) {
          setError('Could not load a question for today. Please try again later.');
          setPhase('error');
          return;
        }
        setSessionId(created.session_id);
        setQuestion(q);
        setTopicMeta(created.topics?.[0] || null);
        setPhase(isSupported(q.question_type, q.passage_id) ? 'question' : 'unsupported');
      } catch (err) {
        if (cancelled) return;
        setError(parseApiError(err, 'Could not load today’s challenge.'));
        setPhase('error');
      }
    })();

    return () => { cancelled = true; };
  }, [open, userId]);

  const handleSubmit = useCallback(async () => {
    if (!question || sessionId == null) return;
    if (!answerNonEmpty(question, selectedOption, selectedOptions, integerAnswer)) return;

    setPhase('submitting');
    try {
      const answer = buildAnswerPayload(
        question, selectedOption, selectedOptions, integerAnswer,
      );
      await mockTestService.submitTest(sessionId, [answer]);
      // /submit doesn't return solution_text — fetch /result for the prose.
      const res = await mockTestService.getResults(sessionId);
      setResultData(res.results?.[0] || null);
      setPhase('result');
    } catch (err) {
      setError(parseApiError(err, 'Could not submit your answer.'));
      setPhase('error');
    }
  }, [question, sessionId, selectedOption, selectedOptions, integerAnswer]);

  if (!open) return null;

  return (
    <div
      className={styles.backdrop}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="potd-title"
      >
        <header className={styles.dialogHeader}>
          <div className={styles.titleWrap}>
            <p className={styles.eyebrow}>⚡ Daily Challenge</p>
            <h2 id="potd-title" className={styles.title}>Problem of the Day</h2>
            {topicMeta?.topic_name ? (
              <p className={styles.topicChip}>
                {topicMeta.topic_name}
                {question?.difficulty ? ` · ${question.difficulty}` : ''}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </header>

        <div className={styles.body}>
          {phase === 'loading' || phase === 'submitting' ? (
            <div className={styles.centerState}>
              <Loader />
              <p className={styles.stateText}>
                {phase === 'loading' ? 'Loading today’s question…' : 'Checking your answer…'}
              </p>
            </div>
          ) : null}

          {phase === 'error' ? (
            <div className={styles.centerState}>
              <p className={styles.errorText}>{error}</p>
              <button type="button" className={styles.secondaryBtn} onClick={onClose}>
                Close
              </button>
            </div>
          ) : null}

          {phase === 'no-data' ? (
            <div className={styles.centerState}>
              <p className={styles.stateText}>
                Take your first mock test to unlock the daily challenge.
              </p>
              <p className={styles.stateHint}>
                Once you’ve attempted a few topics, we’ll pick the question that
                matches your weakest area.
              </p>
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => { onClose(); navigate('/tests'); }}
              >
                Start a mock test
              </button>
            </div>
          ) : null}

          {phase === 'unsupported' && sessionId != null ? (
            <div className={styles.centerState}>
              <p className={styles.stateText}>
                Today’s question is in a special format that needs the full
                test view.
              </p>
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => { onClose(); navigate(`/tests/${sessionId}`); }}
              >
                Open in test view
              </button>
            </div>
          ) : null}

          {phase === 'question' && question ? (
            <QuestionView
              question={question}
              selectedOption={selectedOption}
              setSelectedOption={setSelectedOption}
              selectedOptions={selectedOptions}
              setSelectedOptions={setSelectedOptions}
              integerAnswer={integerAnswer}
              setIntegerAnswer={setIntegerAnswer}
            />
          ) : null}

          {phase === 'result' && question && resultData ? (
            <ResultView question={question} result={resultData} />
          ) : null}
        </div>

        {phase === 'question' ? (
          <footer className={styles.footer}>
            <button type="button" className={styles.secondaryBtn} onClick={onClose}>
              Maybe later
            </button>
            <button
              type="button"
              className={styles.primaryBtn}
              onClick={handleSubmit}
              disabled={!answerNonEmpty(question, selectedOption, selectedOptions, integerAnswer)}
            >
              Submit answer
            </button>
          </footer>
        ) : null}

        {phase === 'result' ? (
          <footer className={styles.footer}>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => navigate('/analytics')}
            >
              See analytics
            </button>
            <button type="button" className={styles.primaryBtn} onClick={onClose}>
              Done
            </button>
          </footer>
        ) : null}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Question view (renders the right input for the question type)
// ---------------------------------------------------------------------------

const QuestionView = ({
  question,
  selectedOption, setSelectedOption,
  selectedOptions, setSelectedOptions,
  integerAnswer, setIntegerAnswer,
}) => {
  const type = question.question_type;

  const toggleMulti = (key) => {
    setSelectedOptions((cur) => {
      const set = new Set(cur);
      if (set.has(key)) set.delete(key);
      else set.add(key);
      return Array.from(set).sort();
    });
  };

  return (
    <>
      <div className={styles.questionText}>
        <MarkdownText text={question.question_text} />
      </div>
      {question.question_image ? (
        <img src={question.question_image} alt="" className={styles.questionImage} />
      ) : null}

      {(type === 'single_correct' || type === 'multi_correct') ? (
        <ul className={styles.optionList}>
          {(question.options || []).map((opt) => {
            const isPicked = type === 'single_correct'
              ? selectedOption === opt.key
              : selectedOptions.includes(opt.key);
            return (
              <li key={opt.key}>
                <button
                  type="button"
                  className={`${styles.option} ${isPicked ? styles.optionPicked : ''}`}
                  onClick={() => {
                    if (type === 'single_correct') setSelectedOption(opt.key);
                    else toggleMulti(opt.key);
                  }}
                >
                  <span className={styles.optionKey}>{opt.key}</span>
                  <span className={styles.optionText}>
                    <MarkdownText text={opt.text} inline />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {type === 'integer' ? (
        <div className={styles.integerWrap}>
          <input
            type="number"
            inputMode="numeric"
            className={styles.integerInput}
            value={integerAnswer}
            onChange={(e) => setIntegerAnswer(e.target.value)}
            placeholder="Type your answer"
            aria-label="Integer answer"
          />
        </div>
      ) : null}
    </>
  );
};

// ---------------------------------------------------------------------------
// Result view (correct/wrong + solution)
// ---------------------------------------------------------------------------

const ResultView = ({ question, result }) => {
  const correct = result.is_correct;
  const correctAns = formatAnswer(result.correct_answer);
  const userAns = formatAnswer(result.user_answer);

  return (
    <>
      <div className={`${styles.verdict} ${correct ? styles.verdictWin : styles.verdictLose}`}>
        <span className={styles.verdictIcon}>{correct ? '✓' : '✗'}</span>
        <span className={styles.verdictText}>
          {correct ? 'Correct!' : 'Not quite.'}
        </span>
        <span className={styles.verdictScore}>
          {correct ? `+${result.score_contribution || 0}` : ''}
        </span>
      </div>

      <div className={styles.questionText}>
        <MarkdownText text={question.question_text} />
      </div>

      {/* Options replay (single/multi only) */}
      {(question.options || []).length > 0 ? (
        <ul className={styles.optionList}>
          {question.options.map((opt) => {
            const isCorrect = matchesAnswer(opt.key, result.correct_answer);
            const isUser = matchesAnswer(opt.key, result.user_answer);
            const cls = [
              styles.option,
              styles.optionStatic,
              isCorrect ? styles.optionCorrect : '',
              !isCorrect && isUser ? styles.optionWrong : '',
            ].join(' ');
            return (
              <li key={opt.key}>
                <div className={cls}>
                  <span className={styles.optionKey}>{opt.key}</span>
                  <span className={styles.optionText}>
                    <MarkdownText text={opt.text} inline />
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className={styles.answerRow}>
          <div>
            <p className={styles.answerLabel}>Your answer</p>
            <p className={styles.answerValue}>{userAns || '—'}</p>
          </div>
          <div>
            <p className={styles.answerLabel}>Correct answer</p>
            <p className={styles.answerValue}>{correctAns || '—'}</p>
          </div>
        </div>
      )}

      {result.solution_text ? (
        <section className={styles.solution}>
          <p className={styles.solutionTitle}>Solution</p>
          <div className={styles.solutionBody}>
            <MarkdownText text={result.solution_text} />
          </div>
        </section>
      ) : null}

      {result.solution_image ? (
        <img src={result.solution_image} alt="" className={styles.solutionImg} />
      ) : null}
    </>
  );
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isSupported(type, passageId) {
  if (passageId != null) return false;
  return type === 'single_correct' || type === 'multi_correct' || type === 'integer';
}

function answerNonEmpty(question, sel, selMulti, intAns) {
  switch (question.question_type) {
    case 'single_correct': return !!sel;
    case 'multi_correct':  return selMulti.length > 0;
    case 'integer':        return String(intAns).trim() !== '';
    default:               return false;
  }
}

function buildAnswerPayload(question, sel, selMulti, intAns) {
  const base = { question_id: Number(question.question_id) };
  switch (question.question_type) {
    case 'single_correct': return { ...base, selected_option: sel };
    case 'multi_correct':  return { ...base, selected_options: selMulti };
    case 'integer':        return { ...base, integer_answer: Number(intAns) };
    default:               return base;
  }
}

function matchesAnswer(key, ans) {
  if (ans == null) return false;
  if (Array.isArray(ans)) return ans.map(String).includes(String(key));
  return String(ans).toUpperCase() === String(key).toUpperCase();
}

function formatAnswer(ans) {
  if (ans == null) return '';
  if (Array.isArray(ans)) return ans.join(', ');
  return String(ans);
}

export default PotdModal;
