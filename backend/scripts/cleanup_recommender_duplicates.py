"""
One-time cleanup script: remove duplicate (student_id, topic_id) rows from
adaptive_practice.student_topic_state on the PYQ cluster.

After running this, the unique index on (student_id, topic_id) will build
cleanly on the next server start.

Usage (from the backend/ directory):
    python scripts/cleanup_recommender_duplicates.py [--dry-run]

Requires PYQ_MONGO_URI to be set in backend/.env.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# ── resolve backend/ as the package root ─────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

# load .env before importing settings
from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

COLLECTION = "student_topic_state"
DB_NAME    = os.getenv("JEE_QUESTIONS_DB_NAME", "adaptive_practice")


async def run(dry_run: bool) -> None:
    uri = os.getenv("PYQ_MONGO_URI", "")
    if not uri:
        log.error("PYQ_MONGO_URI is not set in .env — aborting.")
        sys.exit(1)

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10_000, tz_aware=True)
    db     = client[DB_NAME]
    col    = db[COLLECTION]

    log.info("Connected to %s / %s", uri.split("@")[-1], DB_NAME)

    # Find groups that have more than one doc for the same (student_id, topic_id)
    pipeline = [
        {"$group": {
            "_id": {"student_id": "$student_id", "topic_id": "$topic_id"},
            "ids":   {"$push": "$_id"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]

    duplicate_groups = await col.aggregate(pipeline).to_list(length=None)

    if not duplicate_groups:
        log.info("No duplicates found — collection is already clean.")
        client.close()
        return

    total_to_delete = sum(len(g["ids"]) - 1 for g in duplicate_groups)
    log.info(
        "Found %d duplicate group(s) → %d extra doc(s) to delete.",
        len(duplicate_groups),
        total_to_delete,
    )

    if dry_run:
        log.info("DRY RUN — no changes made. Re-run without --dry-run to apply.")
        for g in duplicate_groups:
            log.info(
                "  student_id=%-26s  topic_id=%s  copies=%d",
                g["_id"]["student_id"], g["_id"]["topic_id"], g["count"],
            )
        client.close()
        return

    deleted_total = 0
    for g in duplicate_groups:
        # Keep the first doc (oldest insert order), delete the rest
        ids_to_delete = g["ids"][1:]
        result = await col.delete_many({"_id": {"$in": ids_to_delete}})
        deleted_total += result.deleted_count
        log.info(
            "  Deleted %d duplicate(s) for student_id=%s topic_id=%s",
            result.deleted_count,
            g["_id"]["student_id"],
            g["_id"]["topic_id"],
        )

    log.info("Done — deleted %d duplicate doc(s) total.", deleted_total)
    log.info(
        "Restart the server; the unique index on (%s, topic_id) will now build cleanly.",
        "student_id",
    )
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove duplicate student_topic_state docs.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be deleted without actually deleting anything.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
