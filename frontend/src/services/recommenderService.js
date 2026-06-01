import api, { ensureFreshAccessToken } from './axiosInstance';
import { API_BASE_URL } from '../config';

export const recommenderService = {
  /**
   * Connect to the SSE endpoint and stream agent events while the session
   * plan is being built.  onEvent is called for every parsed SSE data line.
   * Resolves when the stream closes (type: 'done').
   */
  async startSessionStream(onEvent, signal) {
    let token = localStorage.getItem('mmm_access_token');
    const url  = `${API_BASE_URL}/recommender/session/start-stream`;

    let response = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    });

    // Single token refresh attempt on 401 (mirrors the axios interceptor).
    if (response.status === 401) {
      token = await ensureFreshAccessToken();
      response = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
        signal,
      });
    }

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${response.status}`);
    }

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';
      for (const part of parts) {
        const line = part.trim();
        if (line.startsWith('data: ')) {
          try { onEvent(JSON.parse(line.slice(6))); } catch { /* malformed chunk */ }
        }
      }
    }
  },


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

  /**
   * Stream reasoning steps while the AI selects the next question.
   * onEvent is called per SSE event; resolves when stream closes.
   * Falls back to the regular endpoint if streaming fails.
   */
  async nextQuestionStream(payload, onEvent, signal) {
    let token = localStorage.getItem('mmm_access_token');
    const url  = `${API_BASE_URL}/recommender/session/next-question-stream`;

    let response = await fetch(url, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body:    JSON.stringify(payload),
      signal,
    });

    if (response.status === 401) {
      token    = await ensureFreshAccessToken();
      response = await fetch(url, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body:    JSON.stringify(payload),
        signal,
      });
    }

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${response.status}`);
    }

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';
      for (const part of parts) {
        const line = part.trim();
        if (line.startsWith('data: ')) {
          try { onEvent(JSON.parse(line.slice(6))); } catch { /* malformed */ }
        }
      }
    }
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

  async getAttemptedQuestions(correct, limit = 20) {
    const { data } = await api.get('/recommender/attempted-questions', {
      params: { correct, limit },
    });
    return data;
  },

  async getCatalogSubjects() {
    const { data } = await api.get('/recommender/catalog-subjects');
    return data;
  },
};
