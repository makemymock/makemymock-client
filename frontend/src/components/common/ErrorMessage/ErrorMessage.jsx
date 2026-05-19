import React from 'react';
import styles from './ErrorMessage.module.css';

const ErrorMessage = ({ message, className = '' }) => {
  if (!message) return null;
  return (
    <div className={`${styles.error} ${className}`} role="alert">
      <span className={styles.dot} aria-hidden="true" />
      <span className={styles.text}>{message}</span>
    </div>
  );
};

export default ErrorMessage;
