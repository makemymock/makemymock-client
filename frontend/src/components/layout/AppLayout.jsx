import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import useTheme from '../../hooks/useTheme';
import { authService } from '../../services/authService';
import { tokenStorage } from '../../utils/token';
import styles from './AppLayout.module.css';

// ---------- icons (inline SVG, no dependencies) ----------
const IconHome = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" />
  </svg>
);
const IconTest = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M7 3h10l3 4v14H4V7z" /><path d="M9 12h6M9 16h6M9 8h3" />
  </svg>
);
const IconSpark = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
    <circle cx="12" cy="12" r="3.5" />
  </svg>
);
// Trophy — used for the "Compete" nav item. Replaces the older crossed-
// swords glyph because Compete now bundles Battle + Contest + Leaderboard
// and the trophy reads better as the parent metaphor.
const IconCompete = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M8 21h8" />
    <path d="M12 17v4" />
    <path d="M7 4h10v5a5 5 0 0 1-10 0V4z" />
    <path d="M17 5h3v3a3 3 0 0 1-3 3" />
    <path d="M7 5H4v3a3 3 0 0 0 3 3" />
  </svg>
);
const IconChart = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </svg>
);
// Graduation cap — the "Learn" (Pattern Path) nav item.
const IconLearn = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M22 10L12 5 2 10l10 5 10-5z" />
    <path d="M6 12v5c0 1 2.7 2.5 6 2.5s6-1.5 6-2.5v-5" />
  </svg>
);
const IconLogout = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M10 17l5-5-5-5" /><path d="M15 12H4" /><path d="M21 4v16" />
  </svg>
);
const IconUser = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
  </svg>
);
const IconSun = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41
             M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
  </svg>
);
const IconMoon = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
  </svg>
);
// ---------- five-item navigation ----------
// `match` (optional) lets a nav item claim the active state on routes
// other than its own `to`. Compete owns everything under /compete,
// /contest, and the legacy /battle paths — without this NavLink would
// show no active item on the Lobby / Result pages even though they
// belong to the Compete feature.
const NAV_ITEMS = [
  { to: '/dashboard', label: 'Home',      Icon: IconHome,    end: true, tour: 'nav.dashboard' },
  { to: '/tests',     label: 'Practice',  Icon: IconTest,    tour: 'nav.practice',
    match: (p) => p.startsWith('/tests') },
  { to: '/solverx',   label: 'SolverX',   Icon: IconSpark,   tour: 'nav.solverx' },
  { to: '/learn',     label: 'Patterns',  Icon: IconLearn,   tour: 'nav.learn',
    match: (p) => p.startsWith('/learn') },
  { to: '/compete',   label: 'Compete',   Icon: IconCompete, tour: 'nav.compete',
    match: (p) => p.startsWith('/compete')
               || p.startsWith('/contest')
               || p.startsWith('/battle') },
  { to: '/analytics', label: 'Analytics', Icon: IconChart,   tour: 'nav.analytics',
    match: (p) => p.startsWith('/analytics') },
];

// Routes that own the whole viewport (no sidebar, no topbar, no bottom
// nav). Active test / battle / contest screens hide chrome so a stray
// tap can't disrupt an attempt.
const FULLSCREEN_RE = [
  /^\/tests\/[^/]+$/,            // /tests/:sessionId (active test only)
  /^\/battle\/play$/,            // active 1-vs-1 battle
  /^\/contest\/[^/]+\/play$/,    // active contest run
];

// Routes that keep the global sidebar + top bar, but render edge-to-edge
// (no `max-width` clamp, no padding). Chat-style surfaces like SolverX
// look best when they fill the available real estate.
const FULLBLEED_RE = [
  /^\/solverx$/,
];

const AppLayout = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();

  const fullscreen = FULLSCREEN_RE.some((re) => re.test(location.pathname));
  if (fullscreen) return <Outlet />;

  const fullBleed = FULLBLEED_RE.some((re) => re.test(location.pathname));

  const handleLogout = () => {
    authService.logout();
    navigate('/login', { replace: true });
  };

  const user = tokenStorage.getUser();

  return (
    <div className={styles.shell}>
      {/* Quiet line-grid backdrop */}
      <div className={styles.gridBg} aria-hidden="true" />
      <SideNav onLogout={handleLogout} />

      <div className={styles.contentArea}>
        <TopBar
          user={user}
          theme={theme}
          onToggleTheme={toggleTheme}
          onLogout={handleLogout}
        />
        <main className={`${styles.main} ${fullBleed ? styles.mainFullBleed : ''}`}>
          <Outlet />
        </main>
      </div>

      <BottomNav />
    </div>
  );
};

// ============================================================================
// Sub-components
// ============================================================================

// NavLink's built-in `isActive` only matches the item's own `to`. For
// items with a `match` predicate (Compete owns /contest + /battle too)
// we fall back to the current pathname so the active style sticks
// across the whole feature area.
const isItemActive = (item, builtIn, pathname) =>
  item.match ? item.match(pathname) : builtIn;

const SideNav = ({ onLogout }) => {
  const { pathname } = useLocation();
  return (
    <nav className={styles.sideNav} aria-label="Primary">
      <ul className={styles.sideNavList}>
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              data-tour={item.tour}
              className={({ isActive }) => {
                const active = isItemActive(item, isActive, pathname);
                return `${styles.sideNavItem} ${active ? styles.sideNavItemActive : ''}`;
              }}
              title={item.label}
            >
              <item.Icon className={styles.sideNavIcon} />
              <span className={styles.sideNavLabel}>{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className={styles.sideNavItem}
        onClick={onLogout}
        title="Sign out"
      >
        <IconLogout className={styles.sideNavIcon} />
        <span className={styles.sideNavLabel}>Sign out</span>
      </button>
    </nav>
  );
};

const BottomNav = () => {
  const { pathname } = useLocation();
  return (
    <nav className={styles.bottomNav} aria-label="Primary">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          data-tour={item.tour}
          className={({ isActive }) => {
            const active = isItemActive(item, isActive, pathname);
            return `${styles.bottomNavItem} ${active ? styles.bottomNavItemActive : ''}`;
          }}
        >
          <item.Icon className={styles.bottomNavIcon} />
          <span className={styles.bottomNavLabel}>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
};

const TopBar = ({ user, theme, onToggleTheme, onLogout }) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const userAreaRef = useRef(null);
  const isDark = theme === 'dark';
  const initials = (user?.username || '?').slice(0, 1).toUpperCase();
  const logoSrc = isDark
    ? '/logo_dark-removebg-preview.png'
    : '/logo_light-removebg-preview.png';

  // Close the profile menu on any click outside it or on Escape.
  useEffect(() => {
    if (!menuOpen) return undefined;
    const onPointerDown = (e) => {
      if (userAreaRef.current && !userAreaRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('touchstart', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('touchstart', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  return (
    <header className={styles.topBar}>
      <NavLink
        to="/dashboard"
        end
        className={styles.brand}
        aria-label="Make My Mock — Dashboard"
      >
        <img src={logoSrc} alt="Make My Mock" className={styles.brandLogo} />
        <span className={styles.brandTag}>Mock. Analyse. Succeed.</span>
      </NavLink>

      <div className={styles.topBarRight}>
        <button
          type="button"
          className={styles.themeToggle}
          onClick={onToggleTheme}
          aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {isDark ? <IconSun className={styles.themeIcon} />
                  : <IconMoon className={styles.themeIcon} />}
        </button>

        <div className={styles.userArea} ref={userAreaRef}>
          <button
            type="button"
            className={styles.userChip}
            onClick={() => setMenuOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            <span className={styles.avatar}>{initials}</span>
            <span className={styles.userText}>
              <span className={styles.userName}>{user?.username || 'You'}</span>
              <span className={styles.userEmail}>{user?.email}</span>
            </span>
          </button>
          {menuOpen ? (
            <div className={styles.userMenu} role="menu">
              <Link
                to="/profile"
                className={`${styles.userMenuItem} ${styles.userMenuItemNeutral}`}
                onClick={() => setMenuOpen(false)}
                role="menuitem"
              >
                <IconUser className={styles.userMenuIcon} /> Profile
              </Link>
              <button
                type="button"
                className={styles.userMenuItem}
                onClick={onLogout}
              >
                <IconLogout className={styles.userMenuIcon} /> Sign out
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
};

export default AppLayout;
