// Per-tab draft storage for an in-progress mock test. Uses sessionStorage
// (NOT localStorage) so unsubmitted answers stay scoped to the tab the user
// is actually testing in. Keyed by session id so multiple tabs don't clash.
//
// Stored payload shape per session:
//   {
//     answers:  { [questionId]: AnswerInput },
//     marks:    { [questionId]: boolean },
//     visited:  { [questionId]: boolean },
//     activeIndex: number,
//     startedAt:   ISO date string,
//   }

const KEY_PREFIX = 'mmm_test_';

function key(sessionId) {
  return `${KEY_PREFIX}${sessionId}`;
}

function read(sessionId) {
  const raw = sessionStorage.getItem(key(sessionId));
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function write(sessionId, value) {
  sessionStorage.setItem(key(sessionId), JSON.stringify(value));
}

export const examDraft = {
  load(sessionId) {
    return read(sessionId);
  },

  ensure(sessionId, defaults) {
    const existing = read(sessionId);
    if (existing) return existing;
    const fresh = {
      answers: {},
      marks: {},
      visited: {},
      activeIndex: 0,
      startedAt: new Date().toISOString(),
      ...defaults,
    };
    write(sessionId, fresh);
    return fresh;
  },

  save(sessionId, draft) {
    write(sessionId, draft);
  },

  clear(sessionId) {
    sessionStorage.removeItem(key(sessionId));
  },
};
