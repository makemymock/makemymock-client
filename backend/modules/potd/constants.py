"""Constants for the Problem-of-the-Day module."""

# ---------- Collections ----------
# One row per user per day — records which question was picked.
POTD_ASSIGNMENTS_COLLECTION = "potd_assignments"
# One row per user per day they engaged — drives streak + calendar.
POTD_USER_STATE_COLLECTION = "potd_user_state"

# ---------- Retry caps ----------
# Only single_correct gets a cap (brute-force risk on a 4-option pick).
# multi_correct / integer / matching are not realistically brute-forceable
# and stay unlimited. Tune from here without a redeploy elsewhere.
MAX_RETRIES_SINGLE_CORRECT = 3

# Question types that the POTD picker is allowed to surface. Passages have
# multiple sub-questions and the "one question per day" framing breaks down
# — we exclude them entirely so the daily commitment stays small.
ELIGIBLE_QUESTION_TYPES = {"single_correct", "multi_correct", "integer", "matching"}

# ---------- Engagement states stored in `potd_user_state.status` ----------
STATUS_IN_PROGRESS = "in_progress"  # at least one attempt, not yet correct, retries still available
STATUS_SOLVED = "solved"            # correct on some attempt — streak credit earned
STATUS_VIEWED = "viewed"            # explicit "give up" — solution revealed, streak broken
STATUS_EXHAUSTED = "exhausted"      # single_correct used all retries and never landed correct

# ---------- Calendar window defaults ----------
DEFAULT_HISTORY_DAYS = 60
MAX_HISTORY_DAYS = 365
