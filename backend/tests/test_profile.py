"""Profile endpoints: /profile/*"""

SERVICE = "profile"


def run(h):
    h.service(SERVICE)

    # The test account should already have a profile.
    r = h.check("me (profile)", "GET", "/profile/me", extra_ok=(404,))
    profile = r.json() if r is not None and r.status_code == 200 else None

    # Create is idempotent-ish: 201 if missing, 409/400 if it already exists.
    # Either way the route works; we don't want to overwrite real data, so
    # only attempt creation when there's no profile AND writes are enabled.
    if profile is None and h.needs_writes("create profile", "POST", "/profile/create"):
        h.check(
            "create profile", "POST", "/profile/create",
            json={
                "full_name": "Smoke Test", "date_of_birth": "2005-01-01",
                "class_grade": "12", "target_exam": "jee_main", "state": "WB",
                "school_name": "Test School", "city": "Kolkata",
                "preferred_language": "English", "phone_number": "+910000000000",
                "gender": "prefer_not_to_say",
            },
            expect=(201,), extra_ok=(400, 409),
        )
    elif profile is not None:
        h.skip("create profile", "POST", "/profile/create", "profile already exists")

    # Idempotent update: write back a field to its current value.
    if profile is not None:
        h.check(
            "update profile (idempotent)", "PUT", "/profile/update",
            json={"full_name": profile.get("full_name", "Smoke Test")},
        )
    else:
        h.skip("update profile", "PUT", "/profile/update", "no profile to update")

    # Marking a tour complete mutates tours_completed — gate behind writes.
    if h.needs_writes("complete tour", "POST", "/profile/tours/smoke_probe/complete"):
        h.check("complete tour", "POST", "/profile/tours/smoke_probe/complete")
