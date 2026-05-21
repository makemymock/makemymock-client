import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import ThemeToggle from '../../common/ThemeToggle/ThemeToggle';
import useTheme from '../../../hooks/useTheme';
import { authService } from '../../../services/authService';
import styles from './ExamShell.module.css';

const ExamShell = ({ title, subtitle, eyebrow, sticky, children }) => {
  const { theme, toggleTheme } = useTheme();
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

  return (
    <div className={styles.page}>
      <div className={styles.gridBg} aria-hidden="true" />

      <header className={styles.header}>
        <Link to="/dashboard" className={styles.brand} aria-label="Make My Mock home">
          <img src={logoSrc} alt="Make My Mock" className={styles.brandLogo} />
        </Link>

        <div className={styles.headerCenter}>{sticky}</div>

        <div className={styles.headerActions}>
          <ThemeToggle theme={theme} onToggle={toggleTheme} />
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
