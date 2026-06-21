import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import RichContent from '../../components/learn/RichContent';
import { patternLearningService } from '../../services/patternLearningService';
import { parseApiError } from '../../utils/validators';
import styles from './SolveQuestion.module.css';

const SolveQuestion = () => {
  const { questionId } = useParams();
  const navigate = useNavigate();

  const [content, setContent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // selection
  const [single, setSingle] = useState('');
  const [multi, setMulti] = useState([]);
  const [integer, setInteger] = useState('');

  const [result, setResult] = useState(null);   // fresh submit response
  const [submitting, setSubmitting] = useState(false);

  // (Re)load whenever the question changes — also resets all local state.
  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError('');
      setResult(null);
      setSingle(''); setMulti([]); setInteger('');
      try {
        const data = await patternLearningService.getQuestion(questionId);
        if (!alive) return;
        setContent(data);
        // Pre-fill a prior answer so a re-opened (already-solved) question
        // shows what the student picked.
        if (data.answer_revealed && data.prior_answer != null) {
          if (data.type === 'mcqm' && Array.isArray(data.prior_answer)) setMulti(data.prior_answer);
          else if (data.type === 'integer') setInteger(String(data.prior_answer));
          else setSingle(String(data.prior_answer));
        }
      } catch (err) {
        if (alive) {
          setError(parseApiError(err, 'This question is locked or unavailable.'));
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [questionId]);

  // Already-answered state comes either from a fresh submit or from the
  // server saying answer_revealed (re-opened question).
  const revealed = result != null || (content?.answer_revealed ?? false);
  const correctOptions = result?.correct_options ?? content?.correct_options ?? [];
  const correctValue = result?.correct_value ?? content?.correct_value ?? null;
  const explanation = result?.explanation_html ?? content?.explanation_html ?? '';
  const isCorrect = result ? result.is_correct : content?.prior_correct;

  const toggleMulti = (id) => {
    if (revealed) return;
    setMulti((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const answer = useMemo(() => {
    if (!content) return null;
    if (content.type === 'mcqm') return multi;
    if (content.type === 'integer') return integer.trim();
    return single;
  }, [content, single, multi, integer]);

  const canSubmit = !revealed && !submitting && (
    content?.type === 'mcqm' ? multi.length > 0
      : content?.type === 'integer' ? integer.trim() !== ''
      : single !== ''
  );

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const res = await patternLearningService.submitAnswer(questionId, answer);
      setResult(res);
    } catch (err) {
      setError(parseApiError(err, 'Could not submit your answer.'));
    } finally {
      setSubmitting(false);
    }
  };

  const goNext = useCallback(() => {
    const next = result?.next_question_id;
    if (next) {
      navigate(`/learn/questions/${encodeURIComponent(next)}`);
    } else if (content?.pattern_id) {
      navigate(`/learn/patterns/${encodeURIComponent(content.pattern_id)}`);
    }
  }, [result, content, navigate]);

  if (loading) return <Loader />;
  if (error && !content) return <div className={styles.page}><div className={styles.error}>{error}</div></div>;
  if (!content) return null;

  const isPicked = (id) =>
    content.type === 'mcqm' ? multi.includes(id) : single === id;

  return (
    <div className={styles.page}>
      <button
        className={styles.back}
        onClick={() => navigate(`/learn/patterns/${encodeURIComponent(content.pattern_id)}`)}
      >
        ← Back to the path
      </button>

      <div className={styles.card}>
        <RichContent html={content.question_html} className={styles.question} />

        {content.type === 'integer' ? (
          <input
            className={styles.intInput}
            type="text"
            inputMode="decimal"
            placeholder="Your answer"
            value={integer}
            disabled={revealed}
            onChange={(e) => setInteger(e.target.value)}
          />
        ) : (
          <ul className={styles.options}>
            {content.options.map((o) => {
              const picked = isPicked(o.identifier);
              const isRight = correctOptions.includes(o.identifier);
              const cls = [
                styles.option,
                picked ? styles.picked : '',
                revealed && isRight ? styles.right : '',
                revealed && picked && !isRight ? styles.wrong : '',
              ].join(' ');
              return (
                <li key={o.identifier}>
                  <button
                    type="button"
                    className={cls}
                    disabled={revealed}
                    onClick={() =>
                      content.type === 'mcqm'
                        ? toggleMulti(o.identifier)
                        : setSingle(o.identifier)
                    }
                  >
                    <span className={styles.optId}>{o.identifier}</span>
                    <RichContent html={o.content} block={false} className={styles.optBody} />
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        {content.type === 'mcqm' && !revealed && (
          <p className={styles.hint}>Select all that apply.</p>
        )}
        {error && <div className={styles.error}>{error}</div>}

        {!revealed ? (
          <button className={styles.submit} onClick={submit} disabled={!canSubmit}>
            {submitting ? 'Checking…' : 'Submit'}
          </button>
        ) : (
          <div className={styles.feedbackBlock}>
            <div className={`${styles.verdict} ${isCorrect ? styles.vRight : styles.vWrong}`}>
              {isCorrect ? '✓ Correct!' : '✗ Not quite'}
              {content.type === 'integer' && correctValue != null && (
                <span className={styles.answerLine}>
                  {' '}Answer: <RichContent html={correctValue} block={false} />
                </span>
              )}
            </div>

            {explanation && (
              <div className={styles.explanation}>
                <span className={styles.explTitle}>Solution</span>
                <RichContent html={explanation} />
              </div>
            )}

            <button className={styles.submit} onClick={goNext}>
              {result?.next_question_id
                ? 'Next question →'
                : result?.pattern_completed
                  ? 'Pattern complete 🎉 — back to path'
                  : 'Back to path'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default SolveQuestion;
