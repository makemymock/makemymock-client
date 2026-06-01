import { useEffect, useMemo, useState } from 'react';
import InputField from '../../components/common/InputField/InputField';
import SelectField from '../../components/common/SelectField/SelectField';
import Button from '../../components/common/Button/Button';
import Loader from '../../components/common/Loader/Loader';
import ErrorMessage from '../../components/common/ErrorMessage/ErrorMessage';
import { profileService } from '../../services/profileService';
import { parseApiError, validateProfile } from '../../utils/validators';
import { tokenStorage } from '../../utils/token';
import styles from './userProfile.module.css';

// Mirrors the option lists in ProfileSetup so the same selects render in
// both create and update flows. If these grow we'd extract them to a
// shared module, but five short arrays inline is fine.
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

const LABEL_BY_VALUE = (options, value) =>
  options.find((o) => o.value === value)?.label ?? value ?? '—';

const FIELD_LAYOUT = [
  { key: 'full_name', label: 'Full name' },
  { key: 'date_of_birth', label: 'Date of birth', kind: 'date' },
  { key: 'class_grade', label: 'Class / Grade', kind: 'select', options: CLASS_OPTIONS },
  { key: 'target_exam', label: 'Target exam', kind: 'select', options: TARGET_EXAM_OPTIONS },
  { key: 'school_name', label: 'School / Coaching name' },
  { key: 'phone_number', label: 'Phone number' },
  { key: 'state', label: 'State' },
  { key: 'city', label: 'City' },
  { key: 'preferred_language', label: 'Preferred language', kind: 'select', options: LANGUAGE_OPTIONS },
  { key: 'gender', label: 'Gender', kind: 'select', options: GENDER_OPTIONS },
];

// The profile shape the form deals in — strings everywhere, including
// the date as ISO YYYY-MM-DD, since that's what <input type="date">
// understands. Backend accepts the same.
const toFormShape = (p) => ({
  full_name: p?.full_name ?? '',
  date_of_birth: p?.date_of_birth ?? '',
  class_grade: p?.class_grade ?? '',
  target_exam: p?.target_exam ?? '',
  state: p?.state ?? '',
  school_name: p?.school_name ?? '',
  city: p?.city ?? '',
  preferred_language: p?.preferred_language ?? '',
  phone_number: p?.phone_number ?? '',
  gender: p?.gender ?? '',
});

const UserProfile = () => {
  const cachedUser = tokenStorage.getUser();
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState('');

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(toFormShape(null));
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await profileService.getMyProfile();
        if (!cancelled) {
          setProfile(data);
          setForm(toFormShape(data));
        }
      } catch (err) {
        if (!cancelled) setPageError(parseApiError(err, 'Could not load your profile.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const startEdit = () => {
    setForm(toFormShape(profile));
    setErrors({});
    setFormError('');
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setForm(toFormShape(profile));
    setErrors({});
    setFormError('');
  };

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
      // PUT /profile/update accepts a partial — sending the full form is
      // fine; the backend treats unchanged values the same as edits.
      const updated = await profileService.updateProfile({
        ...form,
        full_name: form.full_name.trim(),
        state: form.state.trim(),
        school_name: form.school_name.trim(),
        city: form.city.trim(),
        phone_number: form.phone_number.trim(),
      });
      setProfile(updated);
      setForm(toFormShape(updated));
      setEditing(false);
    } catch (err) {
      setFormError(parseApiError(err, 'Could not save your profile. Please try again.'));
    } finally {
      setSubmitting(false);
    }
  };

  const todayIso = useMemo(() => new Date().toISOString().split('T')[0], []);

  if (loading) {
    return (
      <div className={styles.wrap}>
        <Loader />
      </div>
    );
  }

  if (pageError && !profile) {
    return (
      <div className={styles.wrap}>
        <ErrorMessage message={pageError} />
      </div>
    );
  }

  return (
    <div className={styles.wrap}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Profile</p>
          <h1 className={styles.title}>
            {profile?.full_name || cachedUser?.username || 'Your profile'}
          </h1>
          <p className={styles.subtitle}>
            {cachedUser?.email ? `Signed in as ${cachedUser.email}` : 'Manage your details'}
          </p>
        </div>
        {!editing ? (
          <Button type="button" fullWidth={false} onClick={startEdit}>
            Edit profile
          </Button>
        ) : null}
      </header>

      <section className={styles.card}>
        {editing ? (
          <form className={styles.form} onSubmit={handleSubmit} noValidate>
            <div className={styles.grid}>
              {FIELD_LAYOUT.map((f) => {
                if (f.kind === 'select') {
                  return (
                    <SelectField
                      key={f.key}
                      label={f.label}
                      name={f.key}
                      value={form[f.key]}
                      onChange={handleChange}
                      onBlur={handleBlur}
                      options={f.options}
                      placeholder="Select"
                      error={errors[f.key]}
                    />
                  );
                }
                return (
                  <InputField
                    key={f.key}
                    label={f.label}
                    name={f.key}
                    type={f.kind === 'date' ? 'date' : 'text'}
                    value={form[f.key]}
                    onChange={handleChange}
                    onBlur={handleBlur}
                    error={errors[f.key]}
                    max={f.kind === 'date' ? todayIso : undefined}
                  />
                );
              })}
            </div>

            {formError ? <ErrorMessage message={formError} /> : null}

            <div className={styles.actions}>
              <Button type="submit" fullWidth={false} loading={submitting}>
                Save changes
              </Button>
              <button
                type="button"
                className={styles.cancelBtn}
                onClick={cancelEdit}
                disabled={submitting}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <dl className={styles.viewGrid}>
            {FIELD_LAYOUT.map((f) => {
              const raw = profile?.[f.key];
              const display = f.kind === 'select'
                ? LABEL_BY_VALUE(f.options, raw)
                : (raw || '—');
              return (
                <div key={f.key} className={styles.viewRow}>
                  <dt className={styles.viewLabel}>{f.label}</dt>
                  <dd className={styles.viewValue}>{display}</dd>
                </div>
              );
            })}
          </dl>
        )}
      </section>
    </div>
  );
};

export default UserProfile;
