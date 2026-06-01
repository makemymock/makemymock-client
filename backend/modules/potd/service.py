"""POTD orchestration — picks today's question, grades attempts, drives streak."""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import status

from core.exceptions import AppException
from modules.mock_test.constants import PRACTICE_SESSION_ID
from modules.mock_test.grader import (
    grade_integer,
    grade_matching,
    grade_multi_correct,
    grade_single_correct,
)
from modules.mock_test.model import new_attempt_doc
from modules.mock_test.repository import MockTestRepository
from modules.mock_test.service import MockTestService
from modules.potd.constants import (
    DEFAULT_HISTORY_DAYS,
    ELIGIBLE_QUESTION_TYPES,
    MAX_HISTORY_DAYS,
    MAX_RETRIES_SINGLE_CORRECT,
    STATUS_EXHAUSTED,
    STATUS_IN_PROGRESS,
    STATUS_SOLVED,
    STATUS_VIEWED,
)
from modules.potd.model import (
    new_potd_assignment_doc,
    new_potd_user_state_doc,
    now_utc,
)
from modules.potd.repository import PotdRepository, today_ist
from modules.potd.schema import (
    AttemptRequest,
    AttemptResponse,
    HistoryDay,
    HistoryResponse,
    PastAttemptInfo,
    PastDateResponse,
    PotdOption,
    PotdQuestion,
    StreakResponse,
    TodayResponse,
    ViewSolutionResponse,
)

logger = logging.getLogger(__name__)


class PotdService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = PotdRepository(db)
        # Borrow the mock-test machinery for engine-aware picking, grading,
        # and the cooldown-gated write path. POTD owns its own collections;
        # everything that touches the recommender flows through mock-test.
        self.mock = MockTestService(db)
        self.mock_repo = MockTestRepository(db)

    # ------------------------------------------------------------------
    # Today's POTD
    # ------------------------------------------------------------------

    async def get_today(self, user_oid: ObjectId) -> TodayResponse:
        date_ist = today_ist()
        assignment = await self.repo.get_assignment(user_oid, date_ist)
        if assignment is None:
            assignment = await self._materialise_today(user_oid, date_ist)
            if assignment is None:
                raise AppException(
                    "Couldn't find a question for today's challenge yet.",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                )
        # Ensure the user-state row exists so subsequent queries don't have
        # to special-case a missing record.
        state = await self.repo.get_state(user_oid, date_ist)
        if state is None:
            state = await self.repo.upsert_initial_state(new_potd_user_state_doc(
                user_id=user_oid,
                date_ist=date_ist,
                question_id=assignment["question_id"],
            ))

        question_doc = await self.mock_repo.get_question_by_obj_id(
            str(assignment["question_id"]),
        )
        if question_doc is None:
            raise AppException(
                "Today's question is no longer available.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return self._build_today_response(
            assignment=assignment,
            state=state,
            question_doc=question_doc,
        )

    async def _materialise_today(
        self, user_oid: ObjectId, date_ist: str,
    ) -> Optional[dict]:
        topic_id = await self._pick_topic_id(user_oid)
        if topic_id is None:
            return None
        chosen = await self.mock.pick_potd_candidate(user_oid, topic_id)
        if chosen is None:
            return None
        qtype = (chosen.get("questionType") or "single_correct").lower()
        if qtype not in ELIGIBLE_QUESTION_TYPES:
            # Defensive — pick_potd_candidate already excludes passages.
            return None
        max_attempts = (
            MAX_RETRIES_SINGLE_CORRECT if qtype == "single_correct" else None
        )
        doc = new_potd_assignment_doc(
            user_id=user_oid,
            date_ist=date_ist,
            question_id=chosen["_id"],
            topic_id=int(chosen.get("_topic_id") or await self._resolve_topic_id(chosen)),
            question_type=qtype,
            difficulty=(chosen.get("difficulty") or "medium"),
            max_attempts=max_attempts,
        )
        await self.repo.insert_assignment(doc)
        # Re-read so a race (two tabs) still gets the stored winner.
        return await self.repo.get_assignment(user_oid, date_ist)

    async def _resolve_topic_id(self, doc: dict) -> int:
        _sid, _cid, tid = await self.mock_repo.get_or_create_topic_id(
            (doc.get("subject") or "").strip(),
            (doc.get("chapter") or "").strip(),
            (doc.get("topic") or "").strip(),
        )
        return int(tid)

    async def _pick_topic_id(self, user_oid: ObjectId) -> Optional[int]:
        """Server-side mirror of the old client-side topic picker.

        60% of the time pick the user's highest-priority (weakest) topic,
        40% a random other attempted topic. Brand-new users (no attempts
        yet) get a random topic from the full catalog so day-one POTD
        still works.
        """
        analytics = await self.mock.get_topic_analytics(user_oid)
        topics = list(analytics.topics) if analytics and analytics.topics else []
        if topics:
            top = topics[0]
            others = topics[1:]
            if not others or random.random() < 0.6:
                return int(top.topic_id)
            pick = random.choice(others)
            return int(pick.topic_id)
        # No prior attempts — random catalog fallback.
        catalog = await self.mock.get_catalog_raw()
        eligible = [c for c in catalog if c["question_count"] > 0]
        if not eligible:
            return None
        return int(random.choice(eligible)["topic_id"])

    # ------------------------------------------------------------------
    # Attempt
    # ------------------------------------------------------------------

    async def submit_attempt(
        self, user_oid: ObjectId, payload: AttemptRequest,
    ) -> AttemptResponse:
        date_ist = today_ist()
        assignment = await self.repo.get_assignment(user_oid, date_ist)
        if assignment is None:
            raise AppException(
                "No POTD is set for today yet — open it once to materialise.",
                status.HTTP_404_NOT_FOUND,
            )
        state = await self.repo.get_state(user_oid, date_ist)
        if state is None:
            state = await self.repo.upsert_initial_state(new_potd_user_state_doc(
                user_id=user_oid,
                date_ist=date_ist,
                question_id=assignment["question_id"],
            ))

        if state["status"] in (STATUS_SOLVED, STATUS_VIEWED, STATUS_EXHAUSTED):
            raise AppException(
                "Today's challenge is already settled.",
                status.HTTP_409_CONFLICT,
            )

        question_doc = await self.mock_repo.get_question_by_obj_id(
            str(assignment["question_id"]),
        )
        if question_doc is None:
            raise AppException(
                "Today's question is no longer available.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        qtype = (question_doc.get("questionType") or "single_correct").lower()
        graded = _grade(qtype, payload, question_doc)
        now = datetime.now(timezone.utc)

        # Recommender feed — same cooldown logic as Browse practice.
        obj_id_str = str(question_doc["_id"])
        int_id = await self.mock_repo.get_or_create_question_int_id(obj_id_str, None)
        topic_id = int(assignment["topic_id"])
        difficulty = str(question_doc.get("difficulty") or "medium")
        feeds = await self.mock._attempt_feeds_recommender(
            user_id=user_oid, obj_id=obj_id_str, int_id=int_id, now=now,
        )
        if feeds:
            await self.mock_repo.bulk_upsert_attempts([new_attempt_doc(
                user_id=user_oid, question_id=int_id, topic_id=topic_id,
                is_correct=graded.is_correct, correctness=graded.correctness,
                difficulty=difficulty, score_contribution=0,
                attempted_at=now, session_id=PRACTICE_SESSION_ID,
            )])
        else:
            await self.mock_repo.mark_attempt_non_feeding(
                user_id=user_oid, question_id=int_id, topic_id=topic_id,
                is_correct=graded.is_correct, correctness=graded.correctness,
                difficulty=difficulty, attempted_at=now,
                session_id=PRACTICE_SESSION_ID,
            )

        # Decide the new POTD state.
        new_attempt_count = int(state.get("attempt_count", 0)) + 1
        max_attempts = assignment.get("max_attempts")
        first_correct_at = None
        if graded.is_correct:
            new_status = STATUS_SOLVED
            first_correct_at = now
        elif max_attempts is not None and new_attempt_count >= int(max_attempts):
            new_status = STATUS_EXHAUSTED
        else:
            new_status = STATUS_IN_PROGRESS

        updated = await self.repo.update_state_after_attempt(
            user_id=user_oid,
            date_ist=date_ist,
            new_status=new_status,
            attempt_count=new_attempt_count,
            last_attempt_at=now,
            first_correct_at=first_correct_at,
        )

        # Reveal on correct OR exhausted; otherwise keep the answer hidden.
        reveal = new_status in (STATUS_SOLVED, STATUS_EXHAUSTED)
        correct_answer = _correct_answer_payload(question_doc, qtype) if reveal else None
        solution = (
            question_doc.get("solution") or question_doc.get("explanation") or ""
        ) if reveal else None

        current_streak, _longest, _last = await self.repo.streak_walk(user_oid)
        return AttemptResponse(
            correct=bool(graded.is_correct),
            status=new_status,
            attempt_count=new_attempt_count,
            max_attempts=max_attempts,
            correct_answer=correct_answer,
            solution=solution,
            streak_after=current_streak,
        )

    # ------------------------------------------------------------------
    # View solution (explicit give-up)
    # ------------------------------------------------------------------

    async def view_solution(self, user_oid: ObjectId) -> ViewSolutionResponse:
        date_ist = today_ist()
        assignment = await self.repo.get_assignment(user_oid, date_ist)
        if assignment is None:
            raise AppException(
                "No POTD is set for today yet.",
                status.HTTP_404_NOT_FOUND,
            )
        state = await self.repo.get_state(user_oid, date_ist)
        if state is None:
            state = await self.repo.upsert_initial_state(new_potd_user_state_doc(
                user_id=user_oid,
                date_ist=date_ist,
                question_id=assignment["question_id"],
            ))
        # If the user has already solved, there's no streak to break — but
        # they can still pull up the solution. Don't downgrade `solved` to
        # `viewed`; that would erase legitimate credit.
        if state["status"] != STATUS_SOLVED:
            await self.repo.mark_viewed(user_oid, date_ist)

        question_doc = await self.mock_repo.get_question_by_obj_id(
            str(assignment["question_id"]),
        )
        if question_doc is None:
            return ViewSolutionResponse(solution="", correct_answer=None, streak_after=0)
        qtype = (question_doc.get("questionType") or "single_correct").lower()
        current_streak, _longest, _last = await self.repo.streak_walk(user_oid)
        return ViewSolutionResponse(
            solution=question_doc.get("solution") or question_doc.get("explanation") or "",
            correct_answer=_correct_answer_payload(question_doc, qtype),
            streak_after=current_streak,
        )

    # ------------------------------------------------------------------
    # Streak + calendar
    # ------------------------------------------------------------------

    async def get_streak(self, user_oid: ObjectId) -> StreakResponse:
        current, longest, last = await self.repo.streak_walk(user_oid)
        last_date = None
        if last:
            from datetime import date as _date
            try:
                last_date = _date.fromisoformat(last)
            except Exception:
                last_date = None
        return StreakResponse(
            current=current, longest=longest, last_solved_at=last_date,
        )

    async def get_history(
        self, user_oid: ObjectId, days: int = DEFAULT_HISTORY_DAYS,
    ) -> HistoryResponse:
        from datetime import date as _date, timedelta
        days = max(1, min(int(days), MAX_HISTORY_DAYS))
        today = today_ist()
        from_date = (_date.fromisoformat(today) - timedelta(days=days - 1)).isoformat()
        rows = await self.repo.list_states_in_range(user_oid, from_date, today)
        out = [
            HistoryDay(
                date_ist=str(r["date_ist"]),
                status=r.get("status", STATUS_IN_PROGRESS),
                question_id=str(r["question_id"]),
                attempt_count=int(r.get("attempt_count") or 0),
            )
            for r in rows
        ]
        return HistoryResponse(days=out, range_days=days)

    # ------------------------------------------------------------------
    # Past date detail (calendar cell click)
    # ------------------------------------------------------------------

    async def get_past_date(
        self, user_oid: ObjectId, date_ist: str,
    ) -> PastDateResponse:
        assignment = await self.repo.get_assignment(user_oid, date_ist)
        if assignment is None:
            raise AppException("No POTD recorded for that date.", status.HTTP_404_NOT_FOUND)
        state = await self.repo.get_state(user_oid, date_ist)
        question_doc = await self.mock_repo.get_question_by_obj_id(
            str(assignment["question_id"]),
        )
        if question_doc is None:
            raise AppException("That question is no longer available.", status.HTTP_410_GONE)
        # Opening a past POTD reveals the solution, so bump the cooldown
        # clock for this question. Future browse attempts within 24h are
        # then correctly flagged as non-feeding by the recommender.
        await self.mock_repo.record_view(user_oid, str(assignment["question_id"]))
        qtype = (question_doc.get("questionType") or "single_correct").lower()
        # Past dates always show the answer + solution — there's no streak
        # to protect after the fact.
        return PastDateResponse(
            date_ist=date_ist,
            question=_project_question(
                question_doc, qtype, topic_id=int(assignment["topic_id"]),
            ),
            status=(state.get("status") if state else STATUS_IN_PROGRESS),
            attempt_count=int(state.get("attempt_count") if state else 0),
            correct_answer=_correct_answer_payload(question_doc, qtype),
            solution=(
                question_doc.get("solution") or question_doc.get("explanation") or ""
            ),
            user_last_answer=None,  # not stored — keep blank rather than guessing
            user_last_correct=None,
        )

    # ------------------------------------------------------------------
    # Build the today response (shared by get_today)
    # ------------------------------------------------------------------

    def _build_today_response(
        self, *, assignment: dict, state: dict, question_doc: dict,
    ) -> TodayResponse:
        qtype = (question_doc.get("questionType") or "single_correct").lower()
        status_val = state.get("status", STATUS_IN_PROGRESS)
        reveal = status_val in (STATUS_SOLVED, STATUS_VIEWED, STATUS_EXHAUSTED)
        return TodayResponse(
            date_ist=str(assignment["date_ist"]),
            question=_project_question(
                question_doc, qtype, topic_id=int(assignment["topic_id"]),
            ),
            status=status_val,
            attempt_count=int(state.get("attempt_count") or 0),
            max_attempts=assignment.get("max_attempts"),
            correct_answer=_correct_answer_payload(question_doc, qtype) if reveal else None,
            solution=(
                question_doc.get("solution") or question_doc.get("explanation") or ""
            ) if reveal else None,
            first_correct_at=state.get("first_correct_at"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grade(qtype: str, payload: AttemptRequest, doc: dict):
    if qtype == "single_correct":
        return grade_single_correct(payload.selected_option, doc)
    if qtype == "multi_correct":
        return grade_multi_correct(payload.selected_options, doc)
    if qtype == "integer":
        return grade_integer(payload.integer_answer, doc)
    if qtype == "matching":
        return grade_matching(payload.matching, doc)
    # Unknown — defensive default to single_correct.
    return grade_single_correct(payload.selected_option, doc)


def _project_question(doc: dict, qtype: str, *, topic_id: int) -> PotdQuestion:
    options: list[PotdOption] = []
    for key in ("A", "B", "C", "D"):
        text = doc.get(f"option{key}")
        if text is None or str(text).strip() == "":
            continue
        options.append(PotdOption(key=key, text=str(text)))
    left: list[str] = []
    right: list[str] = []
    if qtype == "matching":
        md = doc.get("matchingData") or {}
        left = [str(x) for x in (md.get("leftColumn") or [])]
        right = [str(x) for x in (md.get("rightColumn") or [])]
    return PotdQuestion(
        question_id=str(doc["_id"]),
        topic_id=topic_id,
        topic_name=(doc.get("topic") or "").strip() or None,
        subject=(doc.get("subject") or "").strip() or None,
        chapter=(doc.get("chapter") or "").strip() or None,
        difficulty=(doc.get("difficulty") or "medium"),
        question_type=qtype,
        question_text=doc.get("questionText") or "",
        options=options,
        left_column=left,
        right_column=right,
    )


def _correct_answer_payload(doc: dict, qtype: str) -> Any:
    if qtype == "single_correct":
        opts = sorted({
            str(x).strip().upper()
            for x in (doc.get("correctOptions") or [])
            if str(x).strip()
        })
        return opts[0] if len(opts) == 1 else opts
    if qtype == "multi_correct":
        return sorted({
            str(x).strip().upper()
            for x in (doc.get("correctOptions") or [])
            if str(x).strip()
        })
    if qtype == "integer":
        return doc.get("integerAnswer")
    if qtype == "matching":
        md = doc.get("matchingData") or {}
        out: dict[str, list[str]] = {}
        for k, v in (md.get("correctMapping") or {}).items():
            if isinstance(v, (list, tuple, set)):
                out[str(k)] = [str(x) for x in v]
            elif v is not None:
                out[str(k)] = [str(v)]
        return out
    return None


# `PastAttemptInfo` is exported for future use when we wire per-attempt
# replay; currently the past-date endpoint returns just the latest snapshot.
__all__ = ["PotdService", "PastAttemptInfo"]
