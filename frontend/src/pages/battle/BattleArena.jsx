import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { battleService } from '../../services/battleService';
import styles from './battleArena.module.css';

// Phases drive which sub-view is rendered.
const PHASE = {
  CONNECTING: 'connecting',
  QUEUED: 'queued',
  MATCHED: 'matched',
  COUNTDOWN: 'countdown',
  QUESTION: 'question',
  RESULT: 'result',
  COMPLETE: 'complete',
  ERROR: 'error',
  TIMEOUT: 'timeout',
};

const BattleArena = () => {
  const navigate = useNavigate();
  const wsRef = useRef(null);
  const [phase, setPhase] = useState(PHASE.CONNECTING);
  const [opponent, setOpponent] = useState(null);
  const [countdown, setCountdown] = useState(null);
  const [question, setQuestion] = useState(null); // {index, total, question_id, ...}
  const [selected, setSelected] = useState(null);
  const [questionStartedAt, setQuestionStartedAt] = useState(null);
  const [timeLeft, setTimeLeft] = useState(null);
  const [opponentLocked, setOpponentLocked] = useState(false);
  const [yourScore, setYourScore] = useState(0);
  const [opponentScore, setOpponentScore] = useState(0);
  const [yourCorrect, setYourCorrect] = useState(false); // for result phase
  const [opponentCorrect, setOpponentCorrect] = useState(false);
  const [yourDelta, setYourDelta] = useState(0);
  const [oppDelta, setOppDelta] = useState(0);
  const [correctOption, setCorrectOption] = useState(null);
  const [finalState, setFinalState] = useState(null); // {result, your_score, ...}
  const [errorMessage, setErrorMessage] = useState('');

  // ---------- WebSocket lifecycle ----------
  useEffect(() => {
    const ws = battleService.openSocket();
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      handleServerMessage(msg);
    };
    ws.onerror = () => {
      setPhase(PHASE.ERROR);
      setErrorMessage('Lost connection to the server.');
    };
    ws.onclose = (ev) => {
      // If we already reached COMPLETE / TIMEOUT, ignore the close.
      setPhase((current) => {
        if (
          current === PHASE.COMPLETE ||
          current === PHASE.TIMEOUT ||
          current === PHASE.ERROR
        ) {
          return current;
        }
        // 4401 = unauthorized, 4409 = duplicate
        if (ev.code === 4401) {
          setErrorMessage('You need to be logged in to play.');
        } else if (ev.code === 4409) {
          setErrorMessage(
            "You're already in a battle on another tab. Close it and try again."
          );
        } else if (current === PHASE.CONNECTING || current === PHASE.QUEUED) {
          // Closed before match was made.
          setErrorMessage('Disconnected before a match was found.');
        } else {
          setErrorMessage('The connection dropped mid-battle.');
        }
        return PHASE.ERROR;
      });
    };

    return () => {
      try {
        ws.close();
      } catch { /* noop */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- Per-question timer ----------
  useEffect(() => {
    if (phase !== PHASE.QUESTION || !question) {
      return undefined;
    }
    const tick = () => {
      const elapsed = (Date.now() - questionStartedAt) / 1000;
      const remaining = Math.max(0, question.time_limit_seconds - elapsed);
      setTimeLeft(remaining);
    };
    tick();
    const id = setInterval(tick, 100);
    return () => clearInterval(id);
  }, [phase, question, questionStartedAt]);

  // ---------- Server → client dispatcher ----------
  const handleServerMessage = useCallback((msg) => {
    switch (msg.type) {
      case 'queued':
        setPhase(PHASE.QUEUED);
        break;
      case 'matched':
        setOpponent(msg.opponent);
        setPhase(PHASE.MATCHED);
        break;
      case 'countdown':
        setCountdown(msg.value);
        setPhase(PHASE.COUNTDOWN);
        break;
      case 'question':
        setQuestion(msg);
        setSelected(null);
        setOpponentLocked(false);
        setQuestionStartedAt(Date.now());
        setTimeLeft(msg.time_limit_seconds);
        setCorrectOption(null);
        setPhase(PHASE.QUESTION);
        break;
      case 'opponent_answered':
        setOpponentLocked(true);
        break;
      case 'question_result':
        setCorrectOption(msg.correct_option);
        setYourCorrect(msg.your_correct);
        setOpponentCorrect(msg.opponent_correct);
        setYourDelta(msg.your_score_delta);
        setOppDelta(msg.opponent_score_delta);
        setYourScore(msg.your_total_score);
        setOpponentScore(msg.opponent_total_score);
        setPhase(PHASE.RESULT);
        break;
      case 'battle_complete':
        setFinalState(msg);
        setPhase(PHASE.COMPLETE);
        break;
      case 'queue_timeout':
        setPhase(PHASE.TIMEOUT);
        break;
      case 'error':
        setErrorMessage(msg.message || 'Something went wrong.');
        setPhase(PHASE.ERROR);
        break;
      default:
        break;
    }
  }, []);

  // ---------- Client → server: submit answer ----------
  const submitAnswer = useCallback(
    (optionKey) => {
      if (phase !== PHASE.QUESTION || selected) return;
      setSelected(optionKey);
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: 'submit_answer',
            question_id: question.question_id,
            selected_option: optionKey,
          })
        );
      }
    },
    [phase, selected, question]
  );

  // ---------- Sub-views ----------
  return (
    <div className={styles.page}>
      {phase === PHASE.CONNECTING && <ConnectingView />}
      {phase === PHASE.QUEUED && <QueuedView onLeave={() => navigate('/battle')} />}
      {phase === PHASE.MATCHED && <MatchedView opponent={opponent} />}
      {phase === PHASE.COUNTDOWN && <CountdownView value={countdown} />}
      {(phase === PHASE.QUESTION || phase === PHASE.RESULT) && (
        <QuestionView
          phase={phase}
          question={question}
          selected={selected}
          correctOption={correctOption}
          opponentLocked={opponentLocked}
          timeLeft={timeLeft}
          yourScore={yourScore}
          opponentScore={opponentScore}
          opponent={opponent}
          yourCorrect={yourCorrect}
          opponentCorrect={opponentCorrect}
          yourDelta={yourDelta}
          oppDelta={oppDelta}
          onSelect={submitAnswer}
        />
      )}
      {phase === PHASE.COMPLETE && finalState && (
        <CompleteView
          state={finalState}
          onPlayAgain={() => window.location.reload()}
          onHome={() => navigate('/battle')}
          onHistory={() => navigate('/battle/history')}
        />
      )}
      {phase === PHASE.TIMEOUT && (
        <TimeoutView
          onRetry={() => window.location.reload()}
          onHome={() => navigate('/battle')}
        />
      )}
      {phase === PHASE.ERROR && (
        <ErrorView
          message={errorMessage}
          onHome={() => navigate('/battle')}
        />
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Sub-views
// ---------------------------------------------------------------------------

const ConnectingView = () => (
  <div className={styles.centeredCard}>
    <div className={styles.spinner} aria-hidden="true" />
    <h2 className={styles.cardTitle}>Connecting…</h2>
    <p className={styles.cardSubtitle}>Opening a line to the battle arena.</p>
  </div>
);

const QueuedView = ({ onLeave }) => {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className={styles.centeredCard}>
      <div className={styles.pulseRing} aria-hidden="true">
        <div />
        <div />
        <div />
      </div>
      <h2 className={styles.cardTitle}>Searching for opponent…</h2>
      <p className={styles.cardSubtitle}>
        {secs < 15
          ? `Looking for another player (${secs}s)`
          : 'Almost there — hold tight.'}
      </p>
      <button type="button" className={styles.ghostButton} onClick={onLeave}>
        Cancel
      </button>
    </div>
  );
};

const MatchedView = ({ opponent }) => (
  <div className={styles.centeredCard}>
    <p className={styles.eyebrow}>Match found</p>
    <h2 className={styles.cardTitle}>
      vs <span className={styles.opponentName}>{opponent?.username || 'Opponent'}</span>
    </h2>
    <p className={styles.cardSubtitle}>Get ready…</p>
  </div>
);

const CountdownView = ({ value }) => (
  <div className={styles.centeredCard}>
    <div key={value} className={styles.countdown}>{value}</div>
    <p className={styles.cardSubtitle}>Steady…</p>
  </div>
);

const QuestionView = ({
  phase,
  question,
  selected,
  correctOption,
  opponentLocked,
  timeLeft,
  yourScore,
  opponentScore,
  opponent,
  yourCorrect,
  opponentCorrect,
  yourDelta,
  oppDelta,
  onSelect,
}) => {
  const total = question?.total || 0;
  const idx = (question?.index ?? 0) + 1;
  const pctRemaining = useMemo(() => {
    if (!question || timeLeft === null) return 100;
    return Math.max(0, Math.min(100, (timeLeft / question.time_limit_seconds) * 100));
  }, [question, timeLeft]);

  return (
    <div className={styles.arena}>
      <header className={styles.arenaHeader}>
        <div className={styles.scoreCard}>
          <span className={styles.scoreName}>YOU</span>
          <span className={styles.scoreValue}>{yourScore}</span>
        </div>
        <div className={styles.questionMeta}>
          <p className={styles.questionPos}>Question {idx} / {total}</p>
          <p className={styles.difficultyTag}>{question?.difficulty}</p>
        </div>
        <div className={styles.scoreCard}>
          <span className={styles.scoreName}>{opponent?.username || 'OPP'}</span>
          <span className={styles.scoreValue}>{opponentScore}</span>
        </div>
      </header>

      <div className={styles.timerTrack}>
        <div
          className={`${styles.timerFill} ${
            timeLeft !== null && timeLeft < 4 ? styles.timerLow : ''
          }`}
          style={{ width: `${pctRemaining}%` }}
        />
        <span className={styles.timerLabel}>
          {timeLeft !== null ? `${timeLeft.toFixed(1)}s` : '—'}
        </span>
      </div>

      <main className={styles.questionBody}>
        <p className={styles.questionPrompt}>{question?.question_text}</p>
        {question?.question_image ? (
          <img
            className={styles.questionImage}
            src={question.question_image}
            alt=""
          />
        ) : null}

        <div className={styles.options}>
          {(question?.options || []).map((opt) => {
            const isPicked = selected === opt.key;
            const isCorrect = phase === PHASE.RESULT && opt.key === correctOption;
            const isWrong =
              phase === PHASE.RESULT &&
              isPicked &&
              opt.key !== correctOption;
            return (
              <button
                key={opt.key}
                type="button"
                disabled={selected !== null || phase === PHASE.RESULT}
                onClick={() => onSelect(opt.key)}
                className={[
                  styles.option,
                  isPicked ? styles.optionPicked : '',
                  isCorrect ? styles.optionCorrect : '',
                  isWrong ? styles.optionWrong : '',
                ].join(' ')}
              >
                <span className={styles.optionKey}>{opt.key}</span>
                <span className={styles.optionText}>{opt.text}</span>
              </button>
            );
          })}
        </div>

        {phase === PHASE.QUESTION ? (
          <div className={styles.statusRow}>
            <span className={selected ? styles.lockedChip : styles.thinkingChip}>
              {selected ? `🔒 You locked ${selected}` : 'Pick an option…'}
            </span>
            <span
              className={
                opponentLocked ? styles.lockedChipOpp : styles.thinkingChipOpp
              }
            >
              {opponentLocked
                ? `🔒 ${opponent?.username || 'Opponent'} locked in`
                : `⏳ ${opponent?.username || 'Opponent'} thinking…`}
            </span>
          </div>
        ) : null}

        {phase === PHASE.RESULT ? (
          <div className={styles.resultPanel}>
            <div
              className={`${styles.deltaChip} ${
                yourCorrect ? styles.deltaWin : styles.deltaLose
              }`}
            >
              YOU {yourCorrect ? `+${yourDelta}` : '+0'}
            </div>
            <div
              className={`${styles.deltaChip} ${
                opponentCorrect ? styles.deltaWin : styles.deltaLose
              }`}
            >
              {opponent?.username || 'OPP'}{' '}
              {opponentCorrect ? `+${oppDelta}` : '+0'}
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
};

const CompleteView = ({ state, onPlayAgain, onHome, onHistory }) => {
  const isWin = state.result === 'win';
  const isDraw = state.result === 'draw';
  const headline = isWin ? 'VICTORY!' : isDraw ? "IT'S A DRAW" : 'DEFEAT';

  return (
    <div className={styles.completePage}>
      {isWin ? <Confetti /> : null}
      <p className={styles.eyebrow}>Battle #{String(state.battle_id).slice(0, 6)}</p>
      <h1
        className={[
          styles.completeHeadline,
          isWin ? styles.headlineWin : '',
          isDraw ? styles.headlineDraw : '',
          !isWin && !isDraw ? styles.headlineLose : '',
        ].join(' ')}
      >
        {headline}
      </h1>

      <div className={styles.completeScores}>
        <div className={styles.completeScoreCard}>
          <p className={styles.completeScoreLabel}>YOU</p>
          <p className={styles.completeScoreValue}>{state.your_score}</p>
          <p className={styles.completeScoreSub}>
            {state.your_correct} correct
          </p>
        </div>
        <div className={styles.completeVs}>VS</div>
        <div className={styles.completeScoreCard}>
          <p className={styles.completeScoreLabel}>
            {state.opponent_username || 'OPPONENT'}
          </p>
          <p className={styles.completeScoreValue}>{state.opponent_score}</p>
          <p className={styles.completeScoreSub}>
            {state.opponent_correct} correct
          </p>
        </div>
      </div>

      <div className={styles.completeActions}>
        <button
          type="button"
          className={styles.primaryAction}
          onClick={onPlayAgain}
        >
          Play again
        </button>
        <button
          type="button"
          className={styles.secondaryAction}
          onClick={onHistory}
        >
          Battle history
        </button>
        <button
          type="button"
          className={styles.ghostAction}
          onClick={onHome}
        >
          Back to arena
        </button>
      </div>
    </div>
  );
};

const TimeoutView = ({ onRetry, onHome }) => (
  <div className={styles.centeredCard}>
    <p className={styles.eyebrow}>No opponent yet</p>
    <h2 className={styles.cardTitle}>The arena is quiet…</h2>
    <p className={styles.cardSubtitle}>
      No one joined within the wait window. Want to try again?
    </p>
    <div className={styles.actionRow}>
      <button type="button" className={styles.primaryAction} onClick={onRetry}>
        Try again
      </button>
      <button type="button" className={styles.ghostButton} onClick={onHome}>
        Back to arena
      </button>
    </div>
  </div>
);

const ErrorView = ({ message, onHome }) => (
  <div className={styles.centeredCard}>
    <p className={styles.eyebrowError}>Something went wrong</p>
    <h2 className={styles.cardTitle}>{message || 'Unknown error.'}</h2>
    <div className={styles.actionRow}>
      <button type="button" className={styles.ghostButton} onClick={onHome}>
        Back to arena
      </button>
    </div>
  </div>
);

// CSS-only confetti — 24 falling pieces, randomised delays.
const Confetti = () => {
  const pieces = Array.from({ length: 24 });
  return (
    <div className={styles.confetti} aria-hidden="true">
      {pieces.map((_, i) => (
        <span
          key={i}
          className={styles.confettiPiece}
          style={{
            left: `${(i * 4.16) % 100}%`,
            animationDelay: `${(i % 8) * 0.15}s`,
            background: ['#6fd9bd', '#f7c66b', '#ff7a59', '#a39bff'][i % 4],
          }}
        />
      ))}
    </div>
  );
};

export default BattleArena;
