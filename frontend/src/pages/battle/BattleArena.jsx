import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { battleService } from '../../services/battleService';
import { authService } from '../../services/authService';
import { tokenStorage } from '../../utils/token';
import MarkdownText from '../../components/common/MarkdownText/MarkdownText';
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
  // The logged-in user's own username — read from local session so the score
  // card shows the actual name (instead of a generic "YOU"). Falls back to
  // "You" only if we somehow don't have it cached.
  const me = tokenStorage.getUser();
  const yourUsername = me?.username || 'You';
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
  // Gamification: per-player consecutive-correct streak (resets on a wrong
  // or missed answer) and who locked first on the current question.
  const [yourStreak, setYourStreak] = useState(0);
  const [opponentStreak, setOpponentStreak] = useState(0);
  const [firstLocker, setFirstLocker] = useState(null); // 'you' | 'opp' | null

  // ---------- Server → client dispatcher ----------
  // Declared before the WebSocket effect that references it: the effect
  // captures this callback in `ws.onmessage`, and a forward reference would
  // trip the `react-hooks/immutability` rule even though useCallback([],)
  // keeps the identity stable.
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
        setFirstLocker(null);
        setQuestionStartedAt(Date.now());
        setTimeLeft(msg.time_limit_seconds);
        setCorrectOption(null);
        setPhase(PHASE.QUESTION);
        break;
      case 'opponent_answered':
        setOpponentLocked(true);
        // If you haven't locked yet, the opponent beat you to the lock.
        setFirstLocker((cur) => cur ?? 'opp');
        break;
      case 'question_result':
        setCorrectOption(msg.correct_option);
        setYourCorrect(msg.your_correct);
        setOpponentCorrect(msg.opponent_correct);
        setYourDelta(msg.your_score_delta);
        setOppDelta(msg.opponent_score_delta);
        setYourScore(msg.your_total_score);
        setOpponentScore(msg.opponent_total_score);
        // Consecutive-correct streak: bump on a right answer, reset on a
        // wrong / missed one — gives a visible "🔥 N" chip when momentum
        // is building.
        setYourStreak((s) => (msg.your_correct ? s + 1 : 0));
        setOpponentStreak((s) => (msg.opponent_correct ? s + 1 : 0));
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

  // ---------- WebSocket lifecycle ----------
  useEffect(() => {
    let cancelled = false;
    let ws = null;

    (async () => {
      // Pre-flight: ping /auth/me through axios. If the access token is
      // expired, the response interceptor in axiosInstance refreshes it
      // and writes the new pair to tokenStorage — so the WebSocket URL
      // we build next picks up the FRESH token instead of the stale one.
      // The WS handshake itself doesn't go through axios, so without this
      // step expired tokens silently fail with HTTP 403 on the upgrade
      // request.
      try {
        await authService.me();
      } catch {
        if (!cancelled) {
          setErrorMessage('Your session has expired. Please log in again.');
          setPhase(PHASE.ERROR);
        }
        return;
      }
      if (cancelled) return;

      ws = battleService.openSocket();
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
        // Don't overwrite an already-set, more specific error.
        setPhase((current) => {
          if (
            current === PHASE.COMPLETE ||
            current === PHASE.TIMEOUT ||
            current === PHASE.ERROR
          ) {
            return current;
          }
          setErrorMessage(
            "Couldn't reach the battle server. Check your connection and try again."
          );
          return PHASE.ERROR;
        });
      };
      ws.onclose = (ev) => {
        setPhase((current) => {
          if (
            current === PHASE.COMPLETE ||
            current === PHASE.TIMEOUT ||
            current === PHASE.ERROR
          ) {
            return current;
          }
          // Custom close codes from the server; the matching `error` JSON
          // message usually arrives first via onmessage and sets the
          // friendlier text — we only fall back here if it didn't.
          if (ev.code === 4401) {
            setErrorMessage('Your session has expired. Please log in again.');
          } else if (ev.code === 4409) {
            setErrorMessage(
              "You're already in a battle on another tab. Close it and try again."
            );
          } else if (current === PHASE.CONNECTING || current === PHASE.QUEUED) {
            setErrorMessage('Disconnected before a match was found.');
          } else {
            setErrorMessage('The connection dropped mid-battle.');
          }
          return PHASE.ERROR;
        });
      };
    })();

    return () => {
      cancelled = true;
      if (ws) {
        try {
          ws.close();
        } catch { /* noop */ }
      }
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

  // ---------- Client → server: submit answer ----------
  const submitAnswer = useCallback(
    (optionKey) => {
      if (phase !== PHASE.QUESTION || selected) return;
      setSelected(optionKey);
      // First-to-lock: if the opponent's "answered" ping hasn't arrived,
      // we beat them to the buzzer for this question.
      setFirstLocker((cur) => cur ?? 'you');
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
      {phase === PHASE.MATCHED && (
        <MatchedView yourUsername={yourUsername} opponent={opponent} />
      )}
      {phase === PHASE.COUNTDOWN && <CountdownView value={countdown} />}
      {(phase === PHASE.QUESTION || phase === PHASE.RESULT) && (
        <QuestionView
          phase={phase}
          question={question}
          selected={selected}
          correctOption={correctOption}
          opponentLocked={opponentLocked}
          timeLeft={timeLeft}
          yourUsername={yourUsername}
          yourScore={yourScore}
          opponentScore={opponentScore}
          opponent={opponent}
          yourCorrect={yourCorrect}
          opponentCorrect={opponentCorrect}
          yourDelta={yourDelta}
          oppDelta={oppDelta}
          yourStreak={yourStreak}
          opponentStreak={opponentStreak}
          firstLocker={firstLocker}
          onSelect={submitAnswer}
        />
      )}
      {phase === PHASE.COMPLETE && finalState && (
        <CompleteView
          state={finalState}
          yourUsername={yourUsername}
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

const MatchedView = ({ yourUsername, opponent }) => (
  <div className={styles.centeredCard}>
    <p className={styles.eyebrow}>Match found</p>
    <div className={styles.matchedDuel}>
      <span className={styles.yourName}>{yourUsername}</span>
      <span className={styles.matchedVs}>VS</span>
      <span className={styles.opponentName}>{opponent?.username || 'Opponent'}</span>
    </div>
    <p className={styles.cardSubtitle}>Get ready…</p>
  </div>
);

// Countdown phase. Each value gets its own visual treatment so the tension
// ramps as the clock burns down — calm green at 5/4, amber warning at 3/2,
// red shake at 1, and a celebratory "GO!" burst at 0.
const CountdownView = ({ value }) => {
  const variant =
    value === 0 ? styles.countdownGo
      : value === 1 ? styles.countdown1
        : value === 2 ? styles.countdown2
          : value === 3 ? styles.countdown3
            : styles.countdownCalm;
  const label =
    value === 0 ? "Let's go."
      : value === 1 ? 'Hands on the buzzer.'
        : value === 2 ? 'Lock in.'
          : value === 3 ? 'Almost there…'
            : 'Steady…';
  const display = value === 0 ? 'GO!' : value;
  return (
    <div className={styles.centeredCard}>
      <div className={styles.countdownRing} aria-hidden="true">
        <div />
        <div />
      </div>
      <div key={value} className={`${styles.countdown} ${variant}`}>{display}</div>
      <p className={styles.cardSubtitle}>{label}</p>
    </div>
  );
};

const QuestionView = ({
  phase,
  question,
  selected,
  correctOption,
  opponentLocked,
  timeLeft,
  yourUsername,
  yourScore,
  opponentScore,
  opponent,
  yourCorrect,
  opponentCorrect,
  yourDelta,
  oppDelta,
  yourStreak,
  opponentStreak,
  firstLocker,
  onSelect,
}) => {
  const total = question?.total || 0;
  const idx = (question?.index ?? 0) + 1;
  const pctRemaining = useMemo(() => {
    if (!question || timeLeft === null) return 100;
    return Math.max(0, Math.min(100, (timeLeft / question.time_limit_seconds) * 100));
  }, [question, timeLeft]);
  const opponentName = opponent?.username || 'Opponent';
  // Crown the leader so it's immediately obvious who's ahead.
  const youLead = yourScore > opponentScore;
  const oppLead = opponentScore > yourScore;
  // Tier the timer drama: warning at <8s, critical at <4s.
  const timerTier =
    timeLeft === null ? ''
      : timeLeft < 4 ? styles.timerCritical
        : timeLeft < 8 ? styles.timerWarn
          : '';
  // Render question-position pips so progress through the round is glanceable.
  const pips = Array.from({ length: total }, (_, i) => i);

  return (
    <div className={styles.arena}>
      <header className={styles.arenaHeader}>
        <div className={`${styles.scoreCard} ${youLead ? styles.scoreCardLead : ''}`}>
          <span className={styles.scoreName} title={yourUsername}>
            {youLead ? '👑 ' : ''}{yourUsername}
          </span>
          <span className={styles.scoreValue}>{yourScore}</span>
          {yourStreak >= 2 ? (
            <span className={styles.streakChip} title={`${yourStreak} in a row`}>
              🔥 {yourStreak}
            </span>
          ) : null}
        </div>
        <div className={styles.questionMeta}>
          <p className={styles.questionPos}>Round {idx} / {total}</p>
          <div className={styles.pipRow} aria-hidden="true">
            {pips.map((i) => (
              <span
                key={i}
                className={`${styles.pip} ${i + 1 < idx ? styles.pipDone : ''} ${i + 1 === idx ? styles.pipNow : ''}`}
              />
            ))}
          </div>
          <p className={styles.difficultyTag}>{question?.difficulty}</p>
        </div>
        <div className={`${styles.scoreCard} ${oppLead ? styles.scoreCardLead : ''}`}>
          <span className={styles.scoreName} title={opponentName}>
            {oppLead ? '👑 ' : ''}{opponentName}
          </span>
          <span className={styles.scoreValue}>{opponentScore}</span>
          {opponentStreak >= 2 ? (
            <span className={styles.streakChip} title={`${opponentStreak} in a row`}>
              🔥 {opponentStreak}
            </span>
          ) : null}
        </div>
      </header>

      <div className={`${styles.timerTrack} ${timerTier}`}>
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
        <div className={styles.questionPrompt}>
          <MarkdownText text={question?.question_text} />
        </div>
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
                <span className={styles.optionText}>
                  <MarkdownText text={opt.text} inline />
                </span>
              </button>
            );
          })}
        </div>

        {phase === PHASE.QUESTION ? (
          <div className={styles.statusRow}>
            <span className={selected ? styles.lockedChip : styles.thinkingChip}>
              {selected ? `🔒 You locked ${selected}` : 'Pick an option…'}
              {firstLocker === 'you' ? (
                <span className={styles.firstBadge} title="First to lock in">⚡ First!</span>
              ) : null}
            </span>
            <span
              className={
                opponentLocked ? styles.lockedChipOpp : styles.thinkingChipOpp
              }
            >
              {opponentLocked
                ? `🔒 ${opponentName} locked in`
                : `⏳ ${opponentName} thinking…`}
              {firstLocker === 'opp' ? (
                <span className={styles.firstBadge} title="First to lock in">⚡ First!</span>
              ) : null}
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
              {yourUsername} {yourCorrect ? `+${yourDelta}` : '+0'}
            </div>
            <div
              className={`${styles.deltaChip} ${
                opponentCorrect ? styles.deltaWin : styles.deltaLose
              }`}
            >
              {opponentName} {opponentCorrect ? `+${oppDelta}` : '+0'}
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
};

const CompleteView = ({ state, yourUsername, onPlayAgain, onHome, onHistory }) => {
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
          <p className={styles.completeScoreLabel} title={yourUsername}>{yourUsername}</p>
          <p className={styles.completeScoreValue}>{state.your_score}</p>
          <p className={styles.completeScoreSub}>
            {state.your_correct} correct
          </p>
        </div>
        <div className={styles.completeVs}>VS</div>
        <div className={styles.completeScoreCard}>
          <p
            className={styles.completeScoreLabel}
            title={state.opponent_username || 'Opponent'}
          >
            {state.opponent_username || 'Opponent'}
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
