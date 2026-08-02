# Local smoke check for the CORS + asyncio.to_thread fixes.
#
# Checks, against a running local backend:
#   1. /health responds
#   2. /docs responds (Swagger UI loads)
#   3. CORS headers are correct for an allowed vs. a disallowed origin
#      (a script can't reproduce real browser CORS enforcement, but it CAN
#      verify the server sends back the right Access-Control-Allow-Origin
#      header — which is exactly what CORSMiddleware controls)
#   4. Login works and returns a token
#   5. Catalog loads and has at least one topic
#   6. Create-test succeeds (exercises engine_create_mock_test, now run via
#      asyncio.to_thread) and returns real questions
#
# Run (from backend/, with `uvicorn main:app --reload --port 8000` already
# running in another terminal):
#
#     python tests/local_verify.py --email you@example.com --password ...
#
# Or set MMM_EMAIL / MMM_PASSWORD once and just run `python tests/local_verify.py`.

import argparse
import os
import sys

import httpx

ALLOWED_ORIGIN = "https://www.makemymock.com"
DISALLOWED_ORIGIN = "https://evil-example.com"


def parse_args():
    p = argparse.ArgumentParser(description="Local smoke check: CORS + engine-in-thread fixes")
    p.add_argument("--base-url", default=os.environ.get("MMM_LOCAL_URL", "http://localhost:8000"))
    p.add_argument("--email", default=os.environ.get("MMM_EMAIL"))
    p.add_argument("--password", default=os.environ.get("MMM_PASSWORD"))
    args = p.parse_args()
    if not args.email or not args.password:
        p.error("need --email/--password, or set MMM_EMAIL / MMM_PASSWORD")
    return args


def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    return ok


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")
    api = f"{base}/api/v1"
    all_ok = True

    with httpx.Client(timeout=120) as client:
        # 1. Health
        try:
            r = client.get(f"{base}/health")
            all_ok &= check("health", r.status_code == 200, f"HTTP {r.status_code}")
        except httpx.RequestError as exc:
            check("health", False, f"server unreachable at {base} ({exc})")
            print("\nIs `uvicorn main:app --reload --port 8000` running?")
            sys.exit(1)

        # 2. Docs
        r = client.get(f"{base}/docs")
        all_ok &= check("docs (swagger ui)", r.status_code == 200, f"HTTP {r.status_code}")

        # 3. CORS headers
        r = client.get(f"{base}/health", headers={"Origin": ALLOWED_ORIGIN})
        got = r.headers.get("access-control-allow-origin")
        all_ok &= check(
            f"CORS allows {ALLOWED_ORIGIN}",
            got == ALLOWED_ORIGIN,
            f"Access-Control-Allow-Origin = {got!r}",
        )

        r = client.get(f"{base}/health", headers={"Origin": DISALLOWED_ORIGIN})
        got = r.headers.get("access-control-allow-origin")
        all_ok &= check(
            f"CORS rejects {DISALLOWED_ORIGIN}",
            got != DISALLOWED_ORIGIN,
            f"Access-Control-Allow-Origin = {got!r}",
        )

        # 4. Login
        r = client.post(f"{api}/auth/login", json={"email": args.email, "password": args.password})
        if not check("login", r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"):
            sys.exit(1)
        token = r.json()["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 5. Catalog -> pick a topic with questions
        r = client.get(f"{api}/mock-test/catalog", headers=headers)
        if not check("catalog", r.status_code == 200, f"HTTP {r.status_code}"):
            sys.exit(1)
        topic_id = None
        for subject in r.json().get("subjects", []):
            for chapter in subject.get("chapters", []):
                for topic in chapter.get("topics", []):
                    if topic.get("question_count", 0) > 0:
                        topic_id = topic["id"]
                        break
                if topic_id:
                    break
            if topic_id:
                break
        if not check("catalog has a topic with questions", topic_id is not None):
            sys.exit(1)

        # 6. Create test (exercises engine_create_mock_test via asyncio.to_thread)
        r = client.post(
            f"{api}/mock-test/create",
            json={"topic_ids": [topic_id], "total_questions": 5, "extra_questions": 0},
            headers=headers,
        )
        if not check("create test", r.status_code in (200, 201), f"HTTP {r.status_code}: {r.text[:300]}"):
            sys.exit(1)
        body = r.json()
        all_ok &= check("session_id present", bool(body.get("session_id")))
        all_ok &= check(
            "questions returned",
            len(body.get("questions", [])) > 0,
            f"{len(body.get('questions', []))} question(s)",
        )

    print()
    if all_ok:
        print("All checks passed.")
    else:
        print("Some checks FAILED — see above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
