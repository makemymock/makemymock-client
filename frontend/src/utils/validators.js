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
