"""Mock-test orchestration.

Wires the FastAPI controller to the engine via the BufferedRepository,
handles catalog projection, builds frontend payloads, and runs the
submission grader.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.exceptions import AppException
from engine.clock import SystemClock
from engine.models import Attempt as EngineAttempt, Question as EngineQuestion
from engine.recommender import create_mock_test as engine_create_mock_test
from engine.recommender import submit_test as engine_submit_test
from engine.models import AnswerEvaluation
from fastapi import status

from modules.mock_test.constants import (
    COUNTER_SESSION,
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
from modules.mock_test.repository import MockTestRepository
from modules.mock_test.schema import (
    AnalyticsOverviewResponse,
    AnalyticsTopicsResponse,
    AnswerInput,
    CatalogChapter,
    CatalogResponse,
    CatalogSubject,
    CatalogTopic,
    CreateMockTestRequest,
    CreateMockTestResponse,
    DifficultyBreakdown,
    HistoryItem,
    HistoryResponse,
    MatchingColumn,
    PerQuestionResult,
    QuestionPayload,
    QuestionPayloadOption,
    SessionResponse,
    SubmitMockTestRequest,
    SubmitMockTestResponse,
    TopicAnalytics,
    TrendPoint,
    TypeBreakdown,
)

logger = logging.getLogger(__name__)


# Display order rule (frontend & backend agree):
# single → multi → passage → matching → integer
_TYPE_RANK = {
    "single_correct": 0,
    "multi_correct": 1,
    "passage": 2,
    "matching": 3,
    "integer": 4,
}


def _user_uuid_from_object_id(oid: ObjectId) -> uuid.UUID:
    """Stable UUID derived from a Mongo ObjectId.

    The engine's models declare `user_id: UUID`. We don't have UUIDs; we
    derive a deterministic one from the 12-byte ObjectId. Same input → same
    UUID across calls, which keeps engine semantics intact.
    """
    raw = oid.binary
    # ObjectId is 12 bytes; pad to 16 for UUID.
    padded = raw + b"\x00" * 4
    return uuid.UUID(bytes=padded)


def _strip_answers(payload: dict) -> dict:
    """Remove answer-revealing fields from a question payload."""
    safe = dict(payload)
    safe.pop("correctOptions", None)
    safe.pop("correctOption", None)
    safe.pop("integerAnswer", None)
    safe.pop("solution", None)
    safe.pop("solutionImg", None)
    md = safe.get("matchingData")
    if isinstance(md, dict):
        new_md = {k: v for k, v in md.items() if k != "correctMapping"}
        safe["matchingData"] = new_md
    return safe


def _options_from_doc(doc: dict) -> list[QuestionPayloadOption]:
    out: list[QuestionPayloadOption] = []
    for key in ("A", "B", "C", "D"):
        text = doc.get(f"option{key}")
        if text is None or str(text).strip() == "":
            continue
        out.append(QuestionPayloadOption(key=key, text=str(text)))
    return out


def _matching_cols(doc: dict) -> tuple[list[MatchingColumn], list[MatchingColumn]]:
    md = doc.get("matchingData") or {}
    left_raw = md.get("leftColumn") or []
    right_raw = md.get("rightColumn") or []

    def _normalize(items, default_prefix):
        out = []
        for i, item in enumerate(items):
            if isinstance(item, dict):
                key = str(item.get("key") or item.get("id") or f"{default_prefix}{i+1}")
                text = str(item.get("text") or item.get("value") or "")
                image = item.get("image") or item.get("img")
                out.append(MatchingColumn(key=key, text=text, image=image))
            else:
                out.append(MatchingColumn(
                    key=f"{default_prefix}{i+1}", text=str(item),
                ))
        return out
    return _normalize(left_raw, "L"), _normalize(right_raw, "R")


class MockTestService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = MockTestRepository(db)

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

        # Fetch user's prior attempts on these topics.
        user_uuid = _user_uuid_from_object_id(user_oid)
        attempt_docs = await self.db["user_topic_attempts"].find(
            {"user_id": user_oid, "topic_id": {"$in": topic_ids}},
        ).to_list(length=None)
        engine_attempts: list[EngineAttempt] = []
        for ad in attempt_docs:
            engine_attempts.append(EngineAttempt(
                user_id=user_uuid,
                topic_id=int(ad["topic_id"]),
                question_id=int(ad["question_id"]),
                is_correct=bool(ad.get("is_correct", False)),
                difficulty=str(ad.get("difficulty", "medium")),
                score_contribution=int(ad.get("score_contribution", 0)),
                attempted_at=ad.get("attempted_at") or datetime.utcnow(),
                correctness=ad.get("correctness"),
            ))

        # Pre-allocate the session id (engine needs an int back from save_session).
        session_id = await self.repo.next_id(COUNTER_SESSION)

        buffered = BufferedRepository(
            user_id=user_uuid,
            preallocated_session_id=session_id,
            attempts_for_topics=engine_attempts,
            attempts_for_user=[],  # extras not supported in UI yet
            available_questions=engine_questions,
            topic_chapters=topic_chapter_map,
        )

        # Run the engine (synchronous on the buffered repo).
        mock_test = engine_create_mock_test(
            buffered,
            user_id=user_uuid,
            topic_ids=topic_ids,
            total_questions=payload.total_questions,
            include_extra=payload.extra_questions > 0,
            extra_count=payload.extra_questions,
            clock=SystemClock(),
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
                    passage_image=(doc.get("passageData") or {}).get("passageImg") or None,
                    passage_sub_index=sub_index,
                    passage_sub_total=len(sub_qs),
                    question_text=sub.get("questionText", ""),
                    question_image=sub.get("questionImg") or None,
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
                question_image=doc.get("questionImg") or None,
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

        # Run engine submit on a fresh buffered repo (writes only).
        user_uuid = _user_uuid_from_object_id(user_oid)
        buffered = BufferedRepository(
            user_id=user_uuid,
            preallocated_session_id=session_id,
            session_topic_lookup=session_topic_lookup,
        )
        result = engine_submit_test(
            buffered,
            session_id=session_id,
            user_id=user_uuid,
            evaluations=evaluations,
            difficulty_by_question=difficulty_by_q,
            clock=SystemClock(),
        )

        # Persist attempt rows.
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

        # Backfill score_contribution into per-question results.
        for r in graded_results:
            r.score_contribution = attempt_sc_by_qid.get(r.question_id, 0)

        await self.repo.update_session_status(
            session_id,
            status="completed",
            score=result.total_score,
            correct=result.correct,
            incorrect=result.incorrect,
            partial=result.partial,
        )

        max_score = float(result.total) if result.total else 1.0
        accuracy_pct = (result.total_score / max_score) * 100 if max_score else 0.0

        # Sort results by display order so the client maps cleanly.
        graded_results.sort(key=lambda r: r.display_order)

        return SubmitMockTestResponse(
            session_id=session_id,
            total=result.total,
            correct=result.correct,
            incorrect=result.incorrect,
            partial=result.partial,
            total_score=result.total_score,
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
            q_image = None
            options: list = []
            left_col: list = []
            right_col: list = []
            passage_text = None
            passage_image = None
            passage_sub_index = None
            passage_sub_total = None
            passage_id = None
            solution_text = None
            solution_image = None

            if sub_index is not None:
                sub_qs = (doc.get("passageData") or {}).get("subQuestions") or []
                sub_doc = sub_qs[sub_index] if sub_index < len(sub_qs) else {}
                correct_answer = sub_doc.get("correctOption") or sub_doc.get("correctOptions")
                qtype = "passage"
                q_text = sub_doc.get("questionText", "")
                q_image = sub_doc.get("questionImg") or None
                options = _options_from_doc(sub_doc)
                passage_text = (doc.get("passageData") or {}).get("passageText", "")
                passage_image = (doc.get("passageData") or {}).get("passageImg") or None
                passage_sub_index = sub_index
                passage_sub_total = len(sub_qs)
                # Parent doc int-id (we have it via md.obj_id → qid_map lookup
                # earlier, but the response_row already carries the parent's
                # int id only for standalones; sub-question rows carry the
                # sub's int-id, so we look up the parent's separately).
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
                solution_image = (
                    sub_doc.get("solutionImg")
                    or doc.get("solutionImg")
                    or None
                )
            else:
                qtype = (doc.get("questionType") or "single_correct").lower()
                if qtype == "matching":
                    correct_answer = (doc.get("matchingData") or {}).get("correctMapping")
                elif qtype == "integer":
                    correct_answer = doc.get("integerAnswer")
                else:
                    correct_answer = doc.get("correctOptions")
                q_text = doc.get("questionText", "")
                q_image = doc.get("questionImg") or None
                if qtype in ("single_correct", "multi_correct"):
                    options = _options_from_doc(doc)
                elif qtype == "matching":
                    left_col, right_col = _matching_cols(doc)
                solution_text = doc.get("solution") or doc.get("explanation") or None
                solution_image = doc.get("solutionImg") or None

            difficulty = (doc.get("difficulty") or "medium").lower()
            is_correct = bool(r.get("is_correct"))
            correctness = r.get("correctness")
            if correctness is None:
                correctness = 1.0 if is_correct else 0.0
            results.append(PerQuestionResult(
                question_id=qid,
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
                question_image=q_image,
                options=options,
                left_column=left_col,
                right_column=right_col,
                passage_text=passage_text,
                passage_image=passage_image,
                passage_sub_index=passage_sub_index,
                passage_sub_total=passage_sub_total,
                passage_id=passage_id,
                solution_text=solution_text,
                solution_image=solution_image,
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

    async def _topic_analytics(
        self, user_oid: ObjectId, attempts: list[dict],
    ) -> list[TopicAnalytics]:
        if not attempts:
            return []
        from engine.priority import priority_scores_for_topics

        topic_ids = sorted({int(a["topic_id"]) for a in attempts})

        # Build engine attempts so we can run priority scoring.
        user_uuid = _user_uuid_from_object_id(user_oid)
        engine_attempts: list[EngineAttempt] = []
        for a in attempts:
            engine_attempts.append(EngineAttempt(
                user_id=user_uuid,
                topic_id=int(a["topic_id"]),
                question_id=int(a["question_id"]),
                is_correct=bool(a.get("is_correct", False)),
                difficulty=str(a.get("difficulty", "medium")),
                score_contribution=int(a.get("score_contribution", 0)),
                attempted_at=a.get("attempted_at") or datetime.utcnow(),
                correctness=a.get("correctness"),
            ))
        topic_chapter_map = await self.repo.topic_chapter_map(topic_ids)
        scores = priority_scores_for_topics(
            topic_ids, engine_attempts, datetime.utcnow(),
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
