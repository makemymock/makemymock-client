from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.exceptions import NoUnlockedTopics, StudentNotInitialized
from modules.recommender.agents import DiagnosisAgent, LatexConverterAgent, QuestionSelectorAgent, SessionPlannerAgent, TrendIntelligenceAgent
from modules.recommender.math_engine import ConfidenceRegulator, IRTEngine, SM2Scheduler, ThompsonSampler
from modules.recommender.models import new_question_history_doc, new_session_summary_doc
from modules.recommender.repository import RecommenderRepository
from modules.recommender.schema import (
    AllTopicStatesResponse,
    AllTrendScoresResponse,
    AttemptedQuestionItem,
    AttemptedQuestionsResponse,
    CatalogChapterInfo,
    CatalogSubjectInfo,
    CatalogSubjectsResponse,
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
    ALL_SUBJECTS,
    INCORRECT_INJECTION_PROB,
    MASTERY_THRESHOLD,
    SUBJECT_MATHEMATICS,
    TREND_HIGH_PRIORITY_THRESHOLD,
)

logger = logging.getLogger(__name__)


def _build_coach_note(
    mode: str,
    topic_id: str,
    mastery_mean: float,
    p_appears: float,
    difficulty_offset: float,
) -> str:
    topic_name  = topic_id.split("::")[-1].replace("-", " ").title()
    mastery_pct = int(mastery_mean * 100)
    jee_pct     = int(p_appears * 100)

    if mode == "recovery":
        return (
            f"Switching to {topic_name} ({mastery_pct}% mastery) — a chapter you know well. "
            "Getting a few right here will get your confidence back before we push harder."
        )
    if mode == "wind_down":
        return f"Finishing strong with {topic_name}. Great session today."

    parts: list[str] = []
    if mastery_pct < 40:
        parts.append(f"{topic_name} is your weakest area at {mastery_pct}% mastery")
    elif mastery_pct < 65:
        parts.append(f"{topic_name} still has room to grow ({mastery_pct}% mastery)")

    if jee_pct >= 70:
        parts.append(f"it appears in ~{jee_pct}% of recent JEE papers")
    elif jee_pct >= 50:
        parts.append(f"it's a regular fixture in JEE")

    if difficulty_offset > 0.4:
        parts.append("pushed to a harder question — you're on a streak")
    elif difficulty_offset < -0.4:
        parts.append("eased the difficulty to keep you in flow")

    if not parts:
        return f"Continuing with {topic_name} — solid growth opportunity."

    if len(parts) == 1:
        return parts[0].capitalize() + "."
    return parts[0].capitalize() + ", and " + parts[1] + "."


class RecommenderService:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self._repo = RecommenderRepository(db)

    async def initialize_student(self, student_id: str) -> InitializeStudentResponse:
        already = await self._repo.student_is_initialized(student_id)
        if already:
            # Idempotent — return success rather than 409 so the client can safely
            # call this endpoint multiple times without seeing an error.
            count = await self._repo.get_topic_state_count(student_id)
            return InitializeStudentResponse(
                student_id=student_id,
                topics_initialized=count,
                personality_created=False,
                message=f"Already initialized with {count} topics.",
            )

        # All subjects initialized from the catalog — no prereq graph
        total = 0
        for subject in ALL_SUBJECTS:
            try:
                total += await self._repo.initialize_student_for_subject(student_id, subject)
            except Exception as exc:
                logger.warning("Could not init %s topics for %s: %s", subject, student_id, exc)
        personality_created = await self._repo.create_personality(student_id)

        logger.info("Initialized student %s: %d topics across all subjects", student_id, total)
        return InitializeStudentResponse(
            student_id=student_id,
            topics_initialized=total,
            personality_created=personality_created,
            message=f"Student initialized with {total} topics across Maths, Physics and Chemistry.",
        )

    async def start_session(self, student_id: str) -> SessionPlanResponse:
        if not await self._repo.student_is_initialized(student_id):
            raise StudentNotInitialized()

        session_id = str(uuid.uuid4())
        plan = await SessionPlannerAgent().run(student_id=student_id, db=self._db)

        return SessionPlanResponse(
            student_id=student_id,
            session_id=session_id,
            focus_topics=plan.get("focus_topics", []),
            session_mode=plan.get("session_mode", "mixed"),
            start_difficulty_offset=float(plan.get("start_difficulty_offset", 0.0)),
            review_injection_rate=float(plan.get("review_injection_rate", 0.25)),
            confidence_note=plan.get("confidence_note", ""),
            reasoning_steps=plan.get("reasoning_steps", []),
            state=SessionState(),
        )

    async def start_session_stream(
        self, student_id: str, event_queue: asyncio.Queue
    ) -> SessionPlanResponse:
        """Like start_session but pushes SSE events into event_queue as each
        agent tool call completes.  The final 'plan' event is pushed last."""
        if not await self._repo.student_is_initialized(student_id):
            raise StudentNotInitialized()

        session_id = str(uuid.uuid4())

        async def _on_step(event: dict) -> None:
            await event_queue.put(event)

        plan = await SessionPlannerAgent().run(
            student_id=student_id, db=self._db, on_step=_on_step
        )

        resp = SessionPlanResponse(
            student_id=student_id,
            session_id=session_id,
            focus_topics=plan.get("focus_topics", []),
            session_mode=plan.get("session_mode", "mixed"),
            start_difficulty_offset=float(plan.get("start_difficulty_offset", 0.0)),
            review_injection_rate=float(plan.get("review_injection_rate", 0.25)),
            confidence_note=plan.get("confidence_note", ""),
            reasoning_steps=plan.get("reasoning_steps", []),
            state=SessionState(),
        )
        await event_queue.put({"type": "plan", **resp.model_dump()})
        return resp

    async def get_next_question(
        self,
        student_id: str,
        focus_topics: list[str],
        start_difficulty_offset: float,
        review_injection_rate: float,
        state: SessionState,
    ) -> NextQuestionResponse:
        personality = await self._repo.get_personality(student_id) or {}
        mode_result = ConfidenceRegulator.get_session_mode(
            consecutive_wrong=state.consecutive_wrong,
            questions_asked=state.questions_asked,
            confidence_profile=personality.get("confidence_profile", "resilient"),
            fatigue_threshold=personality.get("fatigue_threshold_questions", 20),
        )
        difficulty_offset = start_difficulty_offset + mode_result.difficulty_offset

        # Injections must stay within the current session's subject scope.
        # focus_topics is the list of topic IDs the student chose — if set, only
        # inject questions whose topic_id is in that set.
        _in_scope = set(focus_topics) if focus_topics else None

        # ── Incorrect retry injection (p=0.55, checked first) ──────────────────
        if SM2Scheduler.should_inject_review(INCORRECT_INJECTION_PROB) and mode_result.mode == "normal":
            due_wrong = await self._repo.get_due_incorrect_questions(student_id, limit=10)
            retry = next(
                (r for r in due_wrong
                 if r["question_id"] not in state.seen_all_ids
                 and (_in_scope is None or r.get("topic_id") in _in_scope)),
                None,
            )
            if retry:
                consec     = retry.get("consecutive_incorrect", 1)
                days_since = (datetime.now(timezone.utc) - retry["last_attempted_at"]).days if retry.get("last_attempted_at") else 1
                topic_name = retry["topic_id"].split("::")[-1].replace("-", " ").title()
                return NextQuestionResponse(
                    question_id=retry["question_id"],
                    topic_id=retry["topic_id"],
                    difficulty_target=0.0,
                    is_review_injection=True,
                    review_reason=(
                        f"You got this wrong {consec} time(s) — "
                        f"retry after {days_since} day(s). Getting it right consolidates the concept!"
                    ),
                    coach_note=(
                        f"You've gotten {topic_name} wrong {consec} time{'s' if consec > 1 else ''} in a row. "
                        "The AI is bringing it back now — solving it today will break the pattern."
                    ),
                )

        # ── SM-2 review injection (p=review_injection_rate) ────────────────────
        if SM2Scheduler.should_inject_review(review_injection_rate) and mode_result.mode == "normal":
            due = await self._repo.get_due_review_questions(student_id, limit=10)
            review = next(
                (r for r in due
                 if r["question_id"] not in state.seen_all_ids
                 and (_in_scope is None or r.get("topic_id") in _in_scope)),
                None,
            )
            if review:
                attempts   = review.get("times_attempted", 1)
                days_since = (datetime.now(timezone.utc) - review.get("last_attempted_at")).days if review.get("last_attempted_at") else 1
                topic_name = review["topic_id"].split("::")[-1].replace("-", " ").title()
                return NextQuestionResponse(
                    question_id=review["question_id"],
                    topic_id=review["topic_id"],
                    difficulty_target=0.0,
                    is_review_injection=True,
                    review_reason=f"Review #{attempts} — first solved {days_since} day(s) ago.",
                    coach_note=(
                        f"You solved this {topic_name} question {days_since} day(s) ago. "
                        f"This is review #{attempts} — spaced repetition research shows that reviewing at this "
                        "interval is the most efficient way to move it into long-term memory."
                    ),
                )

        # ── Topic selection via Thompson Sampling ───────────────────────────────
        all_states   = await self._repo.get_topic_states_dict(student_id)
        unlocked_set = set(all_states.keys())
        if not unlocked_set:
            raise NoUnlockedTopics()

        if mode_result.topic_override == "pick_mastered_topic":
            strong = set(personality.get("strong_chapters", []))
            pool = [s for tid, s in all_states.items() if tid in unlocked_set and s.get("chapter") in strong]
        else:
            focus_set = set(focus_topics) & unlocked_set if focus_topics else unlocked_set
            pool = [s for tid, s in all_states.items() if tid in focus_set]
        if not pool:
            pool = [s for tid, s in all_states.items() if tid in unlocked_set]

        trend_scores = await self._repo.get_trend_scores_dict()
        target_topic = ThompsonSampler.select_topic(
            topic_states=pool,
            trend_scores=trend_scores,
            focus_topics=focus_topics if mode_result.topic_override is None else None,
        )
        if not target_topic:
            raise NoUnlockedTopics()

        topic_state = all_states[target_topic]
        theta       = float(topic_state.get("theta", 0.0))
        d_target    = IRTEngine.target_difficulty(theta, offset=difficulty_offset)

        # ── Agent selects question via tool calls ───────────────────────────────
        selector    = QuestionSelectorAgent()
        question_id = await selector.run(student_id, target_topic, state.seen_all_ids, self._db)
        if not question_id:
            question_id = await selector.run(student_id, target_topic, [], self._db)
        if not question_id:
            # Hard fallback: agent failed entirely — query DB directly
            fallback = await self._repo.tool_get_candidate_questions(
                topic_id=target_topic, exclude_ids=[], limit=1, student_id=student_id,
            )
            question_id = fallback[0]["question_id"] if fallback else None
        if not question_id:
            raise NoUnlockedTopics(f"No questions available for topic {target_topic}.")

        return NextQuestionResponse(
            question_id=question_id,
            topic_id=target_topic,
            difficulty_target=round(d_target, 3),
            is_review_injection=False,
            coach_note=_build_coach_note(
                mode=mode_result.mode,
                topic_id=target_topic,
                mastery_mean=topic_state.get("alpha", 1) / (topic_state.get("alpha", 1) + topic_state.get("beta", 1)),
                p_appears=trend_scores.get(target_topic, 0.5),
                difficulty_offset=difficulty_offset,
            ),
        )

    async def get_next_question_stream(
        self,
        student_id: str,
        focus_topics: list[str],
        start_difficulty_offset: float,
        review_injection_rate: float,
        state: SessionState,
        event_queue: asyncio.Queue,
    ) -> NextQuestionResponse:
        """Like get_next_question but pushes live reasoning steps into event_queue."""

        async def emit(label: str, tool: str = "system") -> None:
            await event_queue.put({"type": "step", "tool": tool, "label": label})

        personality  = await self._repo.get_personality(student_id) or {}
        mode_result  = ConfidenceRegulator.get_session_mode(
            consecutive_wrong=state.consecutive_wrong,
            questions_asked=state.questions_asked,
            confidence_profile=personality.get("confidence_profile", "resilient"),
            fatigue_threshold=personality.get("fatigue_threshold_questions", 20),
        )
        difficulty_offset = start_difficulty_offset + mode_result.difficulty_offset
        _in_scope = set(focus_topics) if focus_topics else None

        # Incorrect retry injection
        if SM2Scheduler.should_inject_review(INCORRECT_INJECTION_PROB) and mode_result.mode == "normal":
            due_wrong = await self._repo.get_due_incorrect_questions(student_id, limit=10)
            retry = next(
                (r for r in due_wrong
                 if r["question_id"] not in state.seen_all_ids
                 and (_in_scope is None or r.get("topic_id") in _in_scope)),
                None,
            )
            if retry:
                consec = retry.get("consecutive_incorrect", 1)
                tn     = retry["topic_id"].split("::")[-1].replace("-", " ").title()
                await emit(f"Bringing back a question you got wrong {consec} time(s) — {tn}", "retry")
                days_since = (datetime.now(timezone.utc) - retry["last_attempted_at"]).days if retry.get("last_attempted_at") else 1
                resp = NextQuestionResponse(
                    question_id=retry["question_id"], topic_id=retry["topic_id"],
                    difficulty_target=0.0, is_review_injection=True,
                    review_reason=(
                        f"You got this wrong {consec} time(s) — "
                        f"retry after {days_since} day(s). Getting it right consolidates the concept!"
                    ),
                    coach_note=(
                        f"You've gotten {tn} wrong {consec} time{'s' if consec > 1 else ''} in a row. "
                        "Solving it today will break the pattern."
                    ),
                )
                await event_queue.put({"type": "question", **resp.model_dump()})
                return resp

        # SM-2 review injection
        if SM2Scheduler.should_inject_review(review_injection_rate) and mode_result.mode == "normal":
            due = await self._repo.get_due_review_questions(student_id, limit=10)
            review = next(
                (r for r in due
                 if r["question_id"] not in state.seen_all_ids
                 and (_in_scope is None or r.get("topic_id") in _in_scope)),
                None,
            )
            if review:
                tn      = review["topic_id"].split("::")[-1].replace("-", " ").title()
                days_since = (datetime.now(timezone.utc) - review.get("last_attempted_at")).days if review.get("last_attempted_at") else 1
                await emit(f"Spaced repetition — bringing back {tn} (solved {days_since} day(s) ago)", "review")
                attempts = review.get("times_attempted", 1)
                resp = NextQuestionResponse(
                    question_id=review["question_id"], topic_id=review["topic_id"],
                    difficulty_target=0.0, is_review_injection=True,
                    review_reason=f"Review #{attempts} — first solved {days_since} day(s) ago.",
                    coach_note=(
                        f"You solved this {tn} question {days_since} day(s) ago. "
                        f"This is review #{attempts} — the optimal interval for long-term retention."
                    ),
                )
                await event_queue.put({"type": "question", **resp.model_dump()})
                return resp

        # Topic selection via Thompson Sampling
        all_states   = await self._repo.get_topic_states_dict(student_id)
        unlocked_set = set(all_states.keys())
        if not unlocked_set:
            raise NoUnlockedTopics()

        if mode_result.topic_override == "pick_mastered_topic":
            strong = set(personality.get("strong_chapters", []))
            pool   = [s for tid, s in all_states.items() if tid in unlocked_set and s.get("chapter") in strong]
        else:
            focus_set = set(focus_topics) & unlocked_set if focus_topics else unlocked_set
            pool      = [s for tid, s in all_states.items() if tid in focus_set]
        if not pool:
            pool = [s for tid, s in all_states.items() if tid in unlocked_set]

        trend_scores = await self._repo.get_trend_scores_dict()
        target_topic = ThompsonSampler.select_topic(
            topic_states=pool, trend_scores=trend_scores,
            focus_topics=focus_topics if mode_result.topic_override is None else None,
        )
        if not target_topic:
            raise NoUnlockedTopics()

        topic_state = all_states[target_topic]
        alpha_v     = int(topic_state.get("alpha", 1))
        beta_v      = int(topic_state.get("beta", 1))
        p_appears   = trend_scores.get(target_topic, 0.5)
        theta       = float(topic_state.get("theta", 0.0))
        d_target    = IRTEngine.target_difficulty(theta, offset=difficulty_offset)

        # Agent selects question, streaming its own tool steps + thoughts
        async def _on_selector_step(event: dict) -> None:
            await event_queue.put(event)

        selector    = QuestionSelectorAgent()
        question_id = await selector.run(
            student_id, target_topic, state.seen_all_ids, self._db,
            on_step=_on_selector_step,
        )
        if not question_id:
            question_id = await selector.run(
                student_id, target_topic, [], self._db, on_step=_on_selector_step,
            )
        if not question_id:
            fallback    = await self._repo.tool_get_candidate_questions(
                topic_id=target_topic, exclude_ids=[], limit=1, student_id=student_id,
            )
            question_id = fallback[0]["question_id"] if fallback else None
        if not question_id:
            raise NoUnlockedTopics(f"No questions available for topic {target_topic}.")

        resp = NextQuestionResponse(
            question_id=question_id, topic_id=target_topic,
            difficulty_target=round(d_target, 3), is_review_injection=False,
            coach_note=_build_coach_note(
                mode=mode_result.mode, topic_id=target_topic,
                mastery_mean=alpha_v / (alpha_v + beta_v),
                p_appears=p_appears, difficulty_offset=difficulty_offset,
            ),
        )
        await event_queue.put({"type": "question", **resp.model_dump()})
        return resp

    async def process_answer(
        self,
        student_id: str,
        session_id: str,
        question_id: str,
        topic_id: str,
        correct: bool,
        time_ms: int,
        difficulty: float,
        question_type: str,
        state: SessionState,
    ) -> SubmitAnswerResponse:
        chapter = topic_id.split("::")[0] if "::" in topic_id else topic_id

        await self._repo.append_question_history(new_question_history_doc(
            student_id=student_id, session_id=session_id, question_id=question_id,
            topic_id=topic_id, chapter=chapter, correct=correct,
            time_ms=time_ms, difficulty=difficulty, question_type=question_type,
        ))

        topic_state_doc = await self._repo.get_topic_state(student_id, topic_id) or {}
        await self._repo.upsert_solved_question(
            student_id=student_id, question_id=question_id,
            topic_id=topic_id, chapter=chapter,
            difficulty=difficulty, question_type=question_type,
            last_correct=correct,
            subject=topic_state_doc.get("subject", SUBJECT_MATHEMATICS),
        )

        alpha    = int(topic_state_doc.get("alpha", 1))
        beta_val = int(topic_state_doc.get("beta", 1))

        if correct: alpha    += 1
        else:       beta_val += 1

        irt_update = IRTEngine.update_theta(float(topic_state_doc.get("theta", 0.0)), difficulty, correct)
        grade      = SM2Scheduler.compute_grade(correct, time_ms, avg_time_ms=60_000)
        sm2        = SM2Scheduler.update_schedule(
            current_interval=int(topic_state_doc.get("review_interval_days", 1)),
            current_ef=float(topic_state_doc.get("easiness_factor", 2.5)),
            correct=correct, grade=grade,
            is_first_correct=(correct and int(topic_state_doc.get("total_correct", 0)) == 0),
        )
        total_attempts = int(topic_state_doc.get("total_attempts", 0))

        await self._repo.update_topic_state(student_id, topic_id, {
            "alpha": alpha, "beta": beta_val,
            "theta": round(irt_update.theta_new, 4),
            "review_interval_days": sm2.interval_days,
            "easiness_factor": sm2.easiness_factor,
            "next_review_date": sm2.next_review_date,
            "total_attempts": total_attempts + 1,
            "total_correct": int(topic_state_doc.get("total_correct", 0)) + (1 if correct else 0),
            "last_attempted": datetime.now(timezone.utc),
        })

        new_seen = list(state.seen_all_ids)
        if question_id not in new_seen:
            new_seen.append(question_id)

        new_state = SessionState(
            consecutive_wrong=0 if correct else state.consecutive_wrong + 1,
            questions_asked=state.questions_asked + 1,
            seen_all_ids=new_seen,
        )

        all_states     = await self._repo.get_topic_states_dict(student_id)
        newly_unlocked: list[str] = []  # all topics always unlocked — no prereq graph

        frustration_triggered = new_state.consecutive_wrong >= 3
        if frustration_triggered:
            asyncio.create_task(DiagnosisAgent().run(student_id, session_id, "frustration", self._db))
            logger.info("DiagnosisAgent triggered (frustration) for %s", student_id)

        return SubmitAnswerResponse(
            updated_topic=TopicMasteryUpdate(
                topic_id=topic_id, chapter=chapter, alpha=alpha, beta=beta_val,
                mastery_mean=round(alpha / (alpha + beta_val), 3),
                theta=round(irt_update.theta_new, 4),
                next_review_date=sm2.next_review_date,
            ),
            newly_unlocked_topics=newly_unlocked,
            state=new_state,
            frustration_triggered=frustration_triggered,
        )

    async def end_session(self, student_id: str, session_id: str, state: SessionState, started_at: datetime) -> EndSessionResponse:
        ended_at         = datetime.now(timezone.utc)
        duration_minutes = (ended_at - started_at).total_seconds() / 60.0

        history        = await self._repo.get_recent_history(student_id, limit=state.questions_asked + 5)
        # Sort chronologically (get_recent_history returns DESC)
        session_events = sorted(
            [e for e in history if e.get("session_id") == session_id],
            key=lambda e: e.get("timestamp", ""),
        )

        chapter_totals: dict[str, list[bool]] = {}
        topic_times: dict[str, list[float]]   = {}
        for event in session_events:
            chapter_totals.setdefault(event.get("chapter", "unknown"), []).append(event.get("correct", False))
            topic_times.setdefault(event.get("topic_id", ""), []).append(float(event.get("time_ms", 0)) / 1000.0)

        accuracy_by_chapter = {ch: round(sum(outs) / len(outs), 3) for ch, outs in chapter_totals.items() if outs}
        avg_time_by_topic   = {tid: round(sum(ts) / len(ts), 1) for tid, ts in topic_times.items() if ts}

        # First-half vs second-half accuracy derived from event order (no block state needed)
        n    = len(session_events)
        mid  = n // 2
        def _acc(evts): return round(sum(1 for e in evts if e.get("correct")) / len(evts), 3) if evts else 0.0
        first_acc = _acc(session_events[:mid])
        last_acc  = _acc(session_events[mid:])

        summary_id = await self._repo.create_session_summary(new_session_summary_doc(
            session_id=session_id, student_id=student_id, duration_minutes=duration_minutes,
            questions_attempted=n or state.questions_asked,
            accuracy_by_chapter=accuracy_by_chapter, avg_time_by_topic=avg_time_by_topic,
            frustration_events_count=0, topics_unlocked=[],
            first_half_accuracy=first_acc, second_half_accuracy=last_acc,
            hardest_correct_difficulty=None, easiest_wrong_difficulty=None,
            session_mode_sequence=[],
        ))

        asyncio.create_task(DiagnosisAgent().run(student_id, session_id, "session_end", self._db))
        logger.info("DiagnosisAgent triggered (session_end) for %s, session %s", student_id, session_id)

        return EndSessionResponse(
            session_id=session_id, summary_id=summary_id,
            diagnosis_triggered=True, message="Session ended. Diagnosis running in background.",
        )

    async def get_personality(self, student_id: str) -> StudentPersonalityResponse:
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
        if not await self._repo.student_is_initialized(student_id):
            raise StudentNotInitialized()

        all_states = await self._repo.get_all_topic_states(student_id)

        topic_responses = []
        for s in all_states:
            alpha   = int(s.get("alpha", 1))
            beta_val = int(s.get("beta", 1))
            denom   = alpha + beta_val
            topic_responses.append(TopicStateResponse(
                student_id=student_id,
                topic_id=s["topic_id"],
                chapter=s.get("chapter", ""),
                subject=s.get("subject", SUBJECT_MATHEMATICS),
                alpha=alpha, beta=beta_val,
                mastery_mean=round(alpha / denom, 3),
                mastery_uncertainty=round((alpha * beta_val) / (denom ** 2 * (denom + 1)), 4),
                theta=round(float(s.get("theta", 0.0)), 4),
                next_review_date=s.get("next_review_date", ""),
                review_interval_days=int(s.get("review_interval_days", 1)),
                easiness_factor=float(s.get("easiness_factor", 2.5)),
                total_attempts=int(s.get("total_attempts", 0)),
                total_correct=int(s.get("total_correct", 0)),
                last_attempted=s.get("last_attempted"),
                is_unlocked=True,  # all topics unlocked — no prereq gate
            ))

        return AllTopicStatesResponse(
            student_id=student_id,
            topic_states=topic_responses,
            total=len(topic_responses),
            unlocked_count=len(topic_responses),
        )

    async def get_trend_scores(self) -> AllTrendScoresResponse:
        docs = await self._repo.get_all_trend_scores()
        if not docs:
            # First request — kick off computation in the background.
            # Subsequent requests will return real data once it finishes.
            asyncio.create_task(TrendIntelligenceAgent().run(db=self._db))
            return AllTrendScoresResponse(topics=[], total=0, high_priority_count=0, computed_at=None)

        topics = []
        computed_at = None
        for d in docs:
            p = d.get("p_appears", 0.0)
            topics.append(TopicTrendResponse(
                topic_id=d["topic_id"],
                chapter=d.get("chapter", ""),
                subject=d.get("subject", ""),
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
            topics=topics, total=len(topics),
            high_priority_count=sum(1 for t in topics if t.is_high_priority),
            computed_at=computed_at,
        )

    async def get_session_history(self, student_id: str, limit: int = 10) -> SessionHistoryResponse:
        docs = await self._repo.get_last_n_session_summaries(student_id, n=limit)
        sessions = [SessionSummaryResponse(**{k: v for k, v in d.items() if k != "_id"}) for d in docs]
        return SessionHistoryResponse(sessions=sessions, total=len(sessions))

    async def get_question_detail(self, question_id: str) -> QuestionDetailResponse:
        from fastapi import status as http_status
        from core.exceptions import AppException
        doc = await self._repo.get_question_by_pyq_id(question_id)
        if not doc:
            raise AppException(f"Question {question_id} not found.", http_status.HTTP_404_NOT_FOUND)

        raw_question = doc.get("question", "")
        raw_options  = doc.get("options") or []

        # ── LaTeX conversion via Gemini 3.5 Flash (up to 3 attempts) ────────────
        # Only convert non-image questions; image questions can't be rerendered.
        if not doc.get("isImgQuestion", False):
            _last_exc: Exception | None = None
            for _attempt in range(3):
                try:
                    converted    = await LatexConverterAgent().convert(raw_question, raw_options)
                    raw_question = converted["question"]
                    raw_options  = converted["options"]
                    _last_exc    = None
                    break
                except Exception as exc:
                    _last_exc = exc
                    if _attempt < 2:
                        await asyncio.sleep(0.5 * (_attempt + 1))   # 0.5s, 1.0s
            if _last_exc:
                logger.warning("LatexConverter failed after 3 attempts for %s: %s", question_id, _last_exc)

        options      = [QuestionOption(identifier=o.get("identifier", ""), content=o.get("content", "")) for o in raw_options]
        correct_opts = doc.get("correct_options") or []
        # Catalog stores integer answers in 'answer', not 'correct_answer'
        correct_ans  = doc.get("correct_answer") if doc.get("correct_answer") is not None else doc.get("answer")
        return QuestionDetailResponse(
            question_id=str(doc.get("question_id", "")),
            question=raw_question,
            options=options,
            correct_options=[str(x) for x in correct_opts] if isinstance(correct_opts, list) else [],
            correct_answer=str(correct_ans) if correct_ans is not None else None,
            explanation=doc.get("explanation") or "",
            type=doc.get("type", "mcq"),
            chapter=doc.get("chapter", ""), topic=doc.get("topic", ""), subject=doc.get("subject", ""),
            difficulty=doc.get("difficulty", "medium"),
            year=doc.get("year"),
            is_image_question=bool(doc.get("isImgQuestion", False)),
            is_image_option=doc.get("isImgOption", False),
        )

    async def get_attempted_questions(
        self, student_id: str, correct: bool, limit: int = 20,
    ) -> AttemptedQuestionsResponse:
        items_raw = await self._repo.get_attempted_questions_with_content(student_id, correct, limit)
        items = [
            AttemptedQuestionItem(
                question_id=it["question_id"],
                topic_id=it["topic_id"],
                chapter=it["chapter"],
                subject=it.get("subject", SUBJECT_MATHEMATICS),
                correct=it["correct"],
                difficulty=it.get("difficulty"),
                question_type=it.get("question_type", "single_correct"),
                timestamp=it.get("timestamp"),
                question_text=it.get("question_text", ""),
                options=[QuestionOption(**o) for o in it.get("options", [])],
                correct_options=it.get("correct_options", []),
                correct_answer=it.get("correct_answer"),
                year=it.get("year"),
                is_image_question=it.get("is_image_question", False),
            )
            for it in items_raw
        ]
        return AttemptedQuestionsResponse(items=items, total=len(items))

    async def get_catalog_subjects(self) -> CatalogSubjectsResponse:
        raw = await self._repo.get_catalog_subjects()
        subjects = [
            CatalogSubjectInfo(
                subject=s["subject"],
                chapters=[CatalogChapterInfo(**c) for c in s["chapters"]],
                topic_count=s["topic_count"],
            )
            for s in raw
        ]
        return CatalogSubjectsResponse(subjects=subjects)

    async def get_student_stats(self, student_id: str) -> StudentStatsResponse:
        raw     = await self._repo.get_student_stats(student_id)
        total   = raw.get("total_attempts", 0)
        correct = raw.get("total_correct", 0)
        return StudentStatsResponse(
            total_attempts=total, total_correct=correct,
            accuracy=round(correct / total, 3) if total else 0.0,
            topics_attempted=raw.get("topics_attempted", 0),
            topics_mastered=raw.get("topics_mastered", 0),
            unlocked_count=raw.get("unlocked_count", 0),
        )

    async def run_trend_update(self) -> TrendUpdateResponse:
        try:
            updated = await TrendIntelligenceAgent().run(db=self._db)
            return TrendUpdateResponse(status="completed", topics_updated=updated, message=f"Trend scores updated for {updated} topics.")
        except Exception as exc:
            logger.exception("TrendIntelligenceAgent failed: %s", exc)
            return TrendUpdateResponse(status="failed", message=f"Trend update failed: {exc}")
