import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import AuthLayout from '../../components/auth/AuthLayout/AuthLayout';
import InputField from '../../components/common/InputField/InputField';
import PasswordInput from '../../components/auth/PasswordInput/PasswordInput';
import Button from '../../components/common/Button/Button';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import OTPModal from '../../components/auth/OTPModal/OTPModal';
import { authService } from '../../services/authService';
import {
  parseApiError,
  validateConfirmPassword,
  validateEmail,
  validatePassword,
  validateUsername,
} from '../../utils/validators';
import styles from './signup.module.css';

const initialForm = {
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
};

const Signup = () => {
  const navigate = useNavigate();
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [otpOpen, setOtpOpen] = useState(false);
  const [otpExpiry, setOtpExpiry] = useState(5);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: '' }));
    }
    if (formError) setFormError('');
  };

  const handleBlur = (e) => {
    const { name, value } = e.target;
    let fieldError = '';
    if (name === 'username') fieldError = validateUsername(value);
    else if (name === 'email') fieldError = validateEmail(value);
    else if (name === 'password') fieldError = validatePassword(value);
    else if (name === 'confirmPassword') fieldError = validateConfirmPassword(form.password, value);
    setErrors((prev) => ({ ...prev, [name]: fieldError }));
  };

  const validateAll = () => {
    const next = {
      username: validateUsername(form.username),
      email: validateEmail(form.email),
      password: validatePassword(form.password),
      confirmPassword: validateConfirmPassword(form.password, form.confirmPassword),
    };
    setErrors(next);
    return Object.values(next).every((v) => !v);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!validateAll()) return;

    setSubmitting(true);
    setFormError('');
    try {
      const data = await authService.signup({
        username: form.username.trim(),
        email: form.email.trim(),
        password: form.password,
      });
      setOtpExpiry(data?.otp_expires_in_minutes || 5);
      setOtpOpen(true);
    } catch (err) {
      setFormError(parseApiError(err, 'Could not create account. Please try again.'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleVerified = () => {
    setOtpOpen(false);
    navigate('/dashboard', { replace: true });
  };

  return (
    <AuthLayout headerCtaTo="/login" headerCtaLabel="LOGIN">
      <p className={styles.eyebrow}>Get Started</p>
      <h2 className={styles.title}>Create Account</h2>

      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <InputField
          label="Username"
          name="username"
          value={form.username}
          onChange={handleChange}
          onBlur={handleBlur}
          placeholder="e.g. ram_123"
          error={errors.username}
          autoComplete="username"
        />

        <InputField
          label="Email Address"
          type="email"
          name="email"
          value={form.email}
          onChange={handleChange}
          onBlur={handleBlur}
          placeholder="e.g ram@gmail.com"
          error={errors.email}
          autoComplete="email"
        />

        <PasswordInput
          label="Password"
          name="password"
          value={form.password}
          onChange={handleChange}
          onBlur={handleBlur}
          placeholder="At least 8 characters"
          error={errors.password}
          autoComplete="new-password"
        />

        <PasswordInput
          label="Confirm Password"
          name="confirmPassword"
          value={form.confirmPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          placeholder="Re-enter your password"
          error={errors.confirmPassword}
          autoComplete="new-password"
        />

        {formError ? <ErrorMessage message={formError} /> : null}

        <Button type="submit" loading={submitting}>
          SIGN UP
        </Button>

        <p className={styles.footer}>
          Already have an account?{' '}
          <Link to="/login" className={styles.footerLink}>
            Sign in
          </Link>
        </p>
      </form>

      <OTPModal
        open={otpOpen}
        email={form.email.trim()}
        expiresInMinutes={otpExpiry}
        onVerified={handleVerified}
        onClose={() => setOtpOpen(false)}
      />
    </AuthLayout>
  );
};

export default Signup;
