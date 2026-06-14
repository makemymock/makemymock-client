"""Problem-of-the-Day endpoints: /potd/*"""

SERVICE = "potd"


def run(h):
    h.service(SERVICE)

    today = h.check("today", "GET", "/potd/today")
    h.check("streak", "GET", "/potd/streak")
    h.check("history", "GET", "/potd/history", params={"days": 30})

    # Past-date detail: use today's date string from the today payload.
    date_ist = None
    if today is not None and today.status_code == 200:
        date_ist = today.json().get("date_ist")
    if date_ist:
        h.check("past-date detail", "GET", f"/potd/{date_ist}", extra_ok=(404,))
    else:
        h.check("past-date detail (bogus)", "GET", "/potd/2020-01-01", extra_ok=(404,))

    # Attempt records an answer (feeds streak state). Write-gated.
    if h.needs_writes("today attempt", "POST", "/potd/today/attempt"):
        h.check(
            "today attempt", "POST", "/potd/today/attempt",
            json={"selected_option": "A"},
            extra_ok=(400, 409),
        )

    # view-solution breaks the streak — destructive, never in default runs.
    h.skip("today view-solution", "POST", "/potd/today/view-solution",
           "breaks the user's streak — too destructive even for --writes")
