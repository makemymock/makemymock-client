import React, { useId } from 'react';
import styles from './InputField.module.css';

const InputField = ({
  label,
  type = 'text',
  name,
  value,
  onChange,
  onBlur,
  placeholder,
  error,
  autoComplete,
  inputMode,
  disabled,
  rightAdornment,
  className = '',
  ...rest
}) => {
  const inputId = useId();
  const errorId = `${inputId}-error`;

  return (
    <div className={`${styles.wrapper} ${className}`}>
      {label ? (
        <label htmlFor={inputId} className={styles.label}>
          {label}
        </label>
      ) : null}

      <div className={`${styles.inputBox} ${error ? styles.inputBoxError : ''}`}>
        <input
          id={inputId}
          type={type}
          name={name}
          value={value}
          onChange={onChange}
          onBlur={onBlur}
          placeholder={placeholder}
          autoComplete={autoComplete}
          inputMode={inputMode}
          disabled={disabled}
          aria-invalid={!!error}
          aria-describedby={error ? errorId : undefined}
          className={styles.input}
          {...rest}
        />
        {rightAdornment ? <div className={styles.adornment}>{rightAdornment}</div> : null}
      </div>

      {error ? (
        <p id={errorId} className={styles.errorText} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
};

export default InputField;
