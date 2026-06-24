import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Loader from '../../components/common/Loader/Loader';
import { patternLearningService } from '../../services/patternLearningService';
import { parseApiError } from '../../utils/validators';
import styles from './Learn.module.css';

// Entry screen: subject tabs → a progress strip → that subject's chapters as a
// responsive card grid. Picking a chapter opens its pattern roadmap.
// Rendered as the Patterns tab inside the Practice hub, which owns the page
// header — pass `embedded` there to suppress our own intro header.
const Learn = ({ embedded = false }) => {
  const navigate = useNavigate();
  const [subjects, setSubjects] = useState([]);
  const [active, setActive] = useState('');
  const [chapters, setChapters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [chaptersLoading, setChaptersLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await patternLearningService.listSubjects();
        if (!alive) return;
        setSubjects(data.items || []);
        setActive(data.items?.[0]?.subject || '');
      } catch (err) {
        if (alive) setError(parseApiError(err, 'Could not load the learning path.'));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!active) return undefined;
    let alive = true;
    (async () => {
      setChaptersLoading(true);
      try {
        const data = await patternLearningService.listChapters(active);
        if (alive) setChapters(data.items || []);
      } catch (err) {
        if (alive) setError(parseApiError(err, 'Could not load chapters.'));
      } finally {
        if (alive) setChaptersLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [active]);

  // Roll the active subject's chapters into headline numbers.
  const summary = useMemo(() => {
    const totalPatterns = chapters.reduce((s, c) => s + (c.pattern_count || 0), 0);
    const mastered = chapters.reduce((s, c) => s + (c.completed_patterns || 0), 0);
    const unlocked = chapters.filter((c) => c.unlocked).length;
    return { chapters: chapters.length, unlocked, totalPatterns, mastered };
  }, [chapters]);

  if (loading) return <Loader />;

  return (
    <div className={styles.page}>
      {!embedded && (
        <header className={styles.head}>
          <span className={styles.eyebrow}>Pattern Path</span>
          <h1 className={styles.title}>Learn JEE by its patterns</h1>
          <p className={styles.subtitle}>
            Every chapter is a path of the reasoning patterns mined from past
            papers. Clear a chapter in your mock tests to unlock its path, then
            work through each pattern one step at a time.
          </p>
        </header>
      )}

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.tabs} role="tablist">
        {subjects.map((s) => (
          <button
            key={s.subject}
            role="tab"
            aria-selected={s.subject === active}
            className={`${styles.tab} ${s.subject === active ? styles.tabActive : ''}`}
            onClick={() => setActive(s.subject)}
          >
            {s.display_name}
            <span className={styles.tabCount}>{s.chapter_count}</span>
          </button>
        ))}
      </div>

      {chaptersLoading && chapters.length === 0 ? (
        // Only a full loader on the very first load (nothing to show yet).
        <Loader />
      ) : (
        // On a tab switch we already have a layout — keep it and just dim it
        // while the new chapters fetch, so the page doesn't collapse to a
        // spinner and flash back.
        <div className={chaptersLoading ? styles.refreshing : ''}>
          {chapters.length > 0 && (
            <div className={styles.stats}>
              <Stat label="Chapters" value={summary.chapters} />
              <Stat label="Unlocked" value={summary.unlocked} accent />
              <Stat label="Patterns" value={summary.totalPatterns} />
              <Stat label="Mastered" value={summary.mastered} good />
            </div>
          )}

          <div className={styles.grid}>
            {chapters.map((c) => (
              <ChapterCard
                key={c.chapter}
                chapter={c}
                onOpen={() => navigate(`/learn/chapters/${encodeURIComponent(c.chapter)}`)}
              />
            ))}
            {chapters.length === 0 && (
              <p className={styles.empty}>No pattern paths in this subject yet.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const Stat = ({ label, value, accent, good }) => (
  <div className={styles.stat}>
    <span
      className={`${styles.statValue} ${accent ? styles.statAccent : ''} ${good ? styles.statGood : ''}`}
    >
      {value}
    </span>
    <span className={styles.statLabel}>{label}</span>
  </div>
);

const ChapterCard = ({ chapter, onOpen }) => {
  const {
    unlocked, gate_accuracy, gate_required, pattern_count, completed_patterns, display_name,
  } = chapter;
  const pct = pattern_count ? Math.round((completed_patterns / pattern_count) * 100) : 0;
  return (
    <button
      className={`${styles.card} ${unlocked ? '' : styles.cardLocked}`}
      onClick={onOpen}
      type="button"
    >
      <div className={styles.cardTop}>
        <span className={`${styles.badge} ${unlocked ? styles.badgeOpen : ''}`}>
          {pattern_count}
        </span>
        <span className={`${styles.status} ${unlocked ? styles.statusOpen : styles.statusLocked}`}>
          {unlocked ? 'Open' : 'Locked'}
        </span>
      </div>

      <span className={styles.cardName}>{display_name}</span>
      <span className={styles.cardMeta}>
        {pattern_count} pattern{pattern_count === 1 ? '' : 's'}
        {unlocked && completed_patterns > 0 && ` · ${completed_patterns} done`}
      </span>

      {unlocked ? (
        <div className={styles.progressWrap}>
          <div className={styles.progress}>
            <div className={styles.progressFill} style={{ width: `${pct}%` }} />
          </div>
          <span className={styles.pct}>{pct}%</span>
        </div>
      ) : (
        <div className={styles.gate}>
          Reach {gate_required}% in this chapter's mocks — you're at{' '}
          <strong>{gate_accuracy}%</strong>
        </div>
      )}
    </button>
  );
};

export default Learn;
