"""Collection names + tuning for the student-facing contest module."""

# Read from this collection. Writes are owned by the Admin backend.
CONTESTS_COLLECTION = "contests"

# Per-(contest, user) row. Writes owned by this module.
PARTICIPATIONS_COLLECTION = "contest_participations"

# Per-(contest, user, question) row. Writes owned by this module.
RESPONSES_COLLECTION = "contest_responses"

# Questions catalog (bbd_db). Read-only.
QUESTIONS_COLLECTION = "questions"

# Lobby entry window: students can enter the lobby this many seconds
# before start_time, and can press Start only at or after start_time.
LOBBY_OPEN_SECONDS = 5 * 60

# How many recent contests to surface in the public "upcoming/past"
# listing. Past contests are kept for leaderboard access.
LIST_PAGE_SIZE = 50

# Leaderboard cap per request.
LEADERBOARD_PAGE_SIZE = 100
