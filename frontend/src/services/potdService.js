import api from './axiosInstance';

export const potdService = {
  async getToday() {
    const { data } = await api.get('/potd/today');
    return data;
  },

  async submitAttempt(answer) {
    const { data } = await api.post('/potd/today/attempt', answer);
    return data;
  },

  async viewSolution() {
    const { data } = await api.post('/potd/today/view-solution');
    return data;
  },

  async getStreak() {
    const { data } = await api.get('/potd/streak');
    return data;
  },

  async getHistory(days = 60) {
    const { data } = await api.get('/potd/history', { params: { days } });
    return data;
  },

  async getPastDate(dateIso) {
    const { data } = await api.get(`/potd/${dateIso}`);
    return data;
  },
};
