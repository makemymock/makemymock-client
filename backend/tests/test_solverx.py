"""SolverX endpoints: /solverx/*  (the Vertex AI / Gemini surface).

These two SSE endpoints are the real proof that the GCP/Vertex switch works
from this deployment — they call Gemini and must stream actual content.
Any conversations created here are deleted afterward to leave no trace.
"""

SERVICE = "solverx"


def run(h):
    h.service(SERVICE)

    conv = h.check("list conversations", "GET", "/solverx/conversations")
    existing_id = _first_conv_id(conv)
    if existing_id:
        h.check("conversation detail", "GET", f"/solverx/conversations/{existing_id}",
                extra_ok=(404,))
    else:
        h.check("conversation detail (bogus)", "GET",
                "/solverx/conversations/507f1f77bcf86cd799439011",
                expect=(404,), extra_ok=(400, 422))

    # The actual LLM calls. These cost a Vertex request each.
    h.stream_sse(
        "solve (SSE, Vertex)", "/solverx/solve",
        {"question_text": "What is the derivative of sin(x^2)?", "complexity_mode": "guided"},
    )
    h.stream_sse(
        "theory (SSE, Vertex)", "/solverx/theory",
        {"question_text": "Explain the chain rule briefly.", "complexity_mode": "easy"},
    )

    # Clean up any conversations the two streams just created.
    for cid in h.scratch.get("solverx_convs", []):
        h.check(f"delete conversation {cid[:8]}", "DELETE",
                f"/solverx/conversations/{cid}", expect=(204,), extra_ok=(404,))


def _first_conv_id(resp):
    if resp is None or resp.status_code != 200:
        return None
    items = resp.json().get("items", [])
    if items and isinstance(items[0], dict):
        return items[0].get("id")
    return None
