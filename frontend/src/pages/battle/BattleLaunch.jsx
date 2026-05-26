import { useNavigate } from 'react-router-dom';
import ThemeToggle from '../../components/common/ThemeToggle/ThemeToggle';
import useTheme from '../../hooks/useTheme';
import styles from './battleLaunch.module.css';

const PERKS = [
  { title: '5 Questions', body: 'Speed-round style. Be sharp, be quick.' },
  { title: '15 seconds each', body: 'Lock your answer before the bar runs out.' },
  { title: 'Same questions', body: 'Both players see the exact same set — fair fight.' },
  { title: 'Speed bonus', body: 'Faster correct answers earn more points.' },
];

const BattleLaunch = () => {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div aria-hidden="true" className={styles.spacer} />
        <h1 className={styles.brand}>1 vs 1 — BATTLE ARENA</h1>
        <ThemeToggle theme={theme} onToggle={toggleTheme} />
      </header>

      <main className={styles.main}>
        <section className={styles.hero}>
          <p className={styles.eyebrow}>Live match. Real opponent.</p>
          <h2 className={styles.title}>
            Pick up the gauntlet.
            <br />
            <span className={styles.titleAccent}>Out-think. Out-pace.</span>
          </h2>
          <p className={styles.lede}>
            Press <strong>Play</strong> to enter the queue. The next student who hits
            Play within 15&nbsp;seconds is your opponent. Same questions, same timer
            — the winner is whoever scores the most.
          </p>

          <button
            type="button"
            className={styles.playButton}
            onClick={() => navigate('/battle/play')}
          >
            <span className={styles.playLabel}>PLAY</span>
            <span className={styles.playSub}>find me an opponent</span>
          </button>

          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => navigate('/battle/history')}
          >
            View past battles →
          </button>
        </section>

        <section className={styles.perks}>
          {PERKS.map((perk) => (
            <article key={perk.title} className={styles.perk}>
              <h3>{perk.title}</h3>
              <p>{perk.body}</p>
            </article>
          ))}
        </section>
      </main>
    </div>
  );
};

export default BattleLaunch;
