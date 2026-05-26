import api from './axiosInstance';

export const mockTestService = {
  async getCatalog() {
    const { data } = await api.get('/mock-test/catalog');
    return data;
  },

  async createTest({ topic_ids, total_questions, extra_questions = 0 }) {
    const { data } = await api.post('/mock-test/create', {
      topic_ids,
      total_questions,
      extra_questions,
    });
    return data;
  },

  async getSession(sessionId) {
    const { data } = await api.get(`/mock-test/session/${sessionId}`);
    return data;
  },

  async submitTest(sessionId, answers) {
    const { data } = await api.post(
      `/mock-test/session/${sessionId}/submit`,
      { answers },
    );
    return data;
  },

  async getResults(sessionId) {
    const { data } = await api.get(`/mock-test/session/${sessionId}/result`);
    return data;
  },

  async getHistory() {
    const { data } = await api.get('/mock-test/history');
    return data;
  },

  async getOverview() {
    const { data } = await api.get('/mock-test/analytics/overview');
    return data;
  },

  async getTopicAnalytics() {
    const { data } = await api.get('/mock-test/analytics/topics');
    return data;
  },

  async getChapterAnalytics() {
    const { data } = await api.get('/mock-test/analytics/chapters');
    return data;
  },

  async getChapterDetail(chapterId) {
    const { data } = await api.get(`/mock-test/analytics/chapter/${chapterId}`);
    return data;
  },

  async getTopicDetail(topicId) {
    const { data } = await api.get(`/mock-test/analytics/topic/${topicId}`);
    return data;
  },

  async getActivityHeatmap() {
    const { data } = await api.get('/mock-test/analytics/activity-heatmap');
    return data;
  },
};
