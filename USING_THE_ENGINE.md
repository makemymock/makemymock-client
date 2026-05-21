# Using the Mock-Test Engine from Other Features

This document is for engineers building **new features** (Problem of the Day,
1-vs-1 battles, daily challenges, AI tutor, mobile app, dashboard widgets,
etc.) that need to reuse the question-recommender engine.

> **One rule above all:** consume the engine **through the REST API**.
> Do not import anything from `backend/engine/` or
> `backend/modules/mock_test/*` into your feature module. The engine is
> synchronous and assumes a fully pre-fetched `BufferedRepository` — that
> pre-fetch logic lives only inside `MockTestService` and would need to
> be duplicated everywhere if features bypassed the HTTP layer.

If you follow that rule, internal optimisations (snapshot caches, stats
tables, query plan tuning, even swapping the engine implementation) won't
break your feature.

---

## 1. The public surface

All endpoints live under `/api/v1/mock-test/*` and are protected by
`CurrentVerifiedUser` (the same JWT bearer auth used by `/auth/me`).

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/catalog` | Subject → chapter → topic tree | verified user |
| POST | `/create` | Generate a personalised test | verified user |
| GET | `/session/{session_id}` | Fetch session + questions (resume) | verified user (owner only) |
| POST | `/session/{session_id}/submit` | Submit answers, run grading | verified user (owner only) |
| GET | `/session/{session_id}/result` | Per-question results + solutions | verified user (owner only) |
| GET | `/history` | Past sessions for the current user | verified user |
| GET | `/analytics/overview` | Cross-test stats, trend, weak/strong topics | verified user |
| GET | `/analytics/topics` | Per-topic priority + accuracy | verified user |

JSON payload shapes are defined in
[`backend/modules/mock_test/schema.py`](backend/modules/mock_test/schema.py).
Treat the field names there as the source of truth.

### Error envelope

All errors come back as:

```json
{ "detail": "Human-readable message" }
```

…with the standard HTTP status code. The codes you'll actually see:

| Code | Meaning |
|---|---|
| 400 | Bad input — e.g. empty `topic_ids` |
| 401 | No / invalid JWT |
| 403 | Email not verified |
| 404 | Session not found / not yours |
| 409 | Session already submitted (idempotency guard) |
| 422 | Engine couldn't assemble a test (e.g. no questions in selected topics) |
| 500 | Bug — file an issue |

---

## 2. Stability promise

**Stable** (rely on it):

- The 8 paths above.
- The required-field shape of every request/response model in `schema.py`.
- HTTP status codes for the listed error conditions.
- The grading semantics (Jaccard partial credit for multi_correct,
  matches/total for matching, exact for integer, etc. — documented in
  `DECISIONS.md §5`).

**Additive** (new fields may appear, but won't break you if you ignore
unknown fields):

- Extra optional fields on response models (always added with sensible
  defaults / nullables).
- New endpoints under the same prefix.
- New analytics breakdowns.

**Subject to change** (don't depend on these):

- Exact priority numbers — the engine's tuning constants live in
  `engine/config.py` and may be re-tuned.
- The internal Mongo collection schemas (`mock_test_sessions`,
  `user_topic_attempts`, etc.). Other features must not read or write
  these directly.
- The integer ID mapping (`question_id_map`, `topic_id_map`, etc.) —
  treat returned IDs as opaque tokens that round-trip back to the API.

---

## 3. Auth — boilerplate

Every request needs `Authorization: Bearer <access_token>` from the
same login flow the main app uses.

If you're calling from **inside the same backend process** (e.g. a cron
job, or another feature's controller), don't synthesise a token. Either:

1. Make the user-facing endpoint trigger the API call (e.g. dashboard
   loads → call your service → your service calls the mock-test API
   using the user's existing token), **or**
2. Refactor the orchestration into a shared async function that takes a
   `user_id` and reuses the same Motor DB handle. (We can extract such
   a function from `MockTestService` if a real need arises — ask before
   doing it.)

**Never** invent service-to-service tokens or bypass `CurrentVerifiedUser`.
Server-side grading is the only thing standing between a student and an
inflated priority score.

---

## 4. Recipes for the features you're likely to build

### 4.1 Problem of the Day (POTD)

**Goal:** one carefully chosen practice question per user per day, surfaced
on the dashboard.

**How:**

1. On dashboard load, call `GET /analytics/topics`. Take the top entry —
   that's the topic with the highest priority score (the user's weakest).
2. Call `POST /mock-test/create` with:
   ```json
   { "topic_ids": [<weakest_topic_id>], "total_questions": 1 }
   ```
3. Render the returned question in a mini-card. User answers inline.
4. On submit click, call `POST /mock-test/session/{session_id}/submit` with
   the answer payload in the same shape `TakeTest.jsx` uses.
5. Render the `solution_text` / `solution_image` from the result.

**Idempotency:** store the `session_id` returned in step 2 in user-side
state (e.g. a `potd_<user_id>_<YYYY-MM-DD>` row in your POTD collection)
so a refresh re-uses the same question instead of generating a new one.
If the user has already answered, `GET /result` works; if not yet,
`GET /session/{id}` returns the question payload for resume.

**Don't:** call `/create` every page reload — you'll burn through their
weak-topic question pool. Cache the session id for the day on the POTD
feature's own side.

### 4.2 1-vs-1 battle

**Goal:** two students compete on the same questions.

**How:**

1. When a battle starts, decide topics + count on the host's side.
2. Call `POST /mock-test/create` for **each** player. The engine ranks per
   user — to share questions you have two options:
   - **Easy mode:** call create for player A. Store the resulting
     `(question_id, topic_id, display_order)` tuples in your battle
     state. For player B, build a session by hand by **inserting**
     `mock_test_responses` rows referencing those IDs — but this requires
     reaching into our collections, which violates the boundary rule.
     **Don't do this.**
   - **Right mode:** let each player get their own personalised test. The
     battle is "first to N correct" not "same questions, different
     speed". This stays inside the API contract.
3. Each player submits via `POST /submit` independently.
4. Battle service polls `GET /result` for both, computes winner.

If you need true shared-question battles, that's a feature request on
our side — we'd add a `seed_session_id` to `/create` that copies an
existing session's question set verbatim.

### 4.3 Daily / weekly scheduled challenge

**Goal:** auto-generate a test for each enrolled user on a schedule.

**How:**

1. Maintain an enrolment collection on your feature's side
   (e.g. `daily_challenge_enrolments`).
2. Cron job loops over enrolled users. For each, fetch the user's auth
   context **or** (preferred) build a thin internal helper in
   `MockTestService` that accepts a `user_id: ObjectId` directly. Ask
   before extracting that helper — it's a controlled API extension.
3. Persist the resulting `session_id` in your feature's state.
4. Notify the user (email / push) with a deep link to
   `/tests/{session_id}`.

### 4.4 AI tutor / explainer

**Goal:** answer "why did I get this wrong" or "coach me on my weakest
chapter".

**How:**

1. `GET /analytics/topics` → identifies weak topics by priority score.
2. `GET /history` → recent sessions.
3. For a specific test review, `GET /session/{id}/result` returns
   `user_answer`, `correct_answer`, `solution_text`, `correctness`,
   `question_text`, and options. Everything you need for an LLM prompt.
4. **Never** ask the LLM to grade — grading is already server-side and
   trustworthy. Use the LLM only for explanations.

### 4.5 "Practice your weak topic" dashboard widget

**Goal:** a one-click CTA on the dashboard that opens a test pre-filled
with the user's weakest topics.

**How:**

1. `GET /analytics/topics` on dashboard mount.
2. Pre-fill the URL: `/tests?focus=<topic_id_1>,<topic_id_2>,<topic_id_3>`
   (the `TestsLaunch` page can be extended to read this query param;
   ask before doing it).
3. User reviews and clicks **Generate**.

---

## 5. Hard rules

### Never

- ❌ Import from `backend/engine/*` or `backend/modules/mock_test/*` in
  another feature module.
- ❌ Read or write `mock_test_*` / `user_topic_attempts` /
  `question_id_map` / `topic_id_map` collections directly.
- ❌ Trust a client-supplied `is_correct` value. The grader runs
  server-side; the client only sends the user's raw selection.
- ❌ Re-grade attempts on your feature's side. Use the API's
  `correctness` and `is_correct` fields verbatim.
- ❌ Forge a JWT or use a "service account" token. Every call carries the
  real user's bearer.

### Always

- ✅ Pass through unknown fields in responses — they may carry future
  data your feature will want.
- ✅ Handle 409 on submit (test already submitted). It's idempotent —
  retrying is harmless; just call `/result` instead.
- ✅ Time out individual requests at ~10s. Engine work is bounded and
  fast, but Mongo round-trips can stall under load.
- ✅ Use the `session_id` returned by `/create` as the single key for
  your feature's per-test state. It's a stable `int`, unique per test
  across users.
- ✅ When in doubt, log the `detail` field from a non-2xx response.

---

## 6. Extending the engine API

If your feature genuinely needs something the current API doesn't expose,
treat it as an **additive change**:

1. Open an issue describing the use case.
2. Add a new endpoint or new optional field on an existing schema.
3. Never change the meaning of an existing field.
4. Never narrow the type of an existing field (e.g. `Optional[int]` →
   `int`).
5. New endpoints under `/api/v1/mock-test/*` are fine; cross-cutting
   endpoints belong under their own router.

A few extensions we've already discussed and will likely add when needed:

- `POST /create` accepting an optional `seed_session_id` to clone an
  existing test's question set (enables shared-question 1-vs-1).
- `POST /create` accepting an optional `focus_topic_ids` shortcut that
  weights the engine toward those topics without dropping the others.
- Pagination on `/history` and `/analytics/*` once a user has > 200
  tests.
- A `POST /admin/recompute-analytics` endpoint to rebuild any
  pre-computed stats cache (when we add one) for a given user.

---

## 7. Internal performance — what's coming, and why your code shouldn't care

The current implementation recomputes analytics on the fly. Planned
optimisations include:

- Phase-style pre-computed stats collections (`user_profile_stats`,
  `user_topic_strengths`, `user_chapter_strengths`,
  `user_difficulty_stats`, `user_question_type_stats`) refreshed at submit.
- Session question-payload snapshots inside `mock_test_sessions` to
  avoid rebuilding from raw bbd_db docs on every `/session` /
  `/result` read.
- Catalog tree caching.

**These won't change any field your feature reads.** The API contract is
exactly the same; the endpoints will just respond faster. If you build
on the API today, your feature gets the speed-ups for free tomorrow.

---

## 8. Quick reference — example calls

### Create a 10-question test on three topics

```bash
curl -X POST $API_BASE/api/v1/mock-test/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "topic_ids": [12, 47, 81], "total_questions": 10 }'
```

### Submit answers

```bash
curl -X POST $API_BASE/api/v1/mock-test/session/$SID/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "answers": [
      { "question_id": 101, "selected_option": "B" },
      { "question_id": 102, "selected_options": ["A", "C"] },
      { "question_id": 103, "integer_answer": 42 },
      { "question_id": 104, "matching": { "L1": "R2", "L2": "R1" } }
    ]
  }'
```

### Read user's weakest topics

```bash
curl $API_BASE/api/v1/mock-test/analytics/topics \
  -H "Authorization: Bearer $TOKEN"
```

The top entry in the returned `topics` array (already sorted by priority
DESC) is the topic to recommend next.

---

## 9. Who owns what

| Concern | Owner | Source |
|---|---|---|
| Algorithm correctness | `backend/engine/*` (vendored) | INTEGRATION.md, README.md in `recommender/` |
| Mock-test API | `backend/modules/mock_test/*` | This module's `controller.py` + `schema.py` |
| Question content | bbd_db (`questions` collection) | bbd_db creation pipeline |
| New feature using the API | The new feature's module | Talks to this API only over HTTP |

When a question of "should this live in the mock-test module or in my
feature's module?" comes up, the answer is almost always: **your
feature's module, and it talks to the mock-test API.** Keep the engine
and its module focused on one job.

---

## 10. Getting help

- Algorithm questions: `recommender/README.md` and `recommender/INTEGRATION.md`.
- API shape questions: `backend/modules/mock_test/schema.py`.
- Why-was-this-decided questions: `DECISIONS.md` at the repo root.
- Anything else: ping the engine maintainer before reaching into internal
  collections or vendored modules.
