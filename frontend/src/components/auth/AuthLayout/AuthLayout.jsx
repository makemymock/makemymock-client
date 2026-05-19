import React from 'react';
import { Link } from 'react-router-dom';
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

const Logo = () => (
  <Link to="/" className={styles.logo} aria-label="Make My Mock home">
    <svg
      className={styles.logoMark}
      viewBox="0 0 56 56"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect x="6" y="6" width="44" height="44" rx="10" fill="#0d9678" />
      <path
        d="M15 38V18l9 12 9-12v20"
        stroke="#fbfdf4"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="40.5" cy="36" r="3.5" fill="#fbfdf4" />
    </svg>
    <div className={styles.logoText}>
      <span className={styles.logoTitle}>MAKE MY MOCK</span>
      <span className={styles.logoTagline}>Mock. Analyse. Succeed</span>
    </div>
  </Link>
);

const AuthLayout = ({ headerCtaTo, headerCtaLabel, children }) => {
  return (
    <div className={styles.page}>
      <div className={styles.grid} aria-hidden="true" />
      <header className={styles.header}>
        <Logo />
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
  );
};

export default AuthLayout;
