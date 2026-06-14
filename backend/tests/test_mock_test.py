"""Mock-test endpoints: /mock-test/*  (catalog, browse, notebook, sessions, analytics)."""

SERVICE = "mock_test"


def run(h):
    h.service(SERVICE)

    # --- catalog + browse (reads) ----------------------------------------
    cat = h.check("catalog", "GET", "/mock-test/catalog")
    first_topic_id = _first_topic_id(cat)

    browse = h.check("browse (page 1)", "GET", "/mock-test/browse",
                     params={"page": 1, "page_size": 5})
    qid = _first_question_id(browse)

    if qid:
        h.check("browse detail", "GET", f"/mock-test/browse/{qid}", extra_ok=(404,))
    else:
        h.skip("browse detail", "GET", "/mock-test/browse/{id}", "no question id from browse")

    # --- notebook (idempotent add + remove cancels out) ------------------
    h.check("notebook count", "GET", "/mock-test/notebook/count")
    if qid:
        h.check("notebook add", "POST", f"/mock-test/notebook/{qid}", extra_ok=(409,))
        h.check("notebook remove", "DELETE", f"/mock-test/notebook/{qid}", extra_ok=(404,))
    else:
        h.skip("notebook add/remove", "POST", "/mock-test/notebook/{id}", "no question id")

    # --- analytics (reads) -----------------------------------------------
    h.check("analytics overview", "GET", "/mock-test/analytics/overview")
    topics = h.check("analytics topics", "GET", "/mock-test/analytics/topics")
    chapters = h.check("analytics chapters", "GET", "/mock-test/analytics/chapters")
    h.check("analytics activity-heatmap", "GET", "/mock-test/analytics/activity-heatmap")
    h.check("analytics confidence", "GET", "/mock-test/analytics/confidence")
    h.check("history", "GET", "/mock-test/history")

    # Drill-downs need ids; use real ones if present else a bogus id (route must 404, not 500).
    ch_id = _first_id(chapters, "chapter_id") or 1
    tp_id = _first_id(topics, "topic_id") or first_topic_id or 1
    h.check("analytics chapter detail", "GET", f"/mock-test/analytics/chapter/{ch_id}",
            extra_ok=(404,))
    h.check("analytics topic detail", "GET", f"/mock-test/analytics/topic/{tp_id}",
            extra_ok=(404,))

    # Session fetch with a bogus id proves the route handles missing sessions.
    h.check("session fetch (bogus)", "GET", "/mock-test/session/999999999",
            expect=(404,), extra_ok=(400,))

    # --- create -> session -> submit -> result (write flow) --------------
    if not h.needs_writes("create test", "POST", "/mock-test/create"):
        h.skip("session fetch", "GET", "/mock-test/session/{id}", "depends on create")
        h.skip("submit test", "POST", "/mock-test/session/{id}/submit", "depends on create")
        h.skip("result", "GET", "/mock-test/session/{id}/result", "depends on create")
        return

    if not first_topic_id:
        h.skip("create test", "POST", "/mock-test/create", "no topic id from catalog")
        return

    created = h.check(
        "create test", "POST", "/mock-test/create",
        json={"topic_ids": [first_topic_id], "total_questions": 1, "extra_questions": 0},
        expect=(201,), extra_ok=(400, 422),
    )
    if created is None or created.status_code != 201:
        return
    session_id = created.json().get("session_id")
    if session_id is None:
        h.skip("session fetch", "GET", "/mock-test/session/{id}", "no session_id returned")
        return

    h.check("session fetch", "GET", f"/mock-test/session/{session_id}")
    h.check("submit test (empty answers)", "POST",
            f"/mock-test/session/{session_id}/submit", json={"answers": []})
    h.check("result", "GET", f"/mock-test/session/{session_id}/result")


# --- helpers -------------------------------------------------------------

def _first_topic_id(resp):
    if resp is None or resp.status_code != 200:
        return None
    for subj in resp.json().get("subjects", []):
        for ch in subj.get("chapters", []):
            for tp in ch.get("topics", []):
                if isinstance(tp.get("id"), int):
                    return tp["id"]
    return None


def _first_question_id(resp):
    if resp is None or resp.status_code != 200:
        return None
    body = resp.json()
    items = body.get("items") or body.get("questions") or []
    if items:
        it = items[0]
        return it.get("id") or it.get("question_id") or it.get("obj_id")
    return None


def _first_id(resp, key):
    if resp is None or resp.status_code != 200:
        return None
    body = resp.json()
    items = body.get("items") or body.get("chapters") or body.get("topics") or []
    if items and isinstance(items[0], dict):
        return items[0].get(key)
    return None
