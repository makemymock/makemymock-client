"""The data-access seam.

Production wires this to PostgreSQL via SQLAlchemy. Tests wire it to an
InMemoryRepository (see tests/fakes.py) so every algorithmic path is
exercisable without a database.
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol
from uuid import UUID

from engine.models import Attempt, Question


class Repository(Protocol):
    """The minimal data-access interface the recommender needs.

    All methods are synchronous; the production adapter is async but tests
    don't need that complexity.
    """

    # ----- reads -----

    def get_attempts_for_topics(
        self,
        user_id: UUID,
        topic_ids: Iterable[int],
    ) -> list[Attempt]:
        """All of the user's attempts whose topic_id is in topic_ids."""
        ...

    def get_attempts_for_user(self, user_id: UUID) -> list[Attempt]:
        """All attempts for the user, across every topic (for 'extras')."""
        ...

    def get_available_questions(
        self,
        topic_ids: Iterable[int],
    ) -> list[tuple[Question, int]]:
        """All questions tagged to any of these topics, paired with the
        topic_id they were tagged under.

        A question tagged to multiple topics appears once per tagging.

        Passage support: implementations EXPAND each passage document into
        one `Question` per sub-question, all sharing a `passage_id`. The
        engine's Layer 5 groups these into atoms and serves them as
        all-or-nothing units (see engine/selection.py). This is a
        deliberate divergence from Phase backend's `passage_id IS NULL`
        filter — see INTEGRATION.md §4.1.
        """
        ...

    def get_topic_chapter_ids(
        self,
        topic_ids: Iterable[int],
    ) -> dict[int, int]:
        """Map each topic_id to its chapter_id.

        Used by the hierarchical cold-start fallback in Layer 2 so an
        unattempted topic borrows priority from its chapter-mates first,
        before falling back to the global selected-set average.

        Implementations that don't have a chapter notion may return an
        empty dict; the engine will then fall back to flat borrowing.
        """
        ...

    # ----- writes -----

    def save_session(
        self,
        user_id: UUID,
        total_questions: int,
        extra_questions: int,
        status: str,
    ) -> int:
        """Insert a new session row, return its id."""
        ...

    def save_topic_allocations(
        self,
        session_id: int,
        allocations: list[tuple[int, int, float]],  # (topic_id, count, priority_score)
    ) -> None:
        ...

    def save_question_responses(
        self,
        session_id: int,
        responses: list[tuple[int, int, bool]],  # (question_id, topic_id, is_extra)
    ) -> None:
        """Insert blank response rows (user_answer=NULL, is_correct=NULL)."""
        ...

    def upsert_attempts(self, attempts: list[Attempt]) -> None:
        """ON CONFLICT (user_id, question_id) DO UPDATE — matches production."""
        ...

    def mark_session_completed(self, session_id: int) -> None:
        ...

    # ----- helper reads for submission flow -----

    def get_session_topic(self, session_id: int, question_id: int) -> Optional[int]:
        """Look up which topic a question was served under in this session.

        This matters because a question can belong to multiple topics — the
        attempt record must use the topic the question was *served under*,
        not an arbitrary one.
        """
        ...
