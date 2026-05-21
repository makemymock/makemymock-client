"""Collection names and tunable defaults for the mock-test module."""

# ---------- Read-only catalog (bbd_db schema) ----------
QUESTIONS_COLLECTION = "questions"

# ---------- Recommender state, owned by this module ----------
SESSIONS_COLLECTION = "mock_test_sessions"
TOPICS_COLLECTION = "mock_test_topics"
RESPONSES_COLLECTION = "mock_test_responses"
ATTEMPTS_COLLECTION = "user_topic_attempts"

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
MIN_TEST_SIZE = 5
MAX_TEST_SIZE = 100

# ---------- Allowed question types ----------
QUESTION_TYPES = (
    "single_correct",
    "multi_correct",
    "integer",
    "matching",
    "passage",
)
