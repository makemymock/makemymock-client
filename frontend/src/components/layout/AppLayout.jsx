import React, { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
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
const IconSwords = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M14 4l6 6-3 1-1 3-6-6z" /><path d="M10 4L4 10l3 1 1 3 6-6z" />
    <path d="M4 18l3 3M17 17l3 3" />
  </svg>
);
const IconChart = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </svg>
);
const IconLogout = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M10 17l5-5-5-5" /><path d="M15 12H4" /><path d="M21 4v16" />
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
const NAV_ITEMS = [
  { to: '/dashboard', label: 'Home',      Icon: IconHome,    end: true },
  { to: '/tests',     label: 'Tests',     Icon: IconTest },
  { to: '/solverx',   label: 'SolverX',   Icon: IconSpark },
  { to: '/battle',    label: 'Battle',    Icon: IconSwords },
  { to: '/analytics', label: 'Analytics', Icon: IconChart },
];

// Routes that own the whole viewport (no sidebar, no topbar, no bottom
// nav). Active test/battle screens hide chrome so a stray tap can't
// disrupt an attempt.
const FULLSCREEN_RE = [
  /^\/tests\/[^/]+$/,            // /tests/:sessionId (active test only)
  /^\/battle\/play$/,            // active 1-vs-1 battle
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

const SideNav = ({ onLogout }) => (
  <nav className={styles.sideNav} aria-label="Primary">
    <ul className={styles.sideNavList}>
      {NAV_ITEMS.map(({ to, label, Icon, end }) => (
        <li key={to}>
          <NavLink
            to={to}
            end={end}
            className={({ isActive }) =>
              `${styles.sideNavItem} ${isActive ? styles.sideNavItemActive : ''}`
            }
            title={label}
          >
            <Icon className={styles.sideNavIcon} />
            <span className={styles.sideNavLabel}>{label}</span>
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

const BottomNav = () => (
  <nav className={styles.bottomNav} aria-label="Primary">
    {NAV_ITEMS.map(({ to, label, Icon, end }) => (
      <NavLink
        key={to}
        to={to}
        end={end}
        className={({ isActive }) =>
          `${styles.bottomNavItem} ${isActive ? styles.bottomNavItemActive : ''}`
        }
      >
        <Icon className={styles.bottomNavIcon} />
        <span className={styles.bottomNavLabel}>{label}</span>
      </NavLink>
    ))}
  </nav>
);

const TopBar = ({ user, theme, onToggleTheme, onLogout }) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const isDark = theme === 'dark';
  const initials = (user?.username || '?').slice(0, 1).toUpperCase();
  const logoSrc = isDark
    ? '/logo_dark-removebg-preview.png'
    : '/logo_light-removebg-preview.png';

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

        <div className={styles.userArea}>
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
