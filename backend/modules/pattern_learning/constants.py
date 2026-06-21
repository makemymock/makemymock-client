"""Constants for the pattern-learning feature."""

# Per-student progress collection (in the PYQ_PROGRESS_DB_NAME database).
ATTEMPTS_COLLECTION = "pattern_question_attempts"

# Catalog collections we read (in the PYQ_DB_NAME / adaptive_practice database).
PATTERNS_COLLECTION = "patterns"
ASSIGNMENTS_COLLECTION = "pattern_assignments"
QUESTIONS_COLLECTION = "jee_mains_pyqs"

# Unlock gate: minimum mock-test accuracy (%) a student needs IN A CHAPTER to
# open its first pattern. Chapter-specific only — there is NO overall fallback,
# so a chapter the student hasn't practised (or is weak in) stays locked until
# they clear this bar in that chapter's mock questions.
# NOTE: temporarily lowered to 15 to make paths easy to open during testing/demo.
UNLOCK_MIN_ACCURACY = 15.0

# jee_mains_pyqs question types.
QUESTION_TYPE_SINGLE = "mcq"    # single correct option
QUESTION_TYPE_MULTI = "mcqm"    # multiple correct options
QUESTION_TYPE_INTEGER = "integer"  # numeric answer

# Node states surfaced to the frontend roadmap.
STATE_LOCKED = "locked"
STATE_UNLOCKED = "unlocked"
STATE_COMPLETED = "completed"   # a fully-finished pattern
STATE_SOLVED = "solved"         # an answered question
