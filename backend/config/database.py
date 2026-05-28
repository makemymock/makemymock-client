import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from config.settings import settings

logger = logging.getLogger(__name__)


class MongoDB:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None


class PyQMongoDB:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None


mongo = MongoDB()
pyq_mongo = PyQMongoDB()


async def connect_to_mongo() -> None:
    """Initialize Motor client with connection pooling and ensure indexes."""
    logger.info("Connecting to MongoDB...")
    # tz_aware=True so datetime values read back from Mongo carry UTC
    # tzinfo. Without it, Motor returns timezone-naive datetimes and Pydantic
    # serializes them as ISO strings WITHOUT a timezone marker, which the
    # browser then interprets as local time. All datetime arithmetic in this
    # codebase must therefore use `datetime.now(timezone.utc)` (tz-aware)
    # rather than the deprecated `datetime.utcnow()` (tz-naive).
    mongo.client = AsyncIOMotorClient(
        settings.MONGO_URI,
        maxPoolSize=100,
        minPoolSize=10,
        serverSelectionTimeoutMS=5000,
        uuidRepresentation="standard",
        tz_aware=True,
    )
    mongo.db = mongo.client[settings.MONGO_DB_NAME]

    # Sanity ping
    await mongo.client.admin.command("ping")
    logger.info("MongoDB connection established.")

    await _ensure_indexes()

    # Connect to the PYQ cluster (separate credentials/host).
    if settings.PYQ_MONGO_URI:
        try:
            pyq_mongo.client = AsyncIOMotorClient(
                settings.PYQ_MONGO_URI,
                maxPoolSize=20,
                minPoolSize=2,
                serverSelectionTimeoutMS=5000,
                tz_aware=True,
            )
            pyq_mongo.db = pyq_mongo.client[settings.JEE_QUESTIONS_DB_NAME]
            await pyq_mongo.client.admin.command("ping")
            await pyq_mongo.db["jee_mains_pyqs"].create_index(
                [("subject", 1), ("chapter", 1), ("topic", 1)],
            )
            logger.info("PYQ MongoDB connection established.")
        except Exception as exc:
            logger.warning("PYQ MongoDB connection failed: %s — question catalog unavailable.", exc)
            pyq_mongo.client = None
            pyq_mongo.db = None
    else:
        logger.warning("PYQ_MONGO_URI not set; question catalog unavailable.")


async def close_mongo_connection() -> None:
    if mongo.client is not None:
        logger.info("Closing MongoDB connection...")
        mongo.client.close()
        mongo.client = None
        mongo.db = None
    if pyq_mongo.client is not None:
        pyq_mongo.client.close()
        pyq_mongo.client = None
        pyq_mongo.db = None


async def _ensure_indexes() -> None:
    """Create indexes for uniqueness and TTL-style cleanup of OTPs."""
    assert mongo.db is not None

    # users — email & username must be unique
    await mongo.db["users"].create_index([("email", ASCENDING)], unique=True)
    await mongo.db["users"].create_index([("username", ASCENDING)], unique=True)

    # student_profiles — one profile per user
    await mongo.db["student_profiles"].create_index(
        [("user_id", ASCENDING)], unique=True
    )

    # email_otps — quick lookup by email, auto-expire docs once `expires_at` passes
    await mongo.db["email_otps"].create_index([("email", ASCENDING)])
    await mongo.db["email_otps"].create_index("expires_at", expireAfterSeconds=0)

    # ---------- mock-test state ----------
    # Attempts must be unique per (user, question) so retakes overwrite,
    # which is exactly what the engine's `upsert_attempts` relies on.
    await mongo.db["user_topic_attempts"].create_index(
        [("user_id", ASCENDING), ("question_id", ASCENDING)],
        unique=True,
    )
    await mongo.db["user_topic_attempts"].create_index(
        [("user_id", ASCENDING), ("topic_id", ASCENDING)],
    )
    await mongo.db["user_topic_attempts"].create_index(
        [("session_id", ASCENDING)],
    )

    # practice_solution_views — one marker per (user, question) that the
    # user revealed the solution in Browse. Isolated from attempts so a
    # peeked question never feeds the recommender.
    await mongo.db["practice_solution_views"].create_index(
        [("user_id", ASCENDING), ("obj_id", ASCENDING)],
        unique=True,
    )

    # notebook_entries — questions a user marked to revise later. Unique per
    # (user, question) so the same question can't be added twice.
    await mongo.db["notebook_entries"].create_index(
        [("user_id", ASCENDING), ("obj_id", ASCENDING)],
        unique=True,
    )

    await mongo.db["mock_test_sessions"].create_index([("user_id", ASCENDING)])
    await mongo.db["mock_test_sessions"].create_index(
        [("user_id", ASCENDING), ("created_at", -1)],
    )

    await mongo.db["mock_test_topics"].create_index([("session_id", ASCENDING)])

    await mongo.db["mock_test_responses"].create_index(
        [("session_id", ASCENDING), ("question_id", ASCENDING)],
        unique=True,
    )
    await mongo.db["mock_test_responses"].create_index(
        [("session_id", ASCENDING), ("display_order", ASCENDING)],
    )

    # ---------- id-mapping helpers ----------
    # Question int-id map: unique by (obj_id, sub_index).
    await mongo.db["question_id_map"].create_index(
        [("obj_id", ASCENDING), ("sub_index", ASCENDING)],
        unique=True,
    )
    await mongo.db["topic_id_map"].create_index(
        [("chapter_id", ASCENDING), ("name", ASCENDING)],
        unique=True,
    )
    await mongo.db["chapter_id_map"].create_index(
        [("subject_id", ASCENDING), ("name", ASCENDING)],
        unique=True,
    )
    await mongo.db["subject_id_map"].create_index(
        [("name", ASCENDING)],
        unique=True,
    )

    # ---------- questions catalog (bbd_db schema) ----------
    # Backs the per-test candidate-pool query (subject/chapter/topic triple).
    # Created only if it doesn't already exist; safe to call repeatedly.
    await mongo.db["questions"].create_index(
        [("subject", ASCENDING), ("chapter", ASCENDING), ("topic", ASCENDING)],
    )

    # ---------- 1-vs-1 battles ----------
    # History lookups go by either player's user_id, sorted newest first.
    await mongo.db["battles"].create_index(
        [("player_a.user_id", ASCENDING), ("completed_at", -1)],
    )
    await mongo.db["battles"].create_index(
        [("player_b.user_id", ASCENDING), ("completed_at", -1)],
    )

    # ---------- SolverX ----------
    # Conversations are per-user, sorted by recency in the sidebar.
    await mongo.db["solverx_conversations"].create_index(
        [("user_id", ASCENDING), ("updated_at", -1)],
    )
    # Messages join back to their conversation; in-order read on detail.
    await mongo.db["solverx_messages"].create_index(
        [("conversation_id", ASCENDING), ("created_at", ASCENDING)],
    )

    # ---------- JEE Recommender ----------

    # student_topic_state — 156 docs per student; unique on (student_id, topic_id)
    # so a double-initialize call is a no-op rather than a data corruption.
    await mongo.db["student_topic_state"].create_index(
        [("student_id", ASCENDING), ("topic_id", ASCENDING)],
        unique=True,
    )
    # Chapter rollup: used by tool_get_unlocked_topics when filtering by chapter.
    await mongo.db["student_topic_state"].create_index(
        [("student_id", ASCENDING), ("chapter", ASCENDING)],
    )
    # SM-2 due-review query: find all topics due for review today.
    await mongo.db["student_topic_state"].create_index(
        [("student_id", ASCENDING), ("next_review_date", ASCENDING)],
    )

    # student_personality — one doc per student; unique on student_id.
    await mongo.db["student_personality"].create_index(
        [("student_id", ASCENDING)],
        unique=True,
    )

    # student_question_history — raw event log.
    # Primary: time-ordered history for error-cluster computation.
    await mongo.db["student_question_history"].create_index(
        [("student_id", ASCENDING), ("timestamp", DESCENDING)],
    )
    # Seen-question lookup: used by Question Selector to exclude correct repeats.
    await mongo.db["student_question_history"].create_index(
        [("student_id", ASCENDING), ("question_id", ASCENDING)],
    )
    # Session-scoped: session summary generation filters by session_id.
    await mongo.db["student_question_history"].create_index(
        [("student_id", ASCENDING), ("session_id", ASCENDING)],
    )

    # session_summaries — Level-1 memory (≈200 tokens each).
    # Session Planner reads last-3 sorted by recency.
    await mongo.db["session_summaries"].create_index(
        [("student_id", ASCENDING), ("created_at", DESCENDING)],
    )
    # Diagnosis Agent fetches by session_id after session_end trigger.
    await mongo.db["session_summaries"].create_index(
        [("session_id", ASCENDING)],
        unique=True,
        sparse=True,
    )

    # topic_trend_scores — 156 docs, recomputed weekly.
    # Unique on topic_id so upsert-replace is always consistent.
    await mongo.db["topic_trend_scores"].create_index(
        [("topic_id", ASCENDING)],
        unique=True,
    )
    # get_trend_top_topics sorts by p_appears descending.
    await mongo.db["topic_trend_scores"].create_index(
        [("p_appears", DESCENDING)],
    )


def get_database() -> AsyncIOMotorDatabase:
    if mongo.db is None:
        raise RuntimeError("MongoDB has not been initialized. Call connect_to_mongo().")
    return mongo.db


def get_pyq_database() -> Optional[AsyncIOMotorDatabase]:
    return pyq_mongo.db
