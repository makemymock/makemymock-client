import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import AWaves from '../../components/landing/AWaves/AWaves';
import useTheme from '../../hooks/useTheme';
import InputField from '../../components/common/InputField/InputField';
import SelectField from '../../components/common/SelectField/SelectField';
import Button from '../../components/common/Button/Button';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import Loader from '../../components/common/Loader/Loader';
import { authService } from '../../services/authService';
import { profileService } from '../../services/profileService';
import { tokenStorage } from '../../utils/token';
import { parseApiError, validateProfile } from '../../utils/validators';
import styles from './profile.module.css';

const CLASS_OPTIONS = [
  { value: '9', label: 'Class 9' },
  { value: '10', label: 'Class 10' },
  { value: '11', label: 'Class 11' },
  { value: '12', label: 'Class 12' },
  { value: 'dropper', label: 'Dropper' },
];

const TARGET_EXAM_OPTIONS = [
  { value: 'jee_main', label: 'JEE Main' },
  { value: 'jee_advanced', label: 'JEE Advanced' },
  { value: 'boards', label: 'Boards' },
  { value: 'other', label: 'Other (NEET, CUET, etc.)' },
];

const GENDER_OPTIONS = [
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'other', label: 'Other' },
  { value: 'prefer_not_to_say', label: 'Prefer not to say' },
];

const LANGUAGE_OPTIONS = [
  { value: 'English', label: 'English' },
  { value: 'Hindi', label: 'Hindi' },
  { value: 'Bengali', label: 'Bengali' },
  { value: 'Tamil', label: 'Tamil' },
  { value: 'Telugu', label: 'Telugu' },
  { value: 'Marathi', label: 'Marathi' },
  { value: 'Gujarati', label: 'Gujarati' },
  { value: 'Kannada', label: 'Kannada' },
  { value: 'Malayalam', label: 'Malayalam' },
  { value: 'Punjabi', label: 'Punjabi' },
  { value: 'Other', label: 'Other' },
];

const initialForm = {
  full_name: '',
  date_of_birth: '',
  class_grade: '',
  target_exam: '',
  state: '',
  school_name: '',
  city: '',
  preferred_language: '',
  phone_number: '',
  gender: '',
};

const ProfileSetup = () => {
  const navigate = useNavigate();
  const { theme } = useTheme();
  const cachedUser = tokenStorage.getUser();
  const logoSrc = theme === 'dark'
    ? '/logo_dark-removebg-preview.png'
    : '/logo_light-removebg-preview.png';

  const [checking, setChecking] = useState(true);
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // If the user already has a profile, jump straight to the dashboard.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await profileService.getMyProfile();
        if (!cancelled) navigate('/dashboard', { replace: true });
      } catch (err) {
        if (err?.response?.status !== 404 && !cancelled) {
          setFormError(parseApiError(err, 'Could not check your profile status.'));
        }
        if (!cancelled) setChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    if (errors[name]) setErrors((prev) => ({ ...prev, [name]: '' }));
    if (formError) setFormError('');
  };

  const handleBlur = (e) => {
    const { name, value } = e.target;
    const fieldErrors = validateProfile({ ...form, [name]: value });
    setErrors((prev) => ({ ...prev, [name]: fieldErrors[name] || '' }));
  };

  const validateAll = () => {
    const next = validateProfile(form);
    setErrors(next);
    return Object.values(next).every((v) => !v);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!validateAll()) return;
    setSubmitting(true);
    setFormError('');
    try {
      await profileService.createProfile({
        ...form,
        full_name: form.full_name.trim(),
        state: form.state.trim(),
        school_name: form.school_name.trim(),
        city: form.city.trim(),
        phone_number: form.phone_number.trim(),
      });
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setFormError(parseApiError(err, 'Could not save your profile. Please try again.'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogout = () => {
    authService.logout();
    navigate('/login', { replace: true });
  };

  if (checking) {
    return (
      <div className={styles.page}>
        <div className={styles.wavesLayer} aria-hidden="true">
          <AWaves />
        </div>
        <div className={styles.checking}>
          <Loader />
        </div>
      </div>
    );
  }

  const todayIso = new Date().toISOString().split('T')[0];

  return (
    <div className={styles.page}>
      <div className={styles.wavesLayer} aria-hidden="true">
        <AWaves />
      </div>

      <div className={styles.content}>
        <header className={styles.header}>
          <Link to="/" className={styles.brand} aria-label="Make My Mock home">
            <img src={logoSrc} alt="Make My Mock" className={styles.brandLogo} />
          </Link>
          <button type="button" className={styles.headerCta} onClick={handleLogout}>
            SIGN OUT
          </button>
        </header>

        <main className={styles.main}>
          <section className={styles.formCard}>
            <div className={styles.intro}>
              <p className={styles.eyebrow}>Almost there{cachedUser?.username ? `, ${cachedUser.username}` : ''}</p>
              <h1 className={styles.title}>Set up your profile</h1>
              <p className={styles.subtitle}>
                Tell us a bit about yourself so we can tailor practice questions, insights and study
                recommendations to you.
              </p>
            </div>

            <form className={styles.form} onSubmit={handleSubmit} noValidate>
              <div className={styles.grid}>
                <InputField
                  label="Full name"
                  name="full_name"
                  value={form.full_name}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  placeholder="e.g. Aarav Sharma"
                  error={errors.full_name}
                  autoComplete="name"
                />

                <InputField
                  label="Date of birth"
                  type="date"
                  name="date_of_birth"
                  value={form.date_of_birth}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  error={errors.date_of_birth}
                  max={todayIso}
                  autoComplete="bday"
                />

                <SelectField
                  label="Class / Grade"
                  name="class_grade"
                  value={form.class_grade}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  options={CLASS_OPTIONS}
                  placeholder="Select your class"
                  error={errors.class_grade}
                />

                <SelectField
                  label="Target exam"
                  name="target_exam"
                  value={form.target_exam}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  options={TARGET_EXAM_OPTIONS}
                  placeholder="What are you preparing for?"
                  error={errors.target_exam}
                />

                <InputField
                  label="School / Coaching name"
                  name="school_name"
                  value={form.school_name}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  placeholder="e.g. Delhi Public School"
                  error={errors.school_name}
                  autoComplete="organization"
                />

                <InputField
                  label="Phone number"
                  type="tel"
                  name="phone_number"
                  value={form.phone_number}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  placeholder="e.g. +91 98765 43210"
                  error={errors.phone_number}
                  autoComplete="tel"
                />

                <InputField
                  label="State"
                  name="state"
                  value={form.state}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  placeholder="e.g. Maharashtra"
                  error={errors.state}
                  autoComplete="address-level1"
                />

                <InputField
                  label="City"
                  name="city"
                  value={form.city}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  placeholder="e.g. Pune"
                  error={errors.city}
                  autoComplete="address-level2"
                />

                <SelectField
                  label="Preferred language"
                  name="preferred_language"
                  value={form.preferred_language}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  options={LANGUAGE_OPTIONS}
                  placeholder="Choose a language"
                  error={errors.preferred_language}
                />

                <SelectField
                  label="Gender"
                  name="gender"
                  value={form.gender}
                  onChange={handleChange}
                  onBlur={handleBlur}
                  options={GENDER_OPTIONS}
                  placeholder="Select"
                  error={errors.gender}
                />
              </div>

              {formError ? <ErrorMessage message={formError} /> : null}

              <div className={styles.actions}>
                <Button type="submit" loading={submitting}>
                  SAVE &amp; CONTINUE
                </Button>
                <p className={styles.helper}>
                  You can edit any of this later from your dashboard settings.
                </p>
              </div>
            </form>
          </section>
        </main>
      </div>
    </div>
  );
};

export default ProfileSetup;
