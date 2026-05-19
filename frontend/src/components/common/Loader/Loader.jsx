import React from 'react';
import styles from './Loader.module.css';

const Loader = ({ fullscreen = false, label = 'Loading…' }) => {
  if (fullscreen) {
    return (
      <div className={styles.fullscreen} role="status" aria-live="polite">
        <span className={styles.spinner} aria-hidden="true" />
        <span className={styles.srOnly}>{label}</span>
      </div>
    );
  }
  return (
    <div className={styles.inline} role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <span className={styles.srOnly}>{label}</span>
    </div>
  );
};

export default Loader;
