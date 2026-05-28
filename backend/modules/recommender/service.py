"""
Orchestration service for the JEE Recommender.

Implements the four-phase algorithm from §6 of RECOMMENDER_ARCHITECTURE.md:

  Phase A — Session Start     : load state, run Confidence Regulator, call SessionPlannerAgent
  Phase B — Per Question      : hot loop (< 200 ms): regulator → SR check → Thompson → IRT → agent
  Phase C — After Answer      : update Beta / IRT / SM-2, unlock check, async diagnosis trigger
  Phase D — Weekly (external) : trigger TrendIntelligenceAgent (called from admin route)

The service is the ONLY layer that calls agents. It is also the only layer that
coordinates between math_engine, repository, and agents. Controller calls service;
service never imports from controller.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.exceptions import (
    NoUnlockedTopics,
    StudentAlreadyInitialized,
    StudentNotInitialized,
)
from modules.recommender.agents import (
    DiagnosisAgent,
    QuestionSelectorAgent,
    SessionPlannerAgent,
    TrendIntelligenceAgent,
)
from modules.recommender.math_engine import (
    ConfidenceRegulator,
    IRTEngine,
    PrerequisiteChecker,
    SM2Scheduler,
    ThompsonSampler,
)
from modules.recommender.models import (
    new_question_history_doc,
    new_session_summary_doc,
)
from modules.recommender.repository import RecommenderRepository, get_prereq_graph
from modules.recommender.schema import (
    AllTopicStatesResponse,
    AllTrendScoresResponse,
    EndSessionResponse,
    InitializeStudentResponse,
    NextQuestionResponse,
    QuestionDetailResponse,
    QuestionOption,
    SessionHistoryResponse,
    SessionPlanResponse,
    SessionSummaryResponse,
    SessionState,
    StudentPersonalityResponse,
    StudentStatsResponse,
    SubmitAnswerResponse,
    TopicMasteryUpdate,
    TopicStateResponse,
    TopicTrendResponse,
    TrendUpdateResponse,
)
from modules.recommender.constants import (
    MASTERY_THRESHOLD,
    TREND_HIGH_PRIORITY_THRESHOLD,
)

logger = logging.getLogger(__name__)


class RecommenderService:
    """
    Orchestrates all recommender operations for a single request.

    Instantiated per-request (same as other modules) with the Motor database.
    Long-running agent calls are triggered via asyncio.create_task and never
    block the HTTP response.
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self._repo = RecommenderRepository(db)

    # -----------------------------------------------------------------------
    # Student initialization — creates 156 topic states + personality doc
    # -----------------------------------------------------------------------

    async def initialize_student(self, student_id: str) -> InitializeStudentResponse:
        """
        Create all per-topic state documents and the personality document for a new student.

        Raises StudentAlreadyInitialized if the student already has topic states.
        Idempotent: a second call on a partially initialized student fills in missing topics.
        """
        if await self._repo.student_is_initialized(student_id):
            raise StudentAlreadyInitialized()

        count = await self._repo.initialize_student(student_id)
        personality_created = await self._repo.create_personality(student_id)

        logger.info("Initialized student %s: %d topics, personality=%s", student_id, count, personality_created)
        return InitializeStudentResponse(
            student_id=student_id,
            topics_initialized=count,
            personality_created=personality_created,
            message=f"Student initialized with {count} topic states.",
        )

    # -----------------------------------------------------------------------
    # Phase A — Session start
    # -----------------------------------------------------------------------

    async def start_session(self, student_id: str) -> SessionPlanResponse:
        """
        Plan a study session for a student.

        1. Verify the student is initialized.
        2. Load personality and assess starting confidence mode.
        3. Call the SessionPlannerAgent (awaited, ~3 s).
        4. Return the session plan with an initial SessionState.
        """
        if not await self._repo.student_is_initialized(student_id):
            raise StudentNotInitialized()

        personality = await self._repo.get_personality(student_id) or {}
        session_id = str(uuid.uuid4())

        # Run the Session Planner Agent
        planner = SessionPlannerAgent()
        plan = await planner.run(student_id=student_id, db=self._db)

        initial_state = SessionState(
            consecutive_wrong=0,
            questions_asked=0,
            session_mode="normal",
        )

        return SessionPlanResponse(
            student_id=student_id,
            session_id=session_id,
            focus_topics=plan.get("focus_topics", []),
            session_mode=plan.get("session_mode", "mixed"),
            start_difficulty_offset=float(plan.get("start_difficulty_offset", 0.0)),
            review_injection_rate=float(plan.get("review_injection_rate", 0.25)),
            confidence_note=plan.get("confidence_note", ""),
            reasoning_steps=plan.get("reasoning_steps", []),
            state=initial_state,
        )

    # -----------------------------------------------------------------------
    # Phase B — Per-question hot loop
    # -----------------------------------------------------------------------

    async def get_next_question(
        self,
        student_id: str,
        session_id: str,
        focus_topics: list[str],
        start_difficulty_offset: float,
        review_injection_rate: float,
        state: SessionState,
    ) -> NextQuestionResponse:
        """
        Select the next question for the current slot using the full hot-loop pipeline.

        Steps:
          1. Confidence Regulator → determine session mode and difficulty offset.
          2. Spaced repetition injection check.
          3. Filter unlocked topics.
          4. Thompson Sampling over focus_topics ∩ unlocked.
          5. IRT difficulty targeting.
          6. QuestionSelectorAgent → selected_question_id.
        """
        personality = await self._repo.get_personality(student_id) or {}
        confidence_profile = personality.get("confidence_profile", "resilient")
        fatigue_threshold = personality.get("fatigue_threshold_questions", 20)

        # Step 1: Confidence Regulator
        mode_result = ConfidenceRegulator.get_session_mode(
            consecutive_wrong=state.consecutive_wrong,
            questions_asked=state.questions_asked,
            confidence_profile=confidence_profile,
            fatigue_threshold=fatigue_threshold,
        )
        current_mode = mode_result.mode
        difficulty_offset = start_difficulty_offset + mode_result.difficulty_offset

        # Step 2: Spaced repetition injection
        if SM2Scheduler.should_inject_review(review_injection_rate) and mode_result.mode == "normal":
            due_reviews = await self._repo.tool_get_due_reviews(student_id, limit=3)
            reviews_not_served = [
                r for r in due_reviews
                if r["question_id"] not in state.seen_all_ids
            ]
            if reviews_not_served:
                review = reviews_not_served[0]
                return NextQuestionResponse(
                    question_id=review["question_id"],
                    topic_id=review["topic_id"],
                    chapter=review.get("chapter", ""),
                    difficulty_target=0.0,
                    is_review_injection=True,
                    session_mode=current_mode,
                    difficulty_offset_applied=difficulty_offset,
                )

        # Step 3: Load topic states and build unlocked set
        all_states = await self._repo.get_topic_states_dict(student_id)
        graph = get_prereq_graph()
        unlocked_set = PrerequisiteChecker.get_unlocked_set(all_states, graph)

        if not unlocked_set:
            raise NoUnlockedTopics()

        # Step 4: Thompson Sampling
        # In recovery mode, prefer strong chapters (mastered topics)
        if mode_result.topic_override == "pick_mastered_topic":
            strong_chapters = set(personality.get("strong_chapters", []))
            recovery_states = [
                s for tid, s in all_states.items()
                if tid in unlocked_set and s.get("chapter", "") in strong_chapters
            ] or [s for tid, s in all_states.items() if tid in unlocked_set]
            unlocked_states = recovery_states
        else:
            # Use focus_topics ∩ unlocked if available, else all unlocked
            focus_set = set(focus_topics) & unlocked_set if focus_topics else unlocked_set
            unlocked_states = [
                s for tid, s in all_states.items()
                if tid in focus_set
            ]
            if not unlocked_states:
                unlocked_states = [s for tid, s in all_states.items() if tid in unlocked_set]

        trend_scores = await self._repo.get_trend_scores_dict()
        target_topic = ThompsonSampler.select_topic(
            topic_states=unlocked_states,
            trend_scores=trend_scores,
            focus_topics=focus_topics if mode_result.topic_override is None else None,
        )

        if not target_topic:
            raise NoUnlockedTopics()

        topic_state = all_states.get(target_topic, {})
        chapter = topic_state.get("chapter", "")

        # Step 5: IRT difficulty targeting
        theta = float(topic_state.get("theta", 0.0))
        target_difficulty = IRTEngine.target_difficulty(theta, offset=difficulty_offset)
        diff_min, diff_max = IRTEngine.difficulty_band(target_difficulty)

        # Step 6: Question Selector Agent
        error_profile = personality.get("error_profile", {})
        selector = QuestionSelectorAgent()
        question_id = await selector.run(
            student_id=student_id,
            topic_id=target_topic,
            difficulty_min=diff_min,
            difficulty_max=diff_max,
            seen_correct_ids=state.seen_correct_ids,
            error_profile=error_profile,
            db=self._db,
        )

        if not question_id:
            # Sparse topic fallback: widen the difficulty band and try once more
            question_id = await selector.run(
                student_id=student_id,
                topic_id=target_topic,
                difficulty_min=-1.5,
                difficulty_max=1.5,
                seen_correct_ids=[],
                error_profile=error_profile,
                db=self._db,
            )

        if not question_id:
            raise NoUnlockedTopics(
                f"No questions available for topic {target_topic}. Topic may be exhausted."
            )

        return NextQuestionResponse(
            question_id=question_id,
            topic_id=target_topic,
            chapter=chapter,
            difficulty_target=round(target_difficulty, 3),
            is_review_injection=False,
            session_mode=current_mode,
            difficulty_offset_applied=round(difficulty_offset, 3),
        )

    # -----------------------------------------------------------------------
    # Phase C — After answer
    # -----------------------------------------------------------------------

    async def process_answer(
        self,
        student_id: str,
        session_id: str,
        question_id: str,
        topic_id: str,
        chapter: str,
        correct: bool,
        time_ms: int,
        difficulty: float,
        question_type: str,
        state: SessionState,
    ) -> SubmitAnswerResponse:
        """
        Process a student's answer: update all math state, check prereqs, trigger agents.

        Steps (§6 Phase C):
          1. Append to student_question_history.
          2. Update Beta state (Thompson Sampling posterior).
          3. Update IRT theta.
          4. Update SM-2 spaced repetition schedule.
          5. Update session state counters.
          6. Prerequisite unlock check.
          7. If consecutive_wrong == 3: trigger async Diagnosis Agent.
        """
        # Step 1: record event
        avg_time_ms = 60000  # fallback; population average would come from repo in prod
        hist_doc = new_question_history_doc(
            student_id=student_id,
            session_id=session_id,
            question_id=question_id,
            topic_id=topic_id,
            chapter=chapter,
            correct=correct,
            time_ms=time_ms,
            difficulty=difficulty,
            question_type=question_type,
        )
        await self._repo.append_question_history(hist_doc)

        # Step 2 & 3 & 4: load current topic state, apply math updates
        topic_state = await self._repo.get_topic_state(student_id, topic_id) or {}
        alpha = int(topic_state.get("alpha", 1))
        beta_val = int(topic_state.get("beta", 1))
        theta = float(topic_state.get("theta", 0.0))
        current_interval = int(topic_state.get("review_interval_days", 1))
        current_ef = float(topic_state.get("easiness_factor", 2.5))
        total_correct = int(topic_state.get("total_correct", 0))
        total_attempts = int(topic_state.get("total_attempts", 0))

        # Beta update
        if correct:
            alpha += 1
        else:
            beta_val += 1

        # IRT update
        irt_update = IRTEngine.update_theta(theta, difficulty, correct)

        # SM-2 update
        grade = SM2Scheduler.compute_grade(correct, time_ms, avg_time_ms)
        is_first_correct = correct and total_correct == 0
        sm2 = SM2Scheduler.update_schedule(
            current_interval=current_interval,
            current_ef=current_ef,
            correct=correct,
            grade=grade,
            is_first_correct=is_first_correct,
        )

        # Persist updated state
        new_total_correct = total_correct + (1 if correct else 0)
        state_updates = {
            "alpha": alpha,
            "beta": beta_val,
            "theta": round(irt_update.theta_new, 4),
            "review_interval_days": sm2.interval_days,
            "easiness_factor": sm2.easiness_factor,
            "next_review_date": sm2.next_review_date,
            "total_attempts": total_attempts + 1,
            "total_correct": new_total_correct,
            "last_attempted": datetime.now(timezone.utc),
        }
        await self._repo.update_topic_state(student_id, topic_id, state_updates)

        # Step 5: update session state
        new_consecutive_wrong = 0 if correct else state.consecutive_wrong + 1
        new_questions_asked = state.questions_asked + 1

        new_seen_correct = list(state.seen_correct_ids)
        if correct and question_id not in new_seen_correct:
            new_seen_correct.append(question_id)
        new_seen_all = list(state.seen_all_ids)
        if question_id not in new_seen_all:
            new_seen_all.append(question_id)

        # Update block accuracy for fatigue tracking
        block_idx = min(state.questions_asked // 10, 2)
        new_block_correct = list(state.block_correct)
        new_block_total = list(state.block_total)
        if correct:
            new_block_correct[block_idx] += 1
        new_block_total[block_idx] += 1

        new_state = SessionState(
            consecutive_wrong=new_consecutive_wrong,
            questions_asked=new_questions_asked,
            session_mode=state.session_mode,
            seen_correct_ids=new_seen_correct,
            seen_all_ids=new_seen_all,
            block_correct=new_block_correct,
            block_total=new_block_total,
        )

        # Step 6: prerequisite unlock check
        # Reload all states after the update to get accurate mastery means
        all_states = await self._repo.get_topic_states_dict(student_id)
        graph = get_prereq_graph()
        newly_unlocked = PrerequisiteChecker.get_newly_unlocked(topic_id, all_states, graph)

        # Step 7: async Diagnosis Agent trigger on frustration
        frustration_triggered = new_consecutive_wrong >= 3
        diagnosis_triggered = False
        if frustration_triggered:
            diagnosis_triggered = True
            asyncio.create_task(
                DiagnosisAgent().run(
                    student_id=student_id,
                    session_id=session_id,
                    trigger="frustration",
                    db=self._db,
                )
            )
            logger.info("DiagnosisAgent triggered (frustration) for student %s", student_id)

        mastery_mean = alpha / (alpha + beta_val)
        return SubmitAnswerResponse(
            updated_topic=TopicMasteryUpdate(
                topic_id=topic_id,
                chapter=chapter,
                alpha=alpha,
                beta=beta_val,
                mastery_mean=round(mastery_mean, 3),
                theta=round(irt_update.theta_new, 4),
                next_review_date=sm2.next_review_date,
            ),
            newly_unlocked_topics=newly_unlocked,
            state=new_state,
            frustration_triggered=frustration_triggered,
            diagnosis_triggered=diagnosis_triggered,
        )

    # -----------------------------------------------------------------------
    # End session — Phase C teardown
    # -----------------------------------------------------------------------

    async def end_session(
        self,
        student_id: str,
        session_id: str,
        state: SessionState,
        started_at: datetime,
    ) -> EndSessionResponse:
        """
        Finalize the session: generate summary, trigger async Diagnosis Agent.

        The session summary is stored in session_summaries. The Diagnosis Agent
        runs in the background — the HTTP response is not delayed.
        """
        ended_at = datetime.now(timezone.utc)
        duration_minutes = (ended_at - started_at).total_seconds() / 60.0

        # Compute per-chapter accuracy from block data for the summary
        history = await self._repo.get_recent_history(student_id, limit=state.questions_asked + 5)
        session_events = [e for e in history if e.get("session_id") == session_id]

        accuracy_by_chapter: dict[str, float] = {}
        avg_time_by_topic: dict[str, float] = {}
        chapter_totals: dict[str, list[bool]] = {}
        topic_times: dict[str, list[float]] = {}

        for event in session_events:
            ch = event.get("chapter", "unknown")
            chapter_totals.setdefault(ch, []).append(event.get("correct", False))
            tid = event.get("topic_id", "")
            topic_times.setdefault(tid, []).append(float(event.get("time_ms", 0)) / 1000.0)

        for ch, outcomes in chapter_totals.items():
            accuracy_by_chapter[ch] = round(sum(outcomes) / len(outcomes), 3) if outcomes else 0.0
        for tid, times in topic_times.items():
            avg_time_by_topic[tid] = round(sum(times) / len(times), 1) if times else 0.0

        # Block accuracy for fatigue profiling
        first_acc = 0.0
        last_acc = 0.0
        if state.block_total[0] > 0:
            first_acc = state.block_correct[0] / state.block_total[0]
        if state.block_total[2] > 0:
            last_acc = state.block_correct[2] / state.block_total[2]

        summary_doc = new_session_summary_doc(
            session_id=session_id,
            student_id=student_id,
            duration_minutes=duration_minutes,
            questions_attempted=state.questions_asked,
            accuracy_by_chapter=accuracy_by_chapter,
            avg_time_by_topic=avg_time_by_topic,
            frustration_events_count=0,  # counted from history in diagnosis
            topics_unlocked=[],           # filled by diagnosis agent
            first_half_accuracy=round(first_acc, 3),
            second_half_accuracy=round(last_acc, 3),
            hardest_correct_difficulty=None,
            easiest_wrong_difficulty=None,
            session_mode_sequence=[state.session_mode],
        )
        summary_id = await self._repo.create_session_summary(summary_doc)

        # Trigger async Diagnosis Agent
        asyncio.create_task(
            DiagnosisAgent().run(
                student_id=student_id,
                session_id=session_id,
                trigger="session_end",
                db=self._db,
            )
        )
        logger.info("DiagnosisAgent triggered (session_end) for student %s, session %s", student_id, session_id)

        return EndSessionResponse(
            session_id=session_id,
            summary_id=summary_id,
            diagnosis_triggered=True,
            message="Session ended. Diagnosis running in background.",
        )

    # -----------------------------------------------------------------------
    # Read-only endpoints
    # -----------------------------------------------------------------------

    async def get_personality(self, student_id: str) -> StudentPersonalityResponse:
        """Fetch and return the student personality document."""
        doc = await self._repo.get_personality(student_id) or {}
        return StudentPersonalityResponse(
            student_id=student_id,
            learning_style=doc.get("learning_style", "balanced"),
            fatigue_threshold_questions=doc.get("fatigue_threshold_questions", 20),
            confidence_profile=doc.get("confidence_profile", "resilient"),
            improvement_rate=doc.get("improvement_rate", "medium"),
            strong_chapters=doc.get("strong_chapters", []),
            persistent_weak_chapters=doc.get("persistent_weak_chapters", []),
            avoidance_topics=doc.get("avoidance_topics", []),
            question_type_strengths=doc.get("question_type_strengths", {
                "single_correct": 0.5, "multi_correct": 0.5, "integer": 0.5, "matching": 0.5
            }),
            error_profile=doc.get("error_profile", {}),
            notes=doc.get("notes", ""),
            updated_at=doc.get("updated_at"),
        )

    async def get_all_topic_states(self, student_id: str) -> AllTopicStatesResponse:
        """Fetch all 156 topic states with unlock status for a student."""
        if not await self._repo.student_is_initialized(student_id):
            raise StudentNotInitialized()

        all_states = await self._repo.get_all_topic_states(student_id)
        graph = get_prereq_graph()
        states_dict = {s["topic_id"]: s for s in all_states}
        unlocked_set = PrerequisiteChecker.get_unlocked_set(states_dict, graph)

        topic_responses = []
        for s in all_states:
            alpha = int(s.get("alpha", 1))
            beta_val = int(s.get("beta", 1))
            denom = alpha + beta_val
            mean = alpha / denom
            variance = (alpha * beta_val) / (denom ** 2 * (denom + 1))
            topic_responses.append(TopicStateResponse(
                student_id=student_id,
                topic_id=s["topic_id"],
                chapter=s.get("chapter", ""),
                alpha=alpha,
                beta=beta_val,
                mastery_mean=round(mean, 3),
                mastery_uncertainty=round(variance, 4),
                theta=round(float(s.get("theta", 0.0)), 4),
                next_review_date=s.get("next_review_date", ""),
                review_interval_days=int(s.get("review_interval_days", 1)),
                easiness_factor=float(s.get("easiness_factor", 2.5)),
                total_attempts=int(s.get("total_attempts", 0)),
                total_correct=int(s.get("total_correct", 0)),
                last_attempted=s.get("last_attempted"),
                is_unlocked=s["topic_id"] in unlocked_set,
            ))

        return AllTopicStatesResponse(
            student_id=student_id,
            topic_states=topic_responses,
            total=len(topic_responses),
            unlocked_count=len(unlocked_set),
        )

    async def get_trend_scores(self) -> AllTrendScoresResponse:
        """Return all topic trend scores."""
        docs = await self._repo.get_all_trend_scores()
        topics = []
        computed_at = None
        for d in docs:
            p = d.get("p_appears", 0.0)
            topics.append(TopicTrendResponse(
                topic_id=d["topic_id"],
                chapter=d.get("chapter", ""),
                p_appears=p,
                trend_score_raw=d.get("trend_score_raw", 0.0),
                gap_bonus=d.get("gap_bonus", 1.0),
                streak_score=d.get("streak_score", 1.0),
                direction_multiplier=d.get("direction_multiplier", 1.0),
                computed_at=d.get("computed_at"),
                is_high_priority=p >= TREND_HIGH_PRIORITY_THRESHOLD,
            ))
            if computed_at is None and d.get("computed_at"):
                computed_at = d["computed_at"]
        topics.sort(key=lambda x: x.p_appears, reverse=True)
        return AllTrendScoresResponse(
            topics=topics,
            total=len(topics),
            high_priority_count=sum(1 for t in topics if t.is_high_priority),
            computed_at=computed_at,
        )

    async def get_session_history(
        self, student_id: str, limit: int = 10
    ) -> SessionHistoryResponse:
        """Return recent session summaries for a student."""
        docs = await self._repo.get_last_n_session_summaries(student_id, n=limit)
        sessions = [
            SessionSummaryResponse(**{k: v for k, v in d.items() if k != "_id"})
            for d in docs
        ]
        return SessionHistoryResponse(sessions=sessions, total=len(sessions))

    # -----------------------------------------------------------------------
    # Question detail & student stats (frontend helpers)
    # -----------------------------------------------------------------------

    async def get_question_detail(self, question_id: str) -> QuestionDetailResponse:
        from fastapi import status as http_status
        from core.exceptions import AppException
        doc = await self._repo.get_question_by_pyq_id(question_id)
        if not doc:
            raise AppException(f"Question {question_id} not found.", http_status.HTTP_404_NOT_FOUND)
        options = [
            QuestionOption(identifier=o.get("identifier", ""), content=o.get("content", ""))
            for o in (doc.get("options") or [])
        ]
        correct_opts = doc.get("correct_options") or []
        correct_ans = doc.get("correct_answer")
        return QuestionDetailResponse(
            question_id=str(doc.get("question_id", "")),
            question=doc.get("question", ""),
            options=options,
            correct_options=[str(x) for x in correct_opts] if isinstance(correct_opts, list) else [],
            correct_answer=str(correct_ans) if correct_ans is not None else None,
            type=doc.get("type", "mcq"),
            chapter=doc.get("chapter", ""),
            topic=doc.get("topic", ""),
            subject=doc.get("subject", ""),
            difficulty=doc.get("difficulty", "medium"),
            year=doc.get("year"),
            is_image_question=bool(doc.get("isImgQuestion", False)),
            is_image_option=doc.get("isImgOption", False),
        )

    async def get_student_stats(self, student_id: str) -> StudentStatsResponse:
        raw = await self._repo.get_student_stats(student_id)
        total = raw.get("total_attempts", 0)
        correct = raw.get("total_correct", 0)
        return StudentStatsResponse(
            total_attempts=total,
            total_correct=correct,
            accuracy=round(correct / total, 3) if total else 0.0,
            topics_attempted=raw.get("topics_attempted", 0),
            topics_mastered=raw.get("topics_mastered", 0),
            unlocked_count=raw.get("unlocked_count", 0),
        )

    # -----------------------------------------------------------------------
    # Admin — weekly trend update
    # -----------------------------------------------------------------------

    async def run_trend_update(self) -> TrendUpdateResponse:
        """
        Trigger the Trend Intelligence Agent to recompute all p_appears scores.

        Runs synchronously (not fire-and-forget) because this is an admin
        operation called infrequently via a cron route. Returns the result.
        """
        try:
            agent = TrendIntelligenceAgent()
            updated = await agent.run(db=self._db)
            return TrendUpdateResponse(
                status="completed",
                topics_updated=updated,
                message=f"Trend scores updated for {updated} topics.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("TrendIntelligenceAgent failed: %s", exc)
            return TrendUpdateResponse(
                status="failed",
                message=f"Trend update failed: {exc}",
            )
