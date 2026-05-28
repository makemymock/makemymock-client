import { useEffect, useMemo, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { authService } from '../../services/authService';
import { profileService } from '../../services/profileService';
import { mockTestService } from '../../services/mockTestService';
import { battleService } from '../../services/battleService';
import { potdService } from '../../services/potdService';
import { tokenStorage } from '../../utils/token';
import { parseApiError } from '../../utils/validators';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import Heatmap from '../../components/common/Heatmap/Heatmap';
import ConfidenceTrophy from '../../components/common/ConfidenceTrophy/ConfidenceTrophy';
import PotdModal from '../../components/dashboard/PotdModal/PotdModal';
import Tour from '../../components/common/Tour/Tour';
import { useTour } from '../../hooks/useTour';
import { dashboardTourSteps } from '../../components/tours/dashboardSteps';
import styles from './dashboard.module.css';

const TARGET_EXAM_LABEL = {
  jee_main: 'JEE Main',
  jee_advanced: 'JEE Advanced',
  boards: 'Boards',
  other: 'Other',
};

const MS_PER_DAY = 24 * 60 * 60 * 1000;

// ---------- icons used by stat cards (the only icons left on this page).
// Nav/theme/logout icons moved to the global AppLayout component. ----------
const IconTest = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M7 3h10l3 4v14H4V7z" /><path d="M9 12h6M9 16h6M9 8h3" />
  </svg>
);
// Crossed swords — Lucide "swords" glyph. Two blades pointing
// up-right (from the bottom-left hilt) and up-left (from the
// bottom-right hilt), crossing in the middle.
const IconSwords = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5" />
    <line x1="13" y1="19" x2="19" y2="13" />
    <line x1="16" y1="16" x2="20" y2="20" />
    <line x1="19" y1="21" x2="21" y2="19" />
    <polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5" />
    <line x1="5" y1="14" x2="9" y2="18" />
    <line x1="7" y1="17" x2="4" y2="20" />
    <line x1="3" y1="19" x2="5" y2="21" />
  </svg>
);
const IconChart = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </svg>
);

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
  const tour = useTour('dashboard', dashboardTourSteps);

  const [user, setUser] = useState(() => tokenStorage.getUser());
  const [profile, setProfile] = useState(null);
  const [history, setHistory] = useState([]);
  const [overview, setOverview] = useState(null);
  const [battles, setBattles] = useState([]);
  const [heatmap, setHeatmap] = useState(null);
  const [confidence, setConfidence] = useState(null);
  const [notebookCount, setNotebookCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [potdOpen, setPotdOpen] = useState(false);

  // Load everything we need in parallel. Each call is independently
  // tolerant of "no data yet" responses (analytics returns zeros, etc.).
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [me, myProfile, hist, ov, battleData, hm, conf, nb] = await Promise.all([
          authService.me(),
          profileService.getMyProfile().catch((err) => {
            if (err?.response?.status === 404) return null;
            throw err;
          }),
          mockTestService.getHistory().catch(() => ({ items: [] })),
          mockTestService.getOverview().catch(() => null),
          battleService.fetchHistory().catch(() => ({ items: [] })),
          mockTestService.getActivityHeatmap().catch(() => null),
          mockTestService.getConfidence().catch(() => null),
          mockTestService.getNotebookCount().catch(() => ({ count: 0 })),
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
        setHeatmap(hm);
        setConfidence(conf);
        setNotebookCount(nb?.count || 0);
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

  return (
    <>
      {loading ? <Loader /> : null}
      {error ? <ErrorMessage message={error} /> : null}

      {!loading && !error ? (
        <>
          {/* Welcome + gamified trophy share one row on wide screens so
              two light cards don't each eat a full-width band. */}
          {confidence ? (
            <section className={styles.topRow}>
              <HeroCard user={user} profile={profile} />
              <ConfidenceTrophy data={confidence} dataTour="dashboard.confidence" />
            </section>
          ) : (
            <HeroCard user={user} profile={profile} />
          )}

          <div className={styles.quickRow}>
            <PotdBanner onOpen={() => setPotdOpen(true)} />
            <NotebookCard
              count={notebookCount}
              onClick={() => navigate('/tests?tab=notebook')}
              dataTour="dashboard.notebook"
            />
          </div>

          {/* Three compact stat cards, always 3-across on desktop. */}
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

          {/* Main two-column body: the big performance card on the left, a
              dense side column (heatmap + pending + battles) on the right. */}
          <section className={styles.grid}>
            <PerformanceCard
              overview={overview}
              pendingCount={stats.pending.length}
              dataTour="dashboard.performance"
            />
            <SidePanel
              heatmap={heatmap}
              pending={stats.pending}
              battles={battles}
              onResume={(sid) => navigate(`/tests/${sid}`)}
              onNewTest={() => navigate('/tests')}
              onBattle={() => navigate('/battle')}
              dataTour="dashboard.side-panel"
            />
          </section>
        </>
      ) : null}

      <PotdModal
        open={potdOpen}
        onClose={() => setPotdOpen(false)}
      />

      <Tour {...tour} open={tour.open && !loading && !error} />
    </>
  );
};

// ============================================================================
// Sub-components — page content only. The global AppLayout owns the
// sidebar, top bar, and bottom nav; nothing in this file renders chrome.
// ============================================================================

// ---- Problem of the Day banner ----
const PotdBanner = ({ onOpen }) => {
  // Fetch the streak so the card can advertise momentum directly.
  // The backend owns the streak math — this is just a read.
  const [streak, setStreak] = useState(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await potdService.getStreak();
        if (!cancelled) setStreak(s);
      } catch {
        /* non-fatal — the banner still works without the chip */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const current = streak?.current ?? 0;
  return (
    <button
      type="button"
      className={styles.potdBanner}
      data-tour="dashboard.potd"
      onClick={onOpen}
    >
      <span className={styles.potdLeft}>
        <span className={styles.potdEmoji} aria-hidden="true">⚡</span>
        <span className={styles.potdText}>
          <span className={styles.potdEyebrow}>Daily Challenge</span>
          <span className={styles.potdTitle}>Problem of the Day</span>
          <span className={styles.potdSub}>
            {current > 0
              ? `🔥 ${current}-day streak. Keep it going.`
              : 'One question, picked to attack your weakest topic.'}
          </span>
        </span>
      </span>
      {/* Visual cue only — the whole card is the click target. */}
      <span className={styles.potdBtn} aria-hidden="true">
        {current > 0 ? 'Continue streak' : 'Start now'}
        <span className={styles.potdBtnArrow}>→</span>
      </span>
    </button>
  );
};

// ---- Notebook quick-access (revise-later) ----
const NotebookCard = ({ count, onClick, dataTour }) => (
  <button type="button" className={styles.notebookCard} onClick={onClick} data-tour={dataTour}>
    <span className={styles.notebookIcon} aria-hidden="true">🔖</span>
    <span className={styles.notebookMeta}>
      <span className={styles.notebookTitle}>Notebook</span>
      <span className={styles.notebookSub}>
        {count > 0
          ? `${count} question${count === 1 ? '' : 's'} saved to revise`
          : 'Save questions to revise them later'}
      </span>
    </span>
    <span className={styles.notebookArrow} aria-hidden="true">→</span>
  </button>
);

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
    <span className={styles.statCardIconWrap} aria-hidden="true">
      <Icon className={styles.statCardIcon} />
    </span>
    <div className={styles.statCardBody}>
      <p className={styles.statCardValue}>{value}</p>
      <p className={styles.statCardLabel}>{label}</p>
      <p className={styles.statCardSub}>{sub}</p>
    </div>
    {rightTop ? <span className={styles.statCardRightTop}>{rightTop}</span> : null}
  </article>
);

const PerformanceCard = ({ overview, pendingCount, dataTour }) => {
  if (!overview || overview.total_tests === 0) {
    return (
      <section className={styles.perfCard} data-tour={dataTour}>
        <header className={styles.cardHeader}>
          <h2 className={styles.cardTitle}>Performance Overview</h2>
          <p className={styles.cardSubtitle}>Track your learning journey</p>
        </header>
        <div className={styles.emptyState} data-tour="dashboard.focus-areas">
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
    <section className={styles.perfCard} data-tour={dataTour}>
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
          dataTour="dashboard.focus-areas"
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

const TopicList = ({ title, accent, topics, empty, dataTour }) => (
  <div
    className={`${styles.topicList} ${styles[`topicList_${accent}`] || ''}`}
    data-tour={dataTour}
  >
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

const SidePanel = ({ heatmap, pending, battles, onResume, onNewTest, onBattle, dataTour }) => (
  <aside className={styles.sidePanel} data-tour={dataTour}>
    <Heatmap
      days={heatmap?.days || []}
      maxCount={heatmap?.max_count || 0}
      defaultRange="month"
    />

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
