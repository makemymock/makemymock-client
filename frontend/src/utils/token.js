const ACCESS_KEY = 'mmm_access_token';
const REFRESH_KEY = 'mmm_refresh_token';
const USER_KEY = 'mmm_user';

export const tokenStorage = {
  getAccessToken() {
    return localStorage.getItem(ACCESS_KEY);
  },
  getRefreshToken() {
    return localStorage.getItem(REFRESH_KEY);
  },
  getUser() {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  },
  setSession({ tokens, user }) {
    if (tokens?.access_token) localStorage.setItem(ACCESS_KEY, tokens.access_token);
    if (tokens?.refresh_token) localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  setTokens(tokens) {
    if (tokens?.access_token) localStorage.setItem(ACCESS_KEY, tokens.access_token);
    if (tokens?.refresh_token) localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  },
  isAuthenticated() {
    return !!localStorage.getItem(ACCESS_KEY);
  },
};
