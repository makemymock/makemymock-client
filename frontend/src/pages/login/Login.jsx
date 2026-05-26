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
