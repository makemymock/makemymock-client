import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { potdService } from '../../../services/potdService';
import { parseApiError } from '../../../utils/validators';
import MarkdownText from '../../common/MarkdownText/MarkdownText';
import Loader from '../../common/Loader/Loader';
import styles from './PotdModal.module.css';

// ---------------------------------------------------------------------------
// Status semantics (mirror backend):
//   in_progress — still attempting; question editable
//   solved      — got it right; streak credited; show solution
//   viewed      — explicit give-up; solution shown; streak broken
//   exhausted   — single_correct ran out of retries; solution shown; no credit
// ---------------------------------------------------------------------------

const PHASE = {
  LOADING: 'loading',
  ERROR: 'error',
  QUESTION: 'question',
  RESULT_TODAY: 'result-today',
  CALENDAR: 'calendar',
  PAST_DATE: 'past-date',
};

const PotdModal = ({ open, onClose }) => {
  const navigate = useNavigate();
  const dialogRef = useRef(null);

  const [phase, setPhase] = useState(PHASE.LOADING);
  const [error, setError] = useState('');

  // Today's data
  const [today, setToday] = useState(null); // { date_ist, question, status, attempt_count, max_attempts, correct_answer?, solution? }
  const [streak, setStreak] = useState(null); // { current, longest, last_solved_at }

  // Per-attempt input state — reset each time today is refetched.
  const [selectedOption, setSelectedOption] = useState(null);
  const [selectedOptions, setSelectedOptions] = useState([]);
  const [integerAnswer, setIntegerAnswer] = useState('');

  // Transient UI flags.
  const [submitting, setSubmitting] = useState(false);
  const [lastAttemptWrong, setLastAttemptWrong] = useState(false);
  const [confirmingView, setConfirmingView] = useState(false);

  // Calendar state.
  const [history, setHistory] = useState(null); // { days: [...], range_days }
  const [historyLoading, setHistoryLoading] = useState(false);

  // Past-date viewing state.
  const [pastDate, setPastDate] = useState(null);
  const [pastDateLoading, setPastDateLoading] = useState(false);

  // ---- ESC closes ----
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // ---- Lock background scroll ----
  useEffect(() => {
    if (!open) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  // ---- Bootstrap on open ----
  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    (async () => {
      setPhase(PHASE.LOADING);
      setError('');
      setSelectedOption(null);
      setSelectedOptions([]);
      setIntegerAnswer('');
      setLastAttemptWrong(false);
      setConfirmingView(false);
      setHistory(null);
      setPastDate(null);
      try {
        const [t, s] = await Promise.all([
          potdService.getToday(),
          potdService.getStreak(),
        ]);
        if (cancelled) return;
        setToday(t);
        setStreak(s);
        setPhase(
          t.status === 'in_progress' ? PHASE.QUESTION : PHASE.RESULT_TODAY,
        );
      } catch (err) {
        if (cancelled) return;
        setError(parseApiError(err, 'Could not load today’s challenge.'));
        setPhase(PHASE.ERROR);
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  // ---- Submit attempt ----
  const onSubmit = useCallback(async () => {
    if (!today || phase !== PHASE.QUESTION) return;
    const qtype = today.question.question_type;
    if (!answerReady(qtype, selectedOption, selectedOptions, integerAnswer)) return;

    setSubmitting(true);
    setError('');
    setLastAttemptWrong(false);
    try {
      const body = buildPayload(qtype, selectedOption, selectedOptions, integerAnswer);
      const res = await potdService.submitAttempt(body);
      if (res.correct) {
        // Solved → reveal answer + solution, refresh streak chip.
        setToday((cur) => ({
          ...cur,
          status: 'solved',
          attempt_count: res.attempt_count,
          correct_answer: res.correct_answer,
          solution: res.solution,
        }));
        setStreak((cur) => ({
          current: res.streak_after,
          longest: Math.max(cur?.longest || 0, res.streak_after),
          last_solved_at: today.date_ist,
        }));
        setPhase(PHASE.RESULT_TODAY);
      } else if (res.status === 'exhausted') {
        // Single_correct ran out of tries — reveal but no streak credit.
        setToday((cur) => ({
          ...cur,
          status: 'exhausted',
          attempt_count: res.attempt_count,
          correct_answer: res.correct_answer,
          solution: res.solution,
        }));
        setStreak((cur) => ({ ...cur, current: res.streak_after }));
        setPhase(PHASE.RESULT_TODAY);
      } else {
        // Wrong but retries remaining — flash the banner, let user retry.
        setToday((cur) => ({ ...cur, attempt_count: res.attempt_count }));
        setSelectedOption(null);
        setSelectedOptions([]);
        setIntegerAnswer('');
        setLastAttemptWrong(true);
      }
    } catch (err) {
      setError(parseApiError(err, 'Could not submit your answer.'));
    } finally {
      setSubmitting(false);
    }
  }, [today, phase, selectedOption, selectedOptions, integerAnswer]);

  // ---- View solution (graceful give-up) ----
  const onViewSolutionConfirmed = useCallback(async () => {
    if (!today) return;
    setSubmitting(true);
    setConfirmingView(false);
    try {
      const res = await potdService.viewSolution();
      setToday((cur) => ({
        ...cur,
        status: 'viewed',
        correct_answer: res.correct_answer,
        solution: res.solution,
      }));
      setStreak((cur) => ({ ...cur, current: res.streak_after }));
      setPhase(PHASE.RESULT_TODAY);
    } catch (err) {
      setError(parseApiError(err, 'Could not load the solution.'));
    } finally {
      setSubmitting(false);
    }
  }, [today]);

  // ---- Calendar ----
  const openCalendar = useCallback(async () => {
    setPhase(PHASE.CALENDAR);
    if (history) return;
    setHistoryLoading(true);
    try {
      const h = await potdService.getHistory(60);
      setHistory(h);
    } catch (err) {
      setError(parseApiError(err, 'Could not load your history.'));
    } finally {
      setHistoryLoading(false);
    }
  }, [history]);

  const openPastDate = useCallback(async (dateIso) => {
    setPhase(PHASE.PAST_DATE);
    setPastDate(null);
    setPastDateLoading(true);
    try {
      const p = await potdService.getPastDate(dateIso);
      setPastDate(p);
    } catch (err) {
      setError(parseApiError(err, 'Could not load that day’s POTD.'));
      setPhase(PHASE.CALENDAR);
    } finally {
      setPastDateLoading(false);
    }
  }, []);

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
        <ModalHeader
          today={today}
          streak={streak}
          phase={phase}
          onOpenCalendar={openCalendar}
          onCloseCalendar={() => setPhase(today?.status === 'in_progress' ? PHASE.QUESTION : PHASE.RESULT_TODAY)}
          onClose={onClose}
        />

        <div className={styles.body}>
          {phase === PHASE.LOADING ? (
            <div className={styles.centerState}>
              <Loader />
              <p className={styles.stateText}>Loading today’s question…</p>
            </div>
          ) : null}

          {phase === PHASE.ERROR ? (
            <div className={styles.centerState}>
              <p className={styles.errorText}>{error || 'Something went wrong.'}</p>
              <button type="button" className={styles.secondaryBtn} onClick={onClose}>Close</button>
            </div>
          ) : null}

          {phase === PHASE.QUESTION && today ? (
            <QuestionView
              question={today.question}
              attemptCount={today.attempt_count}
              maxAttempts={today.max_attempts}
              lastAttemptWrong={lastAttemptWrong}
              selectedOption={selectedOption}
              setSelectedOption={setSelectedOption}
              selectedOptions={selectedOptions}
              setSelectedOptions={setSelectedOptions}
              integerAnswer={integerAnswer}
              setIntegerAnswer={setIntegerAnswer}
              error={error}
            />
          ) : null}

          {phase === PHASE.RESULT_TODAY && today ? (
            <ResultView today={today} />
          ) : null}

          {phase === PHASE.CALENDAR ? (
            <CalendarView
              history={history}
              loading={historyLoading}
              todayIso={today?.date_ist}
              onReviewSolution={openPastDate}
              onPracticeInBrowse={(qid) => {
                onClose();
                navigate(`/tests/browse/${qid}`);
              }}
              onAttemptToday={() => setPhase(
                today?.status === 'in_progress' ? PHASE.QUESTION : PHASE.RESULT_TODAY,
              )}
            />
          ) : null}

          {phase === PHASE.PAST_DATE ? (
            <PastDateView
              data={pastDate}
              loading={pastDateLoading}
              onBack={() => setPhase(PHASE.CALENDAR)}
            />
          ) : null}
        </div>

        <ModalFooter
          phase={phase}
          today={today}
          submitting={submitting}
          confirmingView={confirmingView}
          setConfirmingView={setConfirmingView}
          canSubmit={today && answerReady(today?.question?.question_type, selectedOption, selectedOptions, integerAnswer)}
          onSubmit={onSubmit}
          onConfirmView={onViewSolutionConfirmed}
          onClose={onClose}
          onGoAnalytics={() => navigate('/analytics')}
        />
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Header — title, topic chip, streak chip, close button
// ---------------------------------------------------------------------------

const ModalHeader = ({ today, streak, phase, onOpenCalendar, onCloseCalendar, onClose }) => {
  const showingCalendar = phase === PHASE.CALENDAR || phase === PHASE.PAST_DATE;
  const current = streak?.current ?? 0;
  return (
    <header className={styles.dialogHeader}>
      <div className={styles.titleWrap}>
        <p className={styles.eyebrow}>⚡ Daily Challenge</p>
        <h2 id="potd-title" className={styles.title}>Problem of the Day</h2>
        {today?.question?.topic_name ? (
          <p className={styles.topicChip}>
            {today.question.topic_name}
            {today.question?.difficulty ? ` · ${today.question.difficulty}` : ''}
          </p>
        ) : null}
      </div>
      <div className={styles.headerRight}>
        {/* Read-only streak indicator — purely a stat, not clickable. */}
        {current > 0 ? (
          <span className={styles.streakBadge} title="Current POTD streak">
            <span aria-hidden="true">🔥</span>
            <span>{current}</span>
          </span>
        ) : null}
        {/* Explicit calendar button so the navigation is obvious. Doubles
            as the back affordance when the calendar is open. */}
        <button
          type="button"
          className={`${styles.calendarBtn} ${showingCalendar ? styles.calendarBtnActive : ''}`}
          onClick={showingCalendar ? onCloseCalendar : onOpenCalendar}
        >
          {showingCalendar ? (
            <>
              <span aria-hidden="true">←</span>
              <span className={styles.calendarBtnText}>Today</span>
            </>
          ) : (
            <>
              <span aria-hidden="true">📅</span>
              <span className={styles.calendarBtnText}>Past POTDs</span>
            </>
          )}
        </button>
        <button
          type="button"
          className={styles.closeBtn}
          onClick={onClose}
          aria-label="Close"
        >×</button>
      </div>
    </header>
  );
};

// ---------------------------------------------------------------------------
// Question view — inputs for the type + retry banner + attempt counter
// ---------------------------------------------------------------------------

const QuestionView = ({
  question, attemptCount, maxAttempts, lastAttemptWrong,
  selectedOption, setSelectedOption,
  selectedOptions, setSelectedOptions,
  integerAnswer, setIntegerAnswer,
  error,
}) => {
  const type = question.question_type;
  // For single_correct on the final permitted attempt, surface a louder
  // warning so the student knows their streak is about to be lost.
  const isFinalAttempt =
    maxAttempts != null && attemptCount + 1 >= maxAttempts;

  const toggleMulti = (key) => {
    setSelectedOptions((cur) => {
      const set = new Set(cur);
      if (set.has(key)) set.delete(key); else set.add(key);
      return Array.from(set).sort();
    });
  };

  return (
    <>
      {maxAttempts != null ? (
        <div className={`${styles.attemptStrip} ${isFinalAttempt ? styles.attemptStripFinal : ''}`}>
          <span>
            Attempt <strong>{attemptCount + 1}</strong> of {maxAttempts}
          </span>
          {isFinalAttempt ? <span className={styles.attemptStripBadge}>Final · streak at risk</span> : null}
        </div>
      ) : null}

      {lastAttemptWrong ? (
        <div className={styles.retryBanner} role="status">
          Not quite. Try again — your streak is still safe.
        </div>
      ) : null}

      {error ? <div className={styles.retryBanner} role="alert">{error}</div> : null}

      <div className={styles.questionText}>
        <MarkdownText text={question.question_text} />
      </div>

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

      {type === 'matching' ? (
        <p className={styles.stateHint}>
          This question type needs the full test view. Open the matching version
          from the Practice section.
        </p>
      ) : null}
    </>
  );
};

// ---------------------------------------------------------------------------
// Result view — solved / viewed / exhausted
// ---------------------------------------------------------------------------

const ResultView = ({ today }) => {
  const status = today.status;
  const heading =
    status === 'solved'   ? { icon: '✓', text: 'Correct! Day credited to your streak.', cls: styles.verdictWin }
    : status === 'viewed'    ? { icon: '👁', text: 'Solution revealed — streak reset for today.', cls: styles.verdictLose }
    : status === 'exhausted' ? { icon: '✗', text: 'Out of attempts — no streak credit today.', cls: styles.verdictLose }
    : { icon: '·', text: '', cls: '' };

  const correctAns = formatAnswer(today.correct_answer);

  return (
    <>
      <div className={`${styles.verdict} ${heading.cls}`}>
        <span className={styles.verdictIcon}>{heading.icon}</span>
        <span className={styles.verdictText}>{heading.text}</span>
      </div>

      <div className={styles.questionText}>
        <MarkdownText text={today.question.question_text} />
      </div>

      {(today.question.options || []).length > 0 ? (
        <ul className={styles.optionList}>
          {today.question.options.map((opt) => {
            const isCorrect = matchesAnswer(opt.key, today.correct_answer);
            const cls = [
              styles.option,
              styles.optionStatic,
              isCorrect ? styles.optionCorrect : '',
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
            <p className={styles.answerLabel}>Correct answer</p>
            <p className={styles.answerValue}>{correctAns || '—'}</p>
          </div>
        </div>
      )}

      {today.solution ? (
        <section className={styles.solution}>
          <p className={styles.solutionTitle}>Solution</p>
          <div className={styles.solutionBody}>
            <MarkdownText text={today.solution} />
          </div>
        </section>
      ) : null}
    </>
  );
};

// ---------------------------------------------------------------------------
// Calendar — month-style grid, last 60 days
// ---------------------------------------------------------------------------

const CalendarView = ({ history, loading, onReviewSolution, onPracticeInBrowse, onAttemptToday, todayIso }) => {
  // Clicked-cell state + the cell's measured geometry. The popover anchors
  // straight onto the cell — clear visual link, no eye travel to the
  // bottom of the panel. `placeBelow=false` flips it above the cell when
  // we're close to the bottom of the grid so it never gets clipped.
  const [picked, setPicked] = useState(null);
  // Which month is currently visible. 0 = current month; negative goes back.
  // Capped to 12 months back so users can't endlessly scroll into the past.
  const [monthOffset, setMonthOffset] = useState(0);
  const gridRef = useRef(null);

  // Today's calendar coordinates — used for "is this today?", future-day
  // dimming, and as the navigation pivot for month offset.
  const today = useMemo(() => {
    const d = new Date();
    return { year: d.getFullYear(), month: d.getMonth(), day: d.getDate(), iso: ymd(d) };
  }, []);

  const visibleMonth = useMemo(() => {
    const d = new Date(today.year, today.month + monthOffset, 1);
    return { year: d.getFullYear(), month: d.getMonth() };
  }, [today, monthOffset]);

  const byDate = useMemo(() => {
    const m = new Map();
    for (const d of (history?.days || [])) m.set(d.date_ist, d);
    return m;
  }, [history]);

  // Build a full month grid: 1 → last day of `visibleMonth`. Leading pad
  // cells align day 1 to its weekday column. Future dates (relative to
  // today) are present but dimmed and not clickable.
  const cells = useMemo(() => {
    const { year, month } = visibleMonth;
    const lastDay = new Date(year, month + 1, 0).getDate();
    const out = [];
    for (let d = 1; d <= lastDay; d += 1) {
      const date = new Date(year, month, d);
      out.push({
        iso: ymd(date),
        dom: d,
        dow: date.getDay(),
        isFuture: date > new Date(today.year, today.month, today.day),
        isToday: ymd(date) === today.iso,
      });
    }
    return out;
  }, [visibleMonth, today]);

  const monthLabel = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' });
    return fmt.format(new Date(visibleMonth.year, visibleMonth.month, 1));
  }, [visibleMonth]);

  const canGoBack = monthOffset > -12;
  const canGoForward = monthOffset < 0;

  // Outside-click dismissal. The popover stamps a `data-potd-popover`
  // attribute on its root, so the check is independent of CSS-module
  // hashing. Any click outside the popover dismisses — except a click
  // on another clickable calendar cell, which re-picks (the cell's own
  // onClick replaces the popover state seamlessly with no flicker).
  useEffect(() => {
    if (!picked) return undefined;
    const handler = (e) => {
      const t = e.target;
      if (!t || typeof t.closest !== 'function') return;
      if (t.closest('[data-potd-popover]')) return;
      // Clicking a clickable cell falls through to that cell's onClick,
      // which sets a new `picked`. Don't dismiss in between or the popover
      // would briefly disappear before the new one appears.
      const cellBtn = t.closest('button');
      if (cellBtn && !cellBtn.disabled && gridRef.current?.contains(cellBtn)) return;
      setPicked(null);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [picked]);

  // ESC closes the popover.
  useEffect(() => {
    if (!picked) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setPicked(null); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [picked]);

  if (loading || !history) {
    return (
      <div className={styles.centerState}>
        <Loader />
        <p className={styles.stateText}>Loading your POTD history…</p>
      </div>
    );
  }

  const firstDow = cells[0]?.dow ?? 0;

  // Compute the cell's position inside the grid and pick a placement
  // direction (above vs below) so the popover never overflows the grid.
  // For TODAY with no attempts yet, we surface a single "Attempt" CTA so
  // the user doesn't accidentally break their streak by clicking
  // "Review solution" before having tried the question.
  const onCellClick = (e, c) => {
    // Clicking the same cell whose popover is already open toggles it
    // off — quick way to dismiss without aiming for the × button.
    if (picked?.date_ist === c.iso) {
      setPicked(null);
      return;
    }
    const day = byDate.get(c.iso);
    if (c.isFuture) return;
    const status = day?.status || 'missed';
    const cellEl = e.currentTarget;
    const gridEl = gridRef.current;
    if (!gridEl) return;
    const cr = cellEl.getBoundingClientRect();
    const gr = gridEl.getBoundingClientRect();
    const cellCenterX = cr.left - gr.left + cr.width / 2;
    const placeBelow = (cr.top - gr.top) < gr.height * 0.55;
    setPicked({
      date_ist: c.iso,
      question_id: day?.question_id || null,
      status,
      isToday: c.isToday,
      hasHistory: !!day,
      cellCenterX,
      cellTop: cr.top - gr.top,
      cellBottom: cr.bottom - gr.top,
      placeBelow,
    });
  };

  return (
    <div className={styles.calendar}>
      <div className={styles.monthNav}>
        <button
          type="button"
          className={styles.monthNavBtn}
          onClick={() => setMonthOffset((n) => Math.max(-12, n - 1))}
          disabled={!canGoBack}
          aria-label="Previous month"
        >‹</button>
        <span className={styles.monthLabel}>{monthLabel}</span>
        <button
          type="button"
          className={styles.monthNavBtn}
          onClick={() => setMonthOffset((n) => Math.min(0, n + 1))}
          disabled={!canGoForward}
          aria-label="Next month"
        >›</button>
      </div>
      <p className={styles.calendarLegend}>
        <span className={`${styles.legendDot} ${styles.dotSolved}`} /> solved
        <span className={`${styles.legendDot} ${styles.dotAttempted}`} /> attempted
        <span className={`${styles.legendDot} ${styles.dotViewed}`} /> viewed
        <span className={`${styles.legendDot} ${styles.dotMissed}`} /> missed
      </p>
      <div className={styles.weekdayRow} aria-hidden="true">
        {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((w, i) => (
          <span key={i} className={styles.weekdayLabel}>{w}</span>
        ))}
      </div>
      <div ref={gridRef} className={styles.calendarGrid}>
        {Array.from({ length: firstDow }).map((_, i) => (
          <span key={`pad-${i}`} className={styles.calendarPad} />
        ))}
        {cells.map((c) => {
          const day = byDate.get(c.iso);
          const status = day?.status || (c.isFuture ? 'future' : 'missed');
          const isPicked = picked?.date_ist === c.iso;
          // Only today + any past day with a real history row are clickable.
          // Missed and future days are rendered as inert <span> elements:
          // a disabled <button> swallows mousedown in most browsers, which
          // would block the outside-click dismissal of the popover.
          const clickable = !c.isFuture && (c.isToday || !!day);
          const cls = [
            styles.calendarCell,
            styles[`cell_${status}`] || '',
            c.isToday ? styles.cellToday : '',
            isPicked ? styles.cellPicked : '',
            !clickable ? styles.cellDim : styles.cellClickable,
            c.isFuture ? styles.cellFuture : '',
          ].join(' ');
          if (!clickable) {
            return (
              <span key={c.iso} className={cls} aria-hidden="true">
                {c.dom}
              </span>
            );
          }
          return (
            <button
              key={c.iso}
              type="button"
              className={cls}
              onClick={(e) => onCellClick(e, c)}
              aria-label={`${c.iso}, ${status}`}
              title={`${c.iso} — ${status}`}
            >
              {c.dom}
            </button>
          );
        })}

        {picked ? (
          <CellPopover
            picked={picked}
            todayIso={todayIso}
            onClose={() => setPicked(null)}
            onReviewSolution={onReviewSolution}
            onPracticeInBrowse={onPracticeInBrowse}
            onAttemptToday={onAttemptToday}
          />
        ) : null}
      </div>
    </div>
  );
};

// ---- Anchored popover that floats over the grid next to the picked cell.
// Two-layer structure to avoid the pop-animation overriding the placement
// transform (which would briefly render the popover under the cell before
// snapping into the correct above/below position):
//   .cellPopoverAnchor — owns absolute positioning + the center/flip transform
//   .cellPopover       — animates scale + opacity, no transform of its own
// ----

const CellPopover = ({ picked, onClose, onReviewSolution, onPracticeInBrowse, onAttemptToday }) => {
  // Special-case: today's POTD, not yet attempted. Showing "Review with
  // solution" here would silently break the user's streak the moment they
  // click it. Surface a focused "Attempt" CTA instead — they should answer
  // the question first.
  const isTodayPending = picked.isToday && (
    !picked.hasHistory || picked.status === 'in_progress'
  );
  const anchorRef = useRef(null);
  // Horizontal clamp — measure after mount and nudge the anchor so the
  // popover doesn't overflow the grid. Initial value is 0 so the first
  // paint is already approximately right (no visible jump).
  const [shift, setShift] = useState(0);

  useEffect(() => {
    const el = anchorRef.current;
    if (!el) return;
    const grid = el.parentElement;
    if (!grid) return;
    const popRect = el.getBoundingClientRect();
    const gridRect = grid.getBoundingClientRect();
    const localLeft = popRect.left - gridRect.left;
    const localRight = localLeft + popRect.width;
    let s = 0;
    if (localLeft < 4) s = 4 - localLeft;
    else if (localRight > gridRect.width - 4) s = (gridRect.width - 4) - localRight;
    if (s !== 0) setShift(s);
  }, [picked.date_ist]);

  // The anchor's transform composes centering with the optional above-flip
  // and the horizontal clamp shift. We bake the shift into the transform
  // (not into `left`) so the arrow can be repositioned independently to
  // keep pointing at the cell's centre.
  const anchorStyle = picked.placeBelow
    ? {
        top: picked.cellBottom + 10,
        left: picked.cellCenterX,
        transform: `translate(calc(-50% + ${shift}px), 0)`,
      }
    : {
        top: picked.cellTop - 10,
        left: picked.cellCenterX,
        transform: `translate(calc(-50% + ${shift}px), -100%)`,
      };

  // Arrow stays glued to the picked cell's centre by counter-shifting
  // against the clamp.
  const arrowStyle = shift !== 0 ? { left: `calc(50% - ${shift}px)` } : undefined;

  return (
    <div
      ref={anchorRef}
      className={`${styles.cellPopoverAnchor} ${picked.placeBelow ? styles.popoverBelow : styles.popoverAbove}`}
      style={anchorStyle}
      data-potd-popover="true"
    >
      <div className={styles.cellPopover} role="dialog" aria-label="Choose action">
        <span className={styles.popoverArrow} style={arrowStyle} aria-hidden="true" />
        <div className={styles.popoverHead}>
          <span className={styles.popoverDate}>{picked.date_ist}</span>
          <span className={styles.popoverStatus}>· {picked.status}</span>
          <button
            type="button"
            className={styles.popoverClose}
            onClick={onClose}
            aria-label="Cancel"
          >×</button>
        </div>
        {isTodayPending ? (
          <div className={styles.popoverActionsSingle}>
            <button
              type="button"
              className={`${styles.popoverAction} ${styles.popoverActionAttempt}`}
              onClick={() => onAttemptToday?.()}
            >
              <span className={styles.popoverActionIcon} aria-hidden="true">⚡</span>
              <span className={styles.popoverActionText}>
                <strong>{picked.hasHistory ? 'Continue attempt' : 'Attempt today’s POTD'}</strong>
                <span>Your streak is safe</span>
              </span>
            </button>
          </div>
        ) : (
          <div className={styles.popoverActions}>
            <button
              type="button"
              className={`${styles.popoverAction} ${styles.popoverActionReview}`}
              onClick={() => picked.question_id && onReviewSolution(picked.date_ist)}
              disabled={!picked.question_id}
            >
              <span className={styles.popoverActionIcon} aria-hidden="true">🔍</span>
              <span className={styles.popoverActionText}>
                <strong>Review</strong>
                <span>solution + answer</span>
              </span>
            </button>
            <button
              type="button"
              className={`${styles.popoverAction} ${styles.popoverActionPractice}`}
              onClick={() => picked.question_id && onPracticeInBrowse(picked.question_id)}
              disabled={!picked.question_id}
            >
              <span className={styles.popoverActionIcon} aria-hidden="true">🎯</span>
              <span className={styles.popoverActionText}>
                <strong>Practice</strong>
                <span>fresh in Browse</span>
              </span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Past-date view — question + correct answer + solution + back link
// ---------------------------------------------------------------------------

const PastDateView = ({ data, loading, onBack }) => {
  if (loading || !data) {
    return (
      <div className={styles.centerState}>
        <Loader />
        <p className={styles.stateText}>Loading that day’s POTD…</p>
      </div>
    );
  }
  return (
    <>
      <button type="button" className={styles.backLink} onClick={onBack}>
        ← Back to calendar
      </button>
      <p className={styles.pastDateChip}>{data.date_ist} · {data.status}</p>
      <div className={styles.questionText}>
        <MarkdownText text={data.question.question_text} />
      </div>
      {(data.question.options || []).length > 0 ? (
        <ul className={styles.optionList}>
          {data.question.options.map((opt) => {
            const isCorrect = matchesAnswer(opt.key, data.correct_answer);
            const cls = [
              styles.option,
              styles.optionStatic,
              isCorrect ? styles.optionCorrect : '',
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
            <p className={styles.answerLabel}>Correct answer</p>
            <p className={styles.answerValue}>{formatAnswer(data.correct_answer) || '—'}</p>
          </div>
        </div>
      )}
      {data.solution ? (
        <section className={styles.solution}>
          <p className={styles.solutionTitle}>Solution</p>
          <div className={styles.solutionBody}>
            <MarkdownText text={data.solution} />
          </div>
        </section>
      ) : null}
    </>
  );
};

// ---------------------------------------------------------------------------
// Footer — varies by phase + handles the view-solution confirm inline
// ---------------------------------------------------------------------------

const ModalFooter = ({
  phase, today, submitting, confirmingView, setConfirmingView,
  canSubmit, onSubmit, onConfirmView, onClose, onGoAnalytics,
}) => {
  if (phase === PHASE.QUESTION && today) {
    if (confirmingView) {
      return (
        <footer className={`${styles.footer} ${styles.footerConfirm}`}>
          <p className={styles.confirmText}>
            Viewing the solution will break your streak. You can still revise the
            question — just no streak credit for today.
          </p>
          <div className={styles.footerBtns}>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => setConfirmingView(false)}
              disabled={submitting}
            >
              Keep trying
            </button>
            <button
              type="button"
              className={styles.dangerBtn}
              onClick={onConfirmView}
              disabled={submitting}
            >
              Show solution
            </button>
          </div>
        </footer>
      );
    }
    return (
      <footer className={styles.footer}>
        <button
          type="button"
          className={styles.linkBtn}
          onClick={() => setConfirmingView(true)}
          disabled={submitting}
        >
          View solution
        </button>
        <div className={styles.footerBtns}>
          <button type="button" className={styles.secondaryBtn} onClick={onClose} disabled={submitting}>
            Maybe later
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={onSubmit}
            disabled={!canSubmit || submitting}
          >
            Submit answer
          </button>
        </div>
      </footer>
    );
  }

  if (phase === PHASE.RESULT_TODAY) {
    return (
      <footer className={styles.footer}>
        <button type="button" className={styles.secondaryBtn} onClick={onGoAnalytics}>
          See analytics
        </button>
        <button type="button" className={styles.primaryBtn} onClick={onClose}>
          Done
        </button>
      </footer>
    );
  }

  if (phase === PHASE.CALENDAR || phase === PHASE.PAST_DATE) {
    return (
      <footer className={styles.footer}>
        <button type="button" className={styles.secondaryBtn} onClick={onClose}>
          Close
        </button>
      </footer>
    );
  }

  return null;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Local YYYY-MM-DD (NOT UTC). The backend stores POTD dates in IST; on the
// frontend we treat dates as the user's wall-clock day so they line up.
function ymd(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function answerReady(qtype, sel, multi, intAns) {
  switch (qtype) {
    case 'single_correct': return !!sel;
    case 'multi_correct':  return multi.length > 0;
    case 'integer':        return String(intAns).trim() !== '';
    case 'matching':       return false; // unsupported in the lightweight modal
    default:               return false;
  }
}

function buildPayload(qtype, sel, multi, intAns) {
  switch (qtype) {
    case 'single_correct': return { selected_option: sel };
    case 'multi_correct':  return { selected_options: multi };
    case 'integer':        return { integer_answer: Number(intAns) };
    default:               return {};
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
  if (typeof ans === 'object') {
    return Object.entries(ans).map(([k, v]) => `${k}→${Array.isArray(v) ? v.join('') : v}`).join(', ');
  }
  return String(ans);
}

export default PotdModal;
