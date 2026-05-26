import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import useTheme from '../../../hooks/useTheme';
import { authService } from '../../../services/authService';
import styles from './ExamShell.module.css';

// The global AppLayout owns the sidebar + top bar on every protected
// route except the active test screen, which is fullscreen. For pages
// other than the active test (Result, Analytics, History, …) we render
// `chromeless` mode — same intro/title section but no internal header
// or page background — so it nests cleanly inside AppLayout's <main>.
const ExamShell = ({
  title,
  subtitle,
  eyebrow,
  sticky,
  children,
  chromeless = false,
}) => {
  const { theme } = useTheme();
  const navigate = useNavigate();

  const logoSrc = useMemo(
    () =>
      theme === 'dark'
        ? '/logo_dark-removebg-preview.png'
        : '/logo_light-removebg-preview.png',
    [theme],
  );

  const handleLogout = () => {
    authService.logout();
    navigate('/login', { replace: true });
  };

  // Chromeless: emit just the intro + children. The surrounding
  // AppLayout already provides the sidebar, top bar, and background.
  if (chromeless) {
    return (
      <div className={styles.chromeless}>
        {(eyebrow || title || subtitle) && (
          <section className={styles.intro}>
            {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
            {title ? <h1 className={styles.title}>{title}</h1> : null}
            {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
          </section>
        )}
        {children}
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.gridBg} aria-hidden="true" />

      <header className={styles.header}>
        <Link to="/dashboard" className={styles.brand} aria-label="Make My Mock home">
          <img src={logoSrc} alt="Make My Mock" className={styles.brandLogo} />
        </Link>

        <div className={styles.headerCenter}>{sticky}</div>

        <div className={styles.headerActions}>
          <button
            type="button"
            className={styles.signOut}
            onClick={handleLogout}
          >
            Sign out
          </button>
        </div>
      </header>

      <main className={styles.main}>
        {(eyebrow || title || subtitle) && (
          <section className={styles.intro}>
            {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
            {title ? <h1 className={styles.title}>{title}</h1> : null}
            {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
          </section>
        )}
        {children}
      </main>
    </div>
  );
};

export default ExamShell;
