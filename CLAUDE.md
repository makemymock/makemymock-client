# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**MakeMyMock** — an edtech mock-test platform with a personalised question recommender. The student picks topics, the engine builds a test weighted toward their weakest areas (highest **priority score**), grades the submission server-side, and feeds the result back into per-topic / per-chapter / per-subject analytics that drive the next test.

Two top-level packages:
- [backend/](backend/) — FastAPI + MongoDB (Motor async) API
- [frontend/](frontend/) — React 19 + Vite + PWA SPA

## Common commands

### Backend (run from [backend/](backend/))

```powershell
# install
pip install -r requirements.txt

# dev server (hot reload). Reads .env from the cwd.
uvicorn main:app --reload --port 8000
```

API docs at http://localhost:8000/docs. Health at `/health`. All feature routes are mounted under `settings.API_V1_PREFIX` (default `/api/v1`).

There is no test runner wired up on the backend yet — `requirements.txt` does not include pytest, and the engine has no test suite checked in here.

### Frontend (run from [frontend/](frontend/))

```powershell
npm install
npm run dev        # vite on :3000, auto-opens browser
npm run build      # production build to dist/
npm run preview    # serve the built dist/
npm run lint       # eslint . (flat config in eslint.config.js)
npm test           # vitest (jsdom env, configured in vite.config.js)
npx vitest path/to/file.test.jsx   # single test file
```

`VITE_API_BASE_URL` (in `frontend/.env`) must point at the backend, e.g. `http://localhost:8000/api/v1`.

## Backend architecture

FastAPI app factory in [backend/main.py](backend/main.py) wires CORS, the `AppException` / `ValidationError` handlers, and the Motor `connect_to_mongo` / `close_mongo_connection` lifespan. Routers from each module are aggregated in [backend/api/__init__.py](backend/api/__init__.py) and mounted under `/api/v1`.

### Layered conventions (see [backend/folder_structure.md](backend/folder_structure.md))

Every feature lives under `backend/modules/<feature>/` and follows **controller → service → repository**:

- `controller.py` — `APIRouter`, route signatures, request/response Pydantic models. No business logic.
- `service.py` — orchestration, raises domain exceptions from `core/exceptions.py`.
- `repository.py` — direct Motor I/O for the module's collections.
- `schema.py` — Pydantic v2 request/response models (the source of truth for API shape).
- `model.py` — `new_*_doc()` factories that produce Mongo documents.
- `constants.py` — collection names, counter ids, tuning numbers.

Cross-cutting helpers live in [backend/core/](backend/core/): `security.py` (bcrypt), `jwt_handler.py`, `email.py` (aiosmtplib + Jinja), `exceptions.py` (`AppException` base + subclasses), `dependencies.py` (`DBDep`, `CurrentUser`, `CurrentVerifiedUser`, `oauth2_scheme`).

Settings + DB lifecycle live in [backend/config/](backend/config/). All Mongo indexes are created in [backend/config/database.py](backend/config/database.py) inside `_ensure_indexes()` — **add new indexes there**, not ad-hoc inside repositories. Secrets only come from `config.settings.settings`, never `os.environ`.

### Feature modules

- [`authentication/`](backend/modules/authentication/) — signup, OTP verify, login, refresh, `me`. Sends OTP email via [core/email.py](backend/core/email.py) + module-local [email_templates/](backend/modules/authentication/email_templates/).
- [`profile/`](backend/modules/profile/) — student profile setup + retrieval (target exam, year, etc.).
- [`mock_test/`](backend/modules/mock_test/) — test creation, submission, results, history, analytics, Browse catalog, notebook, view-solution. **Only caller of the recommender [engine/](backend/engine/).**
- [`potd/`](backend/modules/potd/) — Problem of the Day: `today`, `attempt`, `view-solution`, `streak`, `history`, past-date lookup. Owns `potd_assignments` + `potd_user_state`.
- [`battle/`](backend/modules/battle/) — 1-vs-1 matchmaking + live play. REST (`/battle/history`, `/battle/{id}`) + WebSocket (`/battle/ws?token=…`) with a documented message protocol; matchmaking state lives in [matchmaker.py](backend/modules/battle/matchmaker.py). Persists battle replays to `battles`.
- [`solverx/`](backend/modules/solverx/) — multi-agent LLM solver/tutor over **Vertex AI** (`google-genai`). Two Server-Sent Events endpoints (`/solverx/solve`, `/solverx/theory`) stream status + content tokens; conversation history at `/solverx/conversations`. LaTeX is normalised in [latex_normalize.py](backend/modules/solverx/latex_normalize.py); prompts in [prompts.py](backend/modules/solverx/prompts.py).
- [`contest/`](backend/modules/contest/) — scheduled contests (Admin creates them; Client serves participants). Lobby gate opens 5 min before `start_time`; `/start` returns the question payload + server timer; `/submit` grades with the per-contest marking scheme (`+correct / wrong / unattempted`), persists `contest_participations` + `contest_responses`, and computes rank. Grader lives in [grader.py](backend/modules/contest/grader.py) — pure functions duplicated from mock_test (single/multi/integer/matching; passages excluded in v1).

### Hard rules

1. Async everywhere — Motor, `aiosmtplib`, `async def` on routes/services/repos.
2. Pydantic v2 only — `model_config = ConfigDict(...)`, `model_dump()`, `Annotated[..., StringConstraints(...)]`.
3. Routes take `db: DBDep` and pass it to `Service(db)`. Never call `get_database()` inside services.
4. Raise domain exceptions from `core/exceptions.py` — extend that file rather than raising raw `HTTPException` in services.
5. Mongo docs go through `new_*_doc()` factories so timestamps and shape stay consistent.
6. ObjectId boundary: services accept/return `ObjectId`; controllers/schemas use `str`. Serialize via `str(doc["_id"])`.
7. Auth on protected routes via `CurrentUser` (logged in) or `CurrentVerifiedUser` (email-verified).
8. Routes return Pydantic response models, never raw dicts. **Exceptions**: SolverX SSE endpoints return `StreamingResponse(media_type="text/event-stream")`, and the battle WebSocket route streams JSON messages directly (see protocol in [battle/controller.py](backend/modules/battle/controller.py)).

To register a new module: implement the module, then add `api_router.include_router(...)` in [backend/api/__init__.py](backend/api/__init__.py), add any indexes in [backend/config/database.py](backend/config/database.py), and add any new env vars to **both** `.env.example` and `config/settings.py`.

### The recommender engine — boundary rule

[backend/engine/](backend/engine/) is a vendored, **synchronous** question-recommender library. It assumes a fully pre-fetched [`Repository`](backend/engine/repository.py) protocol and returns `MockTest` / `SubmissionResult` value objects. Tuning constants (priority weights, decay thresholds, progression bands) live in [backend/engine/config.py](backend/engine/config.py).

[`modules/mock_test/`](backend/modules/mock_test/) is the **only** caller of the engine. It bridges Motor (async) to the engine (sync) via:

- [`engine_adapter.py`](backend/modules/mock_test/engine_adapter.py) — `BufferedRepository` that satisfies the engine's `Repository` protocol against pre-fetched lists + a pre-allocated `session_id`. The service drains write buffers back to Motor after the engine returns.
- [`grader.py`](backend/modules/mock_test/grader.py) — server-side answer evaluation (single/multi/integer/matching/passage). Never trust client-supplied correctness.
- [`service.py`](backend/modules/mock_test/service.py) — orchestrates create / submit / result / analytics.

**Other modules MUST consume mock-test through its REST API** — see [USING_THE_ENGINE.md](USING_THE_ENGINE.md) for the full contract, recipes (POTD, 1-vs-1, scheduled challenges, AI tutor, weak-topic widget), and the list of collections (`mock_test_*`, `user_topic_attempts`, `question_id_map`, `topic_id_map`, etc.) that are off-limits to other features. Internal optimisations (snapshot caches, recomputed stats, engine swaps) won't break consumers as long as they stay on the HTTP boundary.

### ID indirection

The bbd_db `questions` catalog uses Mongo ObjectIds, but the engine works in integers. [`question_id_map`](backend/config/database.py) / `topic_id_map` / `chapter_id_map` / `subject_id_map` collections (one counter doc per family in `id_counters`) translate between the two. Passage sub-questions get their own int ids keyed by `(obj_id, sub_index)`. Treat returned integer IDs as opaque round-trip tokens.

## Frontend architecture

React 19 + Vite + `vite-plugin-pwa` SPA. CSS Modules for styling. **No Tailwind / Bootstrap / MUI / Redux** — state is React hooks; cross-page state is localStorage or refetch. See [frontend/folder_structure.md](frontend/folder_structure.md) for the full conventions.

Pages (see [routes/AppRoutes.jsx](frontend/src/routes/AppRoutes.jsx)):
- Public: `/` (`landing/`), `/signup`, `/login`.
- Pre-shell protected: `/profile/setup` (renders before the AppLayout chrome — user has no profile yet).
- Inside [AppLayout](frontend/src/components/layout/AppLayout.jsx): `/dashboard`, `/tests` + `/tests/browse/:questionId`, `/tests/:sessionId` (TakeTest) + `/result`, `/analytics` + `/analytics/chapter/:id` + `/analytics/topic/:id`, `/history`, `/compete` (hub), `/battle/play` + `/battle/history`, `/contest/:id` (lobby) + `/contest/:id/play` (fullscreen) + `/contest/:id/result`, `/solverx`. Active test, live battle, active contest play, and SolverX bypass the chrome via `AppLayout`'s `FULLSCREEN_RE`. Legacy `/battle` redirects to `/compete?tab=battle`.

The `/compete` hub ([pages/compete/Compete.jsx](frontend/src/pages/compete/Compete.jsx)) renders three tabs in one screen: **Battle** (queue + recent), **Contest** (live / upcoming / past cards with countdown), and **Leaderboard** (contest picker → ranked table). Tab state is mirrored to the `?tab=` query string so deep links from elsewhere (e.g. `/compete?tab=leaderboard`) land on the right pane.

Component folders: [components/common/](frontend/src/components/common/) (primitives + charts: `Button`, `InputField`, `SelectField`, `Loader`, `ErrorMessage`, `StatCard`, `BarChart`, `LineChart`, `DonutChart`, `Heatmap`, `ConfidenceTrophy`, `DashboardFab`, `MarkdownText`, `ThemeToggle`, `ThemeToggleFab`), [components/auth/](frontend/src/components/auth/) (`AuthLayout`, `OTPModal`, `PasswordInput`), [components/layout/](frontend/src/components/layout/) (`AppLayout`), [components/landing/](frontend/src/components/landing/), [components/dashboard/](frontend/src/components/dashboard/) (`PotdModal`), [components/mockTest/](frontend/src/components/mockTest/) (`ExamShell`, `QuestionViewer`, `QuestionPalette`, `MatchingEditor`, `SubmitDialog`, `Timer`), [components/solverx/](frontend/src/components/solverx/) (`MessageBlock`).

[hooks/useTheme.js](frontend/src/hooks/useTheme.js) owns light/dark theme state. [utils/examDraft.js](frontend/src/utils/examDraft.js) persists in-progress test answers to localStorage so a refresh during a test doesn't lose work.

### Layer rules

- **`services/` owns all HTTP.** Components never import axios directly. [`axiosInstance.js`](frontend/src/services/axiosInstance.js) is the single configured client — attaches `Authorization: Bearer <token>` from `tokenStorage`, and on 401 calls `/auth/refresh-token` (single-flight) and retries the original request once. If refresh fails, clears storage and redirects to `/login`. Auth endpoints are excluded from refresh so their 401s surface to the form.
- **`utils/token.js` owns localStorage.** Token keys are namespaced `mmm_access_token`, `mmm_refresh_token`, `mmm_user`. Never call `localStorage.*` directly.
- **`utils/validators.js`** — validators return `''` on success, a human-readable string on failure. `parseApiError(error, fallback)` extracts the FastAPI `detail` field (handles the pydantic list form too).
- **Routes live in one place.** [`routes/AppRoutes.jsx`](frontend/src/routes/AppRoutes.jsx) is the only `<Routes>` block. Wrap protected pages in `<ProtectedRoute>` (checks `tokenStorage.isAuthenticated()`, stashes original location in `state.from`). Wrap auth pages in `<RedirectIfAuthed>` so logged-in users don't see `/login`/`/signup`.
- **Pages own their CSS module** (`<page>.module.css`, lowercase). Reusable components own theirs PascalCase. No inline styles, no global CSS for pages, no preprocessors.
- **Mobile-first**: default styles target mobile, scale up with `@media (min-width: …)`. Use `clamp()` for fluid typography.
- **Form pattern**: one `form` object, one `errors` object, one top-level `formError` for API failures. Validate on blur + submit, clear field error on next change, render backend errors through `parseApiError`.
- **Env vars** must start with `VITE_`, be added to both `.env` and `.env.example`, and only be read inside `services/` via `import.meta.env.VITE_*`.

### Auth/token flow

1. Signup → backend emails OTP → frontend opens `OTPModal`.
2. `POST /auth/verify-otp` → response `{user, tokens}` → `tokenStorage.setSession()` → redirect to `/dashboard`.
3. Login → same `{user, tokens}` shape → redirect to `state.from` or `/dashboard`.
4. Authenticated request → interceptor adds bearer.
5. 401 → single-flight `/auth/refresh-token` → retry original. Refresh failure clears storage and routes to `/login`.
6. Logout → `tokenStorage.clear()` + navigate to `/login`. Stateless JWT, no server call.

## Database collections (reference)

User/auth: `users`, `student_profiles`, `email_otps` (TTL-expired by `expires_at`).

Mock-test (owned by `modules/mock_test/`, **off-limits to other modules**):
- `mock_test_sessions` — one doc per test, status pending/completed, score/correct/incorrect/partial.
- `mock_test_topics` — per-session topic allocations with priority + decay.
- `mock_test_responses` — one row per (session_id, question_id), unique; carries `display_order`, `is_correct`, `correctness`, `user_answer`.
- `user_topic_attempts` — unique on (user_id, question_id) so retakes overwrite (the engine's `upsert_attempts` relies on this).
- `practice_solution_views` — unique on (user_id, obj_id). Marker that the user revealed a question's solution in Browse; kept separate from `user_topic_attempts` so a peeked question never feeds the recommender.
- `notebook_entries` — unique on (user_id, obj_id). Questions a user marked to revise later.
- `question_id_map` / `topic_id_map` / `chapter_id_map` / `subject_id_map` / `id_counters` — int ↔ ObjectId / triple indirection.

POTD (owned by `modules/potd/`):
- `potd_assignments` — unique on (user_id, date_ist). Today's POTD per user.
- `potd_user_state` — unique on (user_id, date_ist). Engagement state (attempted / solved / viewed-solution) for streak + calendar.

Battle (owned by `modules/battle/`):
- `battles` — one doc per completed 1-vs-1, with full per-round replay. Indexed for either player's history sort.

SolverX (owned by `modules/solverx/`):
- `solverx_conversations` — per-user, sorted by `updated_at` for the sidebar.
- `solverx_messages` — join back to conversation via `conversation_id`, ordered by `created_at`.

Contests (split ownership — see [`contest/`](backend/modules/contest/) note above):
- `contests` — **written by the Admin backend**, read by Client. Indexed on `start_time` + `end_time` (also serves the no-overlap check).
- `contest_participations` — unique on (contest_id, user_id). Owned by Client `contest/`. Leaderboard sort uses a compound index on (contest_id, score, time_taken_seconds).
- `contest_responses` — unique on (contest_id, user_id, question_id). Owned by Client `contest/`. The per-question review on the result page reads in `display_order`.

Question catalog (read-only, `bbd_db` schema): `questions`, indexed on `(subject, chapter, topic)`.

## Conventions worth knowing

- `ObjectId` is converted to a deterministic `UUID` (via `_user_uuid_from_object_id` in `mock_test/service.py`) before being handed to the engine, since engine models declare `user_id: UUID`. Same input → same UUID.
- Display-order rule for mixed test types (frontend + backend agree): `single → multi → passage → matching → integer`; encoded in `_TYPE_RANK` and re-applied on the frontend at render time.
- Timer: `SECONDS_PER_QUESTION = 90` ([modules/mock_test/constants.py](backend/modules/mock_test/constants.py)).
- **Recommender cooldown**: `RECOMMENDER_COOLDOWN_HOURS = 24`. If a user touches a question (attempt or view-solution) and re-attempts within this window, the answer is still graded for the student but does **not** update recommender priorities. Prevents recently-peeked questions from inflating decay metrics.
- Question types: `single_correct`, `multi_correct`, `integer`, `matching`, `passage` (passages decompose into per-sub `single_correct` engine questions).
- Grading semantics: Jaccard partial credit for multi_correct; matches/total for matching; exact for integer; binary for single_correct and passage sub-Qs. Documented in [GRADING_POLICY.md](GRADING_POLICY.md).
