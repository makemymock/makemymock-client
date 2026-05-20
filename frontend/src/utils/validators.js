const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const USERNAME_REGEX = /^[a-zA-Z0-9_.-]+$/;

export function validateEmail(email) {
  if (!email || !email.trim()) return 'Email is required.';
  if (!EMAIL_REGEX.test(email.trim())) return 'Please enter a valid email address.';
  return '';
}

export function validateUsername(username) {
  if (!username || !username.trim()) return 'Username is required.';
  const value = username.trim();
  if (value.length < 3) return 'Username must be at least 3 characters.';
  if (value.length > 32) return 'Username must be at most 32 characters.';
  if (!USERNAME_REGEX.test(value)) {
    return 'Only letters, numbers, dot, dash and underscore are allowed.';
  }
  return '';
}

export function validatePassword(password) {
  if (!password) return 'Password is required.';
  if (password.length < 8) return 'Password must be at least 8 characters.';
  if (password.length > 128) return 'Password must be at most 128 characters.';
  return '';
}

export function validateConfirmPassword(password, confirm) {
  if (!confirm) return 'Please confirm your password.';
  if (password !== confirm) return 'Passwords do not match.';
  return '';
}

export function validateLoginPassword(password) {
  if (!password) return 'Password is required.';
  return '';
}

export function validateOtp(otp) {
  if (!otp) return 'OTP is required.';
  if (!/^\d{6}$/.test(otp)) return 'OTP must be 6 digits.';
  return '';
}

const PHONE_REGEX = /^\+?[0-9 -]+$/;

export function validateNonEmpty(value, label = 'This field') {
  if (!value || !String(value).trim()) return `${label} is required.`;
  const v = String(value).trim();
  if (v.length > 120) return `${label} must be at most 120 characters.`;
  return '';
}

export function validateFullName(name) {
  if (!name || !name.trim()) return 'Full name is required.';
  if (name.trim().length < 2) return 'Full name must be at least 2 characters.';
  if (name.trim().length > 120) return 'Full name must be at most 120 characters.';
  return '';
}

export function validatePhone(phone) {
  if (!phone || !phone.trim()) return 'Phone number is required.';
  const v = phone.trim();
  if (v.length < 7) return 'Phone number must be at least 7 characters.';
  if (v.length > 20) return 'Phone number must be at most 20 characters.';
  if (!PHONE_REGEX.test(v)) {
    return 'Use only digits, spaces, dashes, or a leading +.';
  }
  return '';
}

export function validateDateOfBirth(dob) {
  if (!dob) return 'Date of birth is required.';
  const d = new Date(dob);
  if (Number.isNaN(d.getTime())) return 'Please enter a valid date.';
  const today = new Date();
  if (d > today) return 'Date of birth cannot be in the future.';
  const minYear = new Date();
  minYear.setFullYear(minYear.getFullYear() - 100);
  if (d < minYear) return 'Please enter a realistic date of birth.';
  return '';
}

export function validateChoice(value, label = 'This field') {
  if (!value) return `Please select ${label.toLowerCase()}.`;
  return '';
}

export function validateProfile(form) {
  return {
    full_name: validateFullName(form.full_name),
    date_of_birth: validateDateOfBirth(form.date_of_birth),
    class_grade: validateChoice(form.class_grade, 'a class'),
    target_exam: validateChoice(form.target_exam, 'a target exam'),
    state: validateNonEmpty(form.state, 'State'),
    school_name: validateNonEmpty(form.school_name, 'School name'),
    city: validateNonEmpty(form.city, 'City'),
    preferred_language: validateChoice(form.preferred_language, 'a preferred language'),
    phone_number: validatePhone(form.phone_number),
    gender: validateChoice(form.gender, 'a gender'),
  };
}

export function parseApiError(error, fallback = 'Something went wrong. Please try again.') {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === 'string') return first;
    if (first?.msg) return first.msg;
  }
  if (error?.message && error.message !== 'Network Error') return error.message;
  if (error?.message === 'Network Error') {
    return 'Unable to reach the server. Check your connection and try again.';
  }
  return fallback;
}
