"""Mongo I/O for the POTD module.

Owns the two per-user-per-day collections (`potd_assignments`, `potd_user_state`)
and the read helpers behind streak + calendar.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from modules.potd.constants import (
    POTD_ASSIGNMENTS_COLLECTION,
    POTD_USER_STATE_COLLECTION,
    STATUS_EXHAUSTED,
    STATUS_SOLVED,
    STATUS_VIEWED,
)
from modules.potd.model import now_utc


# IST has no DST; calendar-day boundaries for the streak/calendar must
# match what students see on their wall clock (the audience is Indian).
IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> str:
    return datetime.now(IST).date().isoformat()


def parse_date_ist(s: str) -> date:
    return date.fromisoformat(s)


class PotdRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.assignments = db[POTD_ASSIGNMENTS_COLLECTION]
        self.user_state = db[POTD_USER_STATE_COLLECTION]

    # ---- assignments ----

    async def get_assignment(
        self, user_id: ObjectId, date_ist: str,
    ) -> Optional[dict]:
        return await self.assignments.find_one(
            {"user_id": user_id, "date_ist": date_ist},
        )

    async def insert_assignment(self, doc: dict) -> None:
        try:
            await self.assignments.insert_one(doc)
        except Exception:
            # Race — another tab created the assignment in the meantime.
            # The unique index keeps both rows from existing; we'll re-read.
            pass

    # ---- user state ----

    async def get_state(
        self, user_id: ObjectId, date_ist: str,
    ) -> Optional[dict]:
        return await self.user_state.find_one(
            {"user_id": user_id, "date_ist": date_ist},
        )

    async def upsert_initial_state(self, doc: dict) -> dict:
        """Create the row if it doesn't exist; never overwrite an in-flight one."""
        await self.user_state.update_one(
            {"user_id": doc["user_id"], "date_ist": doc["date_ist"]},
            {"$setOnInsert": doc},
            upsert=True,
        )
        existing = await self.get_state(doc["user_id"], doc["date_ist"])
        assert existing is not None
        return existing

    async def update_state_after_attempt(
        self,
        *,
        user_id: ObjectId,
        date_ist: str,
        new_status: str,
        attempt_count: int,
        last_attempt_at: datetime,
        first_correct_at: Optional[datetime],
    ) -> dict:
        """Apply the post-attempt status transition.

        `first_correct_at` is set only on the attempt that flipped status to
        `solved` — subsequent attempts on the same day (which can't happen
        in our flow, but defensive) won't overwrite it.
        """
        update: dict[str, Any] = {
            "$set": {
                "status": new_status,
                "attempt_count": int(attempt_count),
                "last_attempt_at": last_attempt_at,
                "updated_at": now_utc(),
            },
        }
        if first_correct_at is not None:
            update["$setOnInsert"] = {}
            update["$set"]["first_correct_at"] = first_correct_at
        doc = await self.user_state.find_one_and_update(
            {"user_id": user_id, "date_ist": date_ist},
            update,
            return_document=ReturnDocument.AFTER,
            upsert=False,
        )
        assert doc is not None, "user_state row must exist before update"
        return doc

    async def mark_viewed(
        self, user_id: ObjectId, date_ist: str,
    ) -> dict:
        doc = await self.user_state.find_one_and_update(
            {"user_id": user_id, "date_ist": date_ist},
            {
                "$set": {
                    "status": "viewed",
                    "updated_at": now_utc(),
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        assert doc is not None
        return doc

    # ---- streak + calendar ----

    async def list_states_in_range(
        self, user_id: ObjectId, from_date: str, to_date: str,
    ) -> list[dict]:
        """All state rows for the user with date_ist in [from_date, to_date].

        date_ist is stored as ISO `YYYY-MM-DD`, so string ordering equals
        chronological ordering — `$gte` / `$lte` work directly.
        """
        cursor = self.user_state.find(
            {
                "user_id": user_id,
                "date_ist": {"$gte": from_date, "$lte": to_date},
            },
        ).sort("date_ist", 1)
        return [d async for d in cursor]

    async def list_solved_dates_since(
        self, user_id: ObjectId, since_date: str,
    ) -> list[str]:
        """Distinct IST date strings the user solved POTD on or after `since_date`.

        Used by the confidence sub-score in mock_test.
        """
        cursor = self.user_state.find(
            {
                "user_id": user_id,
                "status": STATUS_SOLVED,
                "date_ist": {"$gte": since_date},
            },
            {"date_ist": 1},
        )
        return [str(d["date_ist"]) async for d in cursor]

    async def streak_walk(self, user_id: ObjectId) -> tuple[int, int, Optional[str]]:
        """Compute (current_streak, longest_streak, last_solved_date).

        Current streak rules:
        - If today's status is `viewed` or `exhausted`, the streak is broken
          NOW — current = 0 regardless of what yesterday looked like.
        - Otherwise, count the run of consecutive solved days ending today
          (if solved) or yesterday (if today is in_progress / unopened).
        - A gap of more than one day resets the streak.
        Longest is the all-time longest consecutive run.
        """
        cursor = self.user_state.find(
            {"user_id": user_id, "status": STATUS_SOLVED},
            {"date_ist": 1},
        ).sort("date_ist", 1)
        solved_dates: list[date] = []
        async for d in cursor:
            try:
                solved_dates.append(parse_date_ist(d["date_ist"]))
            except Exception:
                continue

        # Longest run — independent of today's status.
        longest = 0
        if solved_dates:
            longest = 1
            current_run = 1
            for prev, curr in zip(solved_dates[:-1], solved_dates[1:]):
                if (curr - prev).days == 1:
                    current_run += 1
                    longest = max(longest, current_run)
                else:
                    current_run = 1

        # Today's status is the deciding factor for the *current* streak.
        today = datetime.now(IST).date()
        today_iso = today.isoformat()
        today_row = await self.user_state.find_one(
            {"user_id": user_id, "date_ist": today_iso},
            {"status": 1},
        )
        today_status = today_row.get("status") if today_row else None

        last_solved = solved_dates[-1] if solved_dates else None

        if today_status in (STATUS_VIEWED, STATUS_EXHAUSTED):
            # Streak broken today — no credit, even if yesterday was solved.
            return 0, longest, last_solved.isoformat() if last_solved else None

        if not solved_dates:
            return 0, longest, None

        # Today is unopened or in_progress (still recoverable), or solved.
        # The streak counts back from the most recent solved date — but
        # only if it sits at today or yesterday in IST.
        if (today - last_solved).days > 1:
            current = 0
        else:
            current = 1
            i = len(solved_dates) - 2
            while i >= 0 and (solved_dates[i + 1] - solved_dates[i]).days == 1:
                current += 1
                i -= 1
        return current, longest, last_solved.isoformat()
