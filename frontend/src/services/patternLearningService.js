// Pattern-learning (Duolingo path) HTTP client.
// Plain axios through the shared instance so token refresh stays consistent.

import api from './axiosInstance';

const enc = encodeURIComponent;

export const patternLearningService = {
  async listSubjects() {
    const { data } = await api.get('/pattern-learning/subjects');
    return data;
  },

  async listChapters(subject) {
    const { data } = await api.get(`/pattern-learning/subjects/${enc(subject)}/chapters`);
    return data;
  },

  async patternRoadmap(chapter) {
    const { data } = await api.get(`/pattern-learning/chapters/${enc(chapter)}/patterns`);
    return data;
  },

  async questionRoadmap(patternId) {
    const { data } = await api.get(`/pattern-learning/patterns/${enc(patternId)}/questions`);
    return data;
  },

  async getQuestion(questionId) {
    const { data } = await api.get(`/pattern-learning/questions/${enc(questionId)}`);
    return data;
  },

  async submitAnswer(questionId, answer) {
    const { data } = await api.post(
      `/pattern-learning/questions/${enc(questionId)}/submit`,
      { answer },
    );
    return data;
  },
};
