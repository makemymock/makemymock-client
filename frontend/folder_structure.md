# Frontend Folder Structure

React (CRA) frontend for **MakeMyMock**. Talks to the FastAPI backend over HTTP, uses **CSS Modules** for styling, **Axios** for HTTP, **React Router DOM** for routing, and **React hooks** for state. No Tailwind, no Bootstrap, no MUI, no Redux.

This document describes the conventions every new page/feature must follow so the codebase stays consistent.

---

## Top-level layout

```
frontend/
├── public/                      # CRA static shell (index.html, favicon, manifest)
├── src/
│   ├── assets/                  # Static images / icons imported by components
│   ├── components/              # Reusable UI — never page-specific
│   │   ├── common/              # Generic primitives (Button, InputField, Loader, ErrorMessage)
│   │   └── auth/                # Auth-flow specific (AuthLayout, OTPModal, PasswordInput)
│   ├── pages/                   # One folder per route, owns its own .module.css
│   │   ├── login/
│   │   ├── signup/
│   │   └── dashboard/
│   ├── routes/                  # Router config + route guards
│   │   ├── AppRoutes.jsx
│   │   └── ProtectedRoute.jsx
│   ├── services/                # All network I/O. Components NEVER call axios directly.
│   │   ├── axiosInstance.js
│   │   └── authService.js
│   ├── utils/                   # Pure, framework-free helpers
│   │   ├── token.js
│   │   └── validators.js
│   ├── App.js                   # BrowserRouter + AppRoutes
│   ├── App.css                  # Global resets + focus styles
│   ├── index.js                 # ReactDOM root
│   └── index.css                # Google Fonts (Inter + Poppins) + body defaults
├── .env                         # REACT_APP_API_BASE_URL (gitignored)
├── .env.example                 # Template
└── package.json
```

---

## Layer responsibilities

### `services/`
All HTTP traffic lives here. **Components and pages NEVER import axios directly** — they import a service.

- `axiosInstance.js` — the single configured Axios client. Reads `REACT_APP_API_BASE_URL`, attaches `Authorization: Bearer <token>` from `tokenStorage` on every request, and on `401` automatically calls `/auth/refresh-token` (single-flight, no stampede) and retries the original request. If refresh fails, it clears storage and redirects to `/login`. Auth endpoints (`/auth/login`, `/auth/signup`, etc.) are excluded from refresh so their 401s surface to the form.
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
| `Loader` | Spinner. `fullscreen` prop for overlay mode. |
| `ErrorMessage` | Tinted error pill. Renders nothing when `message` is empty. |

### `components/auth/`
Reusable components that are specific to the auth flow but still presentational where possible.

| Component | Purpose |
|---|---|
| `AuthLayout` | The two-column shell used by both Login & Signup. Header (logo + CTA pill), left hero card (title + features + footer), right `formCard` for `children`. Drives the responsive collapse. |
| `PasswordInput` | Wraps `InputField` and adds an eye-icon show/hide toggle. |
| `OTPModal` | 6-digit OTP entry. Owns its own state: autotab, backspace, paste, expiry countdown, resend, Enter-to-submit. Calls `authService.verifyOtp` / `resendOtp` and reports back via `onVerified`. |

### `pages/<route>/`
One folder per route. **Pages own their CSS module** (lowercase: `login.module.css`, `signup.module.css`, `dashboard.module.css`). Pages compose `common/` + `auth/` components, call services, manage form state, and navigate.

| Page | Route | Responsibilities |
|---|---|---|
| `Signup` | `/signup` | Username/Email/Password/Confirm form → `authService.signup` → opens `OTPModal` → on verify, navigates to `/dashboard`. |
| `Login` | `/login` | Email/Password form → `authService.login` → navigates to `state.from` or `/dashboard`. |
| `Dashboard` | `/dashboard` *(protected)* | Calls `authService.me()` on mount, shows user, logout button. |

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
9. **File extensions**: `.jsx` for any file with JSX, `.js` for plain JS (services, utils, App.js). CSS Modules are `<page>.module.css` lowercase, `<Component>.module.css` PascalCase to match their component.
10. **Env vars** must start with `REACT_APP_` and be added to **both** `.env` and `.env.example`. Read them only inside `services/`.
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

- **Framework**: React 19 (CRA / react-scripts 5)
- **Routing**: react-router-dom v6
- **HTTP**: axios (single instance + interceptors)
- **Styling**: CSS Modules (no preprocessor)
- **Fonts**: Inter (hero) + Poppins (UI), loaded via Google Fonts in `index.css`
- **State**: React hooks only (`useState`, `useEffect`, `useMemo`, `useRef`, `useId`)
- **Validation**: hand-rolled in `utils/validators.js` (no Yup / Zod / Formik)
- **Backend contract**: `backend/folder_structure.md` is the source of truth for API shapes
