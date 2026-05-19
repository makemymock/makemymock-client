import api from './axiosInstance';
import { tokenStorage } from '../utils/token';

export const authService = {
  async signup({ username, email, password }) {
    const { data } = await api.post('/auth/signup', { username, email, password });
    return data;
  },

  async verifyOtp({ email, otp_code }) {
    const { data } = await api.post('/auth/verify-otp', { email, otp_code });
    tokenStorage.setSession({ tokens: data.tokens, user: data.user });
    return data;
  },

  async resendOtp(email) {
    const { data } = await api.post('/auth/resend-otp', { email });
    return data;
  },

  async login({ email, password }) {
    const { data } = await api.post('/auth/login', { email, password });
    tokenStorage.setSession({ tokens: data.tokens, user: data.user });
    return data;
  },

  async me() {
    const { data } = await api.get('/auth/me');
    return data;
  },

  logout() {
    tokenStorage.clear();
  },
};
