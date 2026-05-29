import { useNavigate } from 'react-router-dom';
import ThemeToggle from '../../common/ThemeToggle/ThemeToggle';
import useTheme from '../../../hooks/useTheme';
import QaCard from '../QaCard/QaCard';
import { tokenStorage } from '../../../utils/token';
import styles from './HeroSection.module.css';

// The two cards float free over the hero. Placement is owned by the
// HeroSection stylesheet (one class per card) so each card carries its own
// responsive rules instead of sharing a positioning sandbox — the previous
// wrapper sat on top of the login/signup buttons and ate their clicks.
const heroCards = [
  {
    id: 'function-qa',
    title: 'What is a function?',
    shortText: 'A function is a relation that assigns exactly one output to each valid input.',
    fullText:
      'A function maps every allowed input to exactly one output. If one input gives two different outputs, it is not a function. In school math, functions are written as f(x) and help describe patterns like straight lines, curves, and growth.',
    pinPosition: 'center',
  },
  {
    id: 'hydrocarbons-qa',
    title: 'What are hydrocarbons?',
    shortText: 'Hydrocarbons are compounds made only of carbon and hydrogen atoms.',
    fullText:
      'Hydrocarbons are organic molecules containing only carbon and hydrogen. They are grouped as alkanes, alkenes, alkynes, and aromatic compounds, and they form the core of many fuels and industrial chemicals used in daily life.',
    pinPosition: 'left',
  },
];

function HeroSection() {
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const isAuthenticated = tokenStorage.isAuthenticated();

  const goTo = (path) => (event) => {
    event.preventDefault();
    navigate(path);
  };

  return (
    <section className={styles.hero} id="home">
      <div className={`${styles.heroGlow} ${styles.heroGlowOne}`} aria-hidden="true" />
      <div className={`${styles.heroGlow} ${styles.heroGlowTwo}`} aria-hidden="true" />
      <div className={`${styles.heroGlow} ${styles.heroGlowThree}`} aria-hidden="true" />
      <div className={`${styles.heroGlow} ${styles.heroGlowFour}`} aria-hidden="true" />

      <header className={styles.topbar}>
        <a className={styles.brand} href="#home" aria-label="Make My Mock home">
          <img
            className={styles.brandLogo}
            src={theme === 'dark' ? '/logo_dark-removebg-preview.png' : '/logo_light-removebg-preview.png'}
            alt="Make My Mock"
          />
        </a>

        <nav className={styles.floatingNav} aria-label="Primary navigation">
          <a
            href="#insight"
            onClick={(e) => {
              e.preventDefault();
              document.getElementById('insight')?.scrollIntoView({ behavior: 'smooth' });
            }}
          >
            Insights
          </a>
          <a
            href="#fix-it"
            onClick={(e) => {
              e.preventDefault();
              document.getElementById('fix-it')?.scrollIntoView({ behavior: 'smooth' });
            }}
          >
            Features
          </a>
          <a
            href="#faq"
            onClick={(e) => {
              e.preventDefault();
              document.getElementById('faq')?.scrollIntoView({ behavior: 'smooth' });
            }}
          >
            FAQ
          </a>
        </nav>

        <div className={styles.topbarActions}>
          <ThemeToggle theme={theme} onToggle={toggleTheme} />
        </div>
      </header>

      <div className={styles.heroDecorations} aria-hidden="true">
        <img className={`${styles.heroDecor} ${styles.heroDecorAtom}`} src="/atom.png" alt="" />
        <img className={`${styles.heroDecor} ${styles.heroDecorGraph}`} src="/graph.png" alt="" />
        <img className={`${styles.heroDecor} ${styles.heroDecorCompound}`} src="/organic_compound.png" alt="" />
        <img className={`${styles.heroDecor} ${styles.heroDecorTubes}`} src="/chemical_tubes.png" alt="" />
        <span className={`${styles.heroSymbol} ${styles.heroSymbolPi}`}>π</span>
        <span className={`${styles.heroSymbol} ${styles.heroSymbolSigma}`}>Σ</span>
        <span className={`${styles.heroSymbol} ${styles.heroSymbolEmc}`}>E = mc²</span>
      </div>

      <div className={styles.heroCopy}>
        <h1>Mock. Analyse. Succeed.</h1>
        <p className={styles.heroDescription}>Personalized practice assistant for smart preparation</p>
        <div className={styles.heroBottomActions}>
          {isAuthenticated ? (
            <a className={`${styles.action} ${styles.actionPrimary}`} href="/dashboard" onClick={goTo('/dashboard')}>
              <span className={styles.actionLabel}>Open my dashboard</span>
            </a>
          ) : (
            <>
              <a className={`${styles.action} ${styles.actionPrimary}`} href="/login" onClick={goTo('/login')}>
                <span className={styles.actionLabel}>Login</span>
              </a>
              <a className={`${styles.action} ${styles.actionSecondary}`} href="/signup" onClick={goTo('/signup')}>
                <span className={styles.actionLabel}>Signup</span>
              </a>
            </>
          )}
        </div>
      </div>

      {heroCards.map((card, i) => (
        <QaCard
          key={card.id}
          card={card}
          pinPosition={card.pinPosition}
          className={i === 0 ? styles.heroQaCardOne : styles.heroQaCardTwo}
        />
      ))}
    </section>
  );
}

export default HeroSection;
