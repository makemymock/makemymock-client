# Backend Folder Structure

FastAPI + MongoDB (Motor async driver) backend for **MakeMyMock**.
This document describes the conventions every new feature/module must follow so the codebase stays consistent.

---

## Top-level layout

```
backend/
├── api/                  # Aggregates module routers under one APIRouter
├── config/               # Settings (.env) + MongoDB client/lifespan
├── core/                 # Cross-cutting concerns shared by all modules
├── engine/               # Vendored synchronous question-recommender library
│                         # (priority/decay/progression). Called only by
│                         # modules/mock_test/.
├── modules/              # Feature modules (one folder per domain)
│   ├── authentication/   # Signup, OTP, login, refresh, /me
│   ├── profile/          # Student profile setup + retrieval
│   ├── mock_test/        # Test create/submit/result/history/analytics,
│   │                     #   Browse catalog, notebook. Sole engine caller.
│   ├── potd/             # Problem of the Day + streak
│   ├── battle/           # 1-vs-1 REST + WebSocket matchmaking & play
│   ├── contest/          # Scheduled contests (lobby + play + leaderboard).
│   │                     #   Admin writes to `contests`; this module owns
│   │                     #   `contest_participations` + `contest_responses`.
│   └── solverx/          # SSE-streamed LLM solver/tutor (Vertex AI)
├── services/             # Reserved for cross-module orchestration services
├── main.py               # FastAPI app factory + lifespan + global handlers
├── requirements.txt
├── .env                  # Real secrets (gitignored)
└── .env.example          # Template
```

---

## Layer responsibilities

### `config/`
- `settings.py` — Pydantic v2 `BaseSettings` reading from `.env`. Add new env vars here as typed fields.
- `database.py` — Motor client lifecycle, connection pool, index creation in `_ensure_indexes()`. Add new indexes here.

### `core/`
Reusable infrastructure. Modules import **from** core, never the reverse.

- `security.py` — bcrypt `hash_password` / `verify_password`.
- `jwt_handler.py` — access + refresh token `create_*` / `decode_token`.
- `email.py` — `send_email`, Jinja2 template rendering, `send_otp_email`.
- `exceptions.py` — domain `HTTPException` subclasses (`AppException` base).
- `dependencies.py` — `DBDep`, `CurrentUser`, `CurrentVerifiedUser`, `oauth2_scheme`.

### `modules/<feature>/`
Every feature module follows the **controller → service → repository** pattern:

| File | Responsibility |
|---|---|
| `controller.py` | `APIRouter`, route definitions, request/response models. **No business logic.** |
| `service.py` | Business logic, orchestration, calls repositories, raises domain exceptions. |
| `repository.py` | Direct MongoDB access for this module's collections. **No business logic.** |
| `schema.py` | Pydantic v2 request/response models + reusable type aliases. |
| `model.py` | Document factories (`new_*_doc`) and domain constants for Mongo docs. |
| `utils.py` *(optional)* | Pure helper functions specific to this module. |
| `constants.py` *(optional)* | Collection names, magic numbers. |
| `email_templates/` *(optional)* | Jinja2 HTML templates if the module sends emails. |

### `api/__init__.py`
Imports each module's `router` and combines them into a single `api_router`. **Register your new module's router here.**

### `main.py`
Mounts `api_router` under `settings.API_V1_PREFIX` (`/api/v1`), wires CORS, registers `AppException` and `ValidationError` handlers, and runs `connect_to_mongo` / `close_mongo_connection` via `lifespan`.

### `services/`
Reserved for **cross-module** services (e.g. notification fan-out, analytics) that don't belong inside a single feature module. Leave empty until you actually need one.

### `engine/`
A vendored, **synchronous** question-recommender library. Holds priority weights, decay thresholds, and progression bands in [`config.py`](engine/config.py); pure value-object I/O via a `Repository` protocol ([`repository.py`](engine/repository.py)). **Only** [`modules/mock_test/`](modules/mock_test/) is allowed to import it — other features must go through `mock_test`'s HTTP API. The sync↔async bridge lives in [`modules/mock_test/engine_adapter.py`](modules/mock_test/engine_adapter.py).

---

## Conventions (must follow)

1. **Async everywhere.** Use Motor, `aiosmtplib`, `async def` for routes/services/repos.
2. **Pydantic v2 only** — `model_config = ConfigDict(...)`, `model_dump()`, `Annotated[str, StringConstraints(...)]`.
3. **Dependency injection for DB access.** Never call `get_database()` directly inside services. Routes take `db: DBDep`; the controller passes it to `Service(db)`.
4. **Auth on protected routes** via `CurrentUser` (any logged-in user) or `CurrentVerifiedUser` (email-verified only).
5. **Raise domain exceptions** from `core/exceptions.py`. Add a new subclass there if a needed error doesn't exist — don't raise generic `HTTPException` inside services.
6. **MongoDB doc creation** goes through a `new_*_doc()` factory in `model.py` so timestamps and shape stay consistent.
7. **Collection names** live in `constants.py`. Indexes are defined in `config/database.py:_ensure_indexes()`.
8. **ObjectId boundary handling**: services accept/return `ObjectId`; controllers/schemas use `str`. Serialize via `str(doc["_id"])` or `serialize_mongo_doc`.
9. **Routes return Pydantic response models**, never raw dicts.
10. **Secrets**: only via `config.settings.settings`. Never read `os.environ` outside `settings.py`.

---

## Adding a new module (checklist)

To add a `notes` module (example):

1. `modules/notes/` with `__init__.py`, `controller.py`, `service.py`, `repository.py`, `schema.py`, `model.py`.
2. Add `NOTES_COLLECTION = "notes"` to `modules/notes/constants.py` (or reuse a shared constants file).
3. Add any required indexes to `config/database.py:_ensure_indexes()`.
4. Define request/response schemas in `schema.py`.
5. Implement `NotesRepository` (Mongo I/O only).
6. Implement `NotesService` (business logic, raises from `core/exceptions.py`).
7. Build `router = APIRouter(prefix="/notes", tags=["Notes"])` in `controller.py`, depending on `DBDep` + `CurrentVerifiedUser`.
8. Register the router in `api/__init__.py`:
   ```python
   from modules.notes.controller import router as notes_router
   api_router.include_router(notes_router)
   ```
9. Add any new env vars to `config/settings.py` **and** `.env.example`.

---

## Request lifecycle (reference)

```
HTTP request
   │
   ▼
main.py  ──►  api_router  ──►  modules/<feature>/controller.py
                                   │
                                   ▼
                              service.py   ◄── core/ (security, jwt, email, exceptions)
                                   │
                                   ▼
                              repository.py
                                   │
                                   ▼
                              MongoDB (via Motor, from config/database.py)
```

Errors raised in services propagate up; `main.py`'s `AppException` handler turns them into clean JSON responses.

---

## Tech stack reference

- **Framework**: FastAPI
- **DB**: MongoDB Atlas via Motor (async pymongo)
- **Validation**: Pydantic v2 + `pydantic-settings`
- **Auth**: JWT (`python-jose`) + bcrypt (`passlib[bcrypt]`)
- **Email**: `aiosmtplib` + Jinja2 templates
- **Python**: 3.11+
