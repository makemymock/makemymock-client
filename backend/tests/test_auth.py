"""Auth endpoints: /auth/*"""

SERVICE = "auth"


def run(h):
    h.service(SERVICE)

    # Already logged in by the runner; confirm the token resolves a user.
    h.check("me (current user)", "GET", "/auth/me")

    # Refresh exchanges the refresh token for a new pair.
    if h.refresh_token:
        h.check(
            "refresh-token", "POST", "/auth/refresh-token",
            json={"refresh_token": h.refresh_token},
        )
    else:
        h.skip("refresh-token", "POST", "/auth/refresh-token", "no refresh token captured")

    # Validation path: a malformed email must be rejected (422) before any
    # email is sent — proves the route + schema validation are wired.
    h.check(
        "signup rejects bad payload", "POST", "/auth/signup",
        json={"email": "not-an-email", "username": "x", "password": "short"},
        expect=(422,),
    )

    # Sends a real OTP email — skip unless writes are enabled.
    if h.needs_writes("resend-otp (sends email)", "POST", "/auth/resend-otp"):
        h.check(
            "resend-otp (sends email)", "POST", "/auth/resend-otp",
            json={"email": "noexist+probe@example.com"},
            # Endpoint returns 200 even for unknown emails (no user enumeration).
            expect=(200,), extra_ok=(429,),
        )

    # signup / verify-otp create accounts + consume OTPs — never run in smoke.
    h.skip("signup (creates account)", "POST", "/auth/signup", "creates a real user + emails OTP")
    h.skip("verify-otp", "POST", "/auth/verify-otp", "needs a live OTP code")
