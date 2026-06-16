import { useCallback, useEffect, useRef, useState } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { parseApiError } from '../../utils/validators';
import Loader from '../../components/common/Loader/Loader';
import { recommenderService } from '../../services/recommenderService';
import styles from './recommender.module.css';

// ─── Icons ────────────────────────────────────────────────────────────────────
const IcoBrain   = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M9.5 2a2.5 2.5 0 0 1 5 0"/><path d="M9 2.5C5.134 3.28 2 6.8 2 11a7 7 0 0 0 7 7h6a7 7 0 0 0 7-7c0-4.2-3.134-7.72-7-8.5"/><path d="M12 11v4"/><path d="M9.5 9.5a2.5 2.5 0 0 1 5 0"/></svg>;
const IcoTarget  = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>;
const IcoZap     = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>;
const IcoStar    = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>;
const IcoCheck   = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" {...p}><polyline points="20 6 9 17 4 12"/></svg>;
const IcoLock    = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>;
const IcoUnlock  = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></svg>;
const IcoArrow   = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>;
const IcoRefresh = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>;
const IcoBook    = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>;
const IcoTrend   = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>;
const IcoList    = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>;
const IcoUser    = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>;
const IcoChevron = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><polyline points="6 9 12 15 18 9"/></svg>;
const IcoXCircle = (p) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" {...p}><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>;

// ─── Subject config ───────────────────────────────────────────────────────────
const SUBJECT_LABELS = {
  mathematics: 'Maths',
  physics:     'Physics',
  chemistry:   'Chemistry',
};
const SUBJECT_ORDER = ['mathematics', 'physics', 'chemistry'];

// ─── Agent tool → emoji icon ──────────────────────────────────────────────────
const TOOL_ICONS = {
  // SessionPlannerAgent tools
  get_unlocked_topics:       '🔓',
  get_due_reviews:           '📅',
  get_weakest_unlocked:      '📉',
  get_trend_top_topics:      '🔥',
  get_candidate_questions:   '🔍',
  get_question_type_weights: '⚖️',
  get_topic_attempt_stats:   '📊',
  get_error_clusters:        '🔬',
  get_session_summary:       '📋',
  // QuestionSelectorAgent / service steps
  regulator:                 '💡',
  thompson:                  '🎯',
  irt:                       '📐',
  retry:                     '🔁',
  review:                    '📅',
  system:                    '⚙️',
};

// ─── Session mode → emoji ─────────────────────────────────────────────────────
const MODE_EMOJI = { drilling: '🔥', review: '📖', recovery: '💜', mixed: '⚡' };

// ─── Constants ────────────────────────────────────────────────────────────────
const INITIAL_SESSION_STATE = {
  consecutive_wrong: 0,
  questions_asked: 0,
  seen_all_ids: [],
};

// ─── Student-friendly helper text ────────────────────────────────────────────
const sessionModeText = (mode) => {
  if (mode === 'drilling') return "You've been on a roll — time for harder questions! 🔥";
  if (mode === 'review')   return "Let's revisit some things you've studied recently";
  if (mode === 'recovery') return "Taking it a bit easier to build your confidence back 💪";
  return "A balanced mix of new and review questions";
};

const diffFriendly = (d) => {
  if (d == null) return 'Medium';
  if (typeof d === 'string') return d.charAt(0).toUpperCase() + d.slice(1);
  if (d < 0.33) return 'Easy';
  if (d < 0.66) return 'Medium';
  return 'Hard';
};

const masteryPct = (mean) => Math.round((mean || 0) * 100);

const masteryColor = (pct) => {
  if (pct >= 70) return '#22c55e';
  if (pct >= 35) return '#f5c451';
  return '#f87171';
};

const masteryLabel = (pct) => {
  if (pct >= 70) return 'Strong';
  if (pct >= 35) return 'Developing';
  if (pct > 0)   return 'Needs work';
  return 'Not started';
};

const learningStyleFriendly = (s) => {
  const map = {
    visual: 'Visual Learner 👁',
    pattern: 'Pattern Thinker 🧩',
    conceptual: 'Concept Builder 🏗',
    practice: 'Practice-Focused 🎯',
    balanced: 'Well-Rounded 🔄',
  };
  return map[s] || (s ? s.charAt(0).toUpperCase() + s.slice(1) : '—');
};

const improvementFriendly = (r) => {
  const map = { fast: 'Fast Learner ⚡', steady: 'Steady Progress 📈', medium: 'Steady Progress 📈', slow: 'Taking It Step by Step 🐢' };
  return map[r] || (r ? r.charAt(0).toUpperCase() + r.slice(1) : '—');
};

// ─── LaTeX renderer ──────────────────────────────────────────────────────────

// Convert plain TeX commands to KaTeX-compatible equivalents
const _fixMath = (math) => {
  let s = math
    .replace(/\n/g, ' ')                      // collapse newlines
    .replace(/\\cr\b/g, '\\\\')               // \cr  → \\
    .replace(/\\left\s*\{/g, '\\left\\{')     // \left{ → \left\{
    .replace(/\\right\s*\}/g, '\\right\\}');  // \right} → \right\}

  // Replace \matrix{...} with \begin{matrix}...\end{matrix} (brace-depth aware)
  let out = '', i = 0;
  while (i < s.length) {
    const m = s.indexOf('\\matrix{', i);
    if (m === -1) { out += s.slice(i); break; }
    out += s.slice(i, m) + '\\begin{matrix}';
    let j = m + 8, depth = 1, inner = '';
    while (j < s.length && depth > 0) {
      const c = s[j];
      if (c === '{') depth++;
      else if (c === '}') { if (--depth === 0) { j++; break; } }
      if (depth > 0) inner += c;
      j++;
    }
    out += inner + '\\end{matrix}';
    i = j;
  }
  return out;
};

// Split a string into alternating text / math segments
const _parseSegments = (text) => {
  const segs = [];
  let rem = text || '';
  while (rem.length) {
    const dbl = rem.indexOf('$$');
    const sgl = rem.match(/(?<![\\$])\$(?!\$)((?:[^$\\]|\\.)+?)\$/);
    const useDisplay = dbl !== -1 && (sgl === null || dbl <= sgl.index);

    if (useDisplay) {
      if (dbl > 0) segs.push({ type: 'text', content: rem.slice(0, dbl) });
      const after = rem.slice(dbl + 2);
      const close = after.indexOf('$$');
      if (close !== -1) {
        segs.push({ type: 'math', display: true, content: after.slice(0, close) });
        rem = after.slice(close + 2);
      } else {
        segs.push({ type: 'text', content: rem });
        break;
      }
    } else if (sgl) {
      if (sgl.index > 0) segs.push({ type: 'text', content: rem.slice(0, sgl.index) });
      segs.push({ type: 'math', display: false, content: sgl[1] });
      rem = rem.slice(sgl.index + sgl[0].length);
    } else {
      segs.push({ type: 'text', content: rem });
      break;
    }
  }
  return segs;
};

const LatexText = ({ children }) => {
  if (!children) return null;
  const segs = _parseSegments(children);
  return (
    <span>
      {segs.map((seg, i) => {
        if (seg.type === 'text') return <span key={i} dangerouslySetInnerHTML={{ __html: seg.content }} />;
        let html;
        try {
          html = katex.renderToString(_fixMath(seg.content), {
            displayMode: seg.display,
            throwOnError: false,
            strict: false,
            trust: true,
          });
        } catch {
          html = `<span style="color:#f87171">${seg.content}</span>`;
        }
        return <span key={i} dangerouslySetInnerHTML={{ __html: html }} />;
      })}
    </span>
  );
};

// ─── ThinkingDots ─────────────────────────────────────────────────────────────
const ThinkingDots = () => (
  <span className={styles.thinkDots}>
    <span /><span /><span />
  </span>
);

// Strip markdown + Gemini's meta-commentary openers from thought text
const _cleanThought = (t = '') =>
  t.replace(/\*\*(.+?)\*\*/gs, '$1')
   .replace(/\*(.+?)\*/gs, '$1')
   .replace(/^#{1,6}\s+/gm, '')
   .replace(/`([^`]+)`/g, '$1')
   // Remove "My Thought Process for X" / "My primary objective is..." openers
   .replace(/^My\s+[Tt]hought\s+[Pp]rocess\s+[^\n]*\n*/m, '')
   .replace(/^[Aa]lright[,\s][^\n]*\n*/m, '')
   .replace(/\n{3,}/g, '\n\n')
   .trim();

// ─── ThoughtBlock — Gemini reasoning, collapsed by default ───────────────────
const ThoughtBlock = ({ text }) => {
  const [open, setOpen] = useState(false);
  const clean   = _cleanThought(text);
  const preview = clean.split('\n')[0].slice(0, 180).trim();
  return (
    <div className={styles.thoughtBlock}>
      <button className={styles.thoughtToggle} onClick={() => setOpen(v => !v)}>
        <span className={styles.thoughtIcon}>💭</span>
        <span className={styles.thoughtPreview}>
          {open ? 'Reasoning' : preview || 'View reasoning…'}
        </span>
        <IcoChevron
          className={`${styles.thinkChevron} ${open ? styles.thinkChevronOpen : ''}`}
          style={{ width: 13, height: 13, flexShrink: 0 }}
        />
      </button>
      {open && <div className={styles.thoughtBody}>{clean}</div>}
    </div>
  );
};

// ─── CoachNoteCard — why the AI chose this question ──────────────────────────
const CoachNoteCard = ({ note, isReview }) => (
  <div className={`${styles.coachNote} ${isReview ? styles.coachNoteReview : ''}`}>
    <span className={styles.coachNoteIcon}>{isReview ? '📅' : '🧠'}</span>
    <p className={styles.coachNoteText}>{note}</p>
  </div>
);

// ─── SolutionCard — step-by-step explanation revealed after submission ────────
const SolutionCard = ({ explanation }) => {
  const [open, setOpen] = useState(false);
  if (!explanation) return null;
  // Strip HTML line-break tags before rendering
  const clean = explanation.replace(/<br\s*\/?>/gi, '\n');
  return (
    <div className={styles.solutionCard}>
      <button className={styles.solutionToggle} onClick={() => setOpen(v => !v)}>
        <span className={styles.solutionToggleLeft}>
          <span className={styles.solutionIcon}>📖</span>
          <span className={styles.solutionToggleLabel}>View Solution</span>
        </span>
        <IcoChevron className={`${styles.thinkChevron} ${open ? styles.thinkChevronOpen : ''}`} />
      </button>
      {open && (
        <div className={styles.solutionBody}>
          <LatexText>{clean}</LatexText>
        </div>
      )}
    </div>
  );
};

// ─── ConfidenceNote — typewriter effect for the AI coach message ───────────────
const ConfidenceNote = ({ text }) => {
  const [shown, setShown] = useState('');
  useEffect(() => {
    let i = 0;
    const tick = () => {
      if (i >= text.length) return;
      setShown(text.slice(0, ++i));
      setTimeout(tick, 16);
    };
    tick();
  }, [text]);
  const done = shown.length >= text.length;
  return (
    <div className={styles.thinkConfidence}>
      <span className={styles.thinkConfidenceEmoji}>💬</span>
      <p className={styles.thinkConfidenceText}>
        <em>&ldquo;{shown}&rdquo;</em>
        {!done && <span className={styles.thinkCursor} />}
      </p>
    </div>
  );
};

// ─── Main Component ───────────────────────────────────────────────────────────
const Recommender = () => {
  const [stats, setStats]             = useState(null);
  const [topicStates, setTopicStates] = useState(null);
  const [personality, setPersonality] = useState(null);
  const [history, setHistory]         = useState(null);
  const [trends, setTrends]           = useState(null);
  const [correctQ, setCorrectQ]       = useState(null);   // AttemptedQuestionsResponse
  const [incorrectQ, setIncorrectQ]   = useState(null);   // AttemptedQuestionsResponse
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState('');
  const [initNeeded, setInitNeeded]   = useState(false);
  const [initializing, setInitializing] = useState(false);

  // Subject tab for chapter grid
  const [activeSubject, setActiveSubject] = useState('mathematics');

  // Recommendation state
  const [selectedChapters, setSelectedChapters] = useState(new Set()); // multi-select
  const [questionTotal, setQuestionTotal]       = useState(5);
  const [questionNum, setQuestionNum]           = useState(0); // 0 = not started
  const [sessionDone, setSessionDone]           = useState(false);
  const [recState, setRecState] = useState(null); // null | 'loading' | 'question' | 'submitted'
  const [session, setSession]   = useState(null);
  const [hotState, setHotState] = useState(INITIAL_SESSION_STATE);
  const [startedAt, setStartedAt] = useState(null);
  const [question, setQuestion] = useState(null);
  const [qContent, setQContent] = useState(null);
  const [selected, setSelected] = useState([]);
  const [intAnswer, setIntAnswer] = useState('');
  const [submitResult, setSubmitResult] = useState(null);
  const [submitting, setSubmitting]     = useState(false);
  const sessionResultsRef = useRef([]); // accumulate results for session summary

  // Post-session AI diagnosis (DiagnosisAgent runs async after end_session)
  const [diagnosisNote, setDiagnosisNote]         = useState('');
  const [diagnosingSession, setDiagnosingSession] = useState(false);
  const diagnosisTimerRef = useRef(null);

  // Thinking panel — each step: { id, kind: 'step'|'note'|'confidence'|'divider', ... }
  const [thinkSteps, setThinkSteps]   = useState([]);
  const [thinkOpen, setThinkOpen]     = useState(true);
  const thinkBodyRef  = useRef(null);   // scrollable container ref
  const thinkEndRef   = useRef(null);   // sentinel for auto-scroll
  const abortCtrlRef  = useRef(null);   // AbortController for the SSE stream

  // Answer timer
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef(null);

  // ── load overview ──────────────────────────────────────────────────────────
  const loadOverview = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [s, ts, p, h, tr, cq, iq] = await Promise.allSettled([
        recommenderService.getStats(),
        recommenderService.getTopicStates(),
        recommenderService.getPersonality(),
        recommenderService.getSessionHistory(),
        recommenderService.getTrends(),
        recommenderService.getAttemptedQuestions(true,  20),
        recommenderService.getAttemptedQuestions(false, 20),
      ]);
      if (s.status  === 'fulfilled') setStats(s.value);
      if (ts.status === 'fulfilled') setTopicStates(ts.value);
      if (p.status  === 'fulfilled') setPersonality(p.value);
      if (h.status  === 'fulfilled') setHistory(h.value);
      if (tr.status === 'fulfilled') setTrends(tr.value);
      if (cq.status === 'fulfilled') setCorrectQ(cq.value);
      if (iq.status === 'fulfilled') setIncorrectQ(iq.value);
      // Only show "Set Up Engine" when the server explicitly says the student
      // is not initialized (404). Any other error (500, network) should NOT
      // prompt a re-initialization — that would loop on 409.
      const needsInit =
        (ts.status === 'rejected' && ts.reason?.response?.status === 404) ||
        (ts.status === 'fulfilled' && ts.value?.total === 0);
      if (needsInit) setInitNeeded(true);
    } catch (err) {
      setError(parseApiError(err, 'Failed to load your data.'));
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadOverview(); }, [loadOverview]);
  useEffect(() => () => {
    stopTimer();
    if (abortCtrlRef.current) abortCtrlRef.current.abort();
    if (diagnosisTimerRef.current) clearTimeout(diagnosisTimerRef.current);
  }, []);

  // Scroll only the thinkBody container (not the whole page) as new steps appear
  useEffect(() => {
    const body = thinkBodyRef.current;
    if (!body) return;
    // Use requestAnimationFrame so the new DOM node is painted before we scroll
    requestAnimationFrame(() => {
      body.scrollTo({ top: body.scrollHeight, behavior: 'smooth' });
    });
  }, [thinkSteps]);

  // Keep thinking panel open whenever a new session loading starts
  useEffect(() => {
    if (recState === 'loading') setThinkOpen(true);
  }, [recState]);


  // ── timer ──────────────────────────────────────────────────────────────────
  const startTimer = () => {
    setElapsed(0);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => setElapsed((e) => e + 100), 100);
  };
  const stopTimer = () => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  };

  // addThought accepts either a plain string (legacy: submit feedback, question info)
  // or a step object { kind, tool?, label?, text? }.
  const addThought = (data) => {
    const step = typeof data === 'string'
      ? { kind: 'note', text: data }
      : data;
    setThinkSteps((prev) => [...prev, { id: Date.now() + Math.random(), ...step }]);
  };

  // ── initialize ─────────────────────────────────────────────────────────────
  const handleInitialize = async () => {
    setInitializing(true);
    try {
      await recommenderService.initialize();
      setInitNeeded(false);
      await loadOverview();
    } catch (err) {
      setError(parseApiError(err, 'Initialization failed.'));
    } finally { setInitializing(false); }
  };

  // ── helpers ────────────────────────────────────────────────────────────────
  const toggleChapter = (ch, hasUnlocked) => {
    if (!hasUnlocked || sessionDone) return;
    setSelectedChapters((prev) => {
      const next = new Set(prev);
      next.has(ch) ? next.delete(ch) : next.add(ch);
      return next;
    });
  };

  const getFocusTopics = (chapters) =>
    (topicStates?.topic_states || [])
      .filter((t) => chapters.has(t.chapter) && t.is_unlocked)
      .map((t) => t.topic_id);

  const fetchNextQuestion = async (plan, currentHot, num) => {
    // Each call gets a completely fresh AbortController so there is
    // zero signal sharing with any previous stream (session-start or earlier questions).
    const ctl = new AbortController();
    abortCtrlRef.current = ctl;     // expose so handleReset can abort it

    const focusTopics = getFocusTopics(selectedChapters);
    const payload = {
      session_id:              plan.session_id,
      focus_topics:            focusTopics.length > 0 ? focusTopics : (plan.focus_topics || []),
      start_difficulty_offset: plan.start_difficulty_offset,
      review_injection_rate:   plan.review_injection_rate,
      state:                   currentHot,
    };

    let resolvedQuestion = null;
    let streamError      = null;

    try {
      await recommenderService.nextQuestionStream(
        payload,
        (event) => {
          if (event.type === 'step') {
            addThought({ kind: 'step', tool: event.tool || 'system', label: event.label });
          } else if (event.type === 'thought') {
            addThought({ kind: 'thought', text: event.text });
          } else if (event.type === 'question') {
            resolvedQuestion = event;
          } else if (event.type === 'error') {
            streamError = event.message;
          }
        },
        ctl.signal,     // always the fresh local signal, not any shared ref
      );
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      streamError = err.message;
    }

    // If stream failed entirely, fall back to regular endpoint
    if (!resolvedQuestion) {
      if (streamError) addThought({ kind: 'note', text: `⚠️ Streaming failed — ${streamError}` });
      const nq = await recommenderService.getNextQuestion(payload);
      resolvedQuestion = nq;
    }

    const nq = resolvedQuestion;
    setQuestion(nq);
    setQuestionNum(num);
    if (nq.is_review_injection && nq.review_reason) {
      addThought({ kind: 'note', text: `📅 ${nq.review_reason}` });
    }

    const content = await recommenderService.getQuestion(nq.question_id);
    setQContent(content);
    return { nq, content };
  };

  // ── start practice (multi-chapter, N questions) ───────────────────────────
  const handleStartPractice = async () => {
    if (selectedChapters.size === 0) return;
    if (session) {
      try { await recommenderService.endSession({ session_id: session.session_id, state: hotState, started_at: startedAt }); } catch { /* best-effort */ }
    }
    // Abort any previous stream still running
    if (abortCtrlRef.current) { abortCtrlRef.current.abort(); abortCtrlRef.current = null; }

    setSessionDone(false);
    sessionResultsRef.current = [];
    setRecState('loading');
    setQuestion(null); setQContent(null); setSubmitResult(null);
    setSelected([]); setIntAnswer(''); setQuestionNum(0);
    setThinkSteps([]);
    setThinkOpen(true);

    abortCtrlRef.current = new AbortController();
    let resolvedPlan = null;
    let streamError  = null;

    try {
      await recommenderService.startSessionStream(
        (event) => {
          if (event.type === 'connected') return;
          if (event.type === 'step') {
            addThought({ kind: 'step', tool: event.tool, label: event.label });
          } else if (event.type === 'thought') {
            addThought({ kind: 'thought', text: event.text });
          } else if (event.type === 'confidence') {
            addThought({ kind: 'confidence', text: event.text });
          } else if (event.type === 'plan') {
            resolvedPlan = event;
          } else if (event.type === 'error') {
            streamError = event.message;
          }
        },
        abortCtrlRef.current.signal,
      );
    } catch (err) {
      if (err.name === 'AbortError') return;   // user navigated away / reset
      streamError = parseApiError(err, 'Please try again.');
    }

    if (streamError) {
      addThought({ kind: 'note', text: `Couldn't start: ${streamError}` });
      setRecState(null);
      return;
    }
    if (!resolvedPlan) { setRecState(null); return; }

    const plan = resolvedPlan;
    setSession(plan);
    const newHot = plan.state || INITIAL_SESSION_STATE;
    setHotState(newHot);
    setStartedAt(new Date().toISOString());

    const chapterNames = [...selectedChapters].join(', ');

    try {
      await fetchNextQuestion(plan, newHot, 1);
      setRecState('question');
      startTimer();
    } catch (err) {
      addThought({ kind: 'note', text: `Couldn't load question: ${parseApiError(err, 'Please try again.')}` });
      setRecState(null);
    }
  };

  // ── submit ─────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (!question || !session || !qContent) return;
    stopTimer();
    setSubmitting(true);

    const isCorrect = evaluateAnswer();
    const qTypeMap = { mcq: 'single_correct', mcqm: 'multi_correct', integer: 'integer' };

    try {
      const resp = await recommenderService.submitAnswer({
        session_id: session.session_id,
        question_id: question.question_id,
        topic_id: question.topic_id,
        correct: isCorrect,
        time_ms: elapsed,
        difficulty: question.difficulty_target || 0.5,
        question_type: qTypeMap[qContent.type] || 'single_correct',
        state: hotState,
      });

      const newHot = resp.state || hotState;
      setHotState(newHot);
      setSubmitResult({ ...resp, isCorrect });

      // accumulate for session summary
      const chapter = question.topic_id?.split('::')[0] || question.topic_id;
      sessionResultsRef.current.push({ isCorrect, topic: question.topic_id, chapter });

      if (isCorrect) {
        addThought('Nicely done! 🎉 That was the correct answer.');
      } else {
        addThought("That wasn't quite right — check the correct answer highlighted below.");
      }
      const newMastery = masteryPct(resp.updated_topic?.mastery_mean);
      addThought(`Your mastery of this topic is now ${newMastery}%`);
      if (resp.newly_unlocked_topics?.length > 0) {
        addThought(`🎊 You just unlocked ${resp.newly_unlocked_topics.length} new topic(s) — keep it up!`);
      }

      setRecState('submitted');
    } catch (err) {
      addThought(`Submission failed: ${parseApiError(err, 'Please try again.')}`);
    } finally { setSubmitting(false); }
  };

  const evaluateAnswer = () => {
    if (!qContent) return false;
    if (qContent.type === 'integer') return String(qContent.correct_answer || '') === intAnswer.trim();
    const correct = qContent.correct_options || [];
    if (qContent.type === 'mcqm') return [...selected].sort().join() === [...correct].sort().join();
    return selected[0] === correct[0];
  };

  // ── next question in current session ─────────────────────────────────────
  const handleNextQuestion = async () => {
    if (!session) return;
    const nextNum = questionNum + 1;

    if (nextNum > questionTotal) {
      // all N done — end session and show summary
      try {
        await recommenderService.endSession({ session_id: session.session_id, state: hotState, started_at: startedAt });
      } catch { /* best-effort */ }
      setSession(null);    // clear so handleReset / handleStartPractice don't call endSession again
      setSessionDone(true);
      setRecState(null);
      setDiagnosisNote('');
      setDiagnosingSession(true);
      await loadOverview();

      // Capture the OLD finding AFTER loadOverview so we can detect when the
      // DiagnosisAgent writes a genuinely new one.
      // DiagnosisAgent has a 16k thinking budget — can take 15-25 seconds.
      // We poll every 5s (up to 8 times = 40s max) until the value changes.
      if (diagnosisTimerRef.current) clearTimeout(diagnosisTimerRef.current);
      const prevFinding = (await recommenderService.getPersonality().catch(() => null))
                            ?.last_session_finding || '';
      let pollCount = 0;

      const doPoll = async () => {
        pollCount++;
        if (pollCount > 8) { setDiagnosingSession(false); return; }
        try {
          const p = await recommenderService.getPersonality();
          const newFinding = p?.last_session_finding || '';
          if (newFinding && newFinding !== prevFinding) {
            setDiagnosisNote(newFinding);
            setPersonality(p);   // update profile card with latest personality
            setDiagnosingSession(false);
            return;
          }
        } catch { /* non-critical */ }
        diagnosisTimerRef.current = setTimeout(doPoll, 5_000);
      };
      diagnosisTimerRef.current = setTimeout(doPoll, 5_000);  // first check after 5s
      return;
    }

    setRecState('loading');
    setQuestion(null); setQContent(null); setSubmitResult(null);
    setSelected([]); setIntAnswer('');

    // Clear thinking steps so each question gets a fresh panel (not an ever-growing list)
    setThinkSteps([]);
    setThinkOpen(true);

    // Scroll back up to the thinking panel — user was scrolled down to the previous question card
    setTimeout(() => {
      document.getElementById('recommendation')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);

    try {
      // No divider needed — panel is fresh per question
      await fetchNextQuestion(session, hotState, nextNum);
      setRecState('question');
      startTimer();
    } catch (err) {
      addThought(`Couldn't load question ${nextNum}: ${parseApiError(err, 'Please try again.')}`);
      setRecState(null);
    }
  };

  // ── reset — go back to chapter selection ─────────────────────────────────
  const handleReset = async () => {
    stopTimer();
    if (abortCtrlRef.current) { abortCtrlRef.current.abort(); abortCtrlRef.current = null; }
    if (session) {
      try { await recommenderService.endSession({ session_id: session.session_id, state: hotState, started_at: startedAt }); } catch { /* best-effort */ }
    }
    setSession(null); setSelectedChapters(new Set()); setRecState(null);
    setThinkSteps([]); setQuestion(null); setQContent(null); setSubmitResult(null);
    setHotState(INITIAL_SESSION_STATE); setQuestionNum(0); setSessionDone(false);
    setDiagnosisNote(''); setDiagnosingSession(false);
    if (diagnosisTimerRef.current) clearTimeout(diagnosisTimerRef.current);
    sessionResultsRef.current = [];
    await loadOverview();
  };

  const toggleOption = (ident) => {
    if (!qContent || recState === 'submitted') return;
    if (qContent.type === 'mcqm') {
      setSelected((prev) => prev.includes(ident) ? prev.filter((x) => x !== ident) : [...prev, ident]);
    } else {
      setSelected([ident]);
    }
  };

  // ─── render ────────────────────────────────────────────────────────────────
  if (loading) return <div className={styles.loaderWrap}><Loader /></div>;

  // ── Build per-subject chapter maps ────────────────────────────────────────
  const bySubjectChapter = {};
  (topicStates?.topic_states || []).forEach((t) => {
    const subj = (t.subject || 'mathematics').toLowerCase();
    if (!bySubjectChapter[subj]) bySubjectChapter[subj] = {};
    (bySubjectChapter[subj][t.chapter] = bySubjectChapter[subj][t.chapter] || []).push(t);
  });

  // Available subjects (those with at least one topic state)
  const availableSubjects = SUBJECT_ORDER.filter((s) => bySubjectChapter[s]);

  const byChapter = bySubjectChapter[activeSubject] || {};

  const sortedChapters = Object.entries(byChapter).sort(([, a], [, b]) => {
    const aU = a.filter((t) => t.is_unlocked).length;
    const bU = b.filter((t) => t.is_unlocked).length;
    if (aU === 0 && bU > 0) return 1;
    if (aU > 0 && bU === 0) return -1;
    const aM = a.reduce((s, t) => s + (t.mastery_mean || 0), 0) / a.length;
    const bM = b.reduce((s, t) => s + (t.mastery_mean || 0), 0) / b.length;
    return aM - bM;
  });

  const trendMap = {};
  (trends?.topics || []).forEach((t) => { trendMap[t.topic_id] = t; });

  const isThinking   = recState === 'loading';
  const sessionActive = session && !sessionDone;
  const sessionResults = sessionResultsRef.current;
  const sessionCorrect = sessionResults.filter((r) => r.isCorrect).length;

  return (
    <div className={styles.page}>

      {/* ── Hero ── */}
      <header className={styles.hero}>
        <div className={styles.heroLeft}>
          <div className={styles.heroEyebrow}>
            <IcoBrain className={styles.heroIcon} />
            <span>AI-Powered PYQ Recommender</span>
          </div>
          <h1 className={styles.heroTitle}>SmartPYQ</h1>
          <p className={styles.heroSub}>
            Learns from 15 years of JEE PYQs to identify exactly where you're weak — then serves the right question at the right time
          </p>
        </div>
        <div className={styles.heroRight}>
          {error && <p className={styles.errorBanner}>{error}</p>}
          {initNeeded && (
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleInitialize} disabled={initializing}>
              {initializing ? <span className={styles.spinner} /> : <IcoZap className={styles.btnIcon} />}
              {initializing ? 'Setting up…' : 'Set Up Engine'}
            </button>
          )}
          <button className={`${styles.btn} ${styles.btnGhost}`} onClick={loadOverview} disabled={loading} title="Refresh data">
            <IcoRefresh className={styles.btnIcon} />
          </button>
        </div>
      </header>

      {/* ── Your Progress (analytics) ── */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Your Progress</h2>
        <StatsRow stats={stats} topicStates={topicStates} history={history} />
      </section>

      {/* ── Chapter grid ── */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>
            {sessionActive
              ? `Practising — ${[...selectedChapters].join(', ')}`
              : sessionDone
              ? 'Session Complete'
              : 'Choose Chapters to Practise'}
          </h2>
          <p className={styles.sectionSub}>
            {sessionActive
              ? `Question ${questionNum} of ${questionTotal}`
              : 'Select one or more chapters · Sorted weakest → strongest'}
          </p>
        </div>

        {/* Subject tabs */}
        {!sessionActive && !sessionDone && availableSubjects.length > 1 && (
          <div className={styles.subjectTabs}>
            {availableSubjects.map((subj) => {
              const chapCount = Object.keys(bySubjectChapter[subj] || {}).length;
              return (
                <button
                  key={subj}
                  className={`${styles.subjectTab} ${activeSubject === subj ? styles.subjectTabActive : ''}`}
                  onClick={() => { setActiveSubject(subj); setSelectedChapters(new Set()); }}
                  disabled={initNeeded}
                >
                  {SUBJECT_LABELS[subj] || subj}
                  <span className={styles.subjectTabCount}>{chapCount}</span>
                </button>
              );
            })}
          </div>
        )}

        {sortedChapters.length === 0 ? (
          <p className={styles.emptyHint}>No chapter data yet. Set up the engine above to get started.</p>
        ) : (
          <div className={styles.chapterGrid}>
            {sortedChapters.map(([ch, topics]) => {
              const unlocked   = topics.filter((t) => t.is_unlocked).length;
              const avgMastery = topics.length
                ? Math.round(topics.reduce((s, t) => s + (t.mastery_mean || 0), 0) / topics.length * 100)
                : 0;
              const hasTrend   = topics.some((t) => trendMap[t.topic_id]?.is_high_priority);
              const color      = masteryColor(avgMastery);
              const isSelected = selectedChapters.has(ch);
              const locked     = unlocked === 0;

              return (
                <button
                  key={ch}
                  className={`${styles.chapterCard} ${isSelected ? styles.chapterCardSelected : ''} ${locked ? styles.chapterCardLocked : ''}`}
                  onClick={() => !sessionActive && !sessionDone && toggleChapter(ch, unlocked > 0)}
                  disabled={locked || sessionActive || sessionDone || initNeeded}
                >
                  <div className={styles.chapterCardTop}>
                    <span className={styles.chapterCardName}>{ch}</span>
                    <span className={styles.chapterCardRight}>
                      {hasTrend && <span className={styles.hotDot} title="Frequently asked in JEE">🔥</span>}
                      {isSelected
                        ? <IcoCheck className={styles.chapterCardLockIcon} style={{ color: 'var(--color-accent)' }} />
                        : locked
                        ? <IcoLock className={styles.chapterCardLockIcon} />
                        : <IcoUnlock className={styles.chapterCardLockIcon} style={{ color }} />}
                    </span>
                  </div>

                  <div className={styles.chapterCardBarTrack}>
                    <div className={styles.chapterCardBarFill} style={{ width: `${avgMastery}%`, background: color }} />
                  </div>

                  <div className={styles.chapterCardBottom}>
                    <span className={styles.chapterCardMasteryPct} style={{ color }}>{avgMastery}%</span>
                    <span className={styles.chapterCardMasteryLabel} style={{ color }}>{masteryLabel(avgMastery)}</span>
                    <span className={styles.chapterCardTopicCount}>
                      {locked ? 'Locked' : `${unlocked} / ${topics.length} topics`}
                    </span>
                  </div>

                  <div className={styles.chapterCardAction}>
                    {locked ? (
                      <span className={styles.chapterCardActionText}><IcoLock className={styles.chapterCardActionIcon} /> Locked</span>
                    ) : isSelected ? (
                      <span className={styles.chapterCardActionText} style={{ color: 'var(--color-accent)' }}>
                        <IcoCheck className={styles.chapterCardActionIcon} /> Selected
                      </span>
                    ) : (
                      <span className={styles.chapterCardActionText}><IcoZap className={styles.chapterCardActionIcon} /> Select</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* Count selector + Start button */}
        {!sessionActive && !sessionDone && selectedChapters.size > 0 && (
          <div className={styles.practiceBar}>
            <span className={styles.practiceBarLabel}>Questions:</span>
            {[3, 5, 10, 15].map((n) => (
              <button
                key={n}
                className={`${styles.countBtn} ${questionTotal === n ? styles.countBtnActive : ''}`}
                onClick={() => setQuestionTotal(n)}
              >
                {n}
              </button>
            ))}
            <button
              className={`${styles.btn} ${styles.btnPrimary} ${styles.startBtn}`}
              onClick={handleStartPractice}
              disabled={recState === 'loading'}
            >
              {recState === 'loading' ? <span className={styles.spinner} /> : <IcoZap className={styles.btnIcon} />}
              {recState === 'loading'
                ? 'Starting…'
                : `Start ${questionTotal} Questions from ${selectedChapters.size} chapter${selectedChapters.size > 1 ? 's' : ''}`}
            </button>
          </div>
        )}
      </section>

      {/* ── Session done summary ── */}
      {sessionDone && (() => {
        const acc = sessionResults.length ? Math.round(sessionCorrect / sessionResults.length * 100) : 0;
        const perfect = sessionCorrect === sessionResults.length && sessionResults.length > 0;

        // per-chapter breakdown
        const chapterMap = {};
        sessionResults.forEach(({ isCorrect, chapter }) => {
          if (!chapterMap[chapter]) chapterMap[chapter] = { correct: 0, total: 0 };
          chapterMap[chapter].total += 1;
          if (isCorrect) chapterMap[chapter].correct += 1;
        });
        const chapters = Object.entries(chapterMap).sort((a, b) =>
          (a[1].correct / a[1].total) - (b[1].correct / b[1].total)
        );

        return (
          <section className={styles.section}>
            <div className={`${styles.sessionSummary} ${perfect ? styles.summaryPerfect : ''}`}>
              <h2 className={styles.summaryTitle}>
                {perfect ? '🎉 Perfect session!' : `Session complete — ${sessionCorrect} / ${sessionResults.length} correct`}
              </h2>

              {/* Accuracy bar */}
              <div className={styles.summaryAccBar}>
                <div className={styles.summaryAccFill} style={{ width: `${acc}%` }} />
              </div>
              <p className={styles.summaryAcc}>
                Overall accuracy: <strong>{acc}%</strong> across {sessionResults.length} questions
              </p>

              {/* Per-chapter breakdown */}
              {chapters.length > 1 && (
                <div className={styles.summaryBreakdown}>
                  {chapters.map(([ch, { correct, total }]) => {
                    const chAcc = Math.round(correct / total * 100);
                    const color = masteryColor(chAcc);
                    return (
                      <div key={ch} className={styles.summaryChapterRow}>
                        <span className={styles.summaryChapterName}>{ch}</span>
                        <div className={styles.summaryChapterBar}>
                          <div className={styles.summaryChapterFill} style={{ width: `${chAcc}%`, background: color }} />
                        </div>
                        <span className={styles.summaryChapterPct} style={{ color }}>{chAcc}%</span>
                        <span className={styles.summaryChapterFrac}>{correct}/{total}</span>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* AI Coach diagnosis — appears after ~10s when DiagnosisAgent finishes */}
              {diagnosingSession && (
                <div className={styles.diagnosisLoading}>
                  <span className={styles.spinnerSm} />
                  <span>Your AI Coach is analysing this session…</span>
                </div>
              )}
              {!diagnosingSession && diagnosisNote && (
                <div className={styles.diagnosisCard}>
                  <span className={styles.diagnosisIcon}>🧠</span>
                  <div>
                    <div className={styles.diagnosisLabel}>Coach's Analysis</div>
                    <p className={styles.diagnosisText}>{diagnosisNote}</p>
                  </div>
                </div>
              )}

              <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleReset}>
                <IcoRefresh className={styles.btnIcon} /> Start New Session
              </button>
            </div>
          </section>
        );
      })()}

      {/* ── Recommendation section ── */}
      {sessionActive && (
        <section className={styles.section} id="recommendation">
          <div className={styles.sectionHead}>
            <div className={styles.progressRow}>
              <span className={styles.progressLabel}>Question {questionNum} of {questionTotal}</span>
              <div className={styles.progressBarTrack}>
                <div className={styles.progressBarFill} style={{ width: `${Math.round((questionNum - 1) / questionTotal * 100)}%` }} />
              </div>
              <button className={`${styles.btn} ${styles.btnGhost} ${styles.btnSm}`} onClick={handleReset} disabled={submitting}>
                End Session
              </button>
            </div>
          </div>

          <div className={styles.recLayout}>
            {/* Thinking panel */}
            {thinkSteps.length > 0 && (
              <div className={styles.thinkPanel}>
                <button className={styles.thinkToggle} onClick={() => setThinkOpen((v) => !v)}>
                  <span className={styles.thinkToggleLeft}>
                    {isThinking
                      ? <ThinkingDots />
                      : <span className={styles.thinkDoneCircle}><IcoCheck className={styles.thinkDoneCheckIcon} /></span>}
                    <span className={styles.thinkToggleLabel}>
                      {isThinking ? 'SmartPYQ is thinking…' : 'SmartPYQ · Ready'}
                    </span>
                    {!isThinking && session && (
                      <span className={`${styles.modeBadge} ${styles[`modeBadge_${session.session_mode}`] || ''}`}>
                        {MODE_EMOJI[session.session_mode] || '⚡'} {session.session_mode}
                      </span>
                    )}
                  </span>
                  <IcoChevron className={`${styles.thinkChevron} ${thinkOpen ? styles.thinkChevronOpen : ''}`} />
                </button>

                {thinkOpen && (
                  <div className={styles.thinkBody} ref={thinkBodyRef}>
                    {thinkSteps.map((step) => {
                      if (step.kind === 'divider') return (
                        <div key={step.id} className={styles.thinkDivider}>{step.text}</div>
                      );
                      if (step.kind === 'confidence') return (
                        <ConfidenceNote key={step.id} text={step.text} />
                      );
                      if (step.kind === 'thought') return (
                        <ThoughtBlock key={step.id} text={step.text} />
                      );
                      if (step.kind === 'step') return (
                        <div key={step.id} className={styles.thinkStepItem}>
                          <span className={styles.thinkStepEmoji}>{TOOL_ICONS[step.tool] || '✦'}</span>
                          <span className={styles.thinkStepLabel}>{step.label}</span>
                          <IcoCheck className={styles.thinkStepCheck} />
                        </div>
                      );
                      // kind === 'note' — free text (submit feedback, question info, errors)
                      return (
                        <div key={step.id} className={styles.thinkNoteItem}>
                          <span className={styles.thinkNoteStepDot} />
                          <span className={styles.thinkStepText}>{step.text}</span>
                        </div>
                      );
                    })}
                    {isThinking && (
                      <div className={styles.thinkWaitRow}>
                        <span className={styles.spinnerSm} />
                        <span className={styles.thinkWaitText}>Working on it…</span>
                      </div>
                    )}
                    <div ref={thinkEndRef} />
                  </div>
                )}
              </div>
            )}

            {/* Question card */}
            {(recState === 'question' || recState === 'submitted') && qContent && (
              <QuestionCard
                qContent={qContent}
                question={question}
                recState={recState}
                selected={selected}
                intAnswer={intAnswer}
                setIntAnswer={setIntAnswer}
                elapsed={elapsed}
                submitting={submitting}
                submitResult={submitResult}
                questionNum={questionNum}
                questionTotal={questionTotal}
                onToggle={toggleOption}
                onSubmit={handleSubmit}
                onNext={handleNextQuestion}
                onReset={handleReset}
              />
            )}
          </div>
        </section>
      )}

      {/* ── Bottom grid ── */}
      <div className={styles.bottomGrid}>
        <PersonalityCard personality={personality} />
        <SessionHistoryCard history={history} />
        <TrendCard trends={trends} />
      </div>

      {/* ── Attempted questions ── */}
      <div className={styles.attemptedGrid}>
        <CorrectQuestionsCard items={correctQ?.items || []} />
        <IncorrectQuestionsCard items={incorrectQ?.items || []} />
      </div>
    </div>
  );
};

// ─── QuestionCard ─────────────────────────────────────────────────────────────
const QuestionCard = ({
  qContent, question, recState,
  selected, intAnswer, setIntAnswer,
  elapsed, submitting, submitResult,
  questionNum, questionTotal,
  onToggle, onSubmit, onNext, onReset,
}) => {
  const correctOptions = qContent.correct_options || [];

  const canSubmit = () => {
    if (qContent.type === 'integer') return intAnswer.trim() !== '';
    return selected.length > 0;
  };

  const getOptClass = (ident) => {
    if (recState !== 'submitted') return selected.includes(ident) ? styles.optSelected : '';
    const isSel = selected.includes(ident), isCorr = correctOptions.includes(ident);
    if (isSel && isCorr)  return styles.optCorrect;
    if (isSel && !isCorr) return styles.optWrong;
    if (!isSel && isCorr) return styles.optReveal;
    return styles.optDimmed;
  };

  const diffLabel = qContent.difficulty;
  const diffClass = styles[`diff_${diffLabel}`] || styles.diff_medium;

  return (
    <div className={styles.qCard}>
      {/* Meta chips */}
      <div className={styles.qMeta}>
        <span className={styles.qChip}>{qContent.chapter}</span>
        <span className={`${styles.qChip} ${styles.qChipTopic}`}>{qContent.topic}</span>
        <span className={`${styles.qDiff} ${diffClass}`}>
          {diffLabel?.charAt(0).toUpperCase() + diffLabel?.slice(1)}
        </span>
        {qContent.year && (
          <span className={styles.qYear}>JEE {qContent.year}</span>
        )}
        {question?.is_review_injection && (
          <span className={styles.qReview}>📅 Review</span>
        )}
      </div>

      {/* Coach note — why the AI chose this question */}
      {question?.coach_note && (
        <CoachNoteCard note={question.coach_note} isReview={question.is_review_injection} />
      )}

      {/* Question text */}
      <div className={styles.qText}>
        {qContent.is_image_question
          ? <p className={styles.qImgNote}>This question has an image. View it in the full exam app.</p>
          : <LatexText>{qContent.question}</LatexText>}
      </div>

      {/* Integer input */}
      {qContent.type === 'integer' ? (
        <div className={styles.intWrap}>
          <label className={styles.intLabel}>Type your answer (integer):</label>
          <input
            type="number"
            className={`${styles.intInput} ${recState === 'submitted' ? (submitResult?.isCorrect ? styles.intInputCorrect : styles.intInputWrong) : ''}`}
            value={intAnswer}
            onChange={(e) => setIntAnswer(e.target.value)}
            placeholder="Enter a number"
            disabled={recState === 'submitted'}
          />
          {recState === 'submitted' && (
            <div className={`${styles.answerReveal} ${submitResult?.isCorrect ? styles.answerRevealCorrect : styles.answerRevealWrong}`}>
              {submitResult?.isCorrect
                ? <><IcoCheck className={styles.answerRevealIcon} /> Your answer is correct!</>
                : qContent.correct_answer != null
                  ? <><IcoXCircle className={styles.answerRevealIcon} /> Correct answer: <strong>{qContent.correct_answer}</strong></>
                  : <><IcoXCircle className={styles.answerRevealIcon} /> Incorrect</>}
            </div>
          )}
        </div>
      ) : (
        /* MCQ / MCQM */
        <div className={styles.optList}>
          {qContent.options.map((opt) => {
            const isImg = qContent.is_image_option === true ||
              (Array.isArray(qContent.is_image_option) &&
                qContent.is_image_option[opt.identifier.charCodeAt(0) - 65]);
            return (
              <button
                key={opt.identifier}
                className={`${styles.optBtn} ${getOptClass(opt.identifier)}`}
                onClick={() => onToggle(opt.identifier)}
                disabled={recState === 'submitted'}
              >
                <span className={styles.optId}>{opt.identifier}</span>
                <span className={styles.optText}>{isImg ? '[Image option]' : <LatexText>{opt.content}</LatexText>}</span>
                {recState === 'submitted' && correctOptions.includes(opt.identifier) && (
                  <IcoCheck className={styles.optCheckIcon} />
                )}
                {recState === 'submitted' && selected.includes(opt.identifier) && !correctOptions.includes(opt.identifier) && (
                  <IcoXCircle className={styles.optXIcon} />
                )}
              </button>
            );
          })}
          {qContent.type === 'mcqm' && recState === 'question' && (
            <p className={styles.mcqmHint}>This question has multiple correct answers — select all that apply</p>
          )}
          {/* Explicit correct-answer banner — shown when student got it wrong */}
          {recState === 'submitted' && !submitResult?.isCorrect && correctOptions.length > 0 && (
            <div className={styles.answerReveal}>
              <IcoCheck className={styles.answerRevealIcon} />
              Correct answer: <strong>{correctOptions.join(' and ')}</strong>
            </div>
          )}
        </div>
      )}

      {/* Submit */}
      {recState === 'question' && (
        <div className={styles.submitRow}>
          <span className={styles.timerBadge}>⏱ {Math.floor(elapsed / 1000)}s</span>
          <button
            className={`${styles.btn} ${styles.btnPrimary} ${styles.btnFull}`}
            onClick={onSubmit}
            disabled={!canSubmit() || submitting}
          >
            {submitting ? <span className={styles.spinner} /> : <IcoArrow className={styles.btnIcon} />}
            {submitting ? 'Submitting…' : 'Submit Answer'}
          </button>
        </div>
      )}

      {/* Solution (revealed after submission) */}
      {recState === 'submitted' && <SolutionCard explanation={qContent.explanation} />}

      {/* Result */}
      {recState === 'submitted' && submitResult && (
        <div className={`${styles.resultCard} ${submitResult.isCorrect ? styles.resultGood : styles.resultBad}`}>
          <div className={styles.resultHeader}>
            {submitResult.isCorrect
              ? <><IcoCheck className={styles.resultIcon} /><span>Correct! Well done 🎉</span></>
              : <><IcoXCircle className={styles.resultIcon} /><span>Incorrect — the correct answer is highlighted above</span></>}
          </div>
          <div className={styles.masteryRow}>
            <span className={styles.masteryLabel}>
              Your mastery of this topic
            </span>
            <span className={styles.masteryPct}>
              {masteryPct(submitResult.updated_topic?.mastery_mean)}%
            </span>
          </div>
          <div className={styles.masteryBarTrack}>
            <div
              className={styles.masteryBarFill}
              style={{ width: `${masteryPct(submitResult.updated_topic?.mastery_mean)}%` }}
            />
          </div>
          {submitResult.newly_unlocked_topics?.length > 0 && (
            <p className={styles.unlockedMsg}>
              🎊 You unlocked {submitResult.newly_unlocked_topics.length} new topic{submitResult.newly_unlocked_topics.length > 1 ? 's' : ''}!
            </p>
          )}
          <div className={styles.resultActions}>
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={onNext}>
              {questionNum >= questionTotal
                ? <><IcoCheck className={styles.btnIcon} /> Finish Session</>
                : <><IcoArrow className={styles.btnIcon} /> Next Question ({questionNum + 1} of {questionTotal})</>}
            </button>
            <button className={`${styles.btn} ${styles.btnGhost}`} onClick={onReset}>
              End Session
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

// ─── StatsRow ─────────────────────────────────────────────────────────────────
const StatsRow = ({ stats, topicStates, history }) => {
  const totalSessions = history?.total ?? 0;
  const recentAcc = (() => {
    const s = history?.sessions?.slice(0, 3) || [];
    if (!s.length) return null;
    const all = s.flatMap((x) => Object.values(x.accuracy_by_chapter || {}));
    if (!all.length) return null;
    return Math.round(all.reduce((a, b) => a + b, 0) / all.length * 100);
  })();

  return (
    <div className={styles.statsRow}>
      {[
        { Icon: IcoBook,   label: 'Questions Solved',   value: stats?.total_attempts ?? '—',     sub: `${stats?.total_correct ?? 0} correct` },
        { Icon: IcoUnlock, label: 'Topics Unlocked',    value: topicStates?.unlocked_count ?? '—', sub: `out of ${topicStates?.total ?? 156}` },
        { Icon: IcoTarget, label: 'All-Time Accuracy',  value: stats?.total_attempts ? `${Math.round((stats.accuracy || 0) * 100)}%` : '—', sub: 'across all topics' },
        { Icon: IcoStar,   label: 'Study Sessions',     value: totalSessions, sub: recentAcc != null ? `Recent accuracy: ${recentAcc}%` : 'No sessions yet' },
      ].map(({ Icon, label, value, sub }) => (
        <div key={label} className={styles.statCard}>
          <div className={styles.statIcon}><Icon /></div>
          <div className={styles.statBody}>
            <span className={styles.statValue}>{value}</span>
            <span className={styles.statLabel}>{label}</span>
            <span className={styles.statSub}>{sub}</span>
          </div>
        </div>
      ))}
    </div>
  );
};

// ─── PersonalityCard ──────────────────────────────────────────────────────────
const PersonalityCard = ({ personality: p }) => (
  <section className={styles.card}>
    <div className={styles.cardHead}>
      <IcoUser className={styles.cardIcon} />
      <div>
        <h2 className={styles.cardTitle}>Your Learning Profile</h2>
        <p className={styles.cardSub}>How the AI sees you as a learner</p>
      </div>
    </div>
    <div className={styles.personalityGrid}>
      <ProfileChip label="Study Style"        value={learningStyleFriendly(p?.learning_style)} />
      <ProfileChip label="Improvement"        value={improvementFriendly(p?.improvement_rate)} />
      <ProfileChip label="Focus before break" value={p?.fatigue_threshold_questions ? `Every ${p.fatigue_threshold_questions} questions` : '—'} />
      <ProfileChip label="Confidence"         value={p?.confidence_profile ? p.confidence_profile.charAt(0).toUpperCase() + p.confidence_profile.slice(1) : '—'} />
      {p?.strong_chapters?.length > 0 && (
        <div className={styles.profileSection}>
          <span className={styles.profileSectionLabel}>You're strong at</span>
          <div className={styles.chipRow}>
            {p.strong_chapters.slice(0, 4).map((c) => (
              <span key={c} className={`${styles.chip} ${styles.chipGreen}`}>{c}</span>
            ))}
          </div>
        </div>
      )}
      {p?.persistent_weak_chapters?.length > 0 && (
        <div className={styles.profileSection}>
          <span className={styles.profileSectionLabel}>Needs more practice</span>
          <div className={styles.chipRow}>
            {p.persistent_weak_chapters.slice(0, 4).map((c) => (
              <span key={c} className={`${styles.chip} ${styles.chipRed}`}>{c}</span>
            ))}
          </div>
        </div>
      )}
      {p?.notes && (
        <div className={styles.profileSection}>
          <span className={styles.profileSectionLabel}>AI diagnosis</span>
          <p className={styles.profileNotes}>{p.notes}</p>
        </div>
      )}
      {!p?.notes && (
        <p className={styles.profileHint}>Keep practicing — your profile gets smarter every session</p>
      )}
    </div>
  </section>
);

const ProfileChip = ({ label, value }) => (
  <div className={styles.profileChip}>
    <span className={styles.profileChipLabel}>{label}</span>
    <span className={styles.profileChipValue}>{value || '—'}</span>
  </div>
);

// ─── SessionHistoryCard ───────────────────────────────────────────────────────
const SessionHistoryCard = ({ history }) => {
  const sessions = history?.sessions?.slice(0, 5) || [];
  return (
    <section className={styles.card}>
      <div className={styles.cardHead}>
        <IcoList className={styles.cardIcon} />
        <div>
          <h2 className={styles.cardTitle}>Past Sessions</h2>
          <p className={styles.cardSub}>{history?.total ?? 0} sessions total</p>
        </div>
      </div>
      {sessions.length === 0 ? (
        <p className={styles.empty}>No sessions yet. Start practicing above!</p>
      ) : (
        <div className={styles.historyList}>
          {sessions.map((s, i) => {
            const allAcc = Object.values(s.accuracy_by_chapter || {});
            const avgAcc = allAcc.length
              ? Math.round(allAcc.reduce((a, b) => a + b, 0) / allAcc.length * 100)
              : null;
            return (
              <div key={s.session_id || i} className={styles.historyRow}>
                <div className={styles.historyLeft}>
                  <span className={styles.historyNum}>#{history.total - i}</span>
                  <div>
                    <span className={styles.historyMeta}>
                      {s.questions_attempted} questions · {Math.round(s.duration_minutes)} min
                    </span>
                    {s.topics_unlocked?.length > 0 && (
                      <span className={styles.historyUnlock}>
                        🔓 {s.topics_unlocked.length} topic{s.topics_unlocked.length > 1 ? 's' : ''} unlocked
                      </span>
                    )}
                  </div>
                </div>
                {avgAcc != null && (
                  <span className={`${styles.historyAcc} ${avgAcc >= 70 ? styles.accGood : avgAcc >= 40 ? styles.accMid : styles.accBad}`}>
                    {avgAcc}%
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

// ─── TrendCard ────────────────────────────────────────────────────────────────
const TrendCard = ({ trends }) => {
  const allTopics = trends?.topics || [];
  const [activeSubj, setActiveSubj] = useState('');

  // Build per-subject lists on every render (fast, allTopics is ≤ a few hundred)
  const bySubject = {};
  allTopics.forEach((t) => {
    const s = (t.subject || 'other').toLowerCase();
    (bySubject[s] = bySubject[s] || []).push(t);
  });
  const subjOrder  = ['mathematics', 'physics', 'chemistry'];
  const subjLabel  = { mathematics: 'Maths', physics: 'Physics', chemistry: 'Chemistry' };
  const availSubjs = subjOrder.filter((s) => bySubject[s]?.length > 0);

  // Default to first available subject
  const currentSubj = activeSubj && bySubject[activeSubj] ? activeSubj : availSubjs[0] || '';
  const subjectTopics = bySubject[currentSubj] || [];

  // Show high-priority first; if none reach the threshold, show top-6 anyway
  const highPri = subjectTopics.filter((t) => t.is_high_priority);
  const display = (highPri.length > 0 ? highPri : subjectTopics).slice(0, 6);
  const computing = allTopics.length === 0;

  return (
    <section className={styles.card}>
      <div className={styles.cardHead}>
        <IcoTrend className={styles.cardIcon} />
        <div>
          <h2 className={styles.cardTitle}>Hot Topics in JEE</h2>
          <p className={styles.cardSub}>
            {computing
              ? 'Computing trends…'
              : `${trends?.high_priority_count ?? 0} topics frequently asked · ${currentSubj ? subjLabel[currentSubj] || currentSubj : ''}`}
          </p>
        </div>
      </div>

      {/* Subject tabs */}
      {availSubjs.length > 1 && (
        <div className={styles.trendSubjectTabs}>
          {availSubjs.map((s) => (
            <button
              key={s}
              className={`${styles.trendSubjectTab} ${currentSubj === s ? styles.trendSubjectTabActive : ''}`}
              onClick={() => setActiveSubj(s)}
            >
              {subjLabel[s] || s}
              <span className={styles.trendTabCount}>{bySubject[s]?.filter(t => t.is_high_priority).length || bySubject[s]?.length || 0}</span>
            </button>
          ))}
        </div>
      )}

      {computing ? (
        <p className={styles.empty}>Calculating trends from exam history — refresh in a moment.</p>
      ) : display.length === 0 ? (
        <p className={styles.empty}>No trend data for this subject yet.</p>
      ) : (
        <div className={styles.trendList}>
          {display.map((t) => (
            <div key={t.topic_id} className={styles.trendRow}>
              <div className={styles.trendLeft}>
                <span className={styles.trendName}>{t.topic_id.split('::')[1] || t.topic_id}</span>
                <span className={styles.trendChapter}>{t.chapter}</span>
              </div>
              <div className={styles.trendRight}>
                <div className={styles.trendBarTrack}>
                  <div className={styles.trendBarFill} style={{ width: `${Math.round(t.p_appears * 100)}%` }} />
                </div>
                <span className={styles.trendPct}>{Math.round(t.p_appears * 100)}%</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

// ─── AttemptedQuestionRow ──────────────────────────────────────────────────────
const AttemptedQuestionRow = ({ item, isCorrect }) => {
  const [open, setOpen] = useState(false);
  const topicName = item.topic_id?.split('::')[1] || item.topic_id || item.chapter;
  const diffLabel = typeof item.difficulty === 'string'
    ? item.difficulty
    : item.difficulty == null ? '' : item.difficulty < 0.33 ? 'easy' : item.difficulty < 0.66 ? 'medium' : 'hard';
  const diffClass = styles[`diff_${diffLabel}`] || styles.diff_medium;
  const subjLabel = SUBJECT_LABELS[(item.subject || 'mathematics').toLowerCase()] || item.subject;

  return (
    <div className={styles.aqRow}>
      <button className={styles.aqRowHeader} onClick={() => setOpen((v) => !v)}>
        <span className={styles.aqRowLeft}>
          <span className={`${styles.aqDot} ${isCorrect ? styles.aqDotCorrect : styles.aqDotWrong}`} />
          <span className={styles.aqRowTopic}>{topicName}</span>
          <span className={styles.aqRowChips}>
            <span className={styles.qChip}>{item.chapter}</span>
            {subjLabel && <span className={`${styles.qChip} ${styles.aqSubjectChip}`}>{subjLabel}</span>}
            {diffLabel && <span className={`${styles.qDiff} ${diffClass}`}>{diffLabel.charAt(0).toUpperCase() + diffLabel.slice(1)}</span>}
            {item.year && <span className={styles.qYear}>JEE {item.year}</span>}
          </span>
        </span>
        <IcoChevron className={`${styles.aqChevron} ${open ? styles.aqChevronOpen : ''}`} />
      </button>

      {open && (
        <div className={styles.aqRowBody}>
          {item.is_image_question ? (
            <p className={styles.qImgNote}>This question has an image — view it in the full exam app.</p>
          ) : (
            <div className={styles.aqQText}><LatexText>{item.question_text}</LatexText></div>
          )}

          {item.options?.length > 0 && (
            <div className={styles.aqOptList}>
              {item.options.map((opt) => {
                const isCorr = (item.correct_options || []).includes(opt.identifier);
                return (
                  <div
                    key={opt.identifier}
                    className={`${styles.aqOpt} ${isCorr ? styles.aqOptCorrect : ''}`}
                  >
                    <span className={styles.optId}>{opt.identifier}</span>
                    <span className={styles.optText}><LatexText>{opt.content}</LatexText></span>
                    {isCorr && <IcoCheck className={styles.optCheckIcon} />}
                  </div>
                );
              })}
            </div>
          )}

          {item.correct_answer != null && item.options?.length === 0 && (
            <p className={styles.correctHint}>
              Correct answer: <strong>{item.correct_answer}</strong>
            </p>
          )}
        </div>
      )}
    </div>
  );
};

// ─── CorrectQuestionsCard ──────────────────────────────────────────────────────
const CorrectQuestionsCard = ({ items }) => (
  <section className={styles.card}>
    <div className={styles.cardHead}>
      <IcoCheck className={`${styles.cardIcon} ${styles.iconGreen}`} />
      <div>
        <h2 className={styles.cardTitle}>Questions You Got Right</h2>
        <p className={styles.cardSub}>{items.length} recent correct answers</p>
      </div>
    </div>
    {items.length === 0 ? (
      <p className={styles.empty}>No correct answers yet — start practising above!</p>
    ) : (
      <div className={styles.aqList}>
        {items.map((item) => (
          <AttemptedQuestionRow key={`${item.question_id}-${item.timestamp}`} item={item} isCorrect />
        ))}
      </div>
    )}
  </section>
);

// ─── IncorrectQuestionsCard ────────────────────────────────────────────────────
const IncorrectQuestionsCard = ({ items }) => (
  <section className={styles.card}>
    <div className={styles.cardHead}>
      <IcoXCircle className={`${styles.cardIcon} ${styles.iconRed}`} />
      <div>
        <h2 className={styles.cardTitle}>Questions to Review</h2>
        <p className={styles.cardSub}>{items.length} recent incorrect answers · will come back for retry</p>
      </div>
    </div>
    {items.length === 0 ? (
      <p className={styles.empty}>No incorrect answers yet. Keep it up!</p>
    ) : (
      <div className={styles.aqList}>
        {items.map((item) => (
          <AttemptedQuestionRow key={`${item.question_id}-${item.timestamp}`} item={item} isCorrect={false} />
        ))}
      </div>
    )}
  </section>
);

export default Recommender;
