"""Collection names and tunable defaults for the mock-test module."""

# ---------- Read-only catalog (bbd_db schema) ----------
QUESTIONS_COLLECTION = "questions"

# ---------- Recommender state, owned by this module ----------
SESSIONS_COLLECTION = "mock_test_sessions"
TOPICS_COLLECTION = "mock_test_topics"
RESPONSES_COLLECTION = "mock_test_responses"
ATTEMPTS_COLLECTION = "user_topic_attempts"

# Browse / practice: records that a user revealed a question's solution.
# Kept separate from `user_topic_attempts` so a peeked question never feeds
# the recommender — viewing the solution is "seen", not "attempted".
PRACTICE_VIEWS_COLLECTION = "practice_solution_views"

# Notebook: questions a user marked to revise later. One doc per
# (user, question); unique so a question can't be marked twice.
NOTEBOOK_COLLECTION = "notebook_entries"

# Sentinel session id stamped on attempts made through the Browse/practice
# flow (no real mock-test session exists for them).
PRACTICE_SESSION_ID = 0

# ---------- ID mapping (ObjectId / triple ↔ int) ----------
QUESTION_ID_MAP_COLLECTION = "question_id_map"
TOPIC_ID_MAP_COLLECTION = "topic_id_map"
CHAPTER_ID_MAP_COLLECTION = "chapter_id_map"
SUBJECT_ID_MAP_COLLECTION = "subject_id_map"
COUNTERS_COLLECTION = "id_counters"

# Counter document ids
COUNTER_SESSION = "session_seq"
COUNTER_QUESTION = "question_int_id"
COUNTER_TOPIC = "topic_int_id"
COUNTER_CHAPTER = "chapter_int_id"
COUNTER_SUBJECT = "subject_int_id"

# ---------- Timer policy ----------
SECONDS_PER_QUESTION = 90  # 1.5 minutes per question

# ---------- Recommender feed cooldown ----------
# When a user touches a question (attempts it anywhere, or reveals its
# solution in Browse), the next attempt within this window grades the
# answer for the student but does NOT update recommender priorities.
# Keeps fresh signal honest: students who just saw the answer can't
# inflate their priority/decay metrics by re-attempting.
RECOMMENDER_COOLDOWN_HOURS = 24
