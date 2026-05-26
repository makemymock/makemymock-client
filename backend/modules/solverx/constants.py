"""Constants for the SolverX module."""

CONVERSATIONS_COLLECTION = "solverx_conversations"
MESSAGES_COLLECTION = "solverx_messages"

# ---- Conversation modes ----
MODE_SOLVE = "solve"
MODE_THEORY = "theory"

# ---- Complexity values ----
# Solve mode uses GUIDED / DEEP; Theory mode uses EASY / DEEP. Both can
# arrive on the same `complexity_mode` field so we accept all four and
# the dispatcher picks the right path. `simple` is the umbrella term for
# the one-shot Flash path (Guided + Easy both map to it).
COMPLEXITY_GUIDED = "guided"   # Solve  → one-shot Flash
COMPLEXITY_DEEP = "deep"       # Either → multi-agent (Pro + Flash-Lite)
COMPLEXITY_EASY = "easy"       # Theory → one-shot Flash

# Routing helper: which complexity values trigger the simple, one-shot
# path. Everything else (today: just "deep") triggers the multi-agent
# pipeline.
SIMPLE_COMPLEXITIES = frozenset({COMPLEXITY_GUIDED, COMPLEXITY_EASY})

# ---- Block types ----
# Sectional markers the planning + solve stages emit. The frontend splits
# on these to build structured blocks.
#
# `diagram_pending` is reserved for the streaming flow: when the Deep
# pipeline emits an in-line diagram slot, the service yields a
# `diagram_pending` block immediately so the frontend can render a
# "Generating figure…" loading state in that exact position. A separate
# `diagram_ready` SSE event replaces it with the SVG once the diagram
# agent finishes. Stored / replayed conversations only ever see the
# settled `diagram` block.
BLOCK_TYPES = (
    "understanding",
    "key_concept",
    "step",
    "intuition",
    "warning",
    "diagram",
    "diagram_pending",
    "final_answer",
    "alternative",
    "summary",
    "insight",
)

# ---- Vertex AI request budget ----
# Per-request soft timeout in seconds. Streaming uses a separate read
# deadline of `None` (SDK default) since the connection is held open
# for the full generation.
VERTEX_REQUEST_TIMEOUT = 120.0

# ---- Status-message scripts ----
# The orchestrator emits these between agents so the UI can show the
# "we're thinking" feel. Solve and Theory use different vocabularies.

SOLVE_STATUS_MESSAGES = {
    # Simple (Guided) path
    "simple_solve_start": "Solving with focused single-pass reasoning…",

    # Deep path
    "plan_start": "Plan agent analyzing your question…",
    "plan_done": "Pedagogy plan ready — handing off to the solver…",
    "solve_start": "Solver agent constructing the full walkthrough…",
    "solve_progress": "Polishing each step…",
    "insight": "Reading your practice analytics for personalized signal…",
    "diagram_draft": "Visual reasoning agent sketching figure…",
    "diagram_polish": "Diagram refactor agent auditing the figure…",
    "done": "Done.",
}

THEORY_STATUS_MESSAGES = {
    # Simple (Easy) path
    "simple_solve_start": "Explaining the concept concisely…",

    # Deep path
    "plan_start": "Concept agent identifying what you're asking about…",
    "plan_done": "Tutor agent planning the explanation…",
    "solve_start": "Building intuitive explanation with examples…",
    "solve_progress": "Adding analogies, derivations, and worked examples…",
    "insight": "Linking this to your recent practice topics…",
    "diagram_draft": "Visual reasoning agent sketching figure…",
    "diagram_polish": "Diagram refactor agent auditing the figure…",
    "done": "Done.",
}

# Backwards-compat alias kept so callers that import the old name still
# work without a service-wide rename. Maps to the new SOLVE script.
STATUS_MESSAGES = SOLVE_STATUS_MESSAGES
