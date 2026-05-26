"""Constants for the SolverX module."""

CONVERSATIONS_COLLECTION = "solverx_conversations"
MESSAGES_COLLECTION = "solverx_messages"

# Conversation modes
MODE_SOLVE = "solve"
MODE_THEORY = "theory"

# Complexity modes (used in UI as toggle labels).
COMPLEXITY_GUIDED = "guided"   # "Guided Solve"   — fast direct solving
COMPLEXITY_DEEP = "deep"       # "Deep Reasoning" — multi-stage explanation

# Sectional markers the planning + solve stages emit. The frontend splits
# on these to build structured blocks.
BLOCK_TYPES = (
    "understanding",
    "key_concept",
    "step",
    "intuition",
    "warning",
    "diagram",
    "final_answer",
    "alternative",
    "summary",
    "insight",
)

# Groq base URL and a soft timeout that's well below Railway/most
# proxies' read timeout. Streaming overrides the read timeout via
# httpx.Timeout(read=None). Groq is OpenAI-compatible at /openai/v1.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_REQUEST_TIMEOUT = 60.0

# Status-message script that the orchestrator emits between stages. These
# strings carry the "premium multi-agent" feel even though we run a
# consolidated two-call pipeline under the hood — labels read the same
# either way.
STATUS_MESSAGES = {
    "plan_start": "Topic detection agent analyzing your question…",
    "plan_done": "Pedagogy planner laying out the explanation strategy…",
    "solve_start": "Step solver agents constructing the solution…",
    "solve_progress": "Verifying derivation and polishing each step…",
    "insight": "Reading your performance signal for personalized insights…",
    "diagram_draft": "Visual reasoning agent sketching the figure…",
    "diagram_polish": "Refactor agent auditing the diagram…",
    "done": "Done.",
}

# Theory-mode status script — slightly different vocabulary so it doesn't
# sound like we're "solving" a problem when the student asked a concept.
THEORY_STATUS_MESSAGES = {
    "plan_start": "Concept agent identifying what you're asking about…",
    "plan_done": "Tutor agent planning how to teach this clearly…",
    "solve_start": "Building intuitive explanation with examples…",
    "solve_progress": "Adding analogies and visual cues…",
    "insight": "Linking this to your recent practice topics…",
    "diagram_draft": "Visual reasoning agent sketching the figure…",
    "diagram_polish": "Refactor agent auditing the diagram…",
    "done": "Done.",
}
