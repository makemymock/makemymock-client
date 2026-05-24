"""Constants for the 1-vs-1 battle module."""

# ---------- Collections ----------
BATTLES_COLLECTION = "battles"

# Read-only catalog used to source random questions (bbd_db schema, same as
# mock-test). We only read; we never write back to it.
QUESTIONS_COLLECTION = "questions"

# ---------- Game rules ----------
QUESTIONS_PER_BATTLE = 5
SECONDS_PER_QUESTION = 15.0
QUEUE_TIMEOUT_SECONDS = 15.0   # how long a solo player waits for an opponent
REVEAL_PAUSE_SECONDS = 3.0     # pause between question result and next question
COUNTDOWN_SECONDS = 3          # "3, 2, 1, GO" before round 1

# ---------- Scoring ----------
BASE_POINTS_CORRECT = 100
SPEED_BONUS_MAX = 50           # extra points for an instant correct answer

# ---------- WebSocket close codes (custom) ----------
WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_DUPLICATE = 4409
WS_CLOSE_INTERNAL = 4500
