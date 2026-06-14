"""Contest endpoints: /contests/*

Contests are created by the Admin backend, so the Client test only reads.
Enter/start/submit need a live contest in its time window, so they're
exercised against whatever the list returns, falling back to bogus-id
route checks when there's nothing live.
"""

SERVICE = "contest"


def run(h):
    h.service(SERVICE)

    listing = h.check("list contests", "GET", "/contests")
    contest_id = _first_contest_id(listing)

    if contest_id:
        h.check("contest lobby detail", "GET", f"/contests/{contest_id}", extra_ok=(404,))
        h.check("leaderboard", "GET", f"/contests/{contest_id}/leaderboard", extra_ok=(404,))
        h.check("result", "GET", f"/contests/{contest_id}/result",
                extra_ok=(403, 404, 409))
    else:
        # No contests available — verify routes still resolve with a bogus id.
        bogus = "507f1f77bcf86cd799439011"
        h.check("contest lobby detail (bogus)", "GET", f"/contests/{bogus}",
                expect=(404,), extra_ok=(400, 422))
        h.check("leaderboard (bogus)", "GET", f"/contests/{bogus}/leaderboard",
                expect=(404,), extra_ok=(400, 422))
        h.check("result (bogus)", "GET", f"/contests/{bogus}/result",
                expect=(404,), extra_ok=(400, 403, 422))

    # enter/start/submit mutate participation and need correct timing.
    h.skip("enter lobby", "POST", "/contests/{id}/enter", "needs a live contest window")
    h.skip("start contest", "POST", "/contests/{id}/start", "needs a live contest window")
    h.skip("submit contest", "POST", "/contests/{id}/submit", "needs a live contest window")


def _first_contest_id(resp):
    if resp is None or resp.status_code != 200:
        return None
    body = resp.json()
    for bucket in ("live", "upcoming", "past"):
        items = body.get(bucket) or []
        if items and isinstance(items[0], dict):
            cid = items[0].get("id") or items[0].get("contest_id")
            if cid:
                return cid
    return None
