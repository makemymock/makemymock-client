import { useLocation } from 'react-router-dom';
import useTheme from '../../../hooks/useTheme';
import styles from './ThemeToggleFab.module.css';

// Routes where the floating theme-toggle should NOT render. The dashboard
// already shows its own toggle in the topbar, and the active test screen
// hides every chrome element so a stray tap can't disrupt an attempt.
const HIDDEN_EXACT = new Set([
  '/dashboard',
]);
const ACTIVE_TEST_RE = /^\/tests\/[^/]+$/;

const SunIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
       className={styles.icon}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
  </svg>
);

const MoonIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
       className={styles.icon}>
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
  </svg>
);

const ThemeToggleFab = () => {
  const location = useLocation();
  const path = location.pathname;
  const { theme, toggleTheme } = useTheme();

  if (HIDDEN_EXACT.has(path)) return null;
  if (ACTIVE_TEST_RE.test(path)) return null;

  const isDark = theme === 'dark';

  return (
    <button
      type="button"
      className={styles.fab}
      onClick={toggleTheme}
      aria-label={`Switch to ${isDark ? 'light' : 'dark'} mode`}
      aria-pressed={!isDark}
      title={`Switch to ${isDark ? 'light' : 'dark'} mode`}
    >
      {isDark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
};

export default ThemeToggleFab;
