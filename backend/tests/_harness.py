"""Shared test harness for the MakeMyMock API smoke tests.

Drives the public REST API exactly like the frontend does (auth via bearer
token), records a PASS / FAIL / SKIP per endpoint, and prints a summary.

These are *integration smoke tests* against a running backend (local or the
deployed Cloud Run URL) — not unit tests. The goal is "does every route
respond sanely with real auth + DB + Vertex behind it", which is what you
want after a deploy or an account/infra switch.

Semantics:
  * PASS  — the endpoint returned a status in its `expect`/`extra_ok` set.
  * FAIL  — unexpected status (esp. 5xx, or 401/403 = auth broken), or a
            transport error (route/host unreachable).
  * SKIP  — intentionally not exercised (needs a live contest, a websocket,
            sends email, or is a destructive write run only with --writes).

A domain 404 (e.g. "battle not found" for a bogus id) is treated as a PASS
when listed in `extra_ok`: it proves the route exists and handles input,
which is all a smoke test can assert without fixture data.
"""

from __future__ import annotations

import json
from typing import Iterable, Optional

import httpx

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)

# Streaming/LLM endpoints can be slow on a cold Vertex call.
TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)


class Result:
    __slots__ = ("service", "name", "method", "path", "status", "state", "detail")

    def __init__(self, service, name, method, path, status, state, detail=""):
        self.service = service
        self.name = name
        self.method = method
        self.path = path
        self.status = status
        self.state = state  # "PASS" | "FAIL" | "SKIP"
        self.detail = detail


class Harness:
    def __init__(self, base_url: str, *, token: Optional[str] = None, include_writes: bool = False):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=TIMEOUT)
        self.token = token
        self.include_writes = include_writes
        self.refresh_token: Optional[str] = None
        self.results: list[Result] = []
        self._service = "?"
        # A scratch space services use to pass ids to one another / within a run.
        self.scratch: dict = {}

    # -- lifecycle ---------------------------------------------------------
    def close(self):
        self.client.close()

    def service(self, name: str):
        self._service = name
        print(f"\n{BOLD}=== {name} ==={RESET}")

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    # -- auth --------------------------------------------------------------
    def login(self, email: str, password: str) -> dict:
        r = self.client.post("/auth/login", json={"email": email, "password": password})
        if r.status_code != 200:
            raise SystemExit(f"{RED}Login failed ({r.status_code}): {r.text}{RESET}")
        body = r.json()
        self.token = body["tokens"]["access_token"]
        self.refresh_token = body["tokens"]["refresh_token"]
        return body["user"]

    # -- recording ---------------------------------------------------------
    def _record(self, name, method, path, status, state, detail=""):
        self.results.append(Result(self._service, name, method, path, status, state, detail))
        tag = {"PASS": f"{GREEN}PASS{RESET}", "FAIL": f"{RED}FAIL{RESET}",
               "SKIP": f"{YELLOW}SKIP{RESET}"}[state]
        code = f"{status}" if status is not None else "---"
        line = f"  {tag} [{code}] {method:6} {path}  {DIM}{name}{RESET}"
        if detail:
            line += f"\n        {DIM}{detail}{RESET}"
        print(line)

    def check(
        self,
        name: str,
        method: str,
        path: str,
        *,
        expect: Iterable[int] = (200,),
        extra_ok: Iterable[int] = (),
        json: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Optional[httpx.Response]:
        """Call an endpoint and record PASS/FAIL. Returns the response (or None)."""
        ok_codes = set(expect) | set(extra_ok)
        try:
            r = self.client.request(
                method, path, json=json, params=params, headers=self.headers
            )
        except httpx.HTTPError as exc:
            self._record(name, method, path, None, "FAIL", f"transport error: {exc}")
            return None
        if r.status_code in ok_codes:
            self._record(name, method, path, r.status_code, "PASS")
        else:
            self._record(name, method, path, r.status_code, "FAIL", r.text[:200])
        return r

    def skip(self, name: str, method: str, path: str, reason: str):
        self._record(name, method, path, None, "SKIP", reason)

    def needs_writes(self, name: str, method: str, path: str) -> bool:
        """Return True if a write test should run; otherwise record a SKIP."""
        if self.include_writes:
            return True
        self.skip(name, method, path, "write/destructive — pass --writes to run")
        return False

    # -- SSE ---------------------------------------------------------------
    def stream_sse(self, name: str, path: str, payload: dict) -> Optional[httpx.Response]:
        """Stream a text/event-stream endpoint; PASS if real content & no error.

        Captures any `done.conversation_id` into self.scratch["solverx_convs"]
        so the caller can clean up created conversations afterward.
        """
        content_chars = 0
        events: dict[str, int] = {}
        error_payload = None
        try:
            with self.client.stream("POST", path, json=payload, headers=self.headers) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", "replace")
                    self._record(name, "POST", path, resp.status_code, "FAIL", body[:200])
                    return None
                event = "message"
                data_lines: list[str] = []
                for line in resp.iter_lines():
                    if line == "":
                        if data_lines:
                            raw = "\n".join(data_lines)
                            try:
                                data = _loads(raw)
                            except ValueError:
                                data = raw
                            events[event] = events.get(event, 0) + 1
                            if event in ("error", "fatal"):
                                error_payload = data
                            if event == "done" and isinstance(data, dict):
                                cid = data.get("conversation_id")
                                if cid:
                                    self.scratch.setdefault("solverx_convs", []).append(cid)
                            if isinstance(data, dict):
                                for k in ("content", "delta", "text", "token"):
                                    v = data.get(k)
                                    if isinstance(v, str):
                                        content_chars += len(v)
                        event, data_lines = "message", []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
        except httpx.HTTPError as exc:
            self._record(name, "POST", path, None, "FAIL", f"transport error: {exc}")
            return None

        summary = ", ".join(f"{k}x{v}" for k, v in sorted(events.items())) or "(none)"
        if error_payload is not None:
            self._record(name, "POST", path, 200, "FAIL",
                         f"error event: {error_payload} | events: {summary}")
        elif content_chars == 0:
            self._record(name, "POST", path, 200, "FAIL",
                         f"no content streamed | events: {summary}")
        else:
            self._record(name, "POST", path, 200, "PASS")
            print(f"        {DIM}{content_chars} content chars | events: {summary}{RESET}")
        return None

    # -- summary -----------------------------------------------------------
    def summary(self) -> int:
        passed = sum(1 for r in self.results if r.state == "PASS")
        failed = sum(1 for r in self.results if r.state == "FAIL")
        skipped = sum(1 for r in self.results if r.state == "SKIP")
        print(f"\n{BOLD}================ SUMMARY ================{RESET}")
        # per-service rollup
        by_service: dict[str, list[int]] = {}
        for r in self.results:
            row = by_service.setdefault(r.service, [0, 0, 0])
            row[0 if r.state == "PASS" else 1 if r.state == "FAIL" else 2] += 1
        for svc, (p, f, s) in by_service.items():
            mark = f"{GREEN}OK{RESET}" if f == 0 else f"{RED}{f} FAIL{RESET}"
            print(f"  {svc:12} {GREEN}{p} pass{RESET}  {RED}{f} fail{RESET}  "
                  f"{YELLOW}{s} skip{RESET}   {mark}")
        if failed:
            print(f"\n{RED}Failures:{RESET}")
            for r in self.results:
                if r.state == "FAIL":
                    print(f"  {r.method} {r.path}  -> {r.status}  {r.detail}")
        print(f"\n{BOLD}TOTAL: {GREEN}{passed} pass{RESET}, "
              f"{RED}{failed} fail{RESET}, {YELLOW}{skipped} skip{RESET}{BOLD}{RESET}")
        return 0 if failed == 0 else 1


def _loads(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
