import { useId } from 'react';
import styles from './SelectField.module.css';

const ChevronDown = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M6 9l6 6 6-6" />
  </svg>
);

const SelectField = ({
  label,
  name,
  value,
  onChange,
  onBlur,
  options = [],
  placeholder,
  error,
  disabled,
  className = '',
  ...rest
}) => {
  const selectId = useId();
  const errorId = `${selectId}-error`;

  return (
    <div className={`${styles.wrapper} ${className}`}>
      {label ? (
        <label htmlFor={selectId} className={styles.label}>
          {label}
        </label>
      ) : null}

      <div className={`${styles.selectBox} ${error ? styles.selectBoxError : ''}`}>
        <select
          id={selectId}
          name={name}
          value={value}
          onChange={onChange}
          onBlur={onBlur}
          disabled={disabled}
          aria-invalid={!!error}
          aria-describedby={error ? errorId : undefined}
          className={styles.select}
          {...rest}
        >
          {placeholder ? (
            <option value="" disabled>
              {placeholder}
            </option>
          ) : null}
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <span className={styles.chevron} aria-hidden="true">
          <ChevronDown />
        </span>
      </div>

      {error ? (
        <p id={errorId} className={styles.errorText} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
};

export default SelectField;
