import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import QuestionViewer from '../../components/mockTest/QuestionViewer/QuestionViewer';
import MarkdownText from '../../components/common/MarkdownText/MarkdownText';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { mockTestService } from '../../services/mockTestService';
import { parseApiError } from '../../utils/validators';
import styles from './result.module.css';

const Result = () => {
  const { sessionId: routeId } = useParams();
  const sessionId = Number(routeId);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await mockTestService.getResults(sessionId);
        if (!cancelled) setData(res);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load results.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const sortedResults = useMemo(
    () => (data ? [...data.results].sort((a, b) => a.display_order - b.display_order) : []),
    [data],
  );

  if (loading) {
    return (
      <ExamShell title="Loading results…">
        <Loader />
      </ExamShell>
    );
  }
  if (error) {
    return (
      <ExamShell title="Couldn't load results">
        <ErrorMessage message={error} />
      </ExamShell>
    );
  }
  if (!data) return null;

  const current = sortedResults[activeIndex];
  const currentQuestion = current ? resultToQuestion(current) : null;

  const acc = data.accuracy_pct.toFixed(1);
  const scorePct = data.max_score
    ? ((data.total_score / data.max_score) * 100).toFixed(1)
    : '0.0';

  return (
    <ExamShell
      eyebrow={`Test #${sessionId}`}
      title="Your results"
      subtitle="Every question is graded server-side. Partial credit is awarded for multi-correct and matching questions. Solutions are shown below each question."
    >
      <section className={styles.summary}>
        <div className={`${styles.bigStat} ${styles.score}`}>
          <span className={styles.statLabel}>Score</span>
          <span className={styles.statValue}>
            {data.total_score.toFixed(2)}
            <span className={styles.statSlash}>/ {data.max_score}</span>
          </span>
          <span className={styles.statSub}>{scorePct}%</span>
        </div>
        <div className={styles.bigStat}>
          <span className={styles.statLabel}>Accuracy</span>
          <span className={styles.statValue}>{acc}%</span>
        </div>
        <div className={styles.miniStats}>
          <div className={styles.miniStat}><span>{data.correct}</span><small>Correct</small></div>
          <div className={styles.miniStat}><span>{data.partial}</span><small>Partial</small></div>
          <div className={styles.miniStat}><span>{data.incorrect}</span><small>Wrong</small></div>
          <div className={styles.miniStat}><span>{data.total}</span><small>Total</small></div>
        </div>
      </section>

      <section className={styles.reviewer}>
        <aside className={styles.reviewerNav}>
          <header className={styles.reviewerHead}>
            <h3>Review answers</h3>
          </header>
          <ol className={styles.reviewList}>
            {sortedResults.map((r, i) => {
              const ok = r.is_correct;
              const partial = !ok && r.correctness > 0 && r.correctness < 1;
              const cls = [
                styles.reviewItem,
                i === activeIndex ? styles.reviewItemActive : '',
                ok ? styles.reviewItemOk : partial ? styles.reviewItemPartial : styles.reviewItemWrong,
              ].filter(Boolean).join(' ');
              return (
                <li key={r.question_id}>
                  <button type="button" className={cls} onClick={() => setActiveIndex(i)}>
                    <span className={styles.reviewIdx}>{i + 1}</span>
                    <span className={styles.reviewType}>{r.question_type}</span>
                    <span className={styles.reviewDiff}>{r.difficulty}</span>
                    <span className={styles.reviewScore}>{Math.round(r.correctness * 100)}%</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </aside>

        <div className={styles.reviewerBody}>
          {current && currentQuestion ? (
            <>
              <QuestionViewer
                question={currentQuestion}
                index={activeIndex}
                total={sortedResults.length}
                answer={inflateAnswerFromResult(current, currentQuestion)}
                onChange={() => {}}
                readOnly
                correctAnswer={current.correct_answer}
                isCorrect={current.is_correct}
              />
              <SolutionPanel result={current} />
            </>
          ) : null}
        </div>
      </section>

      <div className={styles.actions}>
        <Link to="/tests" className={styles.linkBtn}>Take another test</Link>
        <Link to="/analytics" className={styles.linkBtn}>Open analytics</Link>
        <Link to="/history" className={styles.linkBtn}>See history</Link>
      </div>
    </ExamShell>
  );
};

// Turn a PerQuestionResult row into the shape QuestionViewer expects.
function resultToQuestion(r) {
  return {
    question_id: r.question_id,
    topic_id: r.topic_id,
    display_order: r.display_order,
    question_type: r.question_type,
    difficulty: r.difficulty,
    is_extra: false,
    passage_id: r.passage_id ?? null,
    passage_text: r.passage_text ?? null,
    passage_image: r.passage_image ?? null,
    passage_sub_index: r.passage_sub_index ?? null,
    passage_sub_total: r.passage_sub_total ?? null,
    question_text: r.question_text || '',
    question_image: r.question_image ?? null,
    options: r.options || [],
    left_column: r.left_column || [],
    right_column: r.right_column || [],
  };
}

const SolutionPanel = ({ result }) => {
  const hasSolution = !!(result.solution_text || result.solution_image);
  return (
    <section className={styles.solution}>
      <header className={styles.solutionHead}>
        <h3 className={styles.solutionTitle}>Solution</h3>
        <span className={`${styles.solutionVerdict} ${result.is_correct ? styles.verdictOk : styles.verdictBad}`}>
          {result.is_correct
            ? 'Correct'
            : (result.correctness > 0
                ? `Partial · ${Math.round(result.correctness * 100)}%`
                : 'Incorrect')}
        </span>
      </header>

      {hasSolution ? (
        <>
          {result.solution_text ? <MarkdownText text={result.solution_text} /> : null}
          {result.solution_image ? (
            <img src={result.solution_image} alt="" className={styles.solutionImg} />
          ) : null}
        </>
      ) : (
        <p className={styles.solutionEmpty}>
          No written solution available for this question.
        </p>
      )}
    </section>
  );
};

function inflateAnswerFromResult(result, question) {
  const qtype = question.passage_sub_index != null ? 'single_correct' : question.question_type;
  const ua = result.user_answer;
  if (qtype === 'single_correct') return { selected_option: typeof ua === 'string' ? ua : null };
  if (qtype === 'multi_correct') return { selected_options: Array.isArray(ua) ? ua : [] };
  if (qtype === 'integer') return { integer_answer: ua };
  if (qtype === 'matching') return { matching: ua && typeof ua === 'object' ? ua : {} };
  return {};
}

export default Result;
