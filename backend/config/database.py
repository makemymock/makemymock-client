import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from config.settings import settings

logger = logging.getLogger(__name__)


class MongoDB:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None


mongo = MongoDB()


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


async def close_mongo_connection() -> None:
    if mongo.client is not None:
        logger.info("Closing MongoDB connection...")
        mongo.client.close()
        mongo.client = None
        mongo.db = None


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

    # POTD — one assignment + one engagement-state row per (user, date_ist).
    # The streak / calendar reads filter by user_id then range over
    # date_ist (ISO string ordering = chronological), so the compound
    # indexes serve both lookups cleanly.
    await mongo.db["potd_assignments"].create_index(
        [("user_id", ASCENDING), ("date_ist", ASCENDING)],
        unique=True,
    )
    await mongo.db["potd_user_state"].create_index(
        [("user_id", ASCENDING), ("date_ist", ASCENDING)],
        unique=True,
    )
    await mongo.db["potd_user_state"].create_index(
        [("user_id", ASCENDING), ("status", ASCENDING)],
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

    # ---------- Battle invites (battle-a-friend) ----------
    # `code` is the public token — unique so two pending invites can't
    # collide. `expires_at` doubles as a TTL key so Mongo auto-evicts
    # invites after their 10-min window (status is still updated to
    # `expired` at lookup time for any stragglers that read between
    # expiry and eviction).
    await mongo.db["battle_invites"].create_index(
        [("code", ASCENDING)], unique=True,
    )
    await mongo.db["battle_invites"].create_index(
        "expires_at", expireAfterSeconds=0,
    )
    await mongo.db["battle_invites"].create_index(
        [("inviter_user_id", ASCENDING), ("status", ASCENDING)],
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

    # ---------- Contests ----------
    # Admin writes to `contests`; the Client backend reads them and owns
    # the per-user participation / response collections.
    # `start_time` index serves listing (sort + filter) and the no-overlap
    # check on admin create/update.
    await mongo.db["contests"].create_index([("start_time", ASCENDING)])
    await mongo.db["contests"].create_index([("end_time", ASCENDING)])

    # One participation row per (contest, user) — both the lobby-entry
    # upsert and the leaderboard read rely on this.
    await mongo.db["contest_participations"].create_index(
        [("contest_id", ASCENDING), ("user_id", ASCENDING)],
        unique=True,
    )
    # Leaderboard sort key: score desc, time asc — declared as ascending
    # because Mongo can walk indexes in reverse for the score component.
    await mongo.db["contest_participations"].create_index(
        [("contest_id", ASCENDING), ("score", ASCENDING),
         ("time_taken_seconds", ASCENDING)],
    )
    await mongo.db["contest_participations"].create_index([("user_id", ASCENDING)])

    # Per-question responses. Unique per (contest, user, question) so a
    # retry can't double-write; also the in-order read for the result
    # page sorts by display_order.
    await mongo.db["contest_responses"].create_index(
        [("contest_id", ASCENDING), ("user_id", ASCENDING),
         ("question_id", ASCENDING)],
        unique=True,
    )
    await mongo.db["contest_responses"].create_index(
        [("contest_id", ASCENDING), ("user_id", ASCENDING),
         ("display_order", ASCENDING)],
    )

    # ---- Admin observability ----
    # `usage_events` — append-only log of cost-bearing or otherwise
    # interesting actions (currently Vertex AI calls). Indexed by time
    # for the time-series admin charts and by user for per-user
    # aggregations. Source field lets us add new event types later
    # (e.g. mock_test_start, battle_join) without schema changes.
    await mongo.db["usage_events"].create_index([("ts", DESCENDING)])
    await mongo.db["usage_events"].create_index(
        [("user_id", ASCENDING), ("ts", DESCENDING)],
    )
    await mongo.db["usage_events"].create_index(
        [("source", ASCENDING), ("ts", DESCENDING)],
    )

    # NOTE: the pattern-miner collections (patterns / pattern_assignments /
    # checkpoints) live on a separate PYQ cluster, not here — their indexes are
    # created in modules/pattern_miner/db.py:ensure_indexes().


def get_database() -> AsyncIOMotorDatabase:
    if mongo.db is None:
        raise RuntimeError("MongoDB has not been initialized. Call connect_to_mongo().")
    return mongo.db
