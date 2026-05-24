import { useEffect, useMemo, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { authService } from '../../services/authService';
import { profileService } from '../../services/profileService';
import { mockTestService } from '../../services/mockTestService';
import { battleService } from '../../services/battleService';
import { tokenStorage } from '../../utils/token';
import { parseApiError } from '../../utils/validators';
import useTheme from '../../hooks/useTheme';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import styles from './dashboard.module.css';

const TARGET_EXAM_LABEL = {
  jee_main: 'JEE Main',
  jee_advanced: 'JEE Advanced',
  boards: 'Boards',
  other: 'Other',
};

const MS_PER_DAY = 24 * 60 * 60 * 1000;

// ---------- icons (inline SVG, no deps) ----------
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
const IconHistory = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
  </svg>
);
const IconUser = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 5-6 8-6s6.5 2 8 6" />
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

// ---------- nav config (used by sidebar + bottom nav) ----------
const NAV_ITEMS = [
  { to: '/dashboard',       label: 'Home',      Icon: IconHome,    end: true },
  { to: '/tests',           label: 'Tests',     Icon: IconTest },
  { to: '/battle',          label: 'Battle',    Icon: IconSwords },
  { to: '/analytics',       label: 'Analytics', Icon: IconChart },
  { to: '/history',         label: 'History',   Icon: IconHistory },
];

// ---------- helpers ----------
const inLastDays = (iso, days) => {
  if (!iso) return false;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return false;
  return Date.now() - t <= days * MS_PER_DAY;
};

const formatRelative = (iso) => {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  if (diff < 60_000)        return 'just now';
  if (diff < 3_600_000)     return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000)    return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return new Date(iso).toLocaleDateString();
};

// ============================================================================
// Component
// ============================================================================

const Dashboard = () => {
  const navigate = useNavigate();

  const [user, setUser] = useState(() => tokenStorage.getUser());
  const [profile, setProfile] = useState(null);
  const [history, setHistory] = useState([]);
  const [overview, setOverview] = useState(null);
  const [battles, setBattles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Load everything we need in parallel. Each call is independently
  // tolerant of "no data yet" responses (analytics returns zeros, etc.).
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [me, myProfile, hist, ov, battleData] = await Promise.all([
          authService.me(),
          profileService.getMyProfile().catch((err) => {
            if (err?.response?.status === 404) return null;
            throw err;
          }),
          mockTestService.getHistory().catch(() => ({ items: [] })),
          mockTestService.getOverview().catch(() => null),
          battleService.fetchHistory().catch(() => ({ items: [] })),
        ]);
        if (cancelled) return;

        setUser(me);
        tokenStorage.setSession({ user: me });

        if (myProfile === null) {
          navigate('/profile/setup', { replace: true });
          return;
        }
        setProfile(myProfile);
        setHistory(hist.items || []);
        setOverview(ov);
        setBattles(battleData.items || []);
      } catch (err) {
        if (!cancelled) setError(parseApiError(err, 'Could not load your dashboard.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [navigate]);

  // Derived stats.
  const stats = useMemo(() => {
    const completed = history.filter((h) => h.status === 'completed');
    const pending = history.filter((h) => h.status === 'pending');
    const mocksThisWeek = completed.filter((h) => inLastDays(h.completed_at || h.created_at, 7)).length;
    const battlesThisMonth = battles.filter((b) => inLastDays(b.completed_at, 30)).length;
    const battleWins = battles.filter((b) => b.result === 'win').length;
    const battleLosses = battles.filter((b) => b.result === 'loss').length;
    const battleDraws = battles.filter((b) => b.result === 'draw').length;
    return {
      completed,
      pending,
      mocksThisWeek,
      mocksTotal: completed.length,
      battlesThisMonth,
      battlesTotal: battles.length,
      battleWins,
      battleLosses,
      battleDraws,
    };
  }, [history, battles]);

  const handleLogout = () => {
    authService.logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className={styles.shell}>
      <SideNav onLogout={handleLogout} useThemeHook={useTheme} />

      <div className={styles.contentArea}>
        <TopBar user={user} onLogout={handleLogout} />

        <main className={styles.main}>
          {loading ? <Loader /> : null}
          {error ? <ErrorMessage message={error} /> : null}

          {!loading && !error ? (
            <>
              <HeroCard user={user} profile={profile} />

              <section className={styles.statRow}>
                <StatCard
                  accent="teal"
                  label="Mocks this week"
                  sub="Mock tests"
                  value={stats.mocksThisWeek}
                  rightTop={`${stats.mocksTotal} total`}
                  Icon={IconTest}
                />
                <StatCard
                  accent="gold"
                  label="Battles this month"
                  sub="1v1 Quiz Challenge"
                  value={stats.battlesThisMonth}
                  rightTop={`${stats.battleWins}W · ${stats.battleLosses}L · ${stats.battleDraws}D`}
                  Icon={IconSwords}
                />
                <StatCard
                  accent="brown"
                  label="Overall accuracy"
                  sub={overview ? `${overview.total_questions} questions attempted` : '—'}
                  value={overview ? `${(overview.overall_accuracy_pct || 0).toFixed(0)}%` : '—'}
                  rightTop={overview ? `${overview.total_tests} tests` : ''}
                  Icon={IconChart}
                />
              </section>

              <section className={styles.grid}>
                <PerformanceCard overview={overview} pendingCount={stats.pending.length} />
                <SidePanel
                  pending={stats.pending}
                  battles={battles}
                  onResume={(sid) => navigate(`/tests/${sid}`)}
                  onNewTest={() => navigate('/tests')}
                  onBattle={() => navigate('/battle')}
                />
              </section>
            </>
          ) : null}
        </main>
      </div>

      <BottomNav onLogout={handleLogout} />
    </div>
  );
};

// ============================================================================
// Sub-components
// ============================================================================

const SideNav = ({ onLogout, useThemeHook }) => {
  const { theme } = useThemeHook();
  const logoSrc = theme === 'dark'
    ? '/logo_dark-removebg-preview.png'
    : '/logo_light-removebg-preview.png';
  return (
  <nav className={styles.sideNav} aria-label="Primary">
    <NavLink
      to="/dashboard"
      end
      className={styles.sideNavLogo}
      aria-label="Make My Mock — Dashboard"
    >
      <img src={logoSrc} alt="Make My Mock" className={styles.sideNavLogoImg} />
    </NavLink>
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
};

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

const TopBar = ({ user, onLogout }) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const { theme, toggleTheme } = useTheme();
  const initials = (user?.username || '?').slice(0, 1).toUpperCase();
  const isDark = theme === 'dark';
  const logoSrc = isDark
    ? '/logo_dark-removebg-preview.png'
    : '/logo_light-removebg-preview.png';

  return (
    <header className={styles.topBar}>
      <NavLink to="/dashboard" end className={styles.brand} aria-label="Make My Mock — Dashboard">
        <img src={logoSrc} alt="Make My Mock" className={styles.brandLogo} />
        <span className={styles.brandTag}>Mock. Analyse. Succeed.</span>
      </NavLink>
      <div className={styles.topBarRight}>
        <button
          type="button"
          className={styles.themeToggle}
          onClick={toggleTheme}
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
              <button type="button" className={styles.userMenuItem} onClick={onLogout}>
                <IconLogout className={styles.userMenuIcon} /> Sign out
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
};

const HeroCard = ({ user, profile }) => {
  const exam = profile?.target_exam ? TARGET_EXAM_LABEL[profile.target_exam] : null;
  const cls = profile?.class_grade
    ? (profile.class_grade === 'dropper' ? 'Dropper' : `Class ${profile.class_grade}`)
    : null;
  return (
    <section className={styles.hero}>
      <p className={styles.heroEyebrow}>Welcome back</p>
      <h1 className={styles.heroTitle}>Hi, {user?.username || 'there'} 👋</h1>
      <div className={styles.heroMeta}>
        {exam ? <span className={styles.metaTag}>🎯 {exam}</span> : null}
        {cls ? <span className={styles.metaTag}>🎓 {cls}</span> : null}
        <span className={styles.metaTag}>
          {user?.is_verified ? '✓ Verified' : '⏳ Pending verification'}
        </span>
      </div>
    </section>
  );
};

const StatCard = ({ accent, label, sub, value, rightTop, Icon }) => (
  <article className={`${styles.statCard} ${styles[`statCard_${accent}`] || ''}`}>
    <div className={styles.statCardTop}>
      <span className={styles.statCardIconWrap} aria-hidden="true">
        <Icon className={styles.statCardIcon} />
      </span>
      <span className={styles.statCardRightTop}>{rightTop}</span>
    </div>
    <p className={styles.statCardValue}>{value}</p>
    <p className={styles.statCardLabel}>{label}</p>
    <p className={styles.statCardSub}>{sub}</p>
  </article>
);

const PerformanceCard = ({ overview, pendingCount }) => {
  if (!overview || overview.total_tests === 0) {
    return (
      <section className={styles.perfCard}>
        <header className={styles.cardHeader}>
          <h2 className={styles.cardTitle}>Performance Overview</h2>
          <p className={styles.cardSubtitle}>Track your learning journey</p>
        </header>
        <div className={styles.emptyState}>
          <p>No mock tests completed yet.</p>
          <p className={styles.emptyStateHint}>
            Take your first test to start seeing your accuracy, weak topics, and progress here.
          </p>
        </div>
      </section>
    );
  }

  const accuracy = overview.overall_accuracy_pct || 0;
  const correct = Math.round((overview.total_score || 0));
  const totalQ = overview.total_questions || 0;

  return (
    <section className={styles.perfCard}>
      <header className={styles.cardHeader}>
        <div>
          <h2 className={styles.cardTitle}>Performance Overview</h2>
          <p className={styles.cardSubtitle}>Track your learning journey</p>
        </div>
        <NavLink to="/analytics" className={styles.cardLink}>
          View full report →
        </NavLink>
      </header>

      <div className={styles.perfTop}>
        <div className={styles.donutWrap}>
          <AccuracyDonut value={accuracy} />
          <div className={styles.donutLegend}>
            <p className={styles.donutBig}>{overview.total_tests}</p>
            <p className={styles.donutSmall}>Tests completed</p>
            <p className={styles.donutSub}>{totalQ} questions</p>
          </div>
        </div>

        <div className={styles.statsGrid}>
          <MiniStat label="Correct answers" value={`${correct}`} sub={`out of ${totalQ}`} />
          <MiniStat
            label="Pending tests"
            value={pendingCount}
            sub={pendingCount === 0 ? 'all caught up' : 'ready to resume'}
          />
          <MiniStat
            label="Question types covered"
            value={(overview.by_type || []).length}
            sub="distinct types"
          />
          <MiniStat
            label="Difficulty mix"
            value={(overview.by_difficulty || []).length}
            sub="difficulty bands"
          />
        </div>
      </div>

      <div className={styles.topicsRow}>
        <TopicList
          title="Focus areas"
          accent="warn"
          empty="Not enough data yet."
          topics={(overview.weakest_topics || []).slice(0, 3)}
        />
        <TopicList
          title="Your strengths"
          accent="ok"
          empty="Keep practicing — strengths emerge over time."
          topics={(overview.strongest_topics || []).slice(0, 3)}
        />
      </div>
    </section>
  );
};

const TopicList = ({ title, accent, topics, empty }) => (
  <div className={`${styles.topicList} ${styles[`topicList_${accent}`] || ''}`}>
    <p className={styles.topicListTitle}>{title}</p>
    {topics.length === 0 ? (
      <p className={styles.emptyHint}>{empty}</p>
    ) : (
      <ul>
        {topics.map((t) => (
          <li key={t.topic_id} className={styles.topicItem}>
            <span className={styles.topicName}>{t.topic_name}</span>
            <span className={styles.topicMeta}>
              {Math.round(t.accuracy_pct)}% · {t.attempts} attempt{t.attempts === 1 ? '' : 's'}
            </span>
          </li>
        ))}
      </ul>
    )}
  </div>
);

const MiniStat = ({ label, value, sub }) => (
  <div className={styles.miniStat}>
    <p className={styles.miniStatValue}>{value}</p>
    <p className={styles.miniStatLabel}>{label}</p>
    {sub ? <p className={styles.miniStatSub}>{sub}</p> : null}
  </div>
);

// SVG donut for accuracy. value is a 0-100 percentage.
const AccuracyDonut = ({ value }) => {
  const pct = Math.max(0, Math.min(100, value));
  const r = 42;
  const c = 2 * Math.PI * r;
  const offset = c - (pct / 100) * c;
  return (
    <svg viewBox="0 0 100 100" className={styles.donut} role="img"
         aria-label={`Accuracy: ${pct.toFixed(0)} percent`}>
      <circle cx="50" cy="50" r={r} className={styles.donutTrack} />
      <circle
        cx="50" cy="50" r={r}
        className={styles.donutFill}
        strokeDasharray={c}
        strokeDashoffset={offset}
        transform="rotate(-90 50 50)"
      />
      <text x="50" y="48" textAnchor="middle" className={styles.donutPct}>
        {pct.toFixed(0)}%
      </text>
      <text x="50" y="62" textAnchor="middle" className={styles.donutCaption}>
        accuracy
      </text>
    </svg>
  );
};

const SidePanel = ({ pending, battles, onResume, onNewTest, onBattle }) => (
  <aside className={styles.sidePanel}>
    <section className={styles.sidePanelCard}>
      <header className={styles.cardHeader}>
        <h3 className={styles.cardTitle}>Pending tests</h3>
        <span className={styles.pill}>
          <span className={styles.pillDot} aria-hidden="true" /> resume
        </span>
      </header>
      {pending.length === 0 ? (
        <div className={styles.sidePanelEmpty}>
          <p>No tests waiting on you.</p>
          <button type="button" className={styles.primaryBtn} onClick={onNewTest}>
            Start a new test
          </button>
        </div>
      ) : (
        <ul className={styles.pendingList}>
          {pending.slice(0, 4).map((s) => (
            <li key={s.session_id} className={styles.pendingItem}>
              <div className={styles.pendingMeta}>
                <p className={styles.pendingTitle}>
                  Mock #{s.session_id} · {s.total_questions} Q
                </p>
                <p className={styles.pendingDate}>
                  Started {formatRelative(s.created_at)}
                </p>
              </div>
              <button
                type="button"
                className={styles.pendingResumeBtn}
                onClick={() => onResume(s.session_id)}
              >
                Resume
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>

    <section className={styles.sidePanelCard}>
      <header className={styles.cardHeader}>
        <h3 className={styles.cardTitle}>Recent battles</h3>
        <NavLink to="/battle/history" className={styles.cardLink}>All →</NavLink>
      </header>
      {battles.length === 0 ? (
        <div className={styles.sidePanelEmpty}>
          <p>No battles yet.</p>
          <button type="button" className={styles.secondaryBtn} onClick={onBattle}>
            Enter the arena
          </button>
        </div>
      ) : (
        <ul className={styles.battlesList}>
          {battles.slice(0, 4).map((b) => (
            <li
              key={b.battle_id}
              className={`${styles.battleItem} ${styles[`battle_${b.result}`] || ''}`}
            >
              <span className={styles.battleResult}>{b.result.toUpperCase()}</span>
              <div className={styles.battleMeta}>
                <p className={styles.battleOpp}>vs {b.opponent.username}</p>
                <p className={styles.battleDate}>{formatRelative(b.completed_at)}</p>
              </div>
              <span className={styles.battleScore}>
                {b.you.score} – {b.opponent.score}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  </aside>
);

export default Dashboard;
