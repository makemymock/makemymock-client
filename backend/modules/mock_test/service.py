"""Mock-test orchestration.

Wires the FastAPI controller to the engine via the BufferedRepository,
handles catalog projection, builds frontend payloads, and runs the
submission grader.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.exceptions import AppException
from engine.models import Attempt as EngineAttempt, Question as EngineQuestion
from engine.recommender import create_mock_test as engine_create_mock_test
from engine.recommender import submit_test as engine_submit_test
from engine.models import AnswerEvaluation
from fastapi import status

from modules.mock_test.constants import (
    COUNTER_SESSION,
    PRACTICE_SESSION_ID,
    RECOMMENDER_COOLDOWN_HOURS,
    SECONDS_PER_QUESTION,
)
from modules.mock_test.engine_adapter import BufferedRepository
from modules.mock_test.grader import (
    GradedAnswer,
    grade_integer,
    grade_matching,
    grade_multi_correct,
    grade_passage_sub,
    grade_single_correct,
)
from modules.mock_test.model import (
    new_attempt_doc,
    new_response_doc,
    new_topic_allocation_doc,
)
from config.database import get_pyq_database
from modules.mock_test.repository import MockTestRepository
from modules.mock_test.schema import (
    AccuracyTrendPoint,
    ActivityHeatmapResponse,
    AnalyticsChaptersResponse,
    AnalyticsOverviewResponse,
    AnalyticsTopicsResponse,
    AnswerInput,
    BrowseAttemptRequest,
    BrowseAttemptResponse,
    BrowseItem,
    BrowseListResponse,
    BrowsePerformance,
    BrowseQuestionDetail,
    BrowseSolutionResponse,
    NotebookCountResponse,
    NotebookToggleResponse,
    CatalogChapter,
    CatalogResponse,
    CatalogSubject,
    CatalogTopic,
    ChapterAnalytics,
    ChapterDetailResponse,
    CreateMockTestRequest,
    CreateMockTestResponse,
    CumulativePoint,
    ConfidenceResponse,
    ConfidenceSubScore,
    ConfidenceTier,
    DifficultyBreakdown,
    HeatmapDay,
    HistoryItem,
    HistoryResponse,
    PerQuestionResult,
    PriorityTrendPoint,
    QuestionPayload,
    QuestionPayloadOption,
    RecentAttempt,
    SessionResponse,
    SubmitMockTestRequest,
    SubmitMockTestResponse,
    TopicAccuracyTrend,
    TopicAnalytics,
    TopicDetailResponse,
    TopicPriorityTrend,
    TrendPoint,
    TypeBreakdown,
)

logger = logging.getLogger(__name__)


# India Standard Time (UTC+5:30, no DST). MakeMyMock's audience is
# Indian students — day-bucketed analytics (heatmap, daily trends)
# must line up with what students see on their wall clock, not with
# UTC. A problem solved at 01:00 IST belongs to that calendar day.
IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Confidence-score tiers and sub-score weights.
#
# Six bands across the [0, 100] confidence score, each gets a trophy name:
#   0–15   Doubter      — just starting
#   16–32  Explorer     — trying things
#   33–50  Confident    — finding the groove
#   51–68  Focused      — committed practice
#   69–84  Fearless     — high performer
#   85–100 Unstoppable  — elite
# Weights below sum to 1.0; tweak with care — bigger weight on accuracy
# means low-volume high-accuracy students rank above grinders, and so on.
# ---------------------------------------------------------------------------

_CONFIDENCE_TIERS: list[dict[str, Any]] = [
    {"name": "Doubter",     "index": 0, "min": 0,  "max": 15},
    {"name": "Explorer",    "index": 1, "min": 16, "max": 32},
    {"name": "Confident",   "index": 2, "min": 33, "max": 50},
    {"name": "Focused",     "index": 3, "min": 51, "max": 68},
    {"name": "Fearless",    "index": 4, "min": 69, "max": 84},
    {"name": "Unstoppable", "index": 5, "min": 85, "max": 100},
]

_CONFIDENCE_WEIGHTS = {
    "volume":      0.20,   # log-scaled total attempts
    "accuracy":    0.30,   # accuracy adjusted for sample size + floor
    "consistency": 0.20,   # active days in last 30
    "battle":      0.15,   # engagement + win rate in 1v1 battles
    "potd":        0.15,   # Problem-of-the-Day days in last 30
}
assert abs(sum(_CONFIDENCE_WEIGHTS.values()) - 1.0) < 1e-9, (
    "Confidence sub-score weights must sum to 1.0"
)


def _tier_for_confidence(score: float) -> dict[str, Any]:
    """Return the tier dict whose [min, max] band contains `score`."""
    bounded = max(0.0, min(100.0, score))
    for t in _CONFIDENCE_TIERS:
        if t["min"] <= bounded <= t["max"]:
            return t
    return _CONFIDENCE_TIERS[0]


def _next_tier(index: int) -> Optional[dict[str, Any]]:
    return _CONFIDENCE_TIERS[index + 1] if index + 1 < len(_CONFIDENCE_TIERS) else None


# Display order rule (frontend & backend agree):
# single → multi → passage → matching → integer
_TYPE_RANK = {
    "single_correct": 0,
    "multi_correct": 1,
    "passage": 2,
    "matching": 3,
    "integer": 4,
}


def _options_from_doc(doc: dict) -> list[QuestionPayloadOption]:
    out: list[QuestionPayloadOption] = []
    for key in ("A", "B", "C", "D"):
        text = doc.get(f"option{key}")
        if text is None or str(text).strip() == "":
            continue
        out.append(QuestionPayloadOption(key=key, text=str(text)))
    return out


def _bucket_by_key(
    attempts: list[dict],
    *,
    key_fn,
) -> dict[str, tuple[int, float]]:
    """Group attempts by `key_fn(attempt)` → (count, sum-of-effective-correctness)."""
    out: dict[str, tuple[int, float]] = {}
    for a in attempts:
        k = key_fn(a)
        corr = a.get("correctness")
        if corr is None:
            corr = 1.0 if a.get("is_correct") else 0.0
        cur = out.get(k, (0, 0.0))
        out[k] = (cur[0] + 1, cur[1] + float(corr))
    return out


def _cumulative_by_day(attempts: list[dict]):
    """Return [(day, delta, cumulative)] ordered by day.

    Days are bucketed by IST midnight (see the `IST` constant at the
    top of this module) so the chapter / topic trend charts show one
    point per *Indian calendar day*, matching what students see.
    """
    from modules.mock_test.schema import CumulativePoint  # local import avoids cycles
    if not attempts:
        return []
    by_day: dict[datetime, int] = defaultdict(int)
    for a in attempts:
        at = a.get("attempted_at")
        if not isinstance(at, datetime):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        at_ist = at.astimezone(IST)
        day = at_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        by_day[day] += 1
    out = []
    cumulative = 0
    for day in sorted(by_day.keys()):
        delta = by_day[day]
        cumulative += delta
        out.append(CumulativePoint(date=day, delta=delta, cumulative=cumulative))
    return out


def _matching_cols(doc: dict) -> tuple[list[str], list[str]]:
    """Return (leftColumn, rightColumn) as plain LaTeX-bearing strings.

    bbd_db stores both columns as `[String]` and uses 0-based integer
    indices into them everywhere (correctMapping keys + values). We pass
    the strings through unchanged so the client can render `P1..Pn` /
    `Q1..Qm` row & column headers from their list positions.
    """
    md = doc.get("matchingData") or {}
    left = [str(x) for x in (md.get("leftColumn") or [])]
    right = [str(x) for x in (md.get("rightColumn") or [])]
    return left, right


# ---------------------------------------------------------------------------
# Browse (practice) helpers — turn raw grading / stored attempts into the
# `correct / partial / incorrect` status the Browse UI shows.
# ---------------------------------------------------------------------------

def _eff_correctness(is_correct: bool, correctness: Optional[float]) -> float:
    if correctness is not None:
        return float(correctness)
    return 1.0 if is_correct else 0.0


def _browse_status(is_correct: bool, correctness: Optional[float]) -> str:
    if is_correct:
        return "correct"
    return "partial" if _eff_correctness(is_correct, correctness) > 0 else "incorrect"


def _perf_from_graded(g: GradedAnswer) -> BrowsePerformance:
    return BrowsePerformance(
        status=_browse_status(g.is_correct, g.correctness),
        correctness=_eff_correctness(g.is_correct, g.correctness),
        attempted_at=None,
    )


def _perf_from_attempt(a: dict) -> BrowsePerformance:
    ic = bool(a.get("is_correct"))
    corr = a.get("correctness")
    return BrowsePerformance(
        status=_browse_status(ic, corr),
        correctness=_eff_correctness(ic, corr),
        attempted_at=a.get("attempted_at"),
    )


def _aggregate_perf(attempts: list[dict]) -> Optional[BrowsePerformance]:
    """Roll several attempts (e.g. a passage's sub-questions) into one
    status: all-correct → correct, none → incorrect, mixed → partial."""
    if not attempts:
        return None
    effs = [
        _eff_correctness(bool(a.get("is_correct")), a.get("correctness"))
        for a in attempts
    ]
    avg = sum(effs) / len(effs)
    all_correct = all(bool(a.get("is_correct")) for a in attempts)
    if all_correct:
        status = "correct"
    elif avg <= 0:
        status = "incorrect"
    else:
        status = "partial"
    times = [a.get("attempted_at") for a in attempts if a.get("attempted_at")]
    return BrowsePerformance(
        status=status, correctness=avg,
        attempted_at=max(times) if times else None,
    )


# ---------------------------------------------------------------------------
# Composite question-id helpers — the Browse layer addresses standalone
# questions by their Mongo `_id` and passage sub-questions by a synthetic
# `"{obj_id}_{sub_index}"` key. ObjectIds are pure hex (no underscores), so
# the separator is unambiguous.
# ---------------------------------------------------------------------------

def _parse_composite_qid(qid: str) -> tuple[str, Optional[int]]:
    if "_" in qid:
        obj_id, sub_str = qid.rsplit("_", 1)
        try:
            return obj_id, int(sub_str)
        except ValueError:
            return qid, None
    return qid, None


def _make_composite(obj_id: str, sub_index: Optional[int]) -> str:
    return obj_id if sub_index is None else f"{obj_id}_{int(sub_index)}"


def _correct_answer_for(doc: dict, qtype: str) -> Any:
    """Correct answer in the shape `QuestionViewer` expects in readOnly mode."""
    if qtype == "single_correct":
        opts = sorted({str(x).strip().upper() for x in (doc.get("correctOptions") or []) if str(x).strip()})
        return opts[0] if len(opts) == 1 else opts
    if qtype == "multi_correct":
        return sorted({str(x).strip().upper() for x in (doc.get("correctOptions") or []) if str(x).strip()})
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


class MockTestService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = MockTestRepository(db, pyq_db=get_pyq_database())

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    async def get_catalog(self) -> CatalogResponse:
        rows = await self.repo.list_all_catalog_topics()
        if not rows:
            return CatalogResponse(subjects=[])

        # Materialize int ids for every (subject, chapter, topic) in the catalog.
        subjects: dict[str, CatalogSubject] = {}
        chapters: dict[tuple[str, str], CatalogChapter] = {}

        for row in rows:
            subject = row["subject"]
            chapter = row["chapter"]
            topic = row["topic"]
            count = row["question_count"]

            sid, cid, tid = await self.repo.get_or_create_topic_id(
                subject, chapter, topic,
            )

            if subject not in subjects:
                subjects[subject] = CatalogSubject(
                    id=sid, name=subject, chapters=[],
                )
            ch_key = (subject, chapter)
            if ch_key not in chapters:
                ch = CatalogChapter(
                    id=cid, subject_id=sid, name=chapter, topics=[],
                )
                chapters[ch_key] = ch
                subjects[subject].chapters.append(ch)
            chapters[ch_key].topics.append(CatalogTopic(
                id=tid, chapter_id=cid, name=topic, question_count=count,
            ))

        # Stable ordering: subject name → chapter name → topic name.
        ordered_subjects = sorted(subjects.values(), key=lambda s: s.name.lower())
        for s in ordered_subjects:
            s.chapters.sort(key=lambda c: c.name.lower())
            for c in s.chapters:
                c.topics.sort(key=lambda t: t.name.lower())
        return CatalogResponse(subjects=ordered_subjects)

    # ------------------------------------------------------------------
    # Browse (practice catalog)
    # ------------------------------------------------------------------

    async def browse_questions(
        self,
        user_id: ObjectId,
        *,
        subject: Optional[str] = None,
        chapter: Optional[str] = None,
        topic: Optional[str] = None,
        difficulty: Optional[str] = None,
        question_type: Optional[str] = None,
        attempted: Optional[bool] = None,
        marked: Optional[bool] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> BrowseListResponse:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))

        filt: dict[str, Any] = {}
        if subject:
            filt["subject"] = subject
        if chapter:
            filt["chapter"] = chapter
        if topic:
            filt["topic"] = topic
        if difficulty:
            filt["difficulty"] = difficulty
        if question_type:
            filt["questionType"] = question_type
        if search and search.strip():
            filt["questionText"] = {"$regex": re.escape(search.strip()), "$options": "i"}

        # `marked` is a notebook flag stored at the parent obj_id level, so it
        # constrains the pre-expansion `_id`. `attempted` is sub-precise (a
        # passage's other unattempted subs shouldn't be hidden because one sub
        # was attempted), so it's a post-expansion filter on `_composite_key`.
        if marked is not None:
            ids = await self.repo.marked_obj_ids(user_id)
            filt["_id"] = (
                {"$in": [ObjectId(x) for x in ids]}
                if marked else {"$nin": [ObjectId(x) for x in ids]}
            )

        post_filter: Optional[dict[str, Any]] = None
        if attempted is not None:
            ck = await self.repo.attempted_composite_keys(user_id)
            post_filter = {"_composite_key": (
                {"$in": list(ck)} if attempted else {"$nin": list(ck)}
            )}

        total = await self.repo.count_browse(filt, post_filter=post_filter)
        rows = await self.repo.find_browse(
            filt, skip=(page - 1) * page_size, limit=page_size,
            post_filter=post_filter,
        )

        # Collect the (obj_id, sub_index) pairs we need to look up to build
        # per-row attempt + marked status.
        pairs: list[tuple[str, Optional[int]]] = [
            (str(r["_id"]), r.get("_sub_index")) for r in rows
        ]
        obj_id_set = list({p[0] for p in pairs})
        qid_entries = await self.repo.qid_entries_for_obj_ids(obj_id_set)
        pair_to_int_id: dict[tuple[str, Optional[int]], int] = {}
        for obj_id, entries in qid_entries.items():
            for e in entries:
                si = e.get("sub_index")
                pair_to_int_id[(obj_id, None if si is None else int(si))] = int(e["_id"])
        int_ids = [pair_to_int_id[p] for p in pairs if p in pair_to_int_id]
        attempts = await self.repo.attempts_for_int_ids(user_id, int_ids)
        viewed = await self.repo.viewed_obj_ids(user_id, obj_id_set)
        marked_ids = await self.repo.marked_obj_ids(user_id, obj_id_set)

        items: list[BrowseItem] = []
        for r in rows:
            obj_id = str(r["_id"])
            sub_index = r.get("_sub_index")
            is_passage_sub = sub_index is not None
            si = int(sub_index) if is_passage_sub else None
            int_id = pair_to_int_id.get((obj_id, si))
            att = attempts.get(int_id) if int_id is not None else None
            # Surface the sub-question's own text on passage rows so the
            # list preview shows what each sub asks (not the passage stem).
            if is_passage_sub:
                subs = (r.get("passageData") or {}).get("subQuestions") or []
                q_text = subs[si].get("questionText", "") if si is not None and si < len(subs) else ""
                q_type = "single_correct"
            else:
                q_text = r.get("questionText") or ""
                q_type = (r.get("questionType") or "single_correct")
            items.append(BrowseItem(
                question_id=_make_composite(obj_id, si),
                obj_id=obj_id,
                sub_index=si,
                is_passage_sub=is_passage_sub,
                subject=(r.get("subject") or "").strip(),
                chapter=(r.get("chapter") or "").strip(),
                topic=(r.get("topic") or "").strip(),
                difficulty=(r.get("difficulty") or "medium"),
                question_type=q_type,
                question_text=q_text,
                attempted=att is not None,
                viewed=obj_id in viewed,
                marked=obj_id in marked_ids,
                performance=_perf_from_attempt(att) if att is not None else None,
            ))

        return BrowseListResponse(
            items=items, total=total, page=page, page_size=page_size,
        )

    async def _resolve_browse_target(
        self, composite_id: str,
    ) -> tuple[dict, str, Optional[int], bool]:
        """Look up the underlying question doc and confirm composite-id shape.

        Returns (doc, obj_id, sub_index, is_passage_sub). Raises on mismatch
        between composite id and the doc's question type."""
        obj_id, sub_index = _parse_composite_qid(composite_id)
        try:
            doc = await self.repo.get_question_by_obj_id(obj_id)
        except Exception:
            doc = None
        if doc is None:
            raise AppException(
                "Question not found.", status_code=status.HTTP_404_NOT_FOUND,
            )
        qtype = (doc.get("questionType") or "single_correct").lower()
        is_passage = (qtype == "passage")
        if is_passage and sub_index is None:
            raise AppException(
                "Passage requires a sub-question index.",
                status.HTTP_400_BAD_REQUEST,
            )
        if not is_passage and sub_index is not None:
            raise AppException(
                "This question is not a passage.",
                status.HTTP_400_BAD_REQUEST,
            )
        if is_passage:
            subs = (doc.get("passageData") or {}).get("subQuestions") or []
            if sub_index is None or sub_index < 0 or sub_index >= len(subs):
                raise AppException(
                    "Sub-question not found.",
                    status.HTTP_404_NOT_FOUND,
                )
        return doc, obj_id, sub_index, is_passage

    async def _attempt_feeds_recommender(
        self,
        *,
        user_id: ObjectId,
        obj_id: str,
        int_id: Optional[int],
        now: datetime,
    ) -> bool:
        """True when a fresh attempt at this question should feed the
        recommender. Returns False if any recorded event (attempt or
        solution view) on this specific (obj_id, sub_index) — or a
        solution view on the parent obj_id — falls inside the cooldown
        window. Mechanics are internal; never surfaced to the client."""
        cutoff = now - timedelta(hours=RECOMMENDER_COOLDOWN_HOURS)
        last_events: list[datetime] = []
        if int_id is not None:
            att = await self.repo.attempts.find_one(
                {"user_id": user_id, "question_id": int(int_id)},
                {"last_event_at": 1, "attempted_at": 1},
            )
            if att:
                last = att.get("last_event_at") or att.get("attempted_at")
                if isinstance(last, datetime):
                    last_events.append(last)
        view = await self.repo.practice_views.find_one(
            {"user_id": user_id, "obj_id": obj_id},
            {"viewed_at": 1},
        )
        if view and isinstance(view.get("viewed_at"), datetime):
            last_events.append(view["viewed_at"])
        if not last_events:
            return True
        return max(last_events) <= cutoff

    async def get_browse_detail(
        self, user_id: ObjectId, composite_id: str,
    ) -> BrowseQuestionDetail:
        doc, obj_id, sub_index, is_passage_sub = await self._resolve_browse_target(composite_id)
        qtype = (doc.get("questionType") or "single_correct").lower()

        int_id = await self.repo.find_question_int_id(obj_id, sub_index)
        attempt = None
        if int_id is not None:
            attempts = await self.repo.attempts_for_int_ids(user_id, [int_id])
            attempt = attempts.get(int_id)
        marked = await self.repo.is_in_notebook(user_id, obj_id)

        detail = BrowseQuestionDetail(
            question_id=composite_id,
            obj_id=obj_id,
            sub_index=sub_index,
            is_passage_sub=is_passage_sub,
            subject=(doc.get("subject") or "").strip(),
            chapter=(doc.get("chapter") or "").strip(),
            topic=(doc.get("topic") or "").strip(),
            difficulty=(doc.get("difficulty") or "medium"),
            question_type=("single_correct" if is_passage_sub else qtype),
            marked=marked,
            attempted=attempt is not None,
            performance=_perf_from_attempt(attempt) if attempt else None,
        )

        if is_passage_sub:
            subs = (doc.get("passageData") or {}).get("subQuestions") or []
            sub = subs[sub_index]
            detail.passage_text = (doc.get("passageData") or {}).get("passageText") or ""
            detail.question_text = sub.get("questionText") or ""
            detail.options = _options_from_doc(sub)
        else:
            detail.question_text = doc.get("questionText") or ""
            if qtype in ("single_correct", "multi_correct"):
                detail.options = _options_from_doc(doc)
            elif qtype == "matching":
                detail.left_column, detail.right_column = _matching_cols(doc)
        return detail

    async def record_practice_attempt(
        self, user_id: ObjectId, composite_id: str, req: BrowseAttemptRequest,
    ) -> BrowseAttemptResponse:
        doc, obj_id, sub_index, is_passage_sub = await self._resolve_browse_target(composite_id)
        qtype = (doc.get("questionType") or "single_correct").lower()
        difficulty = str(doc.get("difficulty") or "medium")
        now = datetime.now(timezone.utc)

        _sid, _cid, topic_id = await self.repo.get_or_create_topic_id(
            (doc.get("subject") or "").strip(),
            (doc.get("chapter") or "").strip(),
            (doc.get("topic") or "").strip(),
        )

        # Grade the single (sub-)question.
        sub_doc: Optional[dict] = None
        if is_passage_sub:
            subs = (doc.get("passageData") or {}).get("subQuestions") or []
            sub_doc = subs[sub_index]
            graded = grade_passage_sub(req.selected_option, sub_doc)
        elif qtype == "single_correct":
            graded = grade_single_correct(req.selected_option, doc)
        elif qtype == "multi_correct":
            graded = grade_multi_correct(req.selected_options, doc)
        elif qtype == "integer":
            graded = grade_integer(req.integer_answer, doc)
        elif qtype == "matching":
            graded = grade_matching(req.matching, doc)
        else:
            graded = grade_single_correct(req.selected_option, doc)

        # Cooldown check decides whether this attempt feeds the recommender.
        int_id = await self.repo.get_or_create_question_int_id(obj_id, sub_index)
        feeds = await self._attempt_feeds_recommender(
            user_id=user_id, obj_id=obj_id, int_id=int_id, now=now,
        )

        if feeds:
            await self.repo.bulk_upsert_attempts([new_attempt_doc(
                user_id=user_id, question_id=int_id, topic_id=topic_id,
                is_correct=graded.is_correct, correctness=graded.correctness,
                difficulty=difficulty, score_contribution=0,
                attempted_at=now, session_id=PRACTICE_SESSION_ID,
            )])
        else:
            await self.repo.mark_attempt_non_feeding(
                user_id=user_id, question_id=int_id, topic_id=topic_id,
                is_correct=graded.is_correct, correctness=graded.correctness,
                difficulty=difficulty, attempted_at=now,
                session_id=PRACTICE_SESSION_ID,
            )

        response = BrowseAttemptResponse(
            performance=_perf_from_graded(graded),
            correct_answer=None,
            solution=None,
        )

        # Reveal the answer + worked solution only when the attempt is
        # correct. A wrong attempt sends the user back to the same prompt
        # so they can try again (still wrong → still no reveal). Viewing
        # the solution explicitly via the view-solution endpoint is the
        # only other way to surface either.
        if graded.is_correct:
            await self.repo.record_view(user_id, obj_id)
            if is_passage_sub:
                response.correct_answer = sub_doc.get("correctOption") if sub_doc else None
                response.solution = (
                    (sub_doc.get("solution") if sub_doc else None)
                    or (sub_doc.get("explanation") if sub_doc else None)
                    or doc.get("solution")
                    or ""
                )
            else:
                response.correct_answer = _correct_answer_for(doc, qtype)
                response.solution = doc.get("solution") or doc.get("explanation") or ""
        return response

    async def pick_potd_candidate(
        self, user_oid: ObjectId, topic_id: int,
    ) -> Optional[dict]:
        """Pick a single question for POTD using the recommender engine
        WITHOUT creating a mock-test session.

        The engine is the right picker for "what should this user see next"
        — it factors in cooldown / recency / difficulty mix. We feed it
        exactly the same inputs `create_test` does, then take its first
        pick and skip the persistence machinery.

        Passages are excluded — POTD's one-question framing doesn't fit a
        multi-part question. Returns the raw question doc + topic_id, or
        None if the engine couldn't assemble a pick from the topic.
        """
        trip = await self.repo.lookup_topic_triple(topic_id)
        if trip is None:
            return None
        raw_docs = await self.repo.fetch_questions_for_triples([trip])
        if not raw_docs:
            return None

        # Build engine_questions, excluding passage-type docs entirely.
        engine_questions: list[tuple[EngineQuestion, int]] = []
        int_to_obj: dict[int, str] = {}
        for doc in raw_docs:
            qtype = (doc.get("questionType") or "single_correct").lower()
            if qtype == "passage":
                continue
            obj_id = str(doc["_id"])
            difficulty = (doc.get("difficulty") or "medium").lower()
            int_id = await self.repo.get_or_create_question_int_id(obj_id)
            int_to_obj[int_id] = obj_id
            engine_questions.append((EngineQuestion(
                id=int_id,
                topic_ids=(topic_id,),
                difficulty=difficulty,
                question_type=qtype,
            ), topic_id))

        if not engine_questions:
            return None
        engine_questions.sort(key=lambda pair: (pair[1], pair[0].id))

        # Same feeding-only attempt filter as `create_test` (engine-mirror
        # fields when present; legacy rows fall back to user-visible).
        attempt_docs = await self.db["user_topic_attempts"].find(
            {"user_id": user_oid, "topic_id": topic_id},
        ).to_list(length=None)
        engine_attempts: list[EngineAttempt] = []
        for ad in attempt_docs:
            has_engine_fields = "e_attempted_at" in ad
            if has_engine_fields:
                if ad.get("e_attempted_at") is None:
                    continue
                e_is_correct = ad.get("e_is_correct")
                if e_is_correct is None:
                    continue
                engine_attempts.append(EngineAttempt(
                    user_id=user_oid,
                    topic_id=int(ad["topic_id"]),
                    question_id=int(ad["question_id"]),
                    is_correct=bool(e_is_correct),
                    difficulty=str(ad.get("e_difficulty") or "medium"),
                    score_contribution=int(ad.get("e_score_contribution") or 0),
                    attempted_at=ad["e_attempted_at"],
                    correctness=ad.get("e_correctness"),
                ))
            else:
                if ad.get("is_correct") is None:
                    continue
                engine_attempts.append(EngineAttempt(
                    user_id=user_oid,
                    topic_id=int(ad["topic_id"]),
                    question_id=int(ad["question_id"]),
                    is_correct=bool(ad.get("is_correct", False)),
                    difficulty=str(ad.get("difficulty", "medium")),
                    score_contribution=int(ad.get("score_contribution", 0)),
                    attempted_at=ad.get("attempted_at") or datetime.now(timezone.utc),
                    correctness=ad.get("correctness"),
                ))

        topic_chapter_map = await self.repo.topic_chapter_map([topic_id])
        # PRACTICE_SESSION_ID is the sentinel for "no real session" — we
        # don't drain the buffered repo so this id never gets persisted.
        buffered = BufferedRepository(
            user_id=user_oid,
            preallocated_session_id=PRACTICE_SESSION_ID,
            attempts_for_topics=engine_attempts,
            attempts_for_user=[],
            available_questions=engine_questions,
            topic_chapters=topic_chapter_map,
        )
        try:
            mock_test = engine_create_mock_test(
                buffered,
                user_id=user_oid,
                topic_ids=[topic_id],
                total_questions=1,
                include_extra=False,
                extra_count=0,
                shuffle_seed=int(time.time()),
            )
        except Exception:
            logger.exception("POTD engine pick failed for topic %s", topic_id)
            return None
        if not mock_test.questions:
            return None
        picked, _tid = mock_test.questions[0]
        obj_id_str = int_to_obj.get(picked.id)
        if obj_id_str is None:
            return None
        chosen_doc = next((d for d in raw_docs if str(d["_id"]) == obj_id_str), None)
        if chosen_doc is None:
            return None
        return chosen_doc

    async def get_catalog_raw(self) -> list[dict]:
        """Flat list of (subject, chapter, topic, topic_id, question_count)
        rows — used by POTD's random-fallback picker for users with no
        attempts yet. Materialises topic ids on the way out so the caller
        doesn't have to do another round-trip per topic."""
        rows = await self.repo.list_all_catalog_topics()
        out: list[dict] = []
        for row in rows:
            _sid, _cid, tid = await self.repo.get_or_create_topic_id(
                row["subject"], row["chapter"], row["topic"],
            )
            out.append({
                "topic_id": int(tid),
                "subject": row["subject"],
                "chapter": row["chapter"],
                "topic": row["topic"],
                "question_count": int(row["question_count"]),
            })
        return out

    async def view_solution(
        self, user_id: ObjectId, composite_id: str,
    ) -> BrowseSolutionResponse:
        doc, obj_id, sub_index, is_passage_sub = await self._resolve_browse_target(composite_id)
        await self.repo.record_view(user_id, obj_id)

        if is_passage_sub:
            subs = (doc.get("passageData") or {}).get("subQuestions") or []
            sub_doc = subs[sub_index]
            solution_text = (
                sub_doc.get("solution")
                or sub_doc.get("explanation")
                or doc.get("solution")
                or ""
            )
            return BrowseSolutionResponse(
                solution=solution_text,
                correct_answer=sub_doc.get("correctOption"),
            )
        qtype = (doc.get("questionType") or "single_correct").lower()
        return BrowseSolutionResponse(
            solution=doc.get("solution") or "",
            correct_answer=_correct_answer_for(doc, qtype),
        )

    # ------------------------------------------------------------------
    # Notebook (revise-later)
    # ------------------------------------------------------------------

    async def _assert_question_exists(self, obj_id: str) -> None:
        try:
            doc = await self.repo.get_question_by_obj_id(obj_id)
        except Exception:
            doc = None
        if doc is None:
            raise AppException(
                "Question not found.", status_code=status.HTTP_404_NOT_FOUND,
            )

    async def add_to_notebook(
        self, user_id: ObjectId, composite_id: str,
    ) -> NotebookToggleResponse:
        # Notebook is stored at the parent obj_id level — marking any sub
        # of a passage tags the whole passage so the notebook view shows
        # all its subs together.
        obj_id, _sub = _parse_composite_qid(composite_id)
        await self._assert_question_exists(obj_id)
        await self.repo.add_to_notebook(user_id, obj_id)
        return NotebookToggleResponse(marked=True)

    async def remove_from_notebook(
        self, user_id: ObjectId, composite_id: str,
    ) -> NotebookToggleResponse:
        obj_id, _sub = _parse_composite_qid(composite_id)
        await self.repo.remove_from_notebook(user_id, obj_id)
        return NotebookToggleResponse(marked=False)

    async def get_notebook_count(self, user_id: ObjectId) -> NotebookCountResponse:
        return NotebookCountResponse(count=await self.repo.notebook_count(user_id))

    # ------------------------------------------------------------------
    # Create mock test
    # ------------------------------------------------------------------

    async def create_test(
        self,
        user_oid: ObjectId,
        payload: CreateMockTestRequest,
    ) -> CreateMockTestResponse:
        topic_ids = sorted(set(int(t) for t in payload.topic_ids))
        if not topic_ids:
            raise AppException("Select at least one topic.", status.HTTP_400_BAD_REQUEST)

        # Resolve (subject, chapter, topic) for every selected topic so we
        # know what triples to query the catalog for.
        triples: list[tuple[str, str, str]] = []
        topic_to_triple: dict[int, tuple[str, str, str]] = {}
        topic_chapter_map = await self.repo.topic_chapter_map(topic_ids)
        for tid in topic_ids:
            trip = await self.repo.lookup_topic_triple(tid)
            if trip is None:
                raise AppException(
                    f"Unknown topic id {tid}", status.HTTP_400_BAD_REQUEST,
                )
            triples.append(trip)
            topic_to_triple[tid] = trip

        # Fetch raw question docs for those triples.
        raw_docs = await self.repo.fetch_questions_for_triples(triples)
        if not raw_docs:
            raise AppException(
                "No questions are available for the selected topics yet.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Build engine Question objects + remember which Mongo doc each came from.
        engine_questions: list[tuple[EngineQuestion, int]] = []
        # int_id → (obj_id, sub_index_or_None, parent_int_id_or_None)
        qid_origin: dict[int, tuple[str, Optional[int], Optional[int]]] = {}
        # int_id → cached raw doc (parent doc for sub-questions)
        qid_doc: dict[int, dict] = {}

        triple_to_topic = {v: k for k, v in topic_to_triple.items()}

        for doc in raw_docs:
            obj_id = str(doc["_id"])
            subject = (doc.get("subject") or "").strip()
            chapter = (doc.get("chapter") or "").strip()
            topic = (doc.get("topic") or "").strip()
            triple = (subject, chapter, topic)
            tid = triple_to_topic.get(triple)
            if tid is None:
                continue  # not in user's selection
            difficulty = (doc.get("difficulty") or "medium").lower()
            qtype = (doc.get("questionType") or "single_correct").lower()

            if qtype == "passage":
                sub_qs = (doc.get("passageData") or {}).get("subQuestions") or []
                parent_int_id = await self.repo.get_or_create_question_int_id(obj_id)
                qid_origin[parent_int_id] = (obj_id, None, None)
                qid_doc[parent_int_id] = doc
                for i, _sub in enumerate(sub_qs):
                    sub_int_id = await self.repo.get_or_create_question_int_id(
                        obj_id, sub_index=i,
                    )
                    qid_origin[sub_int_id] = (obj_id, i, parent_int_id)
                    qid_doc[sub_int_id] = doc
                    engine_questions.append((EngineQuestion(
                        id=sub_int_id,
                        topic_ids=(tid,),
                        difficulty=difficulty,
                        question_type="single_correct",
                        passage_id=parent_int_id,
                    ), tid))
            else:
                int_id = await self.repo.get_or_create_question_int_id(obj_id)
                qid_origin[int_id] = (obj_id, None, None)
                qid_doc[int_id] = doc
                engine_questions.append((EngineQuestion(
                    id=int_id,
                    topic_ids=(tid,),
                    difficulty=difficulty,
                    question_type=qtype,
                ), tid))

        # Stable order — by topic_id then int id.
        engine_questions.sort(key=lambda pair: (pair[1], pair[0].id))

        # Fetch user's prior attempts on these topics. Non-feeding cooldown
        # rows (`e_attempted_at` exists but is None) are skipped so the
        # recommender stays on honest signal; legacy pre-cooldown rows
        # (no `e_*` fields at all) fall back to the user-visible fields.
        attempt_docs = await self.db["user_topic_attempts"].find(
            {"user_id": user_oid, "topic_id": {"$in": topic_ids}},
        ).to_list(length=None)
        engine_attempts: list[EngineAttempt] = []
        for ad in attempt_docs:
            has_engine_fields = "e_attempted_at" in ad
            if has_engine_fields:
                if ad.get("e_attempted_at") is None:
                    continue  # cooldown-only row — engine ignores it
                e_is_correct = ad.get("e_is_correct")
                if e_is_correct is None:
                    continue
                engine_attempts.append(EngineAttempt(
                    user_id=user_oid,
                    topic_id=int(ad["topic_id"]),
                    question_id=int(ad["question_id"]),
                    is_correct=bool(e_is_correct),
                    difficulty=str(ad.get("e_difficulty") or "medium"),
                    score_contribution=int(ad.get("e_score_contribution") or 0),
                    attempted_at=ad["e_attempted_at"],
                    correctness=ad.get("e_correctness"),
                ))
            else:
                # Legacy row (pre-cooldown) — treat as feeding.
                if ad.get("is_correct") is None:
                    continue
                engine_attempts.append(EngineAttempt(
                    user_id=user_oid,
                    topic_id=int(ad["topic_id"]),
                    question_id=int(ad["question_id"]),
                    is_correct=bool(ad.get("is_correct", False)),
                    difficulty=str(ad.get("difficulty", "medium")),
                    score_contribution=int(ad.get("score_contribution", 0)),
                    attempted_at=ad.get("attempted_at") or datetime.now(timezone.utc),
                    correctness=ad.get("correctness"),
                ))

        # Pre-allocate the session id (engine needs an int back from save_session).
        session_id = await self.repo.next_id(COUNTER_SESSION)

        buffered = BufferedRepository(
            user_id=user_oid,
            preallocated_session_id=session_id,
            attempts_for_topics=engine_attempts,
            attempts_for_user=[],  # extras not supported in UI yet
            available_questions=engine_questions,
            topic_chapters=topic_chapter_map,
        )

        # Run the engine (synchronous on the buffered repo).
        mock_test = engine_create_mock_test(
            buffered,
            user_id=user_oid,
            topic_ids=topic_ids,
            total_questions=payload.total_questions,
            include_extra=payload.extra_questions > 0,
            extra_count=payload.extra_questions,
            shuffle_seed=int(time.time()),
        )

        if not mock_test.questions:
            raise AppException(
                "Could not assemble a mock test from the available pool. "
                "Try fewer topics or a smaller test size.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Display order — engine result, then re-sort by type-rank per UX rule.
        # We keep engine order as the *served* order for analytics truth, but
        # display_order encodes the UX rule. Frontend re-sorts on render too.
        selected = list(mock_test.questions) + list(mock_test.extras)
        # Group passages so siblings stay together.
        passage_first_pos: dict[int, int] = {}
        for idx, (q, _tid) in enumerate(selected):
            pid = q.passage_id
            if pid is not None and pid not in passage_first_pos:
                passage_first_pos[pid] = idx
        def sort_key(item):
            (q, _t) = item
            type_rank = _TYPE_RANK.get(q.question_type, 99)
            if q.passage_id is not None:
                type_rank = _TYPE_RANK["passage"]
            group_key = q.passage_id if q.passage_id is not None else q.id
            return (type_rank, group_key, q.id)
        selected.sort(key=sort_key)

        # Persist session, topic allocations, and blank response rows.
        total_seconds = payload.total_questions * SECONDS_PER_QUESTION

        await self.repo.create_session_doc(
            session_id=session_id,
            user_id=user_oid,
            total_questions=mock_test.total_questions,
            extra_questions=mock_test.extra_questions,
            total_seconds=total_seconds,
            topic_ids=topic_ids,
        )
        topic_rows = []
        for tq in mock_test.topics:
            topic_rows.append(new_topic_allocation_doc(
                session_id=session_id,
                topic_id=tq.topic_id,
                question_count=tq.question_count,
                priority_score=float(tq.priority_score),
                decay_factor=float(tq.decay_factor),
            ))
        await self.repo.insert_topic_allocations(session_id, topic_rows)

        response_rows = []
        for display_order, (q, tid) in enumerate(selected):
            is_extra = any(q.id == ex_q.id for ex_q, _ in mock_test.extras)
            response_rows.append(new_response_doc(
                session_id=session_id,
                question_id=q.id,
                topic_id=tid,
                is_extra=is_extra,
                display_order=display_order,
            ))
        await self.repo.insert_response_rows(response_rows)

        # Build frontend-safe payloads.
        payloads = self._build_question_payloads(
            selected, qid_origin, qid_doc, response_rows,
        )

        session_doc = await self.repo.get_session(session_id, user_oid)
        return CreateMockTestResponse(
            session_id=session_id,
            total_questions=mock_test.total_questions,
            extra_questions=mock_test.extra_questions,
            total_seconds=total_seconds,
            status=session_doc["status"],
            created_at=session_doc["created_at"],
            topics=[{
                "topic_id": tq.topic_id,
                "question_count": tq.question_count,
                "priority_score": float(tq.priority_score),
                "decay_factor": float(tq.decay_factor),
            } for tq in mock_test.topics],
            questions=payloads,
        )

    def _build_question_payloads(
        self,
        selected: list[tuple[EngineQuestion, int]],
        qid_origin: dict[int, tuple[str, Optional[int], Optional[int]]],
        qid_doc: dict[int, dict],
        response_rows: list[dict],
    ) -> list[QuestionPayload]:
        # display_order → (q, tid) from response_rows (built in same order)
        order_by_id = {row["question_id"]: row["display_order"] for row in response_rows}
        is_extra_by_id = {row["question_id"]: row["is_extra"] for row in response_rows}
        out: list[QuestionPayload] = []

        for q, tid in selected:
            origin = qid_origin.get(q.id)
            if origin is None:
                continue
            obj_id, sub_index, _parent_int = origin
            doc = qid_doc.get(q.id)
            if doc is None:
                continue

            if sub_index is not None:
                sub_qs = (doc.get("passageData") or {}).get("subQuestions") or []
                if sub_index >= len(sub_qs):
                    continue
                sub = sub_qs[sub_index]
                payload = QuestionPayload(
                    question_id=q.id,
                    topic_id=tid,
                    display_order=order_by_id.get(q.id, 0),
                    question_type="single_correct",
                    difficulty=q.difficulty,
                    is_extra=bool(is_extra_by_id.get(q.id, False)),
                    passage_id=q.passage_id,
                    passage_text=(doc.get("passageData") or {}).get("passageText", ""),
                    passage_sub_index=sub_index,
                    passage_sub_total=len(sub_qs),
                    question_text=sub.get("questionText", ""),
                    options=_options_from_doc(sub),
                )
                out.append(payload)
                continue

            qtype = (doc.get("questionType") or "single_correct").lower()
            left, right = ([], [])
            if qtype == "matching":
                left, right = _matching_cols(doc)
            payload = QuestionPayload(
                question_id=q.id,
                topic_id=tid,
                display_order=order_by_id.get(q.id, 0),
                question_type=qtype,
                difficulty=q.difficulty,
                is_extra=bool(is_extra_by_id.get(q.id, False)),
                question_text=doc.get("questionText", ""),
                options=_options_from_doc(doc) if qtype in (
                    "single_correct", "multi_correct",
                ) else [],
                left_column=left,
                right_column=right,
            )
            out.append(payload)
        # Sort by display order so the client gets them ready-to-render.
        out.sort(key=lambda p: p.display_order)
        return out

    # ------------------------------------------------------------------
    # Fetch session (resume)
    # ------------------------------------------------------------------

    async def get_session_for_user(
        self, user_oid: ObjectId, session_id: int,
    ) -> SessionResponse:
        session_doc = await self.repo.get_session(session_id, user_oid)
        if session_doc is None:
            raise AppException("Session not found.", status.HTTP_404_NOT_FOUND)

        responses = await self.repo.get_responses_for_session(session_id)
        if not responses:
            raise AppException("Session has no questions.", status.HTTP_404_NOT_FOUND)

        # Hydrate the question docs.
        int_ids = [r["question_id"] for r in responses]
        map_docs = await self.repo.bulk_lookup_question_int_to_obj(int_ids)
        obj_ids = list({d["obj_id"] for d in map_docs.values() if d.get("obj_id")})
        raw_by_obj = await self.repo.fetch_question_docs_by_obj_ids(obj_ids)

        # Build (q, tid) pairs in display order.
        selected_pairs: list[tuple[EngineQuestion, int]] = []
        qid_origin: dict[int, tuple[str, Optional[int], Optional[int]]] = {}
        qid_doc: dict[int, dict] = {}
        for r in responses:
            qid = int(r["question_id"])
            tid = int(r["topic_id"])
            md = map_docs.get(qid)
            if md is None:
                continue
            obj_id = md["obj_id"]
            sub_index = md.get("sub_index")
            doc = raw_by_obj.get(obj_id)
            if doc is None:
                continue
            difficulty = (doc.get("difficulty") or "medium").lower()
            if sub_index is None:
                qtype = (doc.get("questionType") or "single_correct").lower()
                passage_id = None
            else:
                qtype = "single_correct"
                # parent_int_id by looking up the qid map.
                passage_id_doc = await self.repo.qid_map.find_one(
                    {"obj_id": obj_id, "sub_index": None},
                )
                passage_id = int(passage_id_doc["_id"]) if passage_id_doc else None
            qid_origin[qid] = (obj_id, sub_index, passage_id)
            qid_doc[qid] = doc
            selected_pairs.append((EngineQuestion(
                id=qid, topic_ids=(tid,),
                difficulty=difficulty, question_type=qtype,
                passage_id=passage_id,
            ), tid))

        payloads = self._build_question_payloads(
            selected_pairs, qid_origin, qid_doc, responses,
        )

        topic_rows = await self.repo.get_topic_allocations_for_session(session_id)

        return SessionResponse(
            session_id=session_id,
            total_questions=session_doc["total_questions"],
            extra_questions=session_doc.get("extra_questions", 0),
            total_seconds=session_doc.get(
                "total_seconds",
                session_doc["total_questions"] * SECONDS_PER_QUESTION,
            ),
            status=session_doc["status"],
            created_at=session_doc["created_at"],
            topics=[{
                "topic_id": tr["topic_id"],
                "question_count": tr["question_count"],
                "priority_score": float(tr.get("priority_score", 0.0)),
                "decay_factor": float(tr.get("decay_factor", 1.0)),
            } for tr in topic_rows],
            questions=payloads,
        )

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def submit_test(
        self,
        user_oid: ObjectId,
        session_id: int,
        payload: SubmitMockTestRequest,
    ) -> SubmitMockTestResponse:
        session_doc = await self.repo.get_session(session_id, user_oid)
        if session_doc is None:
            raise AppException("Session not found.", status.HTTP_404_NOT_FOUND)
        if session_doc.get("status") == "completed":
            raise AppException(
                "This test has already been submitted.",
                status.HTTP_409_CONFLICT,
            )

        responses = await self.repo.get_responses_for_session(session_id)
        responses_by_qid = {int(r["question_id"]): r for r in responses}

        int_ids = list(responses_by_qid.keys())
        map_docs = await self.repo.bulk_lookup_question_int_to_obj(int_ids)
        obj_ids = list({d["obj_id"] for d in map_docs.values() if d.get("obj_id")})
        raw_by_obj = await self.repo.fetch_question_docs_by_obj_ids(obj_ids)

        # Index user answers by question_id.
        user_answers: dict[int, AnswerInput] = {
            int(a.question_id): a for a in payload.answers
        }

        graded_results: list[PerQuestionResult] = []
        evaluations: list[AnswerEvaluation] = []
        difficulty_by_q: dict[int, str] = {}
        session_topic_lookup: dict[tuple[int, int], int] = {}

        for qid, response_row in responses_by_qid.items():
            md = map_docs.get(qid)
            if md is None:
                continue
            obj_id = md["obj_id"]
            sub_index = md.get("sub_index")
            raw_doc = raw_by_obj.get(obj_id)
            if raw_doc is None:
                continue
            difficulty = (raw_doc.get("difficulty") or "medium").lower()
            difficulty_by_q[qid] = difficulty
            session_topic_lookup[(session_id, qid)] = int(response_row["topic_id"])

            answer = user_answers.get(qid)

            if sub_index is not None:
                sub_qs = (raw_doc.get("passageData") or {}).get("subQuestions") or []
                sub_doc = sub_qs[sub_index] if sub_index < len(sub_qs) else {}
                graded = grade_passage_sub(
                    answer.selected_option if answer else None,
                    sub_doc,
                )
                qtype_used = "passage"
            else:
                qtype = (raw_doc.get("questionType") or "single_correct").lower()
                qtype_used = qtype
                if qtype == "single_correct":
                    graded = grade_single_correct(
                        answer.selected_option if answer else None,
                        raw_doc,
                    )
                elif qtype == "multi_correct":
                    graded = grade_multi_correct(
                        (answer.selected_options if answer else None) or [],
                        raw_doc,
                    )
                elif qtype == "integer":
                    graded = grade_integer(
                        answer.integer_answer if answer else None,
                        raw_doc,
                    )
                elif qtype == "matching":
                    graded = grade_matching(
                        (answer.matching if answer else None) or {},
                        raw_doc,
                    )
                else:
                    # Unknown type — record as wrong rather than guessing.
                    graded = GradedAnswer(
                        is_correct=False, correctness=None,
                        user_answer=None, correct_answer=None,
                    )

            evaluations.append(AnswerEvaluation(
                question_id=qid,
                is_correct=graded.is_correct,
                correctness=graded.correctness,
            ))
            # Per-Q result for the response (filled in with score_contribution
            # later once engine_submit_test returns the new_attempts).
            graded_results.append(PerQuestionResult(
                question_id=qid,
                topic_id=int(response_row["topic_id"]),
                display_order=int(response_row["display_order"]),
                is_correct=graded.is_correct,
                correctness=(
                    graded.correctness if graded.correctness is not None
                    else (1.0 if graded.is_correct else 0.0)
                ),
                user_answer=graded.user_answer,
                correct_answer=graded.correct_answer,
                difficulty=difficulty,
                question_type=qtype_used,
                score_contribution=0,
            ))

            # Persist per-response grading.
            await self.repo.update_response_grading(
                session_id, qid,
                user_answer=graded.user_answer,
                is_correct=graded.is_correct,
                correctness=graded.correctness,
            )

        # Cooldown gate — split the evaluations into feeding / non-feeding.
        # Each question that the user has recently touched (attempt or
        # solution view within RECOMMENDER_COOLDOWN_HOURS) is silently
        # excluded from the engine so its prior signal stays authoritative.
        now = datetime.now(timezone.utc)
        feeds_map: dict[int, bool] = {}
        for qid in responses_by_qid.keys():
            md = map_docs.get(qid)
            if md is None:
                continue
            feeds_map[qid] = await self._attempt_feeds_recommender(
                user_id=user_oid,
                obj_id=str(md["obj_id"]),
                int_id=int(qid),
                now=now,
            )

        feeding_evaluations = [e for e in evaluations if feeds_map.get(int(e.question_id), True)]
        non_feeding_qids = [
            int(e.question_id) for e in evaluations
            if not feeds_map.get(int(e.question_id), True)
        ]

        # Run engine submit on a fresh buffered repo (writes only). The
        # engine only sees the feeding subset, so its score totals reflect
        # those alone — we recompute the user-facing test totals from
        # `graded_results` below.
        buffered = BufferedRepository(
            user_id=user_oid,
            preallocated_session_id=session_id,
            session_topic_lookup=session_topic_lookup,
        )
        result = engine_submit_test(
            buffered,
            session_id=session_id,
            user_id=user_oid,
            evaluations=feeding_evaluations,
            difficulty_by_question=difficulty_by_q,
        )

        # Persist feeding attempt rows (full overwrite — engine signal).
        attempt_docs = []
        attempt_sc_by_qid: dict[int, int] = {}
        for ea in result.new_attempts:
            attempt_sc_by_qid[int(ea.question_id)] = int(ea.score_contribution)
            attempt_docs.append(new_attempt_doc(
                user_id=user_oid,
                question_id=int(ea.question_id),
                topic_id=int(ea.topic_id),
                is_correct=bool(ea.is_correct),
                correctness=ea.correctness,
                difficulty=str(ea.difficulty),
                score_contribution=int(ea.score_contribution),
                attempted_at=ea.attempted_at,
                session_id=session_id,
            ))
        await self.repo.bulk_upsert_attempts(attempt_docs)

        # Cooldown attempts: update the user-visible "latest attempt"
        # fields but leave the engine-mirror fields untouched.
        eval_by_qid = {int(e.question_id): e for e in evaluations}
        for qid in non_feeding_qids:
            ev = eval_by_qid.get(qid)
            if ev is None:
                continue
            md = map_docs.get(qid)
            if md is None:
                continue
            await self.repo.mark_attempt_non_feeding(
                user_id=user_oid,
                question_id=qid,
                topic_id=int(responses_by_qid[qid]["topic_id"]),
                is_correct=ev.is_correct,
                correctness=ev.correctness,
                difficulty=difficulty_by_q.get(qid, "medium"),
                attempted_at=now,
                session_id=session_id,
            )

        # Backfill score_contribution into per-question results. Cooldown
        # questions contributed 0 to the recommender; their grade is still
        # reflected in the user's test score below.
        for r in graded_results:
            r.score_contribution = attempt_sc_by_qid.get(r.question_id, 0)

        # Compute the user-facing test totals from ALL graded results so
        # the score the student sees reflects what they actually answered,
        # not just the engine-fed subset.
        total = len(graded_results)
        correct_count = sum(1 for r in graded_results if r.is_correct)
        partial_count = sum(
            1 for r in graded_results
            if not r.is_correct and (r.correctness or 0) > 0
        )
        incorrect_count = total - correct_count - partial_count
        total_score = sum(float(r.correctness) for r in graded_results)

        await self.repo.update_session_status(
            session_id,
            status="completed",
            score=total_score,
            correct=correct_count,
            incorrect=incorrect_count,
            partial=partial_count,
        )

        max_score = float(total) if total else 1.0
        accuracy_pct = (total_score / max_score) * 100 if max_score else 0.0

        # Sort results by display order so the client maps cleanly.
        graded_results.sort(key=lambda r: r.display_order)

        return SubmitMockTestResponse(
            session_id=session_id,
            total=total,
            correct=correct_count,
            incorrect=incorrect_count,
            partial=partial_count,
            total_score=total_score,
            max_score=max_score,
            accuracy_pct=accuracy_pct,
            results=graded_results,
        )

    # ------------------------------------------------------------------
    # Results (after submit)
    # ------------------------------------------------------------------

    async def get_results(
        self, user_oid: ObjectId, session_id: int,
    ) -> SubmitMockTestResponse:
        session_doc = await self.repo.get_session(session_id, user_oid)
        if session_doc is None:
            raise AppException("Session not found.", status.HTTP_404_NOT_FOUND)
        if session_doc.get("status") != "completed":
            raise AppException(
                "Test has not been submitted yet.",
                status.HTTP_409_CONFLICT,
            )

        responses = await self.repo.get_responses_for_session(session_id)
        int_ids = [r["question_id"] for r in responses]
        map_docs = await self.repo.bulk_lookup_question_int_to_obj(int_ids)
        obj_ids = list({d["obj_id"] for d in map_docs.values() if d.get("obj_id")})
        raw_by_obj = await self.repo.fetch_question_docs_by_obj_ids(obj_ids)

        attempts = await self.db["user_topic_attempts"].find(
            {"user_id": user_oid, "session_id": session_id},
        ).to_list(length=None)
        sc_by_q = {int(a["question_id"]): int(a.get("score_contribution", 0))
                   for a in attempts}

        # Which of these questions the user has marked into their notebook
        # (one lookup; passage sub-Qs share the parent obj_id).
        marked_set = await self.repo.marked_obj_ids(user_oid, obj_ids)

        results: list[PerQuestionResult] = []
        for r in responses:
            qid = int(r["question_id"])
            md = map_docs.get(qid)
            if md is None:
                continue
            doc = raw_by_obj.get(md["obj_id"])
            if doc is None:
                continue
            sub_index = md.get("sub_index")

            # ---- prompt content + solution per (sub-)question ----
            q_text = ""
            options: list = []
            left_col: list = []
            right_col: list = []
            passage_text = None
            passage_sub_index = None
            passage_sub_total = None
            passage_id = None
            solution_text = None

            if sub_index is not None:
                sub_qs = (doc.get("passageData") or {}).get("subQuestions") or []
                sub_doc = sub_qs[sub_index] if sub_index < len(sub_qs) else {}
                # bbd_db schema: passage sub-Qs use `correctOption` (singular).
                correct_answer = sub_doc.get("correctOption")
                qtype = "passage"
                q_text = sub_doc.get("questionText", "")
                options = _options_from_doc(sub_doc)
                passage_text = (doc.get("passageData") or {}).get("passageText", "")
                passage_sub_index = sub_index
                passage_sub_total = len(sub_qs)
                # Parent doc int-id — sub-question rows carry the sub's
                # int-id, so we look up the parent's separately.
                parent_map = await self.repo.qid_map.find_one(
                    {"obj_id": md["obj_id"], "sub_index": None},
                )
                if parent_map is not None:
                    passage_id = int(parent_map["_id"])
                # Solution: prefer per-sub if present, else fall back to
                # the parent passage's shared solution.
                solution_text = (
                    sub_doc.get("solution")
                    or sub_doc.get("explanation")
                    or doc.get("solution")
                    or None
                )
            else:
                qtype = (doc.get("questionType") or "single_correct").lower()
                if qtype == "matching":
                    # Normalize int values -> sorted string lists so the
                    # wire shape matches what `grade_matching` records for
                    # `user_answer`, and what the client matrix-grid expects.
                    raw_cm = (doc.get("matchingData") or {}).get("correctMapping") or {}
                    correct_answer = {
                        str(k): sorted(
                            str(x) for x in (vs if isinstance(vs, (list, tuple, set)) else [vs])
                            if x is not None and str(x).strip() != ""
                        )
                        for k, vs in raw_cm.items()
                    }
                elif qtype == "integer":
                    correct_answer = doc.get("integerAnswer")
                else:
                    # bbd_db schema: standalones use `correctOptions` (array).
                    correct_answer = doc.get("correctOptions")
                q_text = doc.get("questionText", "")
                if qtype in ("single_correct", "multi_correct"):
                    options = _options_from_doc(doc)
                elif qtype == "matching":
                    left_col, right_col = _matching_cols(doc)
                solution_text = doc.get("solution") or doc.get("explanation") or None

            difficulty = (doc.get("difficulty") or "medium").lower()
            is_correct = bool(r.get("is_correct"))
            correctness = r.get("correctness")
            if correctness is None:
                correctness = 1.0 if is_correct else 0.0
            results.append(PerQuestionResult(
                question_id=qid,
                obj_id=str(md["obj_id"]),
                marked=str(md["obj_id"]) in marked_set,
                topic_id=int(r["topic_id"]),
                display_order=int(r["display_order"]),
                is_correct=is_correct,
                correctness=float(correctness),
                user_answer=r.get("user_answer"),
                correct_answer=correct_answer,
                difficulty=difficulty,
                question_type=qtype,
                score_contribution=sc_by_q.get(qid, 0),
                question_text=q_text,
                options=options,
                left_column=left_col,
                right_column=right_col,
                passage_text=passage_text,
                passage_sub_index=passage_sub_index,
                passage_sub_total=passage_sub_total,
                passage_id=passage_id,
                solution_text=solution_text,
            ))

        results.sort(key=lambda r: r.display_order)
        total = len(results)
        correct = int(session_doc.get("correct") or 0)
        incorrect = int(session_doc.get("incorrect") or 0)
        partial = int(session_doc.get("partial") or 0)
        total_score = float(session_doc.get("score") or 0.0)
        max_score = float(total) if total else 1.0
        accuracy_pct = (total_score / max_score) * 100 if max_score else 0.0

        return SubmitMockTestResponse(
            session_id=session_id,
            total=total,
            correct=correct,
            incorrect=incorrect,
            partial=partial,
            total_score=total_score,
            max_score=max_score,
            accuracy_pct=accuracy_pct,
            results=results,
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def get_history(
        self, user_oid: ObjectId, limit: int = 50,
    ) -> HistoryResponse:
        rows = await self.repo.list_user_sessions(user_oid, limit=limit)
        items: list[HistoryItem] = []
        for r in rows:
            total = int(r.get("total_questions") or 0)
            score = r.get("score")
            acc = None
            if score is not None and total:
                acc = (float(score) / total) * 100
            items.append(HistoryItem(
                session_id=int(r["_id"]),
                created_at=r["created_at"],
                completed_at=r.get("completed_at"),
                status=r["status"],
                total_questions=total,
                correct=r.get("correct"),
                incorrect=r.get("incorrect"),
                partial=r.get("partial"),
                score=(float(score) if score is not None else None),
                accuracy_pct=acc,
            ))
        return HistoryResponse(items=items)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    async def get_overview(
        self, user_oid: ObjectId,
    ) -> AnalyticsOverviewResponse:
        attempts = await self.repo.list_user_attempts(user_oid)
        sessions = await self.repo.list_user_sessions(user_oid, limit=200)
        completed = [s for s in sessions if s.get("status") == "completed"]

        total_tests = len(completed)
        total_questions = sum(int(s.get("total_questions") or 0) for s in completed)
        total_score = sum(float(s.get("score") or 0.0) for s in completed)
        overall_acc = (total_score / total_questions * 100) if total_questions else 0.0

        # By difficulty
        by_diff_counts: dict[str, tuple[int, float]] = {}
        for a in attempts:
            d = str(a.get("difficulty", "medium")).lower()
            cur = by_diff_counts.get(d, (0, 0.0))
            corr = a.get("correctness")
            if corr is None:
                corr = 1.0 if a.get("is_correct") else 0.0
            by_diff_counts[d] = (cur[0] + 1, cur[1] + float(corr))
        by_difficulty = [
            DifficultyBreakdown(
                difficulty=d,
                attempts=cnt,
                correct=int(round(score)),
                accuracy_pct=(score / cnt * 100) if cnt else 0.0,
            )
            for d, (cnt, score) in sorted(by_diff_counts.items())
        ]

        # By type (look up via qid map to get the type)
        qids = list({int(a["question_id"]) for a in attempts})
        map_docs = await self.repo.bulk_lookup_question_int_to_obj(qids)
        obj_ids = list({d["obj_id"] for d in map_docs.values() if d.get("obj_id")})
        raw_by_obj = await self.repo.fetch_question_docs_by_obj_ids(obj_ids)
        by_type_counts: dict[str, tuple[int, float]] = {}
        for a in attempts:
            qid = int(a["question_id"])
            md = map_docs.get(qid)
            if md is None:
                continue
            doc = raw_by_obj.get(md["obj_id"])
            if doc is None:
                continue
            if md.get("sub_index") is not None:
                qtype = "passage"
            else:
                qtype = (doc.get("questionType") or "single_correct").lower()
            corr = a.get("correctness")
            if corr is None:
                corr = 1.0 if a.get("is_correct") else 0.0
            cur = by_type_counts.get(qtype, (0, 0.0))
            by_type_counts[qtype] = (cur[0] + 1, cur[1] + float(corr))
        by_type = [
            TypeBreakdown(
                question_type=qt,
                attempts=cnt,
                correct=int(round(score)),
                accuracy_pct=(score / cnt * 100) if cnt else 0.0,
            )
            for qt, (cnt, score) in sorted(by_type_counts.items())
        ]

        # Topics: weakest = highest priority_score; strongest = lowest
        topic_analytics = await self._topic_analytics(user_oid, attempts)
        weakest = sorted(topic_analytics, key=lambda t: t.priority_score, reverse=True)[:5]
        strongest = sorted(topic_analytics, key=lambda t: t.accuracy_pct, reverse=True)[:5]

        # Trend
        trend: list[TrendPoint] = []
        for s in sorted(completed, key=lambda x: x.get("completed_at") or x["created_at"]):
            total = int(s.get("total_questions") or 0)
            score = float(s.get("score") or 0.0)
            acc = (score / total * 100) if total else 0.0
            trend.append(TrendPoint(
                session_id=int(s["_id"]),
                completed_at=s.get("completed_at") or s["created_at"],
                accuracy_pct=acc,
                score=score,
            ))

        return AnalyticsOverviewResponse(
            total_tests=total_tests,
            total_questions=total_questions,
            overall_accuracy_pct=overall_acc,
            total_score=total_score,
            by_difficulty=by_difficulty,
            by_type=by_type,
            weakest_topics=weakest,
            strongest_topics=strongest,
            trend=trend,
        )

    async def get_topic_analytics(
        self, user_oid: ObjectId,
    ) -> AnalyticsTopicsResponse:
        attempts = await self.repo.list_user_attempts(user_oid)
        topics = await self._topic_analytics(user_oid, attempts)
        # Default sort: priority desc (weakest first).
        topics.sort(key=lambda t: t.priority_score, reverse=True)
        return AnalyticsTopicsResponse(topics=topics)

    async def get_activity_heatmap(
        self, user_oid: ObjectId, range_days: int = 182,
    ) -> ActivityHeatmapResponse:
        """Dense daily-count series anchored to IST midnight.

        India Standard Time (UTC+5:30, no DST) is the canonical timezone
        for this product — student-facing dates need to line up with
        local wall-clock days, so a problem solved at 01:00 IST belongs
        to that calendar day, not the previous UTC day.

        Always returns `range_days` contiguous buckets (oldest → newest),
        zero-filling days with no attempts so the frontend can lay out a
        fixed grid without having to handle gaps.
        """
        now_ist = datetime.now(IST)
        today_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ist = today_ist - timedelta(days=range_days - 1)
        end_ist_exclusive = today_ist + timedelta(days=1)

        attempts = await self.repo.list_user_attempts(user_oid)
        counts: dict[str, int] = defaultdict(int)
        for a in attempts:
            at = a.get("attempted_at")
            if not isinstance(at, datetime):
                continue
            # Mongo BSON datetimes come back naive; the spec is they're
            # stored as UTC, so attach that tz before shifting to IST.
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            at_ist = at.astimezone(IST)
            if at_ist < start_ist or at_ist >= end_ist_exclusive:
                continue
            counts[at_ist.strftime("%Y-%m-%d")] += 1

        days: list[HeatmapDay] = []
        max_count = 0
        total = 0
        for i in range(range_days):
            d = start_ist + timedelta(days=i)
            key = d.strftime("%Y-%m-%d")
            c = int(counts.get(key, 0))
            days.append(HeatmapDay(date=key, count=c))
            if c > max_count:
                max_count = c
            total += c

        return ActivityHeatmapResponse(
            days=days,
            range_days=range_days,
            max_count=max_count,
            total=total,
            timezone="Asia/Kolkata",
        )

    async def get_confidence(self, user_oid: ObjectId) -> ConfidenceResponse:
        """Compute the gamified Confidence Score (0–100) + trophy tier.

        The score is a weighted blend of five sub-scores. Each sub-score
        is normalised to [0, 100] independently so weights are tunable
        without scale juggling. See `_CONFIDENCE_WEIGHTS` and
        `_CONFIDENCE_TIERS` for the constants. Math summary:

            V (volume,        20%) = 100 · ln(1+Q) / ln(1+500), capped 100
            A (accuracy,      30%) = max(0, (acc% − 30) · 100/70) · sample_ramp
                where sample_ramp = min(Q, 10) / 10
            C (consistency,   20%) = active_days_30 / 30 · 100
            B (battles,       15%) = min(50, count·5) + win_rate · 50
            P (POTD,          15%) = potd_days_30 / 30 · 100

            Confidence = ΣᵢwᵢSᵢ, clamped to [0, 100].

        All day-windows use IST (see the `IST` constant) so streaks
        match what the student sees on their wall clock.
        """
        attempts = await self.repo.list_user_attempts(user_oid)
        sessions = await self.repo.list_user_sessions(user_oid, limit=500)
        # Read battles directly off the shared db handle — battles is a
        # different module but we only want a simple count + winner check,
        # not enough surface area to justify a cross-module HTTP hop or
        # importing the BattleRepository here.
        battle_cur = self.db["battles"].find({
            "$or": [
                {"player_a.user_id": user_oid},
                {"player_b.user_id": user_oid},
            ],
        })
        battles = [b async for b in battle_cur]

        now_ist = datetime.now(IST)
        cutoff = now_ist - timedelta(days=30)

        # ---- Volume (V) ----
        total_attempts = len(attempts)
        if total_attempts <= 0:
            v_score = 0.0
        else:
            v_score = min(
                100.0,
                100.0 * math.log1p(total_attempts) / math.log1p(500),
            )

        # ---- Accuracy (A) ----
        if total_attempts == 0:
            acc_pct = 0.0
            a_score = 0.0
        else:
            score_sum = 0.0
            for at in attempts:
                corr = at.get("correctness")
                if corr is None:
                    corr = 1.0 if at.get("is_correct") else 0.0
                score_sum += float(corr)
            acc_pct = score_sum / total_attempts * 100.0
            raw_a = max(0.0, (acc_pct - 30.0) * 100.0 / 70.0)
            # Ramp down accuracy weight while sample size is tiny —
            # 80% on 3 questions is noise, not skill.
            sample_ramp = min(total_attempts, 10) / 10.0
            a_score = raw_a * sample_ramp

        # ---- Consistency (C) — distinct IST days w/ ≥ 1 attempt in last 30 ----
        active_days_30: set = set()
        for at in attempts:
            ts = at.get("attempted_at")
            if not isinstance(ts, datetime):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_ist = ts.astimezone(IST)
            if ts_ist >= cutoff:
                active_days_30.add(ts_ist.date())
        c_score = min(100.0, len(active_days_30) / 30.0 * 100.0)

        # ---- Battle (B) — engagement + win rate ----
        battle_count = len(battles)
        if battle_count == 0:
            win_rate = 0.0
            b_score = 0.0
        else:
            wins = 0
            for x in battles:
                w = x.get("winner_user_id")
                # Winner is stored as ObjectId; compare safely against the
                # caller's user_oid. None on draws → not counted as a win.
                if w == user_oid:
                    wins += 1
            win_rate = wins / battle_count
            engagement = min(50.0, battle_count * 5.0)
            b_score = min(100.0, engagement + win_rate * 50.0)

        # ---- POTD (P) — distinct IST days the user actually SOLVED POTD.
        # Pulled from the dedicated `potd_user_state` collection (where
        # status='solved' is the strict signal), rather than counting any
        # 1-question mock-test session like we used to. Same 30-day window
        # and same 0–100 scaling — just a stricter "engaged" predicate.
        from modules.potd.repository import PotdRepository  # local import: avoid cycle
        cutoff_date_iso = cutoff.date().isoformat()
        potd_repo = PotdRepository(self.db)
        solved_iso_dates = await potd_repo.list_solved_dates_since(
            user_oid, cutoff_date_iso,
        )
        potd_days_30 = {d for d in solved_iso_dates}
        p_score = min(100.0, len(potd_days_30) / 30.0 * 100.0)

        # ---- Weighted total ----
        confidence = (
            _CONFIDENCE_WEIGHTS["volume"]      * v_score
            + _CONFIDENCE_WEIGHTS["accuracy"]    * a_score
            + _CONFIDENCE_WEIGHTS["consistency"] * c_score
            + _CONFIDENCE_WEIGHTS["battle"]      * b_score
            + _CONFIDENCE_WEIGHTS["potd"]        * p_score
        )
        confidence = max(0.0, min(100.0, confidence))

        # ---- Tier descriptors ----
        tier_data = _tier_for_confidence(confidence)
        next_data = _next_tier(tier_data["index"])

        tier = ConfidenceTier(
            name=tier_data["name"],
            index=int(tier_data["index"]),
            min_score=float(tier_data["min"]),
            max_score=float(tier_data["max"]),
        )
        next_tier = (
            ConfidenceTier(
                name=next_data["name"],
                index=int(next_data["index"]),
                min_score=float(next_data["min"]),
                max_score=float(next_data["max"]),
            )
            if next_data else None
        )

        sub_scores = [
            ConfidenceSubScore(
                key="volume",
                label="Practice volume",
                score=round(v_score, 1),
                weight=_CONFIDENCE_WEIGHTS["volume"],
                detail=(
                    f"{total_attempts} question{'s' if total_attempts != 1 else ''} attempted overall"
                    if total_attempts else "No attempts yet — try a mock test"
                ),
            ),
            ConfidenceSubScore(
                key="accuracy",
                label="Accuracy",
                score=round(a_score, 1),
                weight=_CONFIDENCE_WEIGHTS["accuracy"],
                detail=(
                    f"{acc_pct:.0f}% correct on {total_attempts} attempts"
                    + (" (sample ramping up)" if total_attempts < 10 else "")
                    if total_attempts else "Solve a few questions to start scoring"
                ),
            ),
            ConfidenceSubScore(
                key="consistency",
                label="Consistency",
                score=round(c_score, 1),
                weight=_CONFIDENCE_WEIGHTS["consistency"],
                detail=(
                    f"{len(active_days_30)} active day"
                    f"{'s' if len(active_days_30) != 1 else ''} in the last 30"
                ),
            ),
            ConfidenceSubScore(
                key="battle",
                label="1v1 battles",
                score=round(b_score, 1),
                weight=_CONFIDENCE_WEIGHTS["battle"],
                detail=(
                    f"{battle_count} battle{'s' if battle_count != 1 else ''}, "
                    f"{int(round(win_rate * 100))}% wins"
                    if battle_count else "No battles yet — enter the arena"
                ),
            ),
            ConfidenceSubScore(
                key="potd",
                label="POTD streak",
                score=round(p_score, 1),
                weight=_CONFIDENCE_WEIGHTS["potd"],
                detail=(
                    f"Solved POTD on {len(potd_days_30)} day"
                    f"{'s' if len(potd_days_30) != 1 else ''} in the last 30"
                    if potd_days_30 else "No POTD solves in the last 30 days"
                ),
            ),
        ]

        return ConfidenceResponse(
            score=round(confidence, 1),
            tier=tier,
            next_tier=next_tier,
            sub_scores=sub_scores,
            total_attempts=total_attempts,
            overall_accuracy_pct=round(acc_pct, 1),
            active_days_30=len(active_days_30),
            potd_days_30=len(potd_days_30),
            battle_count=battle_count,
            battle_win_rate=round(win_rate, 3),
        )

    async def _topic_analytics(
        self, user_oid: ObjectId, attempts: list[dict],
    ) -> list[TopicAnalytics]:
        if not attempts:
            return []
        from engine.priority import priority_scores_for_topics

        topic_ids = sorted({int(a["topic_id"]) for a in attempts})

        # Build engine attempts so we can run priority scoring.
        engine_attempts: list[EngineAttempt] = []
        for a in attempts:
            engine_attempts.append(EngineAttempt(
                user_id=user_oid,
                topic_id=int(a["topic_id"]),
                question_id=int(a["question_id"]),
                is_correct=bool(a.get("is_correct", False)),
                difficulty=str(a.get("difficulty", "medium")),
                score_contribution=int(a.get("score_contribution", 0)),
                attempted_at=a.get("attempted_at") or datetime.now(timezone.utc),
                correctness=a.get("correctness"),
            ))
        topic_chapter_map = await self.repo.topic_chapter_map(topic_ids)
        scores = priority_scores_for_topics(
            topic_ids, engine_attempts, datetime.now(timezone.utc),
            topic_chapters=topic_chapter_map or None,
        )

        # Hydrate names.
        topic_docs = []
        async for t in self.repo.topic_map.find({"_id": {"$in": topic_ids}}):
            topic_docs.append(t)
        topic_by_id = {int(t["_id"]): t for t in topic_docs}

        # Per-topic attempt aggregations.
        by_topic: dict[int, list[dict]] = defaultdict(list)
        for a in attempts:
            by_topic[int(a["topic_id"])].append(a)

        out: list[TopicAnalytics] = []
        for tid in topic_ids:
            t_doc = topic_by_id.get(tid)
            if t_doc is None:
                continue
            t_attempts = by_topic[tid]
            cnt = len(t_attempts)
            score = 0.0
            last = None
            for a in t_attempts:
                corr = a.get("correctness")
                if corr is None:
                    corr = 1.0 if a.get("is_correct") else 0.0
                score += float(corr)
                at = a.get("attempted_at")
                if at is not None and (last is None or at > last):
                    last = at
            ps = scores.get(tid)
            out.append(TopicAnalytics(
                topic_id=tid,
                topic_name=t_doc.get("name", ""),
                chapter_name=t_doc.get("chapter", ""),
                subject_name=t_doc.get("subject", ""),
                attempts=cnt,
                correct=int(round(score)),
                accuracy_pct=(score / cnt * 100) if cnt else 0.0,
                priority_score=float(ps.score) if ps else 0.0,
                decay_factor=float(ps.decay_factor) if ps else 1.0,
                last_attempted_at=last,
            ))
        return out

    # ------------------------------------------------------------------
    # Chapter analytics — list (used by the analytics index page)
    # ------------------------------------------------------------------

    async def get_chapter_analytics(
        self, user_oid: ObjectId,
    ) -> AnalyticsChaptersResponse:
        attempts = await self.repo.list_user_attempts(user_oid)
        if not attempts:
            return AnalyticsChaptersResponse(chapters=[])

        # Topic-level metrics first (we already have this helper).
        topic_analytics = await self._topic_analytics(user_oid, attempts)
        topic_by_id = {t.topic_id: t for t in topic_analytics}

        # Map topic_id → chapter_id and the chapter doc.
        all_topic_ids = list(topic_by_id.keys())
        topic_docs: list[dict] = []
        async for d in self.repo.topic_map.find({"_id": {"$in": all_topic_ids}}):
            topic_docs.append(d)
        topic_to_chapter: dict[int, int] = {
            int(d["_id"]): int(d.get("chapter_id", 0)) for d in topic_docs
        }
        chapter_ids = sorted({cid for cid in topic_to_chapter.values() if cid})

        chapter_docs: dict[int, dict] = {}
        async for d in self.repo.chapter_map.find({"_id": {"$in": chapter_ids}}):
            chapter_docs[int(d["_id"])] = d

        subject_ids = sorted({int(d.get("subject_id", 0)) for d in chapter_docs.values()})
        subject_docs: dict[int, dict] = {}
        async for d in self.repo.subject_map.find({"_id": {"$in": subject_ids}}):
            subject_docs[int(d["_id"])] = d

        # Total topics per chapter from the catalog (denominator for coverage).
        catalog_by_chapter = await self.repo.list_all_topics_grouped_by_chapter()

        # Roll up topic analytics into chapters.
        by_chapter: dict[int, list[TopicAnalytics]] = defaultdict(list)
        for tid, ta in topic_by_id.items():
            cid = topic_to_chapter.get(tid)
            if cid:
                by_chapter[cid].append(ta)

        out: list[ChapterAnalytics] = []
        for cid, topics in by_chapter.items():
            ch_doc = chapter_docs.get(cid, {})
            subj_doc = subject_docs.get(int(ch_doc.get("subject_id", 0)), {})
            attempts_sum = sum(t.attempts for t in topics)
            correct_sum = sum(t.correct for t in topics)
            priority_avg = (
                sum(t.priority_score for t in topics) / len(topics)
                if topics else 0.0
            )
            priority_max = max((t.priority_score for t in topics), default=0.0)
            decay_avg = (
                sum(t.decay_factor for t in topics) / len(topics)
                if topics else 1.0
            )
            last_at = None
            for t in topics:
                if t.last_attempted_at is not None and (
                    last_at is None or t.last_attempted_at > last_at
                ):
                    last_at = t.last_attempted_at

            out.append(ChapterAnalytics(
                chapter_id=cid,
                chapter_name=ch_doc.get("name", ""),
                subject_id=int(ch_doc.get("subject_id", 0)),
                subject_name=subj_doc.get("name", ""),
                attempted_topic_count=len(topics),
                total_topic_count=len(catalog_by_chapter.get(cid, [])),
                attempts=attempts_sum,
                correct=correct_sum,
                accuracy_pct=(correct_sum / attempts_sum * 100) if attempts_sum else 0.0,
                avg_priority_score=priority_avg,
                max_priority_score=priority_max,
                avg_decay_factor=decay_avg,
                last_attempted_at=last_at,
            ))

        # Default: weakest chapters first.
        out.sort(key=lambda c: c.avg_priority_score, reverse=True)
        return AnalyticsChaptersResponse(chapters=out)

    # ------------------------------------------------------------------
    # Chapter detail (drill-down for one chapter)
    # ------------------------------------------------------------------

    async def get_chapter_detail(
        self, user_oid: ObjectId, chapter_id: int,
    ) -> ChapterDetailResponse:
        ch_doc = await self.repo.get_chapter_doc(chapter_id)
        if ch_doc is None:
            raise AppException("Chapter not found.", status.HTTP_404_NOT_FOUND)
        subj_doc = await self.repo.get_subject_doc(int(ch_doc.get("subject_id", 0))) or {}

        # Catalog topics belonging to this chapter.
        catalog_topics = await self.repo.list_topics_for_chapter(chapter_id)
        chapter_topic_ids = {int(t["_id"]) for t in catalog_topics}

        attempts = await self.repo.list_user_attempts(user_oid)
        chapter_attempts = [
            a for a in attempts if int(a.get("topic_id", 0)) in chapter_topic_ids
        ]

        topic_analytics_all = await self._topic_analytics(user_oid, attempts)
        topics_in_chapter = [
            t for t in topic_analytics_all if t.topic_id in chapter_topic_ids
        ]
        topics_in_chapter.sort(key=lambda t: t.priority_score, reverse=True)

        # --- Difficulty / type breakdowns over chapter attempts ---
        by_difficulty = _bucket_by_key(
            chapter_attempts,
            key_fn=lambda a: str(a.get("difficulty", "medium")).lower(),
        )
        diff_rows = [
            DifficultyBreakdown(
                difficulty=k, attempts=cnt, correct=int(round(score)),
                accuracy_pct=(score / cnt * 100) if cnt else 0.0,
            )
            for k, (cnt, score) in sorted(by_difficulty.items())
        ]

        type_rows = await self._type_breakdown_for_attempts(chapter_attempts)

        # --- Priority trend per topic + chapter rollup ---
        allocs = await self.repo.list_topic_allocations_for_user(user_oid)
        chapter_allocs = [a for a in allocs if int(a["topic_id"]) in chapter_topic_ids]

        per_topic_priority_map: dict[int, list[PriorityTrendPoint]] = defaultdict(list)
        # Chapter trend = per-session average of priority scores across all
        # topics from this chapter that appeared in that session.
        rolled_priority_by_session: dict[int, dict] = {}
        for row in chapter_allocs:
            tid = int(row["topic_id"])
            sid = int(row["session_id"])
            completed_at = row.get("completed_at") or row.get("created_at")
            if completed_at is None:
                continue
            pt = PriorityTrendPoint(
                session_id=sid,
                completed_at=completed_at,
                priority_score=float(row.get("priority_score", 0.0)),
                decay_factor=float(row.get("decay_factor", 1.0)),
            )
            per_topic_priority_map[tid].append(pt)
            bucket = rolled_priority_by_session.setdefault(
                sid, {"completed_at": completed_at, "total": 0.0, "count": 0, "decay": 0.0},
            )
            bucket["total"] += pt.priority_score
            bucket["decay"] += pt.decay_factor
            bucket["count"] += 1

        priority_trend = [
            PriorityTrendPoint(
                session_id=sid,
                completed_at=b["completed_at"],
                priority_score=b["total"] / b["count"] if b["count"] else 0.0,
                decay_factor=b["decay"] / b["count"] if b["count"] else 1.0,
            )
            for sid, b in sorted(
                rolled_priority_by_session.items(), key=lambda kv: kv[1]["completed_at"],
            )
        ]

        # --- Accuracy trend per session (chapter rollup) ---
        accuracy_trend = await self._accuracy_trend_for_topics(
            user_oid, chapter_topic_ids,
        )

        # --- Cumulative attempts over time (per chapter) ---
        cumulative = _cumulative_by_day(chapter_attempts)

        # --- Per-topic accuracy trends (kept lightweight: just per topic in chapter) ---
        per_topic_priority = [
            TopicPriorityTrend(
                topic_id=tid,
                topic_name=next(
                    (t.topic_name for t in topics_in_chapter if t.topic_id == tid),
                    "",
                ),
                points=sorted(pts, key=lambda p: p.completed_at),
            )
            for tid, pts in per_topic_priority_map.items()
        ]

        per_topic_accuracy: list[TopicAccuracyTrend] = []
        for t in topics_in_chapter:
            pts = await self._accuracy_trend_for_topics(user_oid, {t.topic_id})
            per_topic_accuracy.append(TopicAccuracyTrend(
                topic_id=t.topic_id, topic_name=t.topic_name, points=pts,
            ))

        attempts_sum = sum(t.attempts for t in topics_in_chapter)
        correct_sum = sum(t.correct for t in topics_in_chapter)
        avg_priority = (
            sum(t.priority_score for t in topics_in_chapter) / len(topics_in_chapter)
            if topics_in_chapter else 0.0
        )
        max_priority = max((t.priority_score for t in topics_in_chapter), default=0.0)
        avg_decay = (
            sum(t.decay_factor for t in topics_in_chapter) / len(topics_in_chapter)
            if topics_in_chapter else 1.0
        )
        total_score = 0.0
        for a in chapter_attempts:
            corr = a.get("correctness")
            if corr is None:
                corr = 1.0 if a.get("is_correct") else 0.0
            total_score += float(corr)

        last_at = None
        for t in topics_in_chapter:
            if t.last_attempted_at is not None and (
                last_at is None or t.last_attempted_at > last_at
            ):
                last_at = t.last_attempted_at

        return ChapterDetailResponse(
            chapter_id=chapter_id,
            chapter_name=ch_doc.get("name", ""),
            subject_id=int(ch_doc.get("subject_id", 0)),
            subject_name=subj_doc.get("name", ""),
            attempts=attempts_sum,
            correct=correct_sum,
            accuracy_pct=(correct_sum / attempts_sum * 100) if attempts_sum else 0.0,
            total_score=total_score,
            avg_priority_score=avg_priority,
            max_priority_score=max_priority,
            avg_decay_factor=avg_decay,
            last_attempted_at=last_at,
            topics=topics_in_chapter,
            priority_trend=priority_trend,
            accuracy_trend=accuracy_trend,
            cumulative_attempts=cumulative,
            by_difficulty=diff_rows,
            by_type=type_rows,
            per_topic_priority=per_topic_priority,
            per_topic_accuracy=per_topic_accuracy,
        )

    # ------------------------------------------------------------------
    # Topic detail (drill-down for one topic)
    # ------------------------------------------------------------------

    async def get_topic_detail(
        self, user_oid: ObjectId, topic_id: int,
    ) -> TopicDetailResponse:
        t_doc = await self.repo.get_topic_doc(topic_id)
        if t_doc is None:
            raise AppException("Topic not found.", status.HTTP_404_NOT_FOUND)

        attempts = await self.repo.list_user_attempts(user_oid)
        topic_attempts = [a for a in attempts if int(a.get("topic_id", 0)) == topic_id]

        # Current priority via the existing helper.
        topic_analytics_all = await self._topic_analytics(user_oid, attempts)
        ta = next((t for t in topic_analytics_all if t.topic_id == topic_id), None)

        # Difficulty breakdown.
        by_difficulty = _bucket_by_key(
            topic_attempts,
            key_fn=lambda a: str(a.get("difficulty", "medium")).lower(),
        )
        diff_rows = [
            DifficultyBreakdown(
                difficulty=k, attempts=cnt, correct=int(round(score)),
                accuracy_pct=(score / cnt * 100) if cnt else 0.0,
            )
            for k, (cnt, score) in sorted(by_difficulty.items())
        ]

        type_rows = await self._type_breakdown_for_attempts(topic_attempts)

        # Priority trend from allocation history.
        allocs = await self.repo.list_topic_allocations_for_user(user_oid)
        topic_allocs = [a for a in allocs if int(a["topic_id"]) == topic_id]
        priority_trend = [
            PriorityTrendPoint(
                session_id=int(a["session_id"]),
                completed_at=a.get("completed_at") or a.get("created_at"),
                priority_score=float(a.get("priority_score", 0.0)),
                decay_factor=float(a.get("decay_factor", 1.0)),
            )
            for a in topic_allocs
            if (a.get("completed_at") or a.get("created_at")) is not None
        ]
        priority_trend.sort(key=lambda p: p.completed_at)

        # Accuracy trend per session.
        accuracy_trend = await self._accuracy_trend_for_topics(user_oid, {topic_id})

        cumulative = _cumulative_by_day(topic_attempts)

        recent = sorted(
            topic_attempts,
            key=lambda a: a.get("attempted_at") or datetime.now(timezone.utc),
            reverse=True,
        )[:25]
        recent_rows = []
        for a in recent:
            corr = a.get("correctness")
            eff = float(corr) if corr is not None else (
                1.0 if a.get("is_correct") else 0.0
            )
            recent_rows.append(RecentAttempt(
                session_id=int(a.get("session_id", 0)),
                question_id=int(a.get("question_id", 0)),
                attempted_at=a.get("attempted_at") or datetime.now(timezone.utc),
                is_correct=bool(a.get("is_correct", False)),
                correctness=eff,
                difficulty=str(a.get("difficulty", "medium")),
                score_contribution=int(a.get("score_contribution", 0)),
            ))

        # Chapter/subject hydration for the header.
        ch_doc = await self.repo.get_chapter_doc(int(t_doc.get("chapter_id", 0))) or {}
        subj_doc = await self.repo.get_subject_doc(int(t_doc.get("subject_id", 0))) or {}

        return TopicDetailResponse(
            topic_id=topic_id,
            topic_name=t_doc.get("name", ""),
            chapter_id=int(t_doc.get("chapter_id", 0)),
            chapter_name=ch_doc.get("name", t_doc.get("chapter", "")),
            subject_id=int(t_doc.get("subject_id", 0)),
            subject_name=subj_doc.get("name", t_doc.get("subject", "")),
            attempts=(ta.attempts if ta else len(topic_attempts)),
            correct=(ta.correct if ta else 0),
            accuracy_pct=(ta.accuracy_pct if ta else 0.0),
            current_priority_score=(ta.priority_score if ta else 0.0),
            current_decay_factor=(ta.decay_factor if ta else 1.0),
            last_attempted_at=(ta.last_attempted_at if ta else None),
            priority_trend=priority_trend,
            accuracy_trend=accuracy_trend,
            cumulative_attempts=cumulative,
            by_difficulty=diff_rows,
            by_type=type_rows,
            recent_attempts=recent_rows,
        )

    # ------------------------------------------------------------------
    # Shared analytics helpers
    # ------------------------------------------------------------------

    async def _type_breakdown_for_attempts(
        self, attempts: list[dict],
    ) -> list[TypeBreakdown]:
        if not attempts:
            return []
        qids = list({int(a["question_id"]) for a in attempts})
        map_docs = await self.repo.bulk_lookup_question_int_to_obj(qids)
        obj_ids = list({d["obj_id"] for d in map_docs.values() if d.get("obj_id")})
        raw_by_obj = await self.repo.fetch_question_docs_by_obj_ids(obj_ids)
        bucket: dict[str, tuple[int, float]] = {}
        for a in attempts:
            qid = int(a["question_id"])
            md = map_docs.get(qid)
            if md is None:
                continue
            doc = raw_by_obj.get(md["obj_id"])
            if doc is None:
                continue
            if md.get("sub_index") is not None:
                qtype = "passage"
            else:
                qtype = (doc.get("questionType") or "single_correct").lower()
            corr = a.get("correctness")
            if corr is None:
                corr = 1.0 if a.get("is_correct") else 0.0
            cur = bucket.get(qtype, (0, 0.0))
            bucket[qtype] = (cur[0] + 1, cur[1] + float(corr))
        return [
            TypeBreakdown(
                question_type=qt, attempts=cnt, correct=int(round(score)),
                accuracy_pct=(score / cnt * 100) if cnt else 0.0,
            )
            for qt, (cnt, score) in sorted(bucket.items())
        ]

    async def _accuracy_trend_for_topics(
        self, user_oid: ObjectId, topic_ids: set[int],
    ) -> list[AccuracyTrendPoint]:
        """Per-session accuracy on the given topic set, ordered by completion."""
        if not topic_ids:
            return []
        sessions = await self.repo.list_user_sessions(user_oid, limit=500)
        completed = [s for s in sessions if s.get("status") == "completed"]
        if not completed:
            return []
        completed.sort(key=lambda s: s.get("completed_at") or s.get("created_at"))
        sids = [int(s["_id"]) for s in completed]

        # Fetch all relevant responses in one shot.
        cursor = self.repo.responses.find({
            "session_id": {"$in": sids},
            "topic_id": {"$in": list(topic_ids)},
        })
        rows = [doc async for doc in cursor]
        by_session: dict[int, list[dict]] = defaultdict(list)
        for r in rows:
            by_session[int(r["session_id"])].append(r)

        out: list[AccuracyTrendPoint] = []
        for s in completed:
            sid = int(s["_id"])
            session_rows = by_session.get(sid, [])
            if not session_rows:
                continue
            total = 0
            score = 0.0
            for r in session_rows:
                if r.get("is_correct") is None:
                    continue
                total += 1
                corr = r.get("correctness")
                if corr is None:
                    corr = 1.0 if r.get("is_correct") else 0.0
                score += float(corr)
            if total == 0:
                continue
            out.append(AccuracyTrendPoint(
                session_id=sid,
                completed_at=s.get("completed_at") or s.get("created_at"),
                accuracy_pct=(score / total * 100) if total else 0.0,
                attempts=total,
                correct=int(round(score)),
            ))
        return out
