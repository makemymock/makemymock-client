import axios from 'axios';
import { tokenStorage } from '../utils/token';
import { API_BASE_URL } from '../config';

const baseURL = API_BASE_URL;

const api = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 100000,
});

api.interceptors.request.use((config) => {
  const token = tokenStorage.getAccessToken();
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshPromise = null;

async function refreshAccessToken() {
  const refresh_token = tokenStorage.getRefreshToken();
  if (!refresh_token) throw new Error('No refresh token available.');
  const response = await axios.post(
    `${baseURL}/auth/refresh-token`,
    { refresh_token },
    { headers: { 'Content-Type': 'application/json' } }
  );
  tokenStorage.setTokens(response.data);
  return response.data.access_token;
}

// Single-flight token refresh shared across the whole app. Exported so
// non-axios callers (the SSE stream in solverxService) can hop on the
// same in-flight refresh instead of racing the axios interceptor.
export async function ensureFreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const status = error.response?.status;
    const isAuthEndpoint = original?.url?.includes('/auth/login')
      || original?.url?.includes('/auth/signup')
      || original?.url?.includes('/auth/verify-otp')
      || original?.url?.includes('/auth/resend-otp')
      || original?.url?.includes('/auth/refresh-token');

    if (status === 401 && !original._retry && !isAuthEndpoint && tokenStorage.getRefreshToken()) {
      original._retry = true;
      try {
        if (!refreshPromise) {
          refreshPromise = refreshAccessToken().finally(() => {
            refreshPromise = null;
          });
        }
        const newAccessToken = await refreshPromise;
        original.headers = original.headers || {};
        original.headers.Authorization = `Bearer ${newAccessToken}`;
        return api(original);
      } catch (refreshError) {
        tokenStorage.clear();
        if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
          window.location.assign('/login');
        }
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

export default api;
