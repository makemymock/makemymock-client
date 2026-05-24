import api from './axiosInstance';
import { tokenStorage } from '../utils/token';

const httpBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

function buildWsUrl() {
  const token = tokenStorage.getAccessToken();
  const wsBase = httpBase.replace(/^http/, 'ws');
  return `${wsBase}/battle/ws?token=${encodeURIComponent(token || '')}`;
}

export const battleService = {
  openSocket() {
    return new WebSocket(buildWsUrl());
  },

  async fetchHistory() {
    const { data } = await api.get('/battle/history');
    return data;
  },

  async fetchBattle(battleId) {
    const { data } = await api.get(`/battle/${battleId}`);
    return data;
  },
};
