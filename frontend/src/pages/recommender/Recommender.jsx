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

// ─── Constants ────────────────────────────────────────────────────────────────
const INITIAL_SESSION_STATE = {
  consecutive_wrong: 0,
  questions_asked: 0,
  session_mode: 'normal',
  seen_correct_ids: [],
  seen_all_ids: [],
  block_correct: [0, 0, 0],
  block_total: [0, 0, 0],
};

// Student-friendly loading steps shown while waiting for the API
const LOADING_STEPS = [
  { at: 0,    text: 'Looking at your recent study history...' },
  { at: 500,  text: 'Checking which topics need the most work...' },
  { at: 1000, text: 'Figuring out the right difficulty level for you...' },
  { at: 1600, text: 'Browsing through thousands of past JEE questions...' },
  { at: 2200, text: 'Making sure this is a fresh question for you...' },
  { at: 2700, text: 'Almost there — picking the perfect match...' },
];

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

// ─── Main Component ───────────────────────────────────────────────────────────
const Recommender = () => {
  const [stats, setStats]             = useState(null);
  const [topicStates, setTopicStates] = useState(null);
  const [personality, setPersonality] = useState(null);
  const [history, setHistory]         = useState(null);
  const [trends, setTrends]           = useState(null);
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState('');
  const [initNeeded, setInitNeeded]   = useState(false);
  const [initializing, setInitializing] = useState(false);

  // Recommendation state
  const [selectedChapter, setSelectedChapter] = useState(null);
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

  // Thinking panel
  const [thinkSteps, setThinkSteps]   = useState([]);
  const [thinkOpen, setThinkOpen]     = useState(true);
  const stepTimersRef = useRef([]);
  const thinkEndRef   = useRef(null);

  // Answer timer
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef(null);

  // ── load overview ──────────────────────────────────────────────────────────
  const loadOverview = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [s, ts, p, h, tr] = await Promise.allSettled([
        recommenderService.getStats(),
        recommenderService.getTopicStates(),
        recommenderService.getPersonality(),
        recommenderService.getSessionHistory(),
        recommenderService.getTrends(),
      ]);
      if (s.status  === 'fulfilled') setStats(s.value);
      if (ts.status === 'fulfilled') setTopicStates(ts.value);
      if (p.status  === 'fulfilled') setPersonality(p.value);
      if (h.status  === 'fulfilled') setHistory(h.value);
      if (tr.status === 'fulfilled') setTrends(tr.value);
      if (ts.status === 'rejected' || ts.value?.total === 0) setInitNeeded(true);
    } catch (err) {
      setError(parseApiError(err, 'Failed to load your data.'));
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadOverview(); }, [loadOverview]);
  useEffect(() => () => { stopTimer(); clearStepTimers(); }, []);

  // Scroll thinking panel to bottom as steps appear
  useEffect(() => {
    if (thinkEndRef.current) thinkEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [thinkSteps]);

  // Open thinking panel when loading starts; stay open so user can read agent thoughts
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

  // ── thinking animation ────────────────────────────────────────────────────
  const clearStepTimers = () => {
    stepTimersRef.current.forEach(clearTimeout);
    stepTimersRef.current = [];
  };

  const startLoadingAnimation = () => {
    setThinkSteps([]);
    clearStepTimers();
    LOADING_STEPS.forEach(({ at, text }) => {
      const t = setTimeout(() => {
        setThinkSteps((prev) => [...prev, { id: Date.now() + Math.random(), text }]);
      }, at);
      stepTimersRef.current.push(t);
    });
  };

  const addThought = (text) => {
    setThinkSteps((prev) => [...prev, { id: Date.now() + Math.random(), text }]);
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

  // ── get recommendation ─────────────────────────────────────────────────────
  const handleGetRecommendation = async (chapter) => {
    if (session) {
      try {
        await recommenderService.endSession({ session_id: session.session_id, state: hotState, started_at: startedAt });
      } catch { /* best-effort */ }
    }

    setSelectedChapter(chapter);
    setRecState('loading');
    setQuestion(null); setQContent(null); setSubmitResult(null);
    setSelected([]); setIntAnswer('');
    startLoadingAnimation();

    try {
      const plan = await recommenderService.startSession();

      // Replace generic loading steps with real agent trace
      clearStepTimers();
      setThinkSteps([]);

      setSession(plan);
      const newHot = plan.state || INITIAL_SESSION_STATE;
      setHotState(newHot);
      setStartedAt(new Date().toISOString());

      const chapterTopics = (topicStates?.topic_states || [])
        .filter((t) => t.chapter === chapter && t.is_unlocked)
        .map((t) => t.topic_id);

      // Show each tool call the agent made, one by one with 250ms gaps
      const agentSteps = [
        ...(plan.reasoning_steps || []),
        plan.confidence_note || sessionModeText(plan.session_mode),
        `Narrowing down to ${chapterTopics.length || 'available'} topics in "${chapter}"...`,
      ].filter(Boolean);

      agentSteps.forEach((text, idx) => {
        const t = setTimeout(() => addThought(text), idx * 250);
        stepTimersRef.current.push(t);
      });

      const nq = await recommenderService.getNextQuestion({
        session_id: plan.session_id,
        focus_topics: chapterTopics.length > 0 ? chapterTopics : (plan.focus_topics || []),
        start_difficulty_offset: plan.start_difficulty_offset,
        review_injection_rate: plan.review_injection_rate,
        state: newHot,
      });
      setQuestion(nq);

      const topicName = nq.topic_id?.split('::')[1] || nq.topic_id;
      addThought(`Found your focus area: "${topicName}"`);
      if (nq.is_review_injection) {
        addThought("This one's coming back for review — let's see if you remember it");
      } else {
        addThought(`Setting difficulty to ${diffFriendly(nq.difficulty_target)} — just right for where you are`);
      }

      const content = await recommenderService.getQuestion(nq.question_id);
      setQContent(content);
      addThought(`${content.year ? `JEE ${content.year}` : 'Past JEE'} question ready for you ✓`);

      setRecState('question');
      startTimer();
    } catch (err) {
      clearStepTimers();
      addThought(`Couldn't find a question right now: ${parseApiError(err, 'No questions available for this chapter.')}`);
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
        chapter: question.chapter,
        correct: isCorrect,
        time_ms: elapsed,
        difficulty: question.difficulty_target || 0.5,
        question_type: qTypeMap[qContent.type] || 'single_correct',
        state: hotState,
      });

      setHotState(resp.state || hotState);
      setSubmitResult({ ...resp, isCorrect });

      // Student-friendly result thoughts
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

  // ── change chapter ─────────────────────────────────────────────────────────
  const handleChangeChapter = async () => {
    stopTimer(); clearStepTimers();
    if (session) {
      try {
        await recommenderService.endSession({ session_id: session.session_id, state: hotState, started_at: startedAt });
      } catch { /* best-effort */ }
    }
    setSession(null); setSelectedChapter(null); setRecState(null);
    setThinkSteps([]); setQuestion(null); setQContent(null); setSubmitResult(null);
    setHotState(INITIAL_SESSION_STATE);
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

  // Build chapter data
  const byChapter = {};
  (topicStates?.topic_states || []).forEach((t) => {
    (byChapter[t.chapter] = byChapter[t.chapter] || []).push(t);
  });

  // Sort: chapters with unlocked topics first, then by mastery ascending (weakest first)
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

  const isThinking = recState === 'loading';
  const thinkDone  = recState === 'question' || recState === 'submitted';

  return (
    <div className={styles.page}>

      {/* ── Hero ── */}
      <header className={styles.hero}>
        <div className={styles.heroLeft}>
          <div className={styles.heroEyebrow}>
            <IcoBrain className={styles.heroIcon} />
            <span>AI Study Cockpit</span>
          </div>
          <h1 className={styles.heroTitle}>Your Personal JEE Coach</h1>
          <p className={styles.heroSub}>
            Pick a chapter below — the AI finds the exact question you need most right now
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
          <h2 className={styles.sectionTitle}>Choose a Chapter to Practice</h2>
          <p className={styles.sectionSub}>
            Sorted weakest → strongest · Click a chapter to get your AI-recommended question
          </p>
        </div>
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
              const isSelected = selectedChapter === ch;
              const isLoading  = isSelected && recState === 'loading';

              return (
                <button
                  key={ch}
                  className={`${styles.chapterCard} ${isSelected ? styles.chapterCardSelected : ''} ${unlocked === 0 ? styles.chapterCardLocked : ''}`}
                  onClick={() => unlocked > 0 && !isLoading && handleGetRecommendation(ch)}
                  disabled={unlocked === 0 || (recState === 'loading' && !isSelected) || initNeeded}
                >
                  <div className={styles.chapterCardTop}>
                    <span className={styles.chapterCardName}>{ch}</span>
                    <span className={styles.chapterCardRight}>
                      {hasTrend && <span className={styles.hotDot} title="Frequently asked in JEE">🔥</span>}
                      {unlocked === 0
                        ? <IcoLock className={styles.chapterCardLockIcon} />
                        : <IcoUnlock className={styles.chapterCardLockIcon} style={{ color }} />}
                    </span>
                  </div>

                  <div className={styles.chapterCardBarTrack}>
                    <div
                      className={styles.chapterCardBarFill}
                      style={{ width: `${avgMastery}%`, background: color }}
                    />
                  </div>

                  <div className={styles.chapterCardBottom}>
                    <span className={styles.chapterCardMasteryPct} style={{ color }}>
                      {avgMastery}%
                    </span>
                    <span className={styles.chapterCardMasteryLabel} style={{ color }}>
                      {masteryLabel(avgMastery)}
                    </span>
                    <span className={styles.chapterCardTopicCount}>
                      {unlocked === 0 ? 'Locked' : `${unlocked} / ${topics.length} topics`}
                    </span>
                  </div>

                  <div className={styles.chapterCardAction}>
                    {unlocked === 0 ? (
                      <span className={styles.chapterCardActionText}>
                        <IcoLock className={styles.chapterCardActionIcon} /> Locked
                      </span>
                    ) : isLoading ? (
                      <span className={styles.chapterCardActionText}>
                        <span className={styles.spinnerSm} /> Finding question…
                      </span>
                    ) : isSelected ? (
                      <span className={styles.chapterCardActionText} style={{ color: 'var(--color-accent)' }}>
                        <IcoCheck className={styles.chapterCardActionIcon} /> Active
                      </span>
                    ) : (
                      <span className={styles.chapterCardActionText}>
                        <IcoZap className={styles.chapterCardActionIcon} /> Get Question
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {/* ── Recommendation section ── */}
      <section className={styles.section} id="recommendation">
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>
            {selectedChapter
              ? `Question from: ${selectedChapter}`
              : 'AI Recommendation'}
          </h2>
          {selectedChapter && (
            <button className={`${styles.btn} ${styles.btnGhost} ${styles.btnSm}`} onClick={handleChangeChapter} disabled={submitting}>
              Change Chapter
            </button>
          )}
        </div>

        {!selectedChapter ? (
          <div className={styles.recIdle}>
            <div className={styles.recIdleIcon}><IcoBrain /></div>
            <p className={styles.recIdleText}>
              Pick a chapter above and the AI will find the right question for you
            </p>
          </div>
        ) : (
          <div className={styles.recLayout}>
            {/* Thinking panel */}
            {thinkSteps.length > 0 && (
              <div className={styles.thinkPanel}>
                <button
                  className={styles.thinkToggle}
                  onClick={() => setThinkOpen((v) => !v)}
                >
                  <span className={styles.thinkToggleLeft}>
                    {isThinking ? <ThinkingDots /> : <IcoCheck className={styles.thinkDoneIcon} />}
                    <span className={styles.thinkToggleLabel}>
                      {isThinking ? 'Thinking…' : 'Thought process'}
                    </span>
                  </span>
                  <IcoChevron className={`${styles.thinkChevron} ${thinkOpen ? styles.thinkChevronOpen : ''}`} />
                </button>

                {thinkOpen && (
                  <div className={styles.thinkContent}>
                    {thinkSteps.map((step) => (
                      <div key={step.id} className={styles.thinkStep}>
                        <span className={styles.thinkStepDot} />
                        <span className={styles.thinkStepText}>{step.text}</span>
                      </div>
                    ))}
                    {isThinking && (
                      <div className={styles.thinkStep}>
                        <span className={styles.thinkStepDot} style={{ opacity: 0.4 }} />
                        <span className={styles.thinkCursor} />
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
                onToggle={toggleOption}
                onSubmit={handleSubmit}
                onNewRec={() => handleGetRecommendation(selectedChapter)}
                onChange={handleChangeChapter}
              />
            )}
          </div>
        )}
      </section>

      {/* ── Bottom grid ── */}
      <div className={styles.bottomGrid}>
        <PersonalityCard personality={personality} />
        <SessionHistoryCard history={history} />
        <TrendCard trends={trends} />
      </div>
    </div>
  );
};

// ─── QuestionCard ─────────────────────────────────────────────────────────────
const QuestionCard = ({
  qContent, question, recState,
  selected, intAnswer, setIntAnswer,
  elapsed, submitting, submitResult,
  onToggle, onSubmit, onNewRec, onChange,
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
            className={styles.intInput}
            value={intAnswer}
            onChange={(e) => setIntAnswer(e.target.value)}
            placeholder="Enter a number"
            disabled={recState === 'submitted'}
          />
          {recState === 'submitted' && qContent.correct_answer != null && (
            <p className={styles.correctHint}>
              ✓ Correct answer: <strong>{qContent.correct_answer}</strong>
            </p>
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

      {/* Result */}
      {recState === 'submitted' && submitResult && (
        <div className={`${styles.resultCard} ${submitResult.isCorrect ? styles.resultGood : styles.resultBad}`}>
          <div className={styles.resultHeader}>
            {submitResult.isCorrect
              ? <><IcoCheck className={styles.resultIcon} /><span>Correct! Well done 🎉</span></>
              : <><IcoXCircle className={styles.resultIcon} /><span>Not quite — check the answer above</span></>}
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
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={onNewRec}>
              <IcoRefresh className={styles.btnIcon} /> Get New Recommendation
            </button>
            <button className={`${styles.btn} ${styles.btnGhost}`} onClick={onChange}>
              Change Chapter
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
  const top = (trends?.topics || []).filter((t) => t.is_high_priority).slice(0, 6);
  return (
    <section className={styles.card}>
      <div className={styles.cardHead}>
        <IcoTrend className={styles.cardIcon} />
        <div>
          <h2 className={styles.cardTitle}>Hot Topics in JEE</h2>
          <p className={styles.cardSub}>
            {trends?.high_priority_count ?? 0} topics frequently asked this year
          </p>
        </div>
      </div>
      {top.length === 0 ? (
        <p className={styles.empty}>Trend data not yet available.</p>
      ) : (
        <div className={styles.trendList}>
          {top.map((t) => (
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

export default Recommender;
