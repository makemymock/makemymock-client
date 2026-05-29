import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import ExamShell from '../../components/mockTest/ExamShell/ExamShell';
import QuestionViewer from '../../components/mockTest/QuestionViewer/QuestionViewer';
import MarkdownText from '../../components/common/MarkdownText/MarkdownText';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import Podium from '../../components/compete/Podium/Podium';
import { contestService } from '../../services/contestService';
import { tokenStorage } from '../../utils/token';
import { parseApiError } from '../../utils/validators';
import styles from './contestResult.module.css';

const fmtTime = (s) => {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}m ${sec.toString().padStart(2, '0')}s`;
};

// Map a per-question result back to the QuestionViewer's answer shape.
const answerFromResult = (r) => {
  switch (r.question_type) {
    case 'single_correct':
      return { selected_option: r.user_answer || '' };
    case 'multi_correct':
      return { selected_options: r.user_answer || [] };
    case 'integer':
      return { integer_answer: r.user_answer ?? '' };
    case 'matching':
      return { matching: r.user_answer || {} };
    default:
      return {};
  }
};

const ContestResult = () => {
  const { contestId } = useParams();
  const me = tokenStorage.getUser();
  const [result, setResult] = useState(null);
  const [board, setBoard] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([
      contestService.getResult(contestId),
      contestService.getLeaderboard(contestId),
    ])
      .then(([r, b]) => { setResult(r); setBoard(b); })
      .catch((err) => setError(parseApiError(err, 'Could not load result.')));
  }, [contestId]);

  if (error) {
    return (
      <ExamShell chromeless title="Result" subtitle="">
        <ErrorMessage message={error} />
        <Link to="/compete?tab=contest" className={styles.backLink}>← Back to contests</Link>
      </ExamShell>
    );
  }
  if (!result) return <ExamShell chromeless title="Result"><Loader /></ExamShell>;

  const scorePct = result.max_score > 0
    ? Math.round((100 * result.score) / result.max_score)
    : 0;

  return (
    <ExamShell
      chromeless
      eyebrow="Result"
      title={result.title}
      subtitle={`Submitted ${new Date(result.submitted_at).toLocaleString()}`}
    >
      <div className={styles.layout}>
        {/* Hero — your headline stats */}
        <section className={styles.hero}>
          <div className={styles.heroLeft}>
            <p className={styles.eyebrow}>Your score</p>
            <p className={styles.scoreBig}>
              {result.score.toFixed(1)}
              <span className={styles.scoreMax}>/ {result.max_score.toFixed(0)}</span>
            </p>
            <p className={styles.scoreSub}>{scorePct}% · {result.accuracy_pct.toFixed(0)}% accuracy</p>
          </div>

          <div className={styles.heroStats}>
            <div className={styles.statTile}>
              <p className={styles.statLabel}>Rank</p>
              <p className={styles.statValue}>
                #{result.rank}
                <span className={styles.statSub}>of {result.total_participants}</span>
              </p>
            </div>
            <div className={styles.statTile}>
              <p className={styles.statLabel}>Time taken</p>
              <p className={styles.statValue}>{fmtTime(result.time_taken_seconds)}</p>
            </div>
            <div className={`${styles.statTile} ${styles.tileOk}`}>
              <p className={styles.statLabel}>Correct</p>
              <p className={styles.statValue}>{result.correct_count}</p>
            </div>
            <div className={`${styles.statTile} ${styles.tileBad}`}>
              <p className={styles.statLabel}>Wrong</p>
              <p className={styles.statValue}>{result.wrong_count}</p>
            </div>
            <div className={`${styles.statTile} ${styles.tileMuted}`}>
              <p className={styles.statLabel}>Skipped</p>
              <p className={styles.statValue}>{result.unattempted_count}</p>
            </div>
          </div>
        </section>

        {/* Leaderboard */}
        <section className={styles.card}>
          <header className={styles.cardHeader}>
            <h2 className={styles.cardTitle}>Leaderboard</h2>
            <Link to="/compete?tab=leaderboard" className={styles.cardLink}>
              All leaderboards →
            </Link>
          </header>
          {board === null ? (
            <Loader />
          ) : board.rows.length === 0 ? (
            <p className={styles.muted}>You're the first to submit.</p>
          ) : (
            <>
              <Podium rows={board.rows.slice(0, 3)} youUserId={me?.id} />
              {board.rows.length > 3 ? (
                <div className={styles.tableWrap}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Student</th>
                        <th>Score</th>
                        <th>Correct</th>
                        <th>Wrong</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {board.rows.slice(3).map((r) => {
                        const meRow = r.is_you || (me && r.user_id === me.id);
                        return (
                          <tr key={r.user_id} className={meRow ? styles.meRow : ''}>
                            <td className={styles.rankCell}>{r.rank}</td>
                            <td>
                              {r.username}
                              {meRow ? <span className={styles.youTag}>You</span> : null}
                            </td>
                            <td><strong>{r.score.toFixed(1)}</strong></td>
                            <td>{r.correct_count}</td>
                            <td>{r.wrong_count}</td>
                            <td>{fmtTime(r.time_taken_seconds)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </>
          )}
        </section>

        {/* Per-question review */}
        <section className={styles.card}>
          <header className={styles.cardHeader}>
            <h2 className={styles.cardTitle}>Question review</h2>
          </header>
          <ol className={styles.reviewList}>
            {result.results.map((r) => {
              const correct = r.is_correct;
              const partial = !correct && r.correctness > 0;
              const empty = !r.user_answer && r.marks_awarded === 0;
              const badge = correct
                ? { cls: styles.badgeOk, label: 'Correct' }
                : partial
                  ? { cls: styles.badgeWarn, label: `Partial (${Math.round(r.correctness * 100)}%)` }
                  : empty
                    ? { cls: styles.badgeMuted, label: 'Skipped' }
                    : { cls: styles.badgeBad, label: 'Wrong' };
              return (
                <li key={r.question_id} className={styles.reviewItem}>
                  <header className={styles.reviewHead}>
                    <span className={`${styles.badge} ${badge.cls}`}>{badge.label}</span>
                    <span className={styles.marksLine}>
                      {r.marks_awarded > 0 ? '+' : ''}{r.marks_awarded.toFixed(1)} marks
                    </span>
                  </header>
                  <QuestionViewer
                    question={{
                      ...r,
                      passage_id: null,
                      passage_text: null,
                      passage_sub_index: null,
                      passage_sub_total: null,
                      topic_id: 0,
                    }}
                    index={r.display_order}
                    total={result.results.length}
                    answer={answerFromResult(r)}
                    onChange={() => {}}
                    readOnly
                    correctAnswer={r.correct_answer}
                    isCorrect={r.is_correct}
                  />
                  {r.solution_text ? (
                    <details className={styles.solution}>
                      <summary>Show worked solution</summary>
                      <div className={styles.solutionBody}>
                        <MarkdownText text={r.solution_text} />
                      </div>
                    </details>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </section>

        <div className={styles.footerRow}>
          <Link to="/compete?tab=contest" className={styles.backLink}>← All contests</Link>
          <Link to="/compete?tab=leaderboard" className={styles.backLink}>Leaderboard →</Link>
        </div>
      </div>
    </ExamShell>
  );
};

export default ContestResult;
