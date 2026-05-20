import React from 'react';
import { Link } from 'react-router-dom';
import AWaves from '../../landing/AWaves/AWaves';
import useTheme from '../../../hooks/useTheme';
import styles from './AuthLayout.module.css';

const FEATURES = [
  {
    n: '01',
    title: 'PERSONALIZED PRACTICE',
    body: 'Practice questions based on your performance — so you focus on what actually needs work.',
  },
  {
    n: '02',
    title: 'CLEAR PERFORMANCE INSIGHTS',
    body: 'Know exactly where you stand with simple, easy-to-understand analysis after every test.',
  },
  {
    n: '03',
    title: 'STEP-BY-STEP SOLUTIONS',
    body: 'Understand every question with clear explanations, not just answers.',
  },
];

const AuthLayout = ({ headerCtaTo, headerCtaLabel, children }) => {
  const { theme } = useTheme();
  const logoSrc = theme === 'dark'
    ? '/logo_dark-removebg-preview.png'
    : '/logo_light-removebg-preview.png';

  return (
    <div className={styles.page}>
      <div className={styles.wavesLayer} aria-hidden="true">
        <AWaves />
      </div>

      <div className={styles.content}>
        <header className={styles.header}>
          <Link to="/" className={styles.brand} aria-label="Make My Mock home">
            <img src={logoSrc} alt="Make My Mock" className={styles.brandLogo} />
          </Link>
          {headerCtaTo && headerCtaLabel ? (
            <Link to={headerCtaTo} className={styles.headerCta}>
              {headerCtaLabel}
            </Link>
          ) : null}
        </header>

        <main className={styles.main}>
          <section className={styles.heroCard} aria-labelledby="hero-title">
            <div className={styles.tag}>
              <span className={styles.tagLine} />
              <span className={styles.tagText}>SMART TEST SERIES PLATFORM</span>
            </div>

            <h1 id="hero-title" className={styles.heroTitle}>
              <span className={styles.heroLine1}>PREPARE SMARTER.</span>
              <span className={styles.heroLine2}>IMPROVE CONSISTENTLY.</span>
            </h1>

            <p className={styles.heroSubtitle}>
              A test series designed to help you understand your mistakes, focus on your weak areas,
              and improve with every attempt.
            </p>

            <ul className={styles.features}>
              {FEATURES.map((f) => (
                <li key={f.n} className={styles.feature}>
                  <span className={styles.featureNum} aria-hidden="true">
                    {f.n}
                  </span>
                  <div className={styles.featureBody}>
                    <p className={styles.featureTitle}>{f.title}</p>
                    <p className={styles.featureText}>{f.body}</p>
                  </div>
                </li>
              ))}
            </ul>

            <div className={styles.heroFooter}>
              <span className={styles.heroFooterLine} aria-hidden="true" />
              <p className={styles.heroFooterText}>
                Built for students preparing for JEE, NEET, CUET &amp; Boards
              </p>
            </div>
          </section>

          <section className={styles.formCard}>{children}</section>
        </main>
      </div>
    </div>
  );
};

export default AuthLayout;
