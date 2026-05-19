import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Button from '../../common/Button/Button';
import ErrorMessage from '../../common/ErrorMessage/ErrorMessage';
import { authService } from '../../../services/authService';
import { parseApiError, validateOtp } from '../../../utils/validators';
import styles from './OTPModal.module.css';

const OTP_LENGTH = 6;

const OTPModal = ({ open, email, expiresInMinutes = 5, onVerified, onClose }) => {
  const [digits, setDigits] = useState(() => Array(OTP_LENGTH).fill(''));
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);
  const [info, setInfo] = useState('');
  const [secondsLeft, setSecondsLeft] = useState(expiresInMinutes * 60);
  const inputsRef = useRef([]);

  const otpString = useMemo(() => digits.join(''), [digits]);

  const resetFor = useCallback(() => {
    setDigits(Array(OTP_LENGTH).fill(''));
    setError('');
    setInfo('');
    setSecondsLeft(expiresInMinutes * 60);
    setTimeout(() => inputsRef.current[0]?.focus(), 0);
  }, [expiresInMinutes]);

  useEffect(() => {
    if (open) resetFor();
  }, [open, resetFor]);

  useEffect(() => {
    if (!open || secondsLeft <= 0) return undefined;
    const id = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [open, secondsLeft]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape' && onClose) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const updateDigit = (index, value) => {
    const clean = value.replace(/\D/g, '').slice(0, 1);
    setDigits((prev) => {
      const next = [...prev];
      next[index] = clean;
      return next;
    });
    if (clean && index < OTP_LENGTH - 1) {
      inputsRef.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (index, e) => {
    if (e.key === 'Backspace' && !digits[index] && index > 0) {
      inputsRef.current[index - 1]?.focus();
    } else if (e.key === 'ArrowLeft' && index > 0) {
      inputsRef.current[index - 1]?.focus();
    } else if (e.key === 'ArrowRight' && index < OTP_LENGTH - 1) {
      inputsRef.current[index + 1]?.focus();
    } else if (e.key === 'Enter') {
      handleVerify();
    }
  };

  const handlePaste = (e) => {
    const pasted = (e.clipboardData?.getData('text') || '').replace(/\D/g, '').slice(0, OTP_LENGTH);
    if (!pasted) return;
    e.preventDefault();
    const next = Array(OTP_LENGTH).fill('');
    for (let i = 0; i < pasted.length; i++) next[i] = pasted[i];
    setDigits(next);
    const focusIndex = Math.min(pasted.length, OTP_LENGTH - 1);
    inputsRef.current[focusIndex]?.focus();
  };

  const handleVerify = async () => {
    const validationError = validateOtp(otpString);
    if (validationError) {
      setError(validationError);
      return;
    }
    setSubmitting(true);
    setError('');
    setInfo('');
    try {
      const data = await authService.verifyOtp({ email, otp_code: otpString });
      if (onVerified) onVerified(data);
    } catch (err) {
      setError(parseApiError(err, 'Could not verify the code. Please try again.'));
      setDigits(Array(OTP_LENGTH).fill(''));
      inputsRef.current[0]?.focus();
    } finally {
      setSubmitting(false);
    }
  };

  const handleResend = async () => {
    setResending(true);
    setError('');
    setInfo('');
    try {
      await authService.resendOtp(email);
      setInfo('A new code has been sent to your email.');
      setSecondsLeft(expiresInMinutes * 60);
    } catch (err) {
      setError(parseApiError(err, 'Could not resend the code.'));
    } finally {
      setResending(false);
    }
  };

  if (!open) return null;

  const minutes = Math.floor(secondsLeft / 60);
  const seconds = secondsLeft % 60;
  const timer = `${minutes}:${seconds.toString().padStart(2, '0')}`;

  return (
    <div
      className={styles.overlay}
      role="dialog"
      aria-modal="true"
      aria-labelledby="otp-title"
      onClick={(e) => {
        if (e.target === e.currentTarget && onClose) onClose();
      }}
    >
      <div className={styles.modal}>
        <button
          type="button"
          className={styles.close}
          onClick={onClose}
          aria-label="Close verification dialog"
        >
          ×
        </button>

        <p className={styles.eyebrow}>Verify your email</p>
        <h2 id="otp-title" className={styles.title}>
          Enter the 6-digit code
        </h2>
        <p className={styles.subtitle}>
          We sent a code to <strong>{email}</strong>. Enter it below to activate your account.
        </p>

        <div
          className={styles.otpRow}
          role="group"
          aria-label="One-time password"
          onPaste={handlePaste}
        >
          {digits.map((d, i) => (
            <input
              key={i}
              ref={(el) => {
                inputsRef.current[i] = el;
              }}
              type="text"
              inputMode="numeric"
              maxLength={1}
              autoComplete={i === 0 ? 'one-time-code' : 'off'}
              value={d}
              onChange={(e) => updateDigit(i, e.target.value)}
              onKeyDown={(e) => handleKeyDown(i, e)}
              className={styles.otpInput}
              aria-label={`Digit ${i + 1}`}
              disabled={submitting}
            />
          ))}
        </div>

        {error ? <ErrorMessage message={error} /> : null}
        {!error && info ? <p className={styles.info}>{info}</p> : null}

        <Button onClick={handleVerify} loading={submitting} fullWidth>
          VERIFY
        </Button>

        <div className={styles.meta}>
          <span className={styles.timer}>
            {secondsLeft > 0 ? `Code expires in ${timer}` : 'Code expired'}
          </span>
          <button
            type="button"
            onClick={handleResend}
            className={styles.resend}
            disabled={resending || submitting}
          >
            {resending ? 'Resending…' : 'Resend code'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default OTPModal;
