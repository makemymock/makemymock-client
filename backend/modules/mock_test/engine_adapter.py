"""Buffered, in-memory adapter the engine talks to.

The engine is synchronous; FastAPI is async. To keep a single Mongo driver
in the hot path (Motor), the controller pre-fetches everything the engine
needs into a `BufferedRepository`, runs the engine synchronously against
that buffer, and then drains the engine's write buffer back to Motor.

`session_id` is pre-allocated *before* the engine is invoked, so the
buffered repo can return it synchronously from `save_session()`.

`user_id` is opaque — we pass the user's Mongo `ObjectId` straight
through. The engine only stores and equality-compares it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from engine.models import Attempt, Question


@dataclass
class BufferedRepository:
    """Holds the engine's pre-fetched reads + write buffers for one request."""

    user_id: Any
    preallocated_session_id: int

    # Pre-fetched reads
    attempts_for_topics: list[Attempt] = field(default_factory=list)
    attempts_for_user: list[Attempt] = field(default_factory=list)
    available_questions: list[tuple[Question, int]] = field(default_factory=list)
    topic_chapters: dict[int, int] = field(default_factory=dict)

    # Write buffers populated by the engine
    saved_session: Optional[tuple[Any, int, int, str]] = None
    saved_topic_allocations: list[tuple[int, int, float]] = field(default_factory=list)
    saved_question_responses: list[tuple[int, int, bool]] = field(default_factory=list)
    new_attempts: list[Attempt] = field(default_factory=list)
    session_completed: bool = False

    # Map populated by the controller before submit_test:
    # (session_id, question_id) → topic_id
    session_topic_lookup: dict[tuple[int, int], int] = field(default_factory=dict)

    # ----- Reads -----

    def get_attempts_for_topics(
        self, user_id: Any, topic_ids: Iterable[int],
    ) -> list[Attempt]:
        wanted = set(topic_ids)
        return [a for a in self.attempts_for_topics
                if a.user_id == user_id and a.topic_id in wanted]

    def get_attempts_for_user(self, user_id: Any) -> list[Attempt]:
        return [a for a in self.attempts_for_user if a.user_id == user_id]

    def get_available_questions(
        self, topic_ids: Iterable[int],
    ) -> list[tuple[Question, int]]:
        wanted = set(topic_ids)
        return [(q, tid) for q, tid in self.available_questions if tid in wanted]

    def get_topic_chapter_ids(
        self, topic_ids: Iterable[int],
    ) -> dict[int, int]:
        return {tid: cid for tid, cid in self.topic_chapters.items()
                if tid in set(topic_ids)}

    # ----- Writes -----

    def save_session(
        self, user_id: Any, total_questions: int, extra_questions: int, status: str,
    ) -> int:
        self.saved_session = (user_id, total_questions, extra_questions, status)
        return self.preallocated_session_id

    def save_topic_allocations(
        self, session_id: int,
        allocations: list[tuple[int, int, float]],
    ) -> None:
        self.saved_topic_allocations = list(allocations)

    def save_question_responses(
        self, session_id: int,
        responses: list[tuple[int, int, bool]],
    ) -> None:
        self.saved_question_responses = list(responses)

    def upsert_attempts(self, attempts: list[Attempt]) -> None:
        self.new_attempts = list(attempts)

    def mark_session_completed(self, session_id: int) -> None:
        self.session_completed = True

    def get_session_topic(
        self, session_id: int, question_id: int,
    ) -> Optional[int]:
        return self.session_topic_lookup.get((session_id, question_id))
