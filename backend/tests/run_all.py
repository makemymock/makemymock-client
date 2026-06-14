"""Run the MakeMyMock API smoke tests against a running backend.

Usage (from backend/):

    python tests/run_all.py                          # all services, deployed URL
    python tests/run_all.py --url http://localhost:8000/api/v1
    python tests/run_all.py --only solverx,auth      # subset
    python tests/run_all.py --writes                 # also run write/mutating tests

Auth: defaults to the hardcoded test account; override with --email/--password
or --token, or the MMM_* env vars.

Exit code is 0 only if there are zero failures (skips don't count as failures).
"""

from __future__ import annotations

import argparse
import os
import sys
from dotenv import load_dotenv

load_dotenv()  # Load env vars from .env, if present.

# Make the sibling test modules importable whether run as a script or module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import Harness  # noqa: E402
import test_auth, test_profile, test_mock_test, test_potd, test_battle, test_contest, test_solverx  # noqa: E402

# Deployed Cloud Run backend (the canonical service URL).
DEFAULT_URL = os.environ.get("DEPLOYED_URL")

# Registration order = run order.
SERVICES = {
    "auth": test_auth,
    "profile": test_profile,
    "mock_test": test_mock_test,
    "potd": test_potd,
    "battle": test_battle,
    "contest": test_contest,
    "solverx": test_solverx,
}


def main() -> int:
    p = argparse.ArgumentParser(description="MakeMyMock API smoke tests")
    p.add_argument("--url", default=os.environ.get("MMM_BASE_URL", DEFAULT_URL))
    p.add_argument("--email", default=os.environ.get("MMM_EMAIL", "Add your test email here"))
    p.add_argument("--password", default=os.environ.get("MMM_PASSWORD", "Add your test password here"))
    p.add_argument("--token", default=os.environ.get("MMM_TOKEN"))
    p.add_argument("--only", help="comma-separated service subset, e.g. solverx,auth")
    p.add_argument("--writes", action="store_true",
                   help="also run write/mutating endpoint tests")
    args = p.parse_args()

    selected = list(SERVICES)
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        unknown = wanted - set(SERVICES)
        if unknown:
            print(f"Unknown service(s): {', '.join(unknown)}. "
                  f"Choose from: {', '.join(SERVICES)}")
            return 2
        selected = [s for s in SERVICES if s in wanted]

    print(f"Target : {args.url}")
    print(f"Writes : {'ON' if args.writes else 'off (reads + idempotent only)'}")

    h = Harness(args.url, token=args.token, include_writes=args.writes)
    try:
        # Reachability check before anything else.
        try:
            h.client.get("/auth/me")
        except Exception as exc:  # noqa: BLE001
            print(f"\nCannot reach {args.url} — is the backend up? ({exc})")
            return 2

        if not args.token:
            user = h.login(args.email, args.password)
            print(f"Logged in as {args.email} (verified={user.get('is_verified')})")

        for name in selected:
            SERVICES[name].run(h)

        return h.summary()
    finally:
        h.close()


if __name__ == "__main__":
    sys.exit(main())
