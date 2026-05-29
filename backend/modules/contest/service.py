"""Student-facing contest service.

Time-gates every action so a client cannot enter early, start early, or
submit after the window. Stores graded responses + the participation
summary so the leaderboard ranks deterministically.

Lifecycle:
    [scheduled] -> lobby opens 5 min before start
       user posts /enter         → entered_at
    [live]      -> at start_time
       user posts /start         → started_at, questions returned
    [submitted] -> user posts /submit OR auto-submit at end_time
       /result, /leaderboard available thereafter
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.exceptions import (
    ContestAlreadySubmitted,
    ContestEnded,
    ContestLobbyClosed,
    ContestNotEntered,
    ContestNotFound,
    ContestNotStarted,
)
from modules.contest.constants import (
    LEADERBOARD_PAGE_SIZE,
    LOBBY_OPEN_SECONDS,
)
from modules.contest.grader import (
    grade_answer,
    is_attempt_empty,
    score_for,
)
from modules.contest.repository import ContestRepository
from modules.contest.schema import (
    ContestAnswerInput,
    ContestListItem,
    ContestListResponse,
    ContestLobbyResponse,
    ContestOption,
    ContestPerQuestionResult,
    ContestQuestion,
    ContestResultResponse,
    EnterLobbyResponse,
    LeaderboardResponse,
    LeaderboardRow,
    MarkingScheme,
    StartContestResponse,
    SubmitContestRequest,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compute_status(start: datetime, end: datetime, now: datetime) -> str:
    if now < start:
        return "scheduled"
    if now >= end:
        return "completed"
    return "live"


def _user_state(participation: Optional[dict], status: str) -> str:
    """Derive the student's per-contest state for the UI badge."""
    if participation is None:
        return "missed" if status == "completed" else "none"
    if participation.get("submitted_at"):
        return "submitted"
    if participation.get("started_at"):
        return "in_progress"
    return "entered"


# ---------------------------------------------------------------------------
# Question payload — bbd_db doc → wire shape
# ---------------------------------------------------------------------------

def _option_list(doc: dict) -> list[ContestOption]:
    out: list[ContestOption] = []
    for key in ("A", "B", "C", "D"):
        text = doc.get(f"option{key}")
        if text is None or str(text).strip() == "":
            continue
        out.append(ContestOption(key=key, text=str(text)))
    return out


def _matching_cols(doc: dict) -> tuple[list[str], list[str]]:
    md = doc.get("matchingData") or {}
    left_raw = md.get("leftColumn") or []
    right_raw = md.get("rightColumn") or []
    left = [str(x.get("text") if isinstance(x, dict) else x) for x in left_raw]
    right = [str(x.get("text") if isinstance(x, dict) else x) for x in right_raw]
    return left, right


def _qtype_of(doc: dict) -> str:
    return (doc.get("questionType") or doc.get("question_type") or "single_correct").lower()


def _to_payload(doc: dict, display_order: int) -> ContestQuestion:
    qtype = _qtype_of(doc)
    left, right = ([], [])
    if qtype == "matching":
        left, right = _matching_cols(doc)
    return ContestQuestion(
        question_id=str(doc["_id"]),
        display_order=display_order,
        question_type=qtype,  # type: ignore[arg-type]
        difficulty=(str(doc.get("difficulty")).lower() if doc.get("difficulty") else None),
        question_text=str(doc.get("questionText") or doc.get("question_text") or ""),
        options=_option_list(doc) if qtype in ("single_correct", "multi_correct") else [],
        left_column=left,
        right_column=right,
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ContestService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.repo = ContestRepository(db)

    # --------------------- listing ---------------------

    async def list_for_user(self, user_id: ObjectId) -> ContestListResponse:
        docs = await self.repo.list_visible()
        # Pre-fetch the user's participations in one query (vs N).
        parts = await self.repo.list_participations_for_user(user_id)
        part_by_contest = {str(p["contest_id"]): p for p in parts}
        now = _utcnow()

        upcoming: list[ContestListItem] = []
        live: list[ContestListItem] = []
        past: list[ContestListItem] = []
        for d in docs:
            item = self._to_list_item(d, part_by_contest.get(str(d["_id"])), now)
            if item.status == "scheduled":
                upcoming.append(item)
            elif item.status == "live":
                live.append(item)
            else:
                past.append(item)

        # Upcoming surfaced soonest-first; past newest-first.
        upcoming.sort(key=lambda x: x.start_time)
        past.sort(key=lambda x: x.start_time, reverse=True)
        return ContestListResponse(upcoming=upcoming, live=live, past=past)

    async def get_lobby(
        self, contest_id: str, user: dict,
    ) -> ContestLobbyResponse:
        doc = await self.repo.get(contest_id)
        if doc is None:
            raise ContestNotFound()
        user_id = user["_id"] if isinstance(user["_id"], ObjectId) else ObjectId(user["_id"])
        part = await self.repo.get_participation(doc["_id"], user_id)
        now = _utcnow()
        start = _as_utc(doc["start_time"])
        end = _as_utc(doc["end_time"])
        status = _compute_status(start, end, now)
        lobby_opens_at = start - timedelta(seconds=LOBBY_OPEN_SECONDS)
        marking = doc.get("marking") or {}
        return ContestLobbyResponse(
            id=str(doc["_id"]),
            title=doc.get("title", ""),
            description=doc.get("description", "") or "",
            rules=doc.get("rules", "") or "",
            start_time=start,
            end_time=end,
            duration_seconds=int(doc.get("duration_seconds", 0)),
            question_count=len(doc.get("question_ids") or []),
            marking=MarkingScheme(
                correct=float(marking.get("correct", 0)),
                wrong=float(marking.get("wrong", 0)),
                unattempted=float(marking.get("unattempted", 0)),
            ),
            status=status,  # type: ignore[arg-type]
            lobby_opens_at=lobby_opens_at,
            lobby_open=now >= lobby_opens_at,
            user_state=_user_state(part, status),  # type: ignore[arg-type]
        )

    # --------------------- lobby + start ---------------------

    async def enter_lobby(
        self, contest_id: str, user: dict,
    ) -> EnterLobbyResponse:
        doc = await self.repo.get(contest_id)
        if doc is None:
            raise ContestNotFound()
        start = _as_utc(doc["start_time"])
        end = _as_utc(doc["end_time"])
        now = _utcnow()
        if now >= end:
            raise ContestEnded()
        lobby_opens_at = start - timedelta(seconds=LOBBY_OPEN_SECONDS)
        if now < lobby_opens_at:
            raise ContestLobbyClosed(
                f"Lobby opens at {lobby_opens_at.isoformat()}."
            )
        user_id = user["_id"] if isinstance(user["_id"], ObjectId) else ObjectId(user["_id"])
        username = user.get("username") or ""
        part = await self.repo.upsert_lobby_entry(doc["_id"], user_id, username)
        return EnterLobbyResponse(
            user_state=_user_state(part, _compute_status(start, end, now)),  # type: ignore[arg-type]
            entered_at=_as_utc(part["entered_at"]),
        )

    async def start(
        self, contest_id: str, user: dict,
    ) -> StartContestResponse:
        doc = await self.repo.get(contest_id)
        if doc is None:
            raise ContestNotFound()
        start = _as_utc(doc["start_time"])
        end = _as_utc(doc["end_time"])
        now = _utcnow()
        if now < start:
            raise ContestNotStarted(
                f"Contest starts at {start.isoformat()}."
            )
        if now >= end:
            raise ContestEnded()
        user_id = user["_id"] if isinstance(user["_id"], ObjectId) else ObjectId(user["_id"])
        part = await self.repo.get_participation(doc["_id"], user_id)
        if part is None:
            raise ContestNotEntered()
        if part.get("submitted_at"):
            raise ContestAlreadySubmitted()

        # Idempotent: re-hitting /start after a refresh returns the
        # same questions + the original started_at so the client timer
        # picks up where it left off.
        if part.get("started_at"):
            started_at = _as_utc(part["started_at"])
        else:
            updated = await self.repo.mark_started(doc["_id"], user_id)
            started_at = _as_utc(updated["started_at"])

        qdocs = await self.repo.fetch_questions_in_order(doc.get("question_ids") or [])
        questions = [_to_payload(q, i) for i, q in enumerate(qdocs)]

        return StartContestResponse(
            contest_id=str(doc["_id"]),
            started_at=started_at,
            end_time=end,
            duration_seconds=int(doc.get("duration_seconds", 0)),
            server_now=now,
            questions=questions,
        )

    # --------------------- submit + result ---------------------

    async def submit(
        self, contest_id: str, user: dict, payload: SubmitContestRequest,
    ) -> ContestResultResponse:
        doc = await self.repo.get(contest_id)
        if doc is None:
            raise ContestNotFound()
        user_id = user["_id"] if isinstance(user["_id"], ObjectId) else ObjectId(user["_id"])
        part = await self.repo.get_participation(doc["_id"], user_id)
        if part is None or not part.get("started_at"):
            raise ContestNotStarted()
        if part.get("submitted_at"):
            raise ContestAlreadySubmitted()

        result = await self._grade_and_persist(doc, user_id, part, payload.answers)
        return result

    async def get_result(
        self, contest_id: str, user: dict,
    ) -> ContestResultResponse:
        doc = await self.repo.get(contest_id)
        if doc is None:
            raise ContestNotFound()
        user_id = user["_id"] if isinstance(user["_id"], ObjectId) else ObjectId(user["_id"])
        part = await self.repo.get_participation(doc["_id"], user_id)
        if part is None or not part.get("submitted_at"):
            raise ContestNotStarted("You haven't submitted this contest yet.")

        responses = await self.repo.list_responses(doc["_id"], user_id)
        qdocs = await self.repo.fetch_questions_in_order(doc.get("question_ids") or [])
        rank, total = await self._rank_for(doc["_id"], user_id)
        return self._build_result(doc, part, qdocs, responses, rank=rank, total=total)

    async def get_leaderboard(
        self, contest_id: str, user: dict,
    ) -> LeaderboardResponse:
        doc = await self.repo.get(contest_id)
        if doc is None:
            raise ContestNotFound()
        rows = await self.repo.leaderboard(doc["_id"], limit=LEADERBOARD_PAGE_SIZE)
        total = await self.repo.count_submitted(doc["_id"])
        user_id = user["_id"] if isinstance(user["_id"], ObjectId) else ObjectId(user["_id"])

        out: list[LeaderboardRow] = []
        your_rank: Optional[int] = None
        for i, r in enumerate(rows):
            rank = i + 1
            is_you = r.get("user_id") == user_id
            if is_you:
                your_rank = rank
            out.append(
                LeaderboardRow(
                    rank=rank,
                    user_id=str(r["user_id"]),
                    username=r.get("username") or "—",
                    is_you=is_you,
                    score=float(r.get("score") or 0),
                    correct_count=int(r.get("correct_count") or 0),
                    wrong_count=int(r.get("wrong_count") or 0),
                    unattempted_count=int(r.get("unattempted_count") or 0),
                    time_taken_seconds=int(r.get("time_taken_seconds") or 0),
                    submitted_at=_as_utc(r["submitted_at"]),
                )
            )
        return LeaderboardResponse(
            contest_id=str(doc["_id"]),
            title=doc.get("title", ""),
            total_participants=total,
            your_rank=your_rank,
            rows=out,
        )

    # --------------------- internals ---------------------

    def _to_list_item(
        self, doc: dict, part: Optional[dict], now: datetime,
    ) -> ContestListItem:
        start = _as_utc(doc["start_time"])
        end = _as_utc(doc["end_time"])
        status = _compute_status(start, end, now)
        marking = doc.get("marking") or {}
        lobby_opens_at = start - timedelta(seconds=LOBBY_OPEN_SECONDS)
        return ContestListItem(
            id=str(doc["_id"]),
            title=doc.get("title", ""),
            description=doc.get("description", "") or "",
            start_time=start,
            end_time=end,
            duration_seconds=int(doc.get("duration_seconds", 0)),
            question_count=len(doc.get("question_ids") or []),
            marking=MarkingScheme(
                correct=float(marking.get("correct", 0)),
                wrong=float(marking.get("wrong", 0)),
                unattempted=float(marking.get("unattempted", 0)),
            ),
            status=status,  # type: ignore[arg-type]
            lobby_opens_at=lobby_opens_at,
            lobby_open=now >= lobby_opens_at,
            user_state=_user_state(part, status),  # type: ignore[arg-type]
        )

    async def _grade_and_persist(
        self,
        doc: dict,
        user_id: ObjectId,
        part: dict,
        answers: list[ContestAnswerInput],
    ) -> ContestResultResponse:
        qdocs = await self.repo.fetch_questions_in_order(doc.get("question_ids") or [])
        marking = doc.get("marking") or {}

        ans_by_id = {a.question_id: a.model_dump() for a in answers}

        response_rows: list[dict[str, Any]] = []
        correct_count = 0
        wrong_count = 0
        unattempted_count = 0
        total_score = 0.0

        for i, q in enumerate(qdocs):
            qid = str(q["_id"])
            qtype = _qtype_of(q)
            ans = ans_by_id.get(qid) or {}
            empty = is_attempt_empty(qtype, ans)
            graded = grade_answer(qtype, ans, q)
            marks = score_for(graded, marking, empty)
            total_score += marks

            if empty:
                unattempted_count += 1
            elif graded.is_correct:
                correct_count += 1
            else:
                wrong_count += 1

            response_rows.append({
                "contest_id": doc["_id"],
                "user_id": user_id,
                "question_id": q["_id"],
                "display_order": i,
                "question_type": qtype,
                "user_answer": graded.user_answer,
                "correct_answer": graded.correct_answer,
                "is_correct": bool(graded.is_correct),
                "correctness": float(graded.correctness),
                "marks_awarded": float(marks),
                "empty": empty,
            })

        time_taken_seconds = int((_utcnow() - _as_utc(part["started_at"])).total_seconds())
        # Cap by contest duration so a late submit can't game the
        # tie-breaker. The server still allows a submit after the
        # window only if the caller manages to land it before
        # /submit's `ContestEnded` check — but if that does happen
        # we clamp the time so the leaderboard stays fair.
        time_taken_seconds = max(0, min(time_taken_seconds, int(doc.get("duration_seconds", 0))))

        await self.repo.replace_responses(doc["_id"], user_id, response_rows)
        await self.repo.mark_submitted(
            doc["_id"], user_id,
            score=total_score,
            correct_count=correct_count,
            wrong_count=wrong_count,
            unattempted_count=unattempted_count,
            time_taken_seconds=time_taken_seconds,
        )

        # Re-fetch the participation row so the response carries the
        # canonical submitted_at the DB stamped (not our local one).
        part_after = await self.repo.get_participation(doc["_id"], user_id)
        assert part_after is not None

        rank, total = await self._rank_for(doc["_id"], user_id)
        return self._build_result(
            doc, part_after, qdocs, response_rows, rank=rank, total=total,
        )

    async def _rank_for(
        self, contest_id: ObjectId, user_id: ObjectId,
    ) -> tuple[int, int]:
        """Compute (rank, total) for one user across all submitted
        participations. Rank is 1-based; 0 means the user hasn't
        submitted (caller should treat the field as a no-op then)."""
        rows = await self.repo.leaderboard(contest_id, limit=10_000)
        total = len(rows)
        for i, r in enumerate(rows):
            if r.get("user_id") == user_id:
                return (i + 1, total)
        return (0, total)

    def _build_result(
        self,
        doc: dict,
        part: dict,
        qdocs: list[dict],
        responses: list[dict],
        *,
        rank: int,
        total: int,
    ) -> ContestResultResponse:
        marking = doc.get("marking") or {}
        max_score = float(marking.get("correct", 0)) * len(qdocs)
        score = float(part.get("score") or 0)

        resp_by_qid = {str(r["question_id"]): r for r in responses}

        per_q: list[ContestPerQuestionResult] = []
        for i, q in enumerate(qdocs):
            qid = str(q["_id"])
            r = resp_by_qid.get(qid) or {}
            qtype = _qtype_of(q)
            left, right = ([], [])
            if qtype == "matching":
                left, right = _matching_cols(q)
            per_q.append(ContestPerQuestionResult(
                question_id=qid,
                display_order=i,
                question_type=qtype,
                difficulty=(str(q.get("difficulty")).lower() if q.get("difficulty") else None),
                question_text=str(q.get("questionText") or q.get("question_text") or ""),
                options=_option_list(q) if qtype in ("single_correct", "multi_correct") else [],
                left_column=left,
                right_column=right,
                user_answer=r.get("user_answer"),
                correct_answer=r.get("correct_answer"),
                is_correct=bool(r.get("is_correct")),
                correctness=float(r.get("correctness") or 0),
                marks_awarded=float(r.get("marks_awarded") or 0),
                solution_text=q.get("solution") or q.get("solutionText"),
            ))

        return ContestResultResponse(
            contest_id=str(doc["_id"]),
            title=doc.get("title", ""),
            total_questions=len(qdocs),
            correct_count=int(part.get("correct_count") or 0),
            wrong_count=int(part.get("wrong_count") or 0),
            unattempted_count=int(part.get("unattempted_count") or 0),
            score=score,
            max_score=max_score,
            accuracy_pct=(100.0 * int(part.get("correct_count") or 0) / max(1, len(qdocs))),
            time_taken_seconds=int(part.get("time_taken_seconds") or 0),
            submitted_at=_as_utc(part["submitted_at"]),
            rank=rank,
            total_participants=total,
            results=per_q,
        )
