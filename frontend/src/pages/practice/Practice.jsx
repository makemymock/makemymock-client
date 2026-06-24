import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import TestsLaunch from '../tests/TestsLaunch';
import Learn from '../learn/Learn';
import styles from './practice.module.css';

// Practice hub — modelled on the Compete hub. One screen, two panes:
//   • Drill session — the personalised, full-screen mock test (what used
//     to live on its own at /tests).
//   • Patterns       — the pattern path mined from past papers (what used
//     to live at /learn).
// Pane state mirrors to ?section= so deep links and the legacy /learn
// redirect land on the right pane. We only ever touch our own key, so
// TestsLaunch's ?tab= (Mock / Browse / Notebook / History) and its browse
// filters ride along untouched.
const TABS = [
  { key: 'drill',    label: 'Drill session', hint: 'Personalised mock test' },
  { key: 'patterns', label: 'Patterns',      hint: 'Pattern path' },
];

const Practice = () => {
  const [params, setParams] = useSearchParams();
  const initial = params.get('section');
  const [section, setSection] = useState(
    TABS.find((t) => t.key === initial) ? initial : 'drill',
  );

  useEffect(() => {
    const current = params.get('section');
    if (current !== section) {
      const next = new URLSearchParams(params);
      next.set('section', section);
      setParams(next, { replace: true });
    }
  }, [section, params, setParams]);

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Practice</p>
        <h1 className={styles.pageTitle}>Drill the questions. Master the patterns.</h1>
        <p className={styles.pageSub}>
          Two ways to train for the same goal. Drills drop you into a
          full-screen, timed mock built around your weakest topics — the real
          exam, on demand. Patterns walk you through the reasoning mined from
          past papers, one chapter at a time. Sharpen your nerve in one,
          deepen your understanding in the other — that's how scores climb.
        </p>
      </header>

      <div role="tablist" aria-label="Practice view" className={styles.tabStrip}>
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={section === t.key}
            onClick={() => setSection(t.key)}
            className={`${styles.tabBtn} ${section === t.key ? styles.tabBtnOn : ''}`}
            title={t.hint}
          >
            <span className={styles.tabLabel}>{t.label}</span>
          </button>
        ))}
      </div>

      <div className={styles.tabBody}>
        {section === 'drill' ? <TestsLaunch embedded /> : null}
        {section === 'patterns' ? <Learn embedded /> : null}
      </div>
    </div>
  );
};

export default Practice;
