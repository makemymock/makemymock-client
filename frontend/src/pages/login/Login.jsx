import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import AuthLayout from '../../components/auth/AuthLayout/AuthLayout';
import InputField from '../../components/common/InputField/InputField';
import PasswordInput from '../../components/auth/PasswordInput/PasswordInput';
import Button from '../../components/common/Button/Button';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { authService } from '../../services/authService';
import {
  parseApiError,
  validateEmail,
  validateLoginPassword,
} from '../../utils/validators';
import styles from './login.module.css';

const initialForm = {
  email: '',
  password: '',
};

const Login = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const redirectTo = location.state?.from?.pathname || '/dashboard';

  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

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
    if (name === 'email') fieldError = validateEmail(value);
    else if (name === 'password') fieldError = validateLoginPassword(value);
    setErrors((prev) => ({ ...prev, [name]: fieldError }));
  };

  const validateAll = () => {
    const next = {
      email: validateEmail(form.email),
      password: validateLoginPassword(form.password),
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
      await authService.login({
        email: form.email.trim(),
        password: form.password,
      });
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setFormError(parseApiError(err, 'Could not sign you in. Please try again.'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSocialClick = (provider) => {
    setFormError(`${provider} sign-in is coming soon.`);
  };

  return (
    <AuthLayout headerCtaTo="/signup" headerCtaLabel="SIGN UP">
      <p className={styles.eyebrow}>Sign in to</p>
      <h2 className={styles.title}>Make My Mock</h2>

      <form className={styles.form} onSubmit={handleSubmit} noValidate>
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

        <div>
          <PasswordInput
            label="Password"
            name="password"
            value={form.password}
            onChange={handleChange}
            onBlur={handleBlur}
            placeholder="Enter your password"
            error={errors.password}
            autoComplete="current-password"
          />
          <div className={styles.forgotRow}>
            <button
              type="button"
              className={styles.forgot}
              onClick={() => setFormError('Password reset is not available yet.')}
            >
              Forgot Password?
            </button>
          </div>
        </div>

        {formError ? <ErrorMessage message={formError} /> : null}

        <Button type="submit" loading={submitting}>
          LOGIN
        </Button>

        <div className={styles.divider} aria-hidden="true" />

        <div className={styles.socialRow}>
          <button
            type="button"
            className={styles.socialBtn}
            onClick={() => handleSocialClick('Google')}
          >
            <svg width="14" height="14" viewBox="0 0 48 48" aria-hidden="true">
              <path
                fill="#FFC107"
                d="M43.6 20.5H42V20H24v8h11.3C33.7 32.6 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.1 29.3 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.4-.4-3.5z"
              />
              <path
                fill="#FF3D00"
                d="M6.3 14.7l6.6 4.8C14.7 16.1 19 13 24 13c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.1 29.3 4 24 4 16.3 4 9.7 8.4 6.3 14.7z"
              />
              <path
                fill="#4CAF50"
                d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.1 35.5 26.7 36 24 36c-5.3 0-9.7-3.4-11.3-8H6v5.1C9.3 39.5 16 44 24 44z"
              />
              <path
                fill="#1976D2"
                d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.3 5.7l6.2 5.2C40 36.5 44 31 44 24c0-1.3-.1-2.4-.4-3.5z"
              />
            </svg>
            <span>Login with Google</span>
          </button>

          <button
            type="button"
            className={styles.socialBtn}
            onClick={() => handleSocialClick('Apple')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M16.4 12.7c0-2.2 1.8-3.2 1.9-3.2-1-1.5-2.6-1.7-3.2-1.7-1.4-.1-2.7.8-3.4.8-.7 0-1.8-.8-3-.8-1.5 0-3 .9-3.8 2.3-1.6 2.8-.4 6.9 1.1 9.2.8 1.1 1.7 2.4 2.9 2.3 1.2 0 1.6-.8 3-.8s1.8.8 3 .7c1.3 0 2.1-1.1 2.8-2.3.9-1.3 1.3-2.6 1.3-2.7 0 0-2.5-1-2.6-3.8zM14.6 6.2c.6-.7 1-1.7.9-2.7-.9 0-2 .6-2.6 1.3-.6.6-1.1 1.6-.9 2.6 1 .1 2-.5 2.6-1.2z"
              />
            </svg>
            <span>Login with Apple</span>
          </button>
        </div>

        <p className={styles.footer}>
          New to Make My Mock?{' '}
          <Link to="/signup" className={styles.footerLink}>
            Create an account
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
};

export default Login;
