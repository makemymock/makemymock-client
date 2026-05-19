import React from 'react';
import styles from './Button.module.css';

const Button = ({
  type = 'button',
  variant = 'primary',
  fullWidth = true,
  loading = false,
  disabled = false,
  onClick,
  children,
  className = '',
  ...rest
}) => {
  const classes = [
    styles.button,
    styles[variant] || '',
    fullWidth ? styles.fullWidth : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <button
      type={type}
      className={classes}
      onClick={onClick}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className={styles.spinner} aria-hidden="true" /> : null}
      <span className={loading ? styles.labelMuted : styles.label}>{children}</span>
    </button>
  );
};

export default Button;
