# API smoke tests

Integration smoke tests that drive the public REST API exactly like the
frontend (bearer auth), one script per service. They answer "does every
route respond sanely with real auth + MongoDB + Vertex behind it" — the
check you want after a deploy or a GCP account/infra switch. They are **not**
unit tests and need a running backend.

## Run

From `backend/`:

```bash
python tests/run_all.py                          # all services, deployed Cloud Run URL
python tests/run_all.py --url http://localhost:8000/api/v1   # local backend
python tests/run_all.py --only solverx,auth      # a subset
python tests/run_all.py --writes                 # also run write/mutating tests
```

Auth defaults to the hardcoded test account. Override with `--email`/
`--password`/`--token` or the `MMM_EMAIL` / `MMM_PASSWORD` / `MMM_TOKEN` /
`MMM_BASE_URL` env vars.

Exit code is `0` only when there are zero failures (skips don't count).

## What PASS / FAIL / SKIP mean

- **PASS** — endpoint returned an expected status. A domain `404` for a
  deliberately bogus id counts as PASS (the route exists and validates input).
- **FAIL** — unexpected status (especially `5xx`, or `401/403` meaning auth
  broke), or the host was unreachable.
- **SKIP** — intentionally not run: needs a live contest window, runs over a
  WebSocket, sends email, or is a destructive write gated behind `--writes`.

## Coverage

| Service   | Covered (default)                                              | Skipped / gated                                  |
|-----------|----------------------------------------------------------------|--------------------------------------------------|
| auth      | me, refresh-token, signup-validation                           | signup/verify (accounts+OTP), resend (`--writes`)|
| profile   | me, idempotent update                                          | create/tour (`--writes`)                         |
| mock_test | catalog, browse, notebook add/remove, all analytics, history   | create→submit→result (`--writes`)                |
| potd      | today, streak, history, past-date                              | attempt (`--writes`), view-solution (destructive)|
| battle    | history, detail, invite create→get→cancel, precheck            | live play (WebSocket)                            |
| contest   | list, lobby/leaderboard/result (real id or bogus)              | enter/start/submit (live window)                 |
| solverx   | list/detail, **solve + theory SSE (Vertex)**, cleanup deletes  | —                                                |

`--writes` enables the mutating flows (real mock-test creation, POTD attempt,
profile create/tour, OTP email). It still never runs the truly destructive
POTD view-solution (breaks the user's streak).

The SolverX `solve`/`theory` streams make a real Gemini call each and delete
the conversations they create afterward.
