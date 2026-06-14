"""Battle endpoints: /battle/*  (REST history/detail + invite lifecycle).

The live battle itself runs over the /battle/ws WebSocket, which needs two
paired clients and isn't covered by this HTTP smoke test.
"""

SERVICE = "battle"


def run(h):
    h.service(SERVICE)

    h.check("history", "GET", "/battle/history")

    # Bogus battle id must 404 (route exists, handles missing), not 500.
    h.check("battle detail (bogus)", "GET", "/battle/507f1f77bcf86cd799439011",
            expect=(404,), extra_ok=(400, 422))

    # Invite lifecycle: create -> get -> cancel. Net-zero, so safe by default.
    invite = h.check("create invite", "POST", "/battle/invites", expect=(201,), extra_ok=(200,))
    code = None
    if invite is not None and invite.status_code in (200, 201):
        body = invite.json()
        code = body.get("code") or body.get("invite_code")
    if code:
        h.check("get invite", "GET", f"/battle/invites/{code}", extra_ok=(404,))
        h.check("cancel invite", "DELETE", f"/battle/invites/{code}",
                expect=(204,), extra_ok=(404,))
    else:
        h.skip("get invite", "GET", "/battle/invites/{code}", "no invite code returned")
        h.skip("cancel invite", "DELETE", "/battle/invites/{code}", "no invite code returned")

    # precheck on a bogus code proves the route validates input.
    h.check("precheck invite (bogus)", "POST", "/battle/invites/NOPE123/precheck",
            extra_ok=(400, 404, 409, 422))

    h.skip("battle play", "WS", "/battle/ws", "WebSocket — needs two paired clients")
