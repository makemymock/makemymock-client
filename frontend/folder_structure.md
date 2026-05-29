# Frontend Folder Structure

React (Vite + PWA) frontend for **MakeMyMock**. Talks to the FastAPI backend over HTTP, uses **CSS Modules** for styling, **Axios** for HTTP, **React Router DOM** for routing, and **React hooks** for state. No Tailwind, no Bootstrap, no MUI, no Redux.

This document describes the conventions every new page/feature must follow so the codebase stays consistent.

---

## Top-level layout

```
frontend/
├── public/                      # Vite static shell (favicon, manifest, PWA icons)
├── src/
│   ├── assets/                  # Static images / icons imported by components
│   ├── components/              # Reusable UI — never page-specific
│   │   ├── common/              # Primitives + charts (Button, InputField, SelectField,
│   │   │                        #   Loader, ErrorMessage, StatCard, BarChart, LineChart,
│   │   │                        #   DonutChart, Heatmap, ConfidenceTrophy, DashboardFab,
│   │   │                        #   MarkdownText, ThemeToggle, ThemeToggleFab)
│   │   ├── auth/                # AuthLayout, OTPModal, PasswordInput
│   │   ├── layout/              # AppLayout (sidebar + outlet; FULLSCREEN_RE bypasses
│   │   │                        #   the chrome for active tests, battles, SolverX)
│   │   ├── landing/              # Marketing hero / FAQ / footer sections
│   │   ├── dashboard/           # PotdModal
│   │   ├── mockTest/            # ExamShell, QuestionViewer, QuestionPalette,
│   │   │                        #   MatchingEditor, SubmitDialog, Timer
│   │   └── solverx/             # MessageBlock
│   ├── pages/                   # One folder per route, owns its own .module.css
│   │   ├── landing/             # / (public)
│   │   ├── signup/  login/      # public auth
│   │   ├── profile/             # /profile/setup (protected, pre-shell)
│   │   ├── dashboard/  history/
│   │   ├── tests/               # TestsLaunch, TakeTest, Result, BrowseQuestion
│   │   ├── analytics/           # Analytics, ChapterAnalytics, TopicAnalytics
│   │   ├── battle/              # BattleLaunch (legacy), BattleArena, BattleHistory
│   │   ├── compete/             # Compete hub (3-tab) + ContestLobby /
│   │   │                        #   ContestPlay (fullscreen) / ContestResult
│   │   └── solverx/             # SolverX chat surface
│   ├── routes/                  # Router config + route guards
│   │   ├── AppRoutes.jsx
│   │   └── ProtectedRoute.jsx
│   ├── services/                # All network I/O. Components NEVER call axios directly.
│   │   ├── axiosInstance.js
│   │   ├── authService.js
│   │   ├── profileService.js
│   │   ├── mockTestService.js
│   │   ├── potdService.js
│   │   ├── battleService.js
│   │   ├── contestService.js
│   │   └── solverxService.js
│   ├── hooks/                   # useTheme (light/dark)
│   ├── context/                 # Reserved — empty today
│   ├── utils/                   # Pure, framework-free helpers
│   │   ├── token.js             # mmm_* localStorage keys
│   │   ├── validators.js
│   │   └── examDraft.js         # In-progress test answers persisted to localStorage
│   ├── App.jsx                  # BrowserRouter + AppRoutes
│   ├── App.css                  # Focus styles + small app-level globals
│   ├── main.jsx                 # ReactDOM root (Vite entry)
│   └── index.css                # Page-level body defaults
├── index.html                   # Vite HTML entry (lives at project root, not in public/)
├── vite.config.js               # Vite + vite-plugin-pwa config
├── .env                         # VITE_API_BASE_URL (gitignored)
├── .env.example                 # Template
└── package.json
```

---

## Layer responsibilities

### `services/`
All HTTP traffic lives here. **Components and pages NEVER import axios directly** — they import a service.

- `axiosInstance.js` — the single configured Axios client. Reads `VITE_API_BASE_URL` (via `import.meta.env`), attaches `Authorization: Bearer <token>` from `tokenStorage` on every request, and on `401` automatically calls `/auth/refresh-token` (single-flight, no stampede) and retries the original request. If refresh fails, it clears storage and redirects to `/login`. Auth endpoints (`/auth/login`, `/auth/signup`, etc.) are excluded from refresh so their 401s surface to the form.
- `authService.js` — typed wrapper around `/auth/*` endpoints (`signup`, `verifyOtp`, `resendOtp`, `login`, `me`, `logout`). Handles writing tokens to storage on successful auth.
- **New domains get a new service file** (e.g. `testService.js`, `profileService.js`). Each service `import api from './axiosInstance'` and exports named methods that return `data` (not the full Axios response).

### `utils/`
Pure functions, no React, no axios. Safe to import anywhere.

- `token.js` — `tokenStorage` object: `getAccessToken`, `getRefreshToken`, `getUser`, `setSession`, `setTokens`, `clear`, `isAuthenticated`. localStorage keys are namespaced (`mmm_*`).
- `validators.js` — field validators (`validateEmail`, `validateUsername`, `validatePassword`, `validateConfirmPassword`, `validateOtp`, `validateLoginPassword`) that return `''` on success and a human-readable error string on failure. Also `parseApiError(error, fallback)` to extract the FastAPI `detail` string (or first item if pydantic returns a list).

### `components/common/`
Reusable, presentational primitives. **Never know about routes, services, or business logic.** Receive everything via props.

| Component | Purpose |
|---|---|
| `Button` | CTA. Variants: `primary` (gradient), `outline` (pill), `ghost`. Supports `loading`, `disabled`, `fullWidth`. |
| `InputField` | Labeled text input with error slot, `useId`-based a11y wiring, and a `rightAdornment` slot. |
| `SelectField` | Labeled dropdown with the same a11y wiring as `InputField`. |
| `Loader` | Spinner. `fullscreen` prop for overlay mode. |
| `ErrorMessage` | Tinted error pill. Renders nothing when `message` is empty. |
| `StatCard` | Headline + value + sub-label for dashboard/analytics tiles. |
| `BarChart` / `LineChart` / `DonutChart` / `Heatmap` | SVG-based analytics charts. |
| `ConfidenceTrophy` | Gamified Confidence Score badge (trophy tier + score). |
| `DashboardFab` / `ThemeToggleFab` | Floating action buttons surfaced on most pages. |
| `ThemeToggle` | Light/dark switch wired to `hooks/useTheme.js`. |
| `MarkdownText` | Renders Markdown + GFM + KaTeX (used by SolverX, solutions). |

### `components/auth/`
Reusable components that are specific to the auth flow but still presentational where possible.

| Component | Purpose |
|---|---|
| `AuthLayout` | The two-column shell used by both Login & Signup. Header (logo + CTA pill), left hero card (title + features + footer), right `formCard` for `children`. Drives the responsive collapse. |
| `PasswordInput` | Wraps `InputField` and adds an eye-icon show/hide toggle. |
| `OTPModal` | 6-digit OTP entry. Owns its own state: autotab, backspace, paste, expiry countdown, resend, Enter-to-submit. Calls `authService.verifyOtp` / `resendOtp` and reports back via `onVerified`. |

### `components/layout/`
- `AppLayout` — global shell rendered as the parent of every protected route. Sidebar nav + `<Outlet>`. The `FULLSCREEN_RE` constant strips the chrome for active mock tests (`/tests/:sessionId`), live battles (`/battle/play`), and SolverX (`/solverx`) so those screens take the full viewport.

### `components/dashboard/`, `components/landing/`, `components/mockTest/`, `components/solverx/`
Feature-scoped components that are too page-specific for `common/` but get reused across multiple files in the same feature.

- `dashboard/` — `PotdModal` (today's Problem of the Day).
- `landing/` — `HeroSection`, `FAQSection`, `FAQ`-style cards, footer, etc.
- `mockTest/` — `ExamShell`, `QuestionViewer`, `QuestionPalette`, `MatchingEditor`, `SubmitDialog`, `Timer`.
- `solverx/` — `MessageBlock` (SSE-streamed message bubble with markdown + KaTeX).

### `hooks/`
- `useTheme.js` — light/dark mode state + localStorage persistence. Wraps `<html data-theme>` flips.

### `context/`
Reserved for future `Context` providers. Empty today — cross-page state is localStorage or refetch.

### `pages/<route>/`
One folder per route. **Pages own their CSS module** (lowercase: `login.module.css`, `dashboard.module.css`, etc.). Pages compose `common/` + feature components, call services, manage form state, and navigate.

| Page | Route | Responsibilities |
|---|---|---|
| `Landing` | `/` | Marketing landing surface (hero, features, FAQ, footer). |
| `Signup` | `/signup` | Username/Email/Password/Confirm → `authService.signup` → opens `OTPModal` → on verify, navigates to `/dashboard`. |
| `Login` | `/login` | Email/Password form → `authService.login` → navigates to `state.from` or `/dashboard`. |
| `ProfileSetup` | `/profile/setup` *(protected, pre-shell)* | Collects target exam, year, etc. Renders **outside** `AppLayout` because the user has no profile yet. |
| `Dashboard` | `/dashboard` *(protected)* | Greeting, Confidence Score trophy, POTD modal trigger, recent activity tiles. |
| `TestsLaunch` | `/tests` *(protected)* | Subject → chapter → topic picker, test config, kickoff via `mockTestService.createTest`. |
| `BrowseQuestion` | `/tests/browse/:questionId` *(protected)* | Browse-mode practice on a single catalog question. |
| `TakeTest` | `/tests/:sessionId` *(protected, fullscreen)* | Active mock test — palette, timer, autosave drafts via `utils/examDraft.js`. |
| `Result` | `/tests/:sessionId/result` *(protected)* | Score, breakdown, question-by-question review. |
| `Analytics` | `/analytics` *(protected)* | Overview + topic + chapter analytics, activity heatmap. |
| `ChapterAnalytics` / `TopicAnalytics` | `/analytics/chapter/:id` + `/analytics/topic/:id` *(protected)* | Drill-down views. |
| `History` | `/history` *(protected)* | List of past mock tests. |
| `BattleArena` / `BattleHistory` | `/battle/play`, `/battle/history` *(protected)* | Fullscreen live WebSocket arena and past replays. The legacy `/battle` route redirects to the Compete hub's Battle tab. |
| `Compete` | `/compete` *(protected)* | Hub page with three tabs — **Battle** (queue + recent), **Contest** (live / upcoming / past cards with countdown), **Leaderboard** (per-contest ranked table). Tab persisted in `?tab=`. |
| `ContestLobby` | `/contest/:id` *(protected)* | Rules markdown + countdown + gated Enter / Start CTA. Server enforces the 5-minute lobby window. |
| `ContestPlay` | `/contest/:id/play` *(protected, fullscreen)* | Active contest run — reuses `Timer`, `QuestionViewer`, `QuestionPalette`. Autosaves draft to `sessionStorage` so a refresh resumes. |
| `ContestResult` | `/contest/:id/result` *(protected)* | Headline score + rank, embedded leaderboard, per-question review with worked solution. |
| `SolverX` | `/solverx` *(protected, fullscreen)* | Chat surface with SSE-streamed Solve / Theory modes + conversation sidebar. |

### `routes/`
- `AppRoutes.jsx` — central `<Routes>` config. Root `/` redirects based on auth state. Public auth pages are wrapped in `<RedirectIfAuthed>` so a logged-in user can't see them. Protected pages are wrapped in `<ProtectedRoute>`.
- `ProtectedRoute.jsx` — checks `tokenStorage.isAuthenticated()`. If false, redirects to `/login` and stashes the original location in `state.from` so login can return the user there.

---

## Conventions (must follow)

1. **No direct `axios.*` calls in components.** Always import from `services/`.
2. **No direct `localStorage.*` calls.** Always go through `tokenStorage` in `utils/token.js`.
3. **No inline styles, no global CSS for pages.** Use `*.module.css`. Class names are `camelCase` and imported as `styles.foo`.
4. **No Tailwind / Bootstrap / MUI / Redux.** Component state is `useState` / `useReducer`; cross-page state lives in localStorage or is re-fetched.
5. **Mobile-first responsive CSS.** Default styles are mobile; scale up with `@media (min-width: …)`. Use `clamp()` for fluid typography and spacing.
6. **Form pattern**: keep one `form` object in state, one `errors` object, and a top-level `formError` string for API failures. Validate on `blur`, then again on submit; clear field error on next change. Use `parseApiError` for backend errors.
7. **Validators return strings, not booleans.** Empty string = valid. Always run them against the backend's exact rules (see `backend/modules/authentication/schema.py`).
8. **Page components are default-exported.** Reusable components are default-exported too. Named exports only for grouped helpers (e.g. `tokenStorage`).
9. **File extensions**: `.jsx` for any file with JSX (including `App.jsx` and `main.jsx`), `.js` for plain JS (services, utils). CSS Modules are `<page>.module.css` lowercase, `<Component>.module.css` PascalCase to match their component.
10. **Env vars** must start with `VITE_` and be added to **both** `.env` and `.env.example`. Read them via `import.meta.env.VITE_*`, only inside `services/`.
11. **Routes are added in one place** (`routes/AppRoutes.jsx`). Don't sprinkle `<Routes>` blocks across pages.
12. **Accessibility**: labels are real `<label htmlFor=…>` (handled by `InputField`), errors use `role="alert"`, modals use `role="dialog" aria-modal`, focusable elements get a visible `:focus-visible` ring.

---

## Adding a new page (checklist)

To add a `Tests` page at `/tests`:

1. Create `pages/tests/Tests.jsx` and `pages/tests/tests.module.css`.
2. Compose UI from `components/common/` (and `components/auth/` if relevant). If you need a new generic primitive, add it under `components/common/`.
3. Create `services/testService.js` for any new endpoints — `import api from './axiosInstance'`, export named methods.
4. If you need a new validator, add it to `utils/validators.js`.
5. Register the route in `routes/AppRoutes.jsx`. Wrap in `<ProtectedRoute>` if it requires login.
6. Default-export the page component. Use `useNavigate` for redirects, `useLocation` for read-only route state.
7. Add any new env vars to `.env` **and** `.env.example`.

---

## Request lifecycle (reference)

```
User action in a page (e.g. Login.jsx)
   │
   ▼
authService.login({email, password})       ◄── services/ wraps all HTTP
   │
   ▼
api.post('/auth/login', body)              ◄── services/axiosInstance.js
   │   • request interceptor attaches Bearer token (from tokenStorage)
   │   • response interceptor refreshes on 401 (single-flight) and retries
   ▼
FastAPI backend  /api/v1/auth/login
   │
   ▼
Response → authService writes tokens via tokenStorage.setSession()
   │
   ▼
Page calls navigate('/dashboard') → ProtectedRoute lets it through
```

Validation errors (network failures, 4xx with `detail`) are caught in the page and passed through `parseApiError` → shown via `ErrorMessage`.

---

## Auth & token flow (reference)

1. **Signup**: `POST /auth/signup` → backend sends OTP email → frontend opens `OTPModal`.
2. **OTP verify**: `POST /auth/verify-otp` → response includes `{user, tokens}` → `tokenStorage.setSession()` → redirect to `/dashboard`.
3. **Login**: `POST /auth/login` → same `{user, tokens}` shape → redirect to `state.from` or `/dashboard`.
4. **Authenticated request**: interceptor adds `Authorization: Bearer <access_token>`.
5. **Token refresh**: on `401`, interceptor calls `POST /auth/refresh-token` with the refresh token. Retries the original request once. If refresh fails, clears storage and routes to `/login`.
6. **Logout**: `tokenStorage.clear()` + navigate to `/login`. No server-side call (stateless JWT).

Token keys in localStorage: `mmm_access_token`, `mmm_refresh_token`, `mmm_user`.

---

## Tech stack reference

- **Framework**: React 19 (Vite 8 + `@vitejs/plugin-react` + `vite-plugin-pwa`)
- **Routing**: react-router-dom v6
- **HTTP**: axios (single instance + interceptors)
- **Styling**: CSS Modules (no preprocessor)
- **Fonts**: Inter (hero) + Poppins (UI), loaded via Google Fonts in `index.css`
- **State**: React hooks only (`useState`, `useEffect`, `useMemo`, `useRef`, `useId`)
- **Validation**: hand-rolled in `utils/validators.js` (no Yup / Zod / Formik)
- **Backend contract**: `backend/folder_structure.md` is the source of truth for API shapes