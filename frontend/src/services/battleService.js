import api from './axiosInstance';
import { tokenStorage } from '../utils/token';
import { WS_BASE_URL } from '../config';

function buildWsUrl() {
  const token = tokenStorage.getAccessToken();
  return `${WS_BASE_URL}/battle/ws?token=${encodeURIComponent(token || '')}`;
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
