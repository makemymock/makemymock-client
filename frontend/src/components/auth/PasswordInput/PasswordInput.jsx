import React, { useState } from 'react';
import InputField from '../../common/InputField/InputField';
import styles from './PasswordInput.module.css';

const EyeIcon = ({ open }) => (
  <svg
    width="20"
    height="20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {open ? (
      <>
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ) : (
      <>
        <path d="M17.94 17.94A10.94 10.94 0 0 1 12 19c-6.5 0-10-7-10-7a18.4 18.4 0 0 1 5.06-5.94" />
        <path d="M9.9 5.08A10.94 10.94 0 0 1 12 5c6.5 0 10 7 10 7a18.4 18.4 0 0 1-2.16 3.19" />
        <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
        <line x1="2" y1="2" x2="22" y2="22" />
      </>
    )}
  </svg>
);

const PasswordInput = ({
  label = 'Password',
  name = 'password',
  value,
  onChange,
  onBlur,
  placeholder = 'Enter your password',
  error,
  autoComplete = 'current-password',
  ...rest
}) => {
  const [visible, setVisible] = useState(false);

  const toggle = () => setVisible((v) => !v);

  return (
    <InputField
      label={label}
      type={visible ? 'text' : 'password'}
      name={name}
      value={value}
      onChange={onChange}
      onBlur={onBlur}
      placeholder={placeholder}
      error={error}
      autoComplete={autoComplete}
      rightAdornment={
        <button
          type="button"
          onClick={toggle}
          className={styles.toggle}
          aria-label={visible ? 'Hide password' : 'Show password'}
          aria-pressed={visible}
          tabIndex={0}
        >
          <EyeIcon open={visible} />
        </button>
      }
      {...rest}
    />
  );
};

export default PasswordInput;
