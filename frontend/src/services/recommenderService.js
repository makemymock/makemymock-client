import api from './axiosInstance';

export const recommenderService = {
  async initialize() {
    const { data } = await api.post('/recommender/initialize');
    return data;
  },

  async startSession() {
    const { data } = await api.post('/recommender/session/start');
    return data;
  },

  async getNextQuestion(payload) {
    const { data } = await api.post('/recommender/session/next-question', payload);
    return data;
  },

  async submitAnswer(payload) {
    const { data } = await api.post('/recommender/session/submit-answer', payload);
    return data;
  },

  async endSession(payload) {
    const { data } = await api.post('/recommender/session/end', payload);
    return data;
  },

  async getPersonality() {
    const { data } = await api.get('/recommender/personality');
    return data;
  },

  async getTopicStates() {
    const { data } = await api.get('/recommender/topic-states');
    return data;
  },

  async getSessionHistory() {
    const { data } = await api.get('/recommender/sessions');
    return data;
  },

  async getTrends() {
    const { data } = await api.get('/recommender/trends');
    return data;
  },

  async getStats() {
    const { data } = await api.get('/recommender/stats');
    return data;
  },

  async getQuestion(questionId) {
    const { data } = await api.get(`/recommender/question/${questionId}`);
    return data;
  },
};
