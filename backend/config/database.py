import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING

from config.settings import settings

logger = logging.getLogger(__name__)


class MongoDB:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None


mongo = MongoDB()


async def connect_to_mongo() -> None:
    """Initialize Motor client with connection pooling and ensure indexes."""
    logger.info("Connecting to MongoDB...")
    mongo.client = AsyncIOMotorClient(
        settings.MONGO_URI,
        maxPoolSize=100,
        minPoolSize=10,
        serverSelectionTimeoutMS=5000,
        uuidRepresentation="standard",
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


def get_database() -> AsyncIOMotorDatabase:
    if mongo.db is None:
        raise RuntimeError("MongoDB has not been initialized. Call connect_to_mongo().")
    return mongo.db
