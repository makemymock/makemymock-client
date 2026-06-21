"""Pattern-learning business logic — the unlock gate + the sequential path.

Unlock rules:
  * A chapter's FIRST pattern opens when the student's mock accuracy IN THAT
    chapter clears UNLOCK_MIN_ACCURACY. Accuracy is chapter-specific —
    there is no overall fallback, so a chapter the student hasn't practised in
    mocks stays locked. Once they've started a chapter's path (any submission),
    it stays open even if their accuracy later dips.
  * Pattern N+1 opens once every question in pattern N is answered (any
    submission counts).
  * Within a pattern, question N+1 opens once question N is answered.

The service reads the catalog + progress from the PYQ cluster and the mock
accuracy from the primary DB (passed in as `db`).
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Union

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.pattern_learning.constants import (
    STATE_COMPLETED,
    STATE_LOCKED,
    STATE_SOLVED,
    STATE_UNLOCKED,
    UNLOCK_MIN_ACCURACY,
)
from modules.pattern_learning.db import get_catalog_db, get_progress_db
from modules.pattern_learning.grader import grade
from modules.pattern_learning.repository import CatalogRepository, ProgressRepository

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]+")


def _slugify(name: str) -> str:
    return "-".join(_WORD.findall((name or "").lower()))


def _humanize(slug: str) -> str:
    return " ".join(w.capitalize() for w in (slug or "").replace("_", "-").split("-") if w)


class PatternLearningService:
    def __init__(self, db: AsyncIOMotorDatabase):
        # `db` is the PRIMARY (makemymock) database — used only for the
        # mock-accuracy gate. Catalog + progress come from the PYQ cluster.
        self.db = db
        self.catalog = CatalogRepository(get_catalog_db())
        self.progress = ProgressRepository(get_progress_db())

    # ------------------------------------------------------------------
    # Unlock gate (mock accuracy)
    # ------------------------------------------------------------------

    async def _mock_accuracy(self, user_oid: ObjectId) -> tuple[dict[str, float], float]:
        """({chapter_slug: accuracy_pct}, overall_accuracy_pct) from mock tests."""
        from modules.mock_test.service import MockTestService

        try:
            resp = await MockTestService(self.db).get_chapter_analytics(user_oid)
        except Exception as exc:  # noqa: BLE001 — gate must never 500 the path
            logger.debug("mock chapter analytics failed: %s", exc)
            return {}, 0.0

        by_slug: dict[str, float] = {}
        total_correct = total_attempts = 0
        for c in getattr(resp, "chapters", []) or []:
            attempts = int(getattr(c, "attempts", 0) or 0)
            correct = int(getattr(c, "correct", 0) or 0)
            slug = _slugify(getattr(c, "chapter_name", "") or "")
            if slug and attempts > 0:
                by_slug[slug] = float(getattr(c, "accuracy_pct", 0.0) or 0.0)
            total_correct += correct
            total_attempts += attempts
        overall = (total_correct / total_attempts * 100.0) if total_attempts else 0.0
        return by_slug, overall

    def _gate(
        self, chapter: str, acc_map: dict[str, float], overall: float, has_started: bool,
    ) -> tuple[bool, float]:
        """(unlocked, accuracy_used). Gate on the student's accuracy IN THIS
        chapter's mocks ONLY — no overall fallback. A chapter with no mock
        attempts reports 0% here, so it stays locked until the student actually
        practises it and clears the bar. Already-started paths stay open.

        `overall` is accepted for call-site stability but intentionally unused."""
        acc = acc_map.get(chapter, 0.0)
        return (has_started or acc >= UNLOCK_MIN_ACCURACY), acc

    # ------------------------------------------------------------------
    # Subjects / chapters
    # ------------------------------------------------------------------

    async def list_subjects(self) -> dict:
        chapters = await self.catalog.chapters_with_patterns()
        subj_by_chap = await self.catalog.subject_by_chapter(chapters)
        counts: dict[str, int] = {}
        for ch in chapters:
            counts[subj_by_chap.get(ch) or "other"] = (
                counts.get(subj_by_chap.get(ch) or "other", 0) + 1
            )
        items = [
            {"subject": s, "display_name": _humanize(s), "chapter_count": n}
            for s, n in sorted(counts.items())
        ]
        return {"items": items}

    async def list_chapters(self, subject: str, user_oid: ObjectId) -> dict:
        chapters = await self.catalog.chapters_with_patterns()
        subj_by_chap = await self.catalog.subject_by_chapter(chapters)
        mine = sorted(c for c in chapters if (subj_by_chap.get(c) or "") == subject)

        acc_map, overall = await self._mock_accuracy(user_oid)
        uid = str(user_oid)
        items = []
        for ch in mine:
            patterns = await self.catalog.patterns_for_chapter(ch)
            assign = await self.catalog.assignments_by_pattern(
                [p["pattern_id"] for p in patterns]
            )
            solved = await self.progress.solved_in_chapter(uid, ch)
            completed = sum(
                1 for p in patterns
                if assign.get(p["pattern_id"])
                and all(q in solved for q in assign[p["pattern_id"]])
            )
            unlocked, acc = self._gate(ch, acc_map, overall, has_started=bool(solved))
            items.append({
                "chapter": ch,
                "display_name": _humanize(ch),
                "pattern_count": len(patterns),
                "unlocked": unlocked,
                "gate_accuracy": round(acc, 1),
                "gate_required": UNLOCK_MIN_ACCURACY,
                "completed_patterns": completed,
            })
        return {"subject": subject, "display_name": _humanize(subject), "items": items}

    # ------------------------------------------------------------------
    # Pattern roadmap (a chapter's patterns)
    # ------------------------------------------------------------------

    async def pattern_roadmap(self, chapter: str, user_oid: ObjectId) -> dict:
        patterns = await self.catalog.patterns_for_chapter(chapter)
        assign = await self.catalog.assignments_by_pattern(
            [p["pattern_id"] for p in patterns]
        )
        uid = str(user_oid)
        solved = await self.progress.solved_in_chapter(uid, chapter)

        acc_map, overall = await self._mock_accuracy(user_oid)
        gate_open, acc = self._gate(chapter, acc_map, overall, has_started=bool(solved))

        items = []
        prev_completed = True  # the first pattern is gated by gate_open, not this
        for i, p in enumerate(patterns):
            qids = assign.get(p["pattern_id"], [])
            total = len(qids)
            solved_count = sum(1 for q in qids if q in solved)
            completed = total > 0 and solved_count == total
            unlocked = gate_open if i == 0 else prev_completed
            if not unlocked:
                state = STATE_LOCKED
            elif completed:
                state = STATE_COMPLETED
            else:
                state = STATE_UNLOCKED
            items.append({
                "pattern_id": p["pattern_id"],
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "sequence": i + 1,
                "state": state,
                "solved_count": solved_count,
                "total_count": total,
            })
            prev_completed = unlocked and completed
        return {
            "chapter": chapter,
            "display_name": _humanize(chapter),
            "unlocked": gate_open,
            "gate_accuracy": round(acc, 1),
            "gate_required": UNLOCK_MIN_ACCURACY,
            "items": items,
        }

    # ------------------------------------------------------------------
    # Question states within a pattern (shared by roadmap / content / submit)
    # ------------------------------------------------------------------

    async def _pattern_unlocked(self, pattern: dict, user_oid: ObjectId) -> bool:
        roadmap = await self.pattern_roadmap(pattern.get("chapter", ""), user_oid)
        for node in roadmap["items"]:
            if node["pattern_id"] == pattern["pattern_id"]:
                return node["state"] != STATE_LOCKED
        return False

    async def _question_states(
        self, pattern: dict, user_oid: ObjectId,
    ) -> tuple[bool, list[str], dict[str, str]]:
        pattern_unlocked = await self._pattern_unlocked(pattern, user_oid)
        qids = await self.catalog.ordered_question_ids(pattern["pattern_id"])
        solved = await self.progress.solved_in_pattern(
            str(user_oid), pattern["pattern_id"]
        )
        states: dict[str, str] = {}
        prev_solved = True
        for i, q in enumerate(qids):
            unlocked = pattern_unlocked if i == 0 else prev_solved
            is_solved = q in solved
            if not unlocked:
                states[q] = STATE_LOCKED
            elif is_solved:
                states[q] = STATE_SOLVED
            else:
                states[q] = STATE_UNLOCKED
            prev_solved = unlocked and is_solved
        return pattern_unlocked, qids, states

    async def question_roadmap(
        self, pattern_id: str, user_oid: ObjectId,
    ) -> Optional[dict]:
        pattern = await self.catalog.get_pattern(pattern_id)
        if pattern is None:
            return None
        pattern_unlocked, qids, states = await self._question_states(pattern, user_oid)
        items = [
            {"question_id": q, "sequence": i + 1, "state": states[q]}
            for i, q in enumerate(qids)
        ]
        return {
            "pattern_id": pattern_id,
            "pattern_name": pattern.get("name", ""),
            "chapter": pattern.get("chapter", ""),
            "unlocked": pattern_unlocked,
            "items": items,
        }

    # ------------------------------------------------------------------
    # Question content + submission
    # ------------------------------------------------------------------

    def _build_content(
        self, q: dict, pattern_id: str, chapter: str, attempt: Optional[dict],
    ) -> dict:
        is_img_opt = q.get("isImgOption") or []
        options = []
        for i, o in enumerate(q.get("options") or []):
            options.append({
                "identifier": o.get("identifier", ""),
                "content": o.get("content", ""),
                "is_image": bool(is_img_opt[i]) if i < len(is_img_opt) else False,
            })
        content = {
            "question_id": q.get("question_id", ""),
            "pattern_id": pattern_id,
            "chapter": chapter,
            "type": q.get("type", ""),
            "question_html": q.get("question", ""),
            "options": options,
            "answer_revealed": attempt is not None,
            "correct_options": [],
            "correct_value": None,
            "explanation_html": None,
            "prior_answer": None,
            "prior_correct": None,
        }
        if attempt is not None:
            _, correct = grade(q, attempt.get("user_answer", ""))
            content["correct_options"] = correct.get("options", [])
            content["correct_value"] = correct.get("value")
            content["explanation_html"] = q.get("explanation", "")
            content["prior_answer"] = attempt.get("user_answer")
            content["prior_correct"] = bool(attempt.get("is_correct"))
        return content

    async def get_question_content(
        self, question_id: str, user_oid: ObjectId,
    ) -> tuple[Optional[dict], Optional[str]]:
        """Returns (content, error) where error ∈ {None, 'not_found', 'locked'}."""
        pattern = await self._pattern_for_question(question_id)
        if pattern is None:
            return None, "not_found"
        _, _, states = await self._question_states(pattern, user_oid)
        if states.get(question_id, STATE_LOCKED) == STATE_LOCKED:
            return None, "locked"
        q = await self.catalog.get_question(question_id)
        if q is None:
            return None, "not_found"
        attempt = await self.progress.get_attempt(str(user_oid), question_id)
        return self._build_content(
            q, pattern["pattern_id"], pattern.get("chapter", ""), attempt
        ), None

    async def submit_answer(
        self, question_id: str, user_oid: ObjectId, answer: Union[str, list[str]],
    ) -> tuple[Optional[dict], Optional[str]]:
        pattern = await self._pattern_for_question(question_id)
        if pattern is None:
            return None, "not_found"
        _, qids, states = await self._question_states(pattern, user_oid)
        if states.get(question_id, STATE_LOCKED) == STATE_LOCKED:
            return None, "locked"
        q = await self.catalog.get_question(question_id)
        if q is None:
            return None, "not_found"

        is_correct, correct = grade(q, answer)
        await self.progress.record_attempt(
            user_id=str(user_oid),
            chapter=pattern.get("chapter", ""),
            pattern_id=pattern["pattern_id"],
            question_id=question_id,
            user_answer=answer,
            is_correct=is_correct,
        )

        # Recompute what this submission unlocks.
        solved = await self.progress.solved_in_pattern(
            str(user_oid), pattern["pattern_id"]
        )
        solved.add(question_id)
        idx = qids.index(question_id) if question_id in qids else -1
        next_qid = qids[idx + 1] if 0 <= idx < len(qids) - 1 else None
        pattern_completed = bool(qids) and all(q_ in solved for q_ in qids)
        return {
            "is_correct": is_correct,
            "correct_options": correct.get("options", []),
            "correct_value": correct.get("value"),
            "explanation_html": q.get("explanation", ""),
            "next_question_id": next_qid,
            "pattern_completed": pattern_completed,
        }, None

    async def _pattern_for_question(self, question_id: str) -> Optional[dict]:
        pid = await self.catalog.pattern_id_for_question(question_id)
        if pid is None:
            return None
        return await self.catalog.get_pattern(pid)
