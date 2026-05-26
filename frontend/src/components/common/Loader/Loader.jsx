import React from 'react';
import styles from './Loader.module.css';

/**
 * Branded loader — a brand-coloured spinner with the tagline
 * "Mock. Analyse. Succeed." cycling word-by-word underneath.
 *
 * Modes:
 *  - fullscreen — fixed overlay over the entire viewport (initial
 *    app boot, large submits)
 *  - cover      — absolute fill of the nearest positioned ancestor
 *    (loading state inside a card / modal body)
 *  - default    — block centered in its parent (used by every
 *    `{loading ? <Loader /> : null}` site already in the codebase)
 *
 * `compact` shrinks everything for tight slots.
 */
const Loader = ({
  fullscreen = false,
  cover = false,
  compact = false,
  label = 'Loading…',
}) => {
  const wrapClass = [
    fullscreen ? styles.fullscreen : cover ? styles.cover : styles.inline,
    compact ? styles.compact : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={wrapClass} role="status" aria-live="polite" aria-busy="true">
      <div className={styles.stack}>
        <span className={styles.spinner} aria-hidden="true" />
        <div className={styles.tagline} aria-hidden="true">
          <span>Mock.</span>
          <span>Analyse.</span>
          <span>Succeed.</span>
        </div>
      </div>
      <span className={styles.srOnly}>{label}</span>
    </div>
  );
};

export default Loader;
