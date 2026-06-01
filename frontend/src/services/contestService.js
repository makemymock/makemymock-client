import api from './axiosInstance';

export const contestService = {
  async list() {
    const { data } = await api.get('/contests');
    return data;
  },

  async get(contestId) {
    const { data } = await api.get(`/contests/${contestId}`);
    return data;
  },

  async enterLobby(contestId) {
    const { data } = await api.post(`/contests/${contestId}/enter`);
    return data;
  },

  async start(contestId) {
    const { data } = await api.post(`/contests/${contestId}/start`);
    return data;
  },

  async submit(contestId, answers) {
    const { data } = await api.post(`/contests/${contestId}/submit`, { answers });
    return data;
  },

  async getResult(contestId) {
    const { data } = await api.get(`/contests/${contestId}/result`);
    return data;
  },

  async getLeaderboard(contestId) {
    const { data } = await api.get(`/contests/${contestId}/leaderboard`);
    return data;
  },
};
