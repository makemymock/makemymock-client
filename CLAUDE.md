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

### Hard rules

1. Async everywhere — Motor, `aiosmtplib`, `async def` on routes/services/repos.
2. Pydantic v2 only — `model_config = ConfigDict(...)`, `model_dump()`, `Annotated[..., StringConstraints(...)]`.
3. Routes take `db: DBDep` and pass it to `Service(db)`. Never call `get_database()` inside services.
4. Raise domain exceptions from `core/exceptions.py` — extend that file rather than raising raw `HTTPException` in services.
5. Mongo docs go through `new_*_doc()` factories so timestamps and shape stay consistent.
6. ObjectId boundary: services accept/return `ObjectId`; controllers/schemas use `str`. Serialize via `str(doc["_id"])`.
7. Auth on protected routes via `CurrentUser` (logged in) or `CurrentVerifiedUser` (email-verified).
8. Routes return Pydantic response models, never raw dicts.

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
- `question_id_map` / `topic_id_map` / `chapter_id_map` / `subject_id_map` / `id_counters` — int ↔ ObjectId / triple indirection.

Question catalog (read-only, `bbd_db` schema): `questions`, indexed on `(subject, chapter, topic)`.

## Conventions worth knowing

- `ObjectId` is converted to a deterministic `UUID` (via `_user_uuid_from_object_id` in `mock_test/service.py`) before being handed to the engine, since engine models declare `user_id: UUID`. Same input → same UUID.
- Display-order rule for mixed test types (frontend + backend agree): `single → multi → passage → matching → integer`; encoded in `_TYPE_RANK` and re-applied on the frontend at render time.
- Timer: `SECONDS_PER_QUESTION = 90` ([modules/mock_test/constants.py](backend/modules/mock_test/constants.py)).
- Question types: `single_correct`, `multi_correct`, `integer`, `matching`, `passage` (passages decompose into per-sub `single_correct` engine questions).
- Grading semantics: Jaccard partial credit for multi_correct; matches/total for matching; exact for integer; binary for single_correct and passage sub-Qs. Documented in `DECISIONS.md §5` (referenced but not in repo yet).
