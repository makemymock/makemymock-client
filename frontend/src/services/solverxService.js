// SolverX HTTP + streaming client.
//
// Axios doesn't deal with Server-Sent Events well — it buffers the
// response body — so the streaming endpoints use native `fetch` with a
// hand-rolled SSE parser. The non-streaming list/detail endpoints use
// the regular axios instance so token refresh stays consistent.

import api from './axiosInstance';
import { API_BASE_URL } from '../config';
import { tokenStorage } from '../utils/token';

const SSE_URL = (path) => `${API_BASE_URL}${path}`;

// ---- SSE plumbing ----

// Parses an SSE chunk and invokes `onEvent({event, data})` for every
// complete `event:`/`data:` pair separated by a blank line.
function makeSseParser(onEvent) {
  let buffer = '';
  return function feed(textChunk) {
    buffer += textChunk;
    let idx;
    // Each SSE message is terminated by a double newline. We loop in
    // case a single chunk contains multiple complete messages.
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const lines = raw.split('\n');
      let event = 'message';
      const dataLines = [];
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) continue;
      let data;
      try {
        data = JSON.parse(dataLines.join('\n'));
      } catch {
        data = dataLines.join('\n');
      }
      onEvent({ event, data });
    }
  };
}

async function streamPost(path, body, { onEvent, signal } = {}) {
  const token = tokenStorage.getAccessToken();
  const res = await fetch(SSE_URL(path), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    let text = '';
    try { text = await res.text(); } catch { /* ignore */ }
    throw new Error(text || `Request failed (${res.status})`);
  }
  if (!res.body) {
    throw new Error('Streaming not supported in this browser.');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = makeSseParser((evt) => {
    try { onEvent?.(evt); } catch (err) { console.error('SolverX event handler crashed', err); }
  });
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    parser(decoder.decode(value, { stream: true }));
  }
  parser(decoder.decode());
}

// ---- Public API ----

export const solverxService = {
  /** Stream a solve request. Returns an AbortController so the caller
   *  can cancel mid-stream when the user navigates away or hits stop. */
  streamSolve({ question_text, complexity_mode, conversation_id, image_data_url, onEvent }) {
    const controller = new AbortController();
    const promise = streamPost(
      '/solverx/solve',
      {
        question_text,
        complexity_mode,
        conversation_id: conversation_id || null,
        image_data_url: image_data_url || null,
      },
      { onEvent, signal: controller.signal },
    );
    return { controller, promise };
  },

  /** Same shape as streamSolve but hits the theory endpoint. */
  streamTheory({ question_text, complexity_mode, conversation_id, image_data_url, onEvent }) {
    const controller = new AbortController();
    const promise = streamPost(
      '/solverx/theory',
      {
        question_text,
        complexity_mode,
        conversation_id: conversation_id || null,
        image_data_url: image_data_url || null,
      },
      { onEvent, signal: controller.signal },
    );
    return { controller, promise };
  },

  async listConversations() {
    const { data } = await api.get('/solverx/conversations');
    return data;
  },

  async getConversation(id) {
    const { data } = await api.get(`/solverx/conversations/${id}`);
    return data;
  },
};
