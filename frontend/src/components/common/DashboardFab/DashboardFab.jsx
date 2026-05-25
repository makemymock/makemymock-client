import { useLocation, useNavigate } from 'react-router-dom';
import { tokenStorage } from '../../../utils/token';
import styles from './DashboardFab.module.css';

// Routes where the floating "Dashboard" button must NOT render:
// - public/auth surfaces where the user isn't logged in
// - the dashboard itself (you're already there)
// - flows that require the user to stay on-page (active test, active
//   battle, profile setup before first dashboard access)
const HIDDEN_EXACT = new Set([
  '/',
  '/login',
  '/signup',
  '/dashboard',
  '/profile/setup',
  '/battle/play',
]);

// /tests/<sessionId> is the active test screen — hide there so a stray
// tap can't yank a student out of their attempt. /tests/<id>/result is
// fine to leave visible.
const ACTIVE_TEST_RE = /^\/tests\/[^/]+$/;

const HomeIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
       className={styles.icon}>
    <path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" />
  </svg>
);

const DashboardFab = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const path = location.pathname;

  if (!tokenStorage.isAuthenticated()) return null;
  if (HIDDEN_EXACT.has(path)) return null;
  if (ACTIVE_TEST_RE.test(path)) return null;

  return (
    <button
      type="button"
      className={styles.fab}
      onClick={() => navigate('/dashboard')}
      aria-label="Go to dashboard"
      title="Go to dashboard"
    >
      <HomeIcon />
      <span className={styles.label}>Dashboard</span>
    </button>
  );
};

export default DashboardFab;
