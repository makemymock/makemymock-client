import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import useTheme from '../../hooks/useTheme';
import ThemeToggle from '../../components/common/ThemeToggle/ThemeToggle';
import FAQSection from '../../components/landing/FAQSection/FAQSection';
import FooterSection from '../../components/landing/FooterSection/FooterSection';
import { tokenStorage } from '../../utils/token';
import styles from './landing.module.css';

// ── Feature cards data ────────────────────────────────────────────────────────
const features = [
  {
    id: 'adaptive',
    accent: 'primary',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2a5 5 0 1 0 0 10A5 5 0 0 0 12 2z" />
        <path d="M8 14s-4 1-4 5h16c0-4-4-5-4-5" />
        <path d="M9 9h.01M15 9h.01" />
      </svg>
    ),
    title: 'Adaptive Mock Tests',
    text: 'AI engine weights questions toward your weakest topics — every test is a precision-targeted training session.',
  },
  {
    id: 'battle',
    accent: 'secondary',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round">
        <polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5" />
        <line x1="13" y1="19" x2="19" y2="13" />
        <line x1="16" y1="16" x2="20" y2="20" />
        <line x1="19" y1="21" x2="21" y2="19" />
        <polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5" />
        <line x1="5" y1="14" x2="9" y2="18" />
        <line x1="7" y1="17" x2="4" y2="20" />
        <line x1="3" y1="19" x2="5" y2="21" />
      </svg>
    ),
    title: '1-vs-1 Battle Mode',
    text: 'Challenge students across India in real-time duels. Speed + accuracy = glory.',
  },
  {
    id: 'solverx',
    accent: 'tertiary',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="10" rx="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        <circle cx="12" cy="16" r="1" fill="currentColor" />
      </svg>
    ),
    title: 'SolverX AI Tutor',
    text: 'Stuck on a problem? Get step-by-step solutions streamed by an AI built for JEE/NEET.',
  },
  {
    id: 'potd',
    accent: 'warning',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round">
        <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" />
      </svg>
    ),
    title: 'POTD & Streaks',
    text: 'One fresh challenge every day. Build your streak and keep momentum alive.',
  },
  {
    id: 'contest',
    accent: 'secondary',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round">
        <path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4z" />
        <path d="M17 5h3v3a3 3 0 0 1-3 3M7 5H4v3a3 3 0 0 0 3 3" />
      </svg>
    ),
    title: 'Live Contests',
    text: 'Compete with thousands in timed competitions. Climb the leaderboard. Earn your rank.',
  },
  {
    id: 'analytics',
    accent: 'primary',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      </svg>
    ),
    title: 'Deep Analytics',
    text: 'See exactly which topics drag you down — down to the subtopic. Fix weaknesses before they cost marks.',
  },
];

// ── Stats strip ───────────────────────────────────────────────────────────────
const stats = [
  { value: '10,000+', label: 'Students' },
  { value: '500,000+', label: 'Questions attempted' },
  { value: '94%', label: 'Report improved accuracy' },
];

// ── Animated counter hook ─────────────────────────────────────────────────────
function useCountUp(target, duration = 1200, active = false) {
  const [display, setDisplay] = useState('0');
  useEffect(() => {
    if (!active) return;
    const num = parseInt(target.replace(/\D/g, ''), 10);
    const suffix = target.replace(/[\d,]/g, '');
    const steps = 40;
    const step = num / steps;
    let current = 0;
    let count = 0;
    const id = setInterval(() => {
      current += step;
      count++;
      if (count >= steps) {
        setDisplay(target);
        clearInterval(id);
      } else {
        setDisplay(Math.floor(current).toLocaleString() + suffix);
      }
    }, duration / steps);
    return () => clearInterval(id);
  }, [active, target, duration]);
  return display;
}

// ── Stat item with count-up ───────────────────────────────────────────────────
function StatItem({ value, label, active }) {
  const display = useCountUp(value, 1200, active);
  return (
    <div className={styles.statItem}>
      <span className={styles.statValue}>{display}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  );
}

// ── Main Landing component ────────────────────────────────────────────────────
export default function Landing() {
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const isAuthenticated = tokenStorage.isAuthenticated();
  const statsRef = useRef(null);
  const [statsVisible, setStatsVisible] = useState(false);

  // Trigger count-up when stats section enters viewport
  useEffect(() => {
    const el = statsRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setStatsVisible(true); },
      { threshold: 0.4 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const goTo = (path) => (e) => { e.preventDefault(); navigate(path); };
  const logoSrc = theme === 'dark'
    ? '/logo_dark-removebg-preview.png'
    : '/logo_light-removebg-preview.png';
  // Product screenshots ship in two captures so they match the active theme
  // — the dark grabs looked out of place once the page is in light mode.
  const shot = (name) => (theme === 'dark' ? `/${name}.png` : `/${name}_light.png`);

  return (
    <div className={styles.pageShell}>

      {/* ── Aurora background blobs ───────────────────────────────── */}
      <div className={`${styles.aurora} ${styles.aurora1}`} aria-hidden="true" />
      <div className={`${styles.aurora} ${styles.aurora2}`} aria-hidden="true" />
      <div className={`${styles.aurora} ${styles.aurora3}`} aria-hidden="true" />

      {/* ── Top nav ───────────────────────────────────────────────── */}
      <nav className={styles.topbar}>
        <div className={styles.topbarInner}>
          <a href="#home" className={styles.brand} aria-label="Make My Mock home">
            <img src={logoSrc} alt="Make My Mock" className={styles.brandLogo} />
          </a>

          <div className={styles.navLinks}>
            <a href="#features" onClick={(e) => { e.preventDefault(); document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' }); }}>Features</a>
            <a href="#solverx" onClick={(e) => { e.preventDefault(); document.getElementById('solverx')?.scrollIntoView({ behavior: 'smooth' }); }}>SolverX</a>
            <a href="#faq" onClick={(e) => { e.preventDefault(); document.getElementById('faq')?.scrollIntoView({ behavior: 'smooth' }); }}>FAQ</a>
          </div>

          <div className={styles.topbarRight}>
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
            <a
              href={isAuthenticated ? '/dashboard' : '/signup'}
              className={styles.ctaBtn}
              onClick={goTo(isAuthenticated ? '/dashboard' : '/signup')}
            >
              {isAuthenticated ? 'Dashboard →' : 'Start for Free →'}
            </a>
          </div>
        </div>
      </nav>

      {/* ── Hero ──────────────────────────────────────────────────── */}
      <section className={styles.hero} id="home">
        <div className={styles.heroCopy}>
          <p className={styles.heroEyebrow}>JEE · NEET · Competitive Exams</p>
          <h1 className={styles.heroH1}>
            Stop Studying<br />
            <span className={styles.heroGradText}>Blind.</span>
          </h1>
          <p className={styles.heroSub}>
            Make My Mock builds you a personalized mock test every time — harder on
            the topics you struggle with, lighter on what you've mastered.
          </p>
          <div className={styles.heroCtas}>
            <a
              href={isAuthenticated ? '/dashboard' : '/signup'}
              className={styles.ctaPrimary}
              onClick={goTo(isAuthenticated ? '/dashboard' : '/signup')}
            >
              {isAuthenticated ? 'Open Dashboard →' : 'Start for Free →'}
            </a>
            <a
              href="#features"
              className={styles.ctaSecondary}
              onClick={(e) => { e.preventDefault(); document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' }); }}
            >
              See How It Works
            </a>
          </div>
        </div>

        {/* Dashboard screenshot preview */}
        <div className={styles.heroVisual} aria-hidden="true">
          <div className={styles.heroScreenshot}>
            <img src={shot('Dashboard')} alt="MakeMyMock dashboard" className={styles.heroScreenshotImg} />
          </div>
        </div>
      </section>

      {/* ── Feature grid ──────────────────────────────────────────── */}
      <section className={styles.section} id="features">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Level Up Your Arsenal</h2>
          <p className={styles.sectionSub}>Tools designed for maximum engagement and retention.</p>
        </div>
        <div className={styles.featureGrid}>
          {features.map((f) => (
            <div key={f.id} className={`${styles.featureCard} ${styles[`featureCard_${f.accent}`]}`}>
              <div className={`${styles.featureIconWrap} ${styles[`featureIconWrap_${f.accent}`]}`}>
                {f.icon}
              </div>
              <h3 className={styles.featureTitle}>{f.title}</h3>
              <p className={styles.featureText}>{f.text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── SolverX section ───────────────────────────────────────── */}
      <section className={`${styles.section} ${styles.sectionNarrow}`} id="solverx">
        <div className={`${styles.showcaseCard} ${styles.showcaseCardCyan}`}>
          <div className={styles.showcaseText}>
            <div className={styles.liveChip}>
              <span className={styles.liveDot} />
              AI TUTOR ONLINE
            </div>
            <h2 className={styles.showcaseTitle}>
              Meet <span className={styles.accentCyan}>SolverX</span>
            </h2>
            <p className={styles.showcaseSub}>
              Don't just get the answer. Understand the logic. SolverX breaks
              down complex physics and maths problems step-by-step, streamed live.
            </p>
            <a href={isAuthenticated ? '/solverx' : '/signup'}
              className={`${styles.ctaSecondary} ${styles.ctaSecondaryInline}`}
              onClick={goTo(isAuthenticated ? '/solverx' : '/signup')}>
              Try SolverX Now
            </a>
          </div>
          <div className={styles.screenshotFrame}>
            <img src={shot('SolverX')} alt="SolverX AI Tutor interface" className={styles.screenshotFrameImg} />
          </div>
        </div>
      </section>

      {/* ── Battle section ────────────────────────────────────────── */}
      <section className={`${styles.section} ${styles.sectionNarrow}`}>
        <div className={`${styles.showcaseCard} ${styles.showcaseCardCyan} ${styles.showcaseCardReverse}`}>
          <div className={styles.screenshotFrame}>
            <img src={shot('Battle')} alt="1-vs-1 Battle Mode arena" className={styles.screenshotFrameImg} />
          </div>
          <div className={styles.showcaseText}>
            <h2 className={styles.showcaseTitle}>
              Arena: <span className={styles.accentCyan}>1-vs-1 Battle Mode</span>
            </h2>
            <p className={styles.showcaseSub}>
              Challenge students across India in real-time. Speed + Accuracy = Glory.
              Same questions, same timer. Speed bonuses reward fast correct answers.
            </p>
            <a href={isAuthenticated ? '/compete?tab=battle' : '/signup'}
              className={`${styles.ctaSecondary} ${styles.ctaSecondaryInline}`}
              onClick={goTo(isAuthenticated ? '/compete?tab=battle' : '/signup')}>
              Enter Arena
            </a>
          </div>
        </div>
      </section>

      {/* ── Analytics section ─────────────────────────────────────── */}
      <section className={`${styles.section} ${styles.sectionNarrow}`}>
        <div className={`${styles.showcaseCard} ${styles.showcaseCardPrimary}`}>
          <div className={styles.screenshotFrame}>
            <img src={shot('Analytics')} alt="Deep analytics dashboard" className={styles.screenshotFrameImg} />
          </div>
          <div className={styles.showcaseText}>
            <h2 className={styles.showcaseTitle}>
              Deep Analytics:{' '}
              <span className={styles.accentPrimary}>Know Your Nemesis</span>
            </h2>
            <p className={styles.showcaseSub}>
              Don't just see your score. See your gaps. Analytics that tell you
              exactly where to focus your next session — down to the subtopic.
            </p>
            <a href={isAuthenticated ? '/analytics' : '/signup'}
              className={`${styles.ctaPrimary} ${styles.ctaPrimaryInline}`}
              onClick={goTo(isAuthenticated ? '/analytics' : '/signup')}>
              View My Insights
            </a>
          </div>
        </div>
      </section>

      {/* ── Stats strip ───────────────────────────────────────────── */}
      <section className={styles.statsStrip} ref={statsRef}>
        <h2 className={styles.statsHeadline}>
          Join <span className={styles.accentPrimary}>10,000+</span> JEE/NEET Warriors
        </h2>
        <p className={styles.statsSub}>Already leveling up their preparation every day.</p>
        <div className={styles.statsRow}>
          {stats.map((s) => (
            <StatItem key={s.label} value={s.value} label={s.label} active={statsVisible} />
          ))}
        </div>
      </section>

      {/* ── FAQ ───────────────────────────────────────────────────── */}
      <FAQSection />

      {/* ── Final CTA ─────────────────────────────────────────────── */}
      <section className={styles.finalCta}>
        <div className={styles.finalCtaInner}>
          <h2 className={styles.finalCtaTitle}>Your rank is decided before exam day.</h2>
          <p className={styles.finalCtaSub}>Start building smarter tests today — it's free.</p>
          <a
            href={isAuthenticated ? '/dashboard' : '/signup'}
            className={styles.ctaPrimary}
            onClick={goTo(isAuthenticated ? '/dashboard' : '/signup')}
          >
            Create My First Mock →
          </a>
        </div>
        {/* Particle dots constellation */}
        <div className={styles.constellation} aria-hidden="true">
          {Array.from({ length: 30 }).map((_, i) => (
            <span key={i} className={styles.particle}
              style={{
                left: `${(i * 37 + i * i * 3) % 100}%`,
                top: `${(i * 53 + i * 7) % 100}%`,
                animationDelay: `${(i * 0.3) % 3}s`,
                width: `${2 + (i % 3)}px`,
                height: `${2 + (i % 3)}px`,
              }}
            />
          ))}
        </div>
      </section>

      {/* ── Footer ────────────────────────────────────────────────── */}
      <FooterSection />

    </div>
  );
}
