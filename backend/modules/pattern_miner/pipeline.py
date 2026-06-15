"""The per-question algorithm and the concurrency around it.

The 7 steps (in plain English), all owned by `Pipeline.process`:
  1. Snapshot this chapter's pattern catalog.
  2. Chunk it into CHUNK_SIZE pieces.
  3. Stage-1 fan-out — one Flash call per chunk, in parallel.
  4. Reduce:
       - 0 matches → step 5
       - 1 match  → that's the winner, step 6
       - 2+       → stage-2 reducer picks the winner OR escalates to step 5
  5. Propose-or-join, under the chapter lock (see `propose_or_join`).
  6. Upsert the assignment.
  7. Checkpoint.

All match decisions are LLM reasoning steps — no embeddings, no kNN. The
chapter lock is the only thing serialising the propose-new path; match-path
writes stay fully concurrent. This module owns ONLY orchestration: every LLM
call lives in `agents.py`, every DB write in `repository.py`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Iterable, Literal

from pymongo.errors import DuplicateKeyError

from modules.pattern_miner.agents import (
    MatchOnlyReducerAgent,
    PatternNamerAgent,
    Stage1ChunkClassifierAgent,
    Stage2ReducerAgent,
)
from modules.pattern_miner.constants import (
    CHUNK_SIZE,
    STAGE1_MIN_CONFIDENCE,
    STAGE2_MIN_CONFIDENCE,
)
from modules.pattern_miner.domain import (
    CleanedQuestion,
    Pattern,
    PatternDraft,
    Stage1Verdict,
)
from modules.pattern_miner.metrics import metrics
from modules.pattern_miner.repository import (
    AssignmentRepository,
    CheckpointRepository,
    PatternRepository,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-chapter lock registry.
#
# Serialises the propose-new path within one chapter while letting different
# chapters propose in parallel. Combined with the Mongo unique index on
# (chapter, slug), that's two layers of defence against duplicate-pattern
# creation under concurrency.
# ---------------------------------------------------------------------------


class ChapterLockManager:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._registry = asyncio.Lock()

    async def for_chapter(self, chapter: str) -> asyncio.Lock:
        async with self._registry:
            lock = self._locks.get(chapter)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[chapter] = lock
            return lock


# ---------------------------------------------------------------------------
# Step 2 — chunking. Step 3 — stage-1 fan-out via asyncio.gather.
# LLM calls are network-bound, so async gives the same parallelism as processes
# with shared state and clean cancellation.
# ---------------------------------------------------------------------------


def chunk_patterns(items: list[Pattern], chunk_size: int) -> list[list[Pattern]]:
    """Split into pieces of `chunk_size`. The last chunk may be shorter."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


async def run_stage1_fanout(
    *,
    agent: Stage1ChunkClassifierAgent,
    question: CleanedQuestion,
    chunks: Iterable[list[Pattern]],
) -> list[Stage1Verdict]:
    """Returns one verdict per chunk, preserving order."""
    chunk_list = [c for c in chunks if c]
    if not chunk_list:
        return []
    coros = [agent.run(question, chunk) for chunk in chunk_list]
    return await asyncio.gather(*coros)


# ---------------------------------------------------------------------------
# Step 5 — the lock-protected propose-or-join path. Only entered when stages 1
# and 2 produced no match.
#
# The critical section:
#   1. Re-read this chapter's CURRENT catalog inside the lock.
#   2. Run the match-only reducer against the FULL current catalog — not just
#      patterns added since the snapshot. This is the real second-chance guard:
#      it catches both patterns added concurrently by other workers AND patterns
#      that stage-1/stage-2 simply missed (their false negatives are the main
#      source of duplicate patterns).
#   3. If that reducer matches → join. Return.
#   4. Otherwise → insert the proposed pattern. On DuplicateKeyError, fall back
#      to join-by-slug (the namer may have echoed an existing slug, or a second
#      process raced us).
#   5. Either way, write the assignment.
#
# Mongo's unique index on (chapter, slug) is the last layer of defence.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposeOrJoinResult:
    outcome: Literal["created", "joined_existing", "joined_lock"]
    pattern_id: str
    confidence: float
    rationale: str
    decided_by: str


async def propose_or_join(
    *,
    question: CleanedQuestion,
    draft: PatternDraft,
    lock_mgr: ChapterLockManager,
    pattern_repo: PatternRepository,
    assignment_repo: AssignmentRepository,
    match_only_agent: MatchOnlyReducerAgent,
) -> ProposeOrJoinResult:
    chapter = question.chapter
    lock = await lock_mgr.for_chapter(chapter)

    async with lock:
        # 1. Re-read the chapter's CURRENT catalog inside the lock.
        latest = await pattern_repo.list_for_chapter(chapter)

        # 2. Second-chance match against the FULL catalog. This is what closes
        #    the duplicate hole: a stage-1/stage-2 miss against an existing
        #    pattern (or a pattern another worker just created) gets one more
        #    look before we mint a new one.
        if latest:
            redecision = await match_only_agent.run(question, latest)
            if redecision.verdict == "match" and redecision.pattern_id:
                await assignment_repo.upsert(
                    question_id=question.question_id,
                    pattern_id=redecision.pattern_id,
                    confidence=redecision.confidence,
                    rationale=redecision.evidence,
                    decided_by="match_only_lock",
                )
                await pattern_repo.increment_member_count(redecision.pattern_id)
                return ProposeOrJoinResult(
                    outcome="joined_lock",
                    pattern_id=redecision.pattern_id,
                    confidence=redecision.confidence,
                    rationale=redecision.evidence,
                    decided_by="match_only_lock",
                )

        # 3. Truly no match — create the pattern.
        try:
            new_pattern = await pattern_repo.create(
                chapter=chapter,
                canonical_question_id=question.question_id,
                draft=draft,
            )
            decided_by = "namer"
            outcome: Literal["created", "joined_existing", "joined_lock"] = "created"
            target_pid = new_pattern.pattern_id
        except DuplicateKeyError:
            # 4. Cross-process race lost. Join the now-existing pattern.
            existing = await pattern_repo.get_by_slug(chapter, draft.slug)
            if existing is None:
                # Wildly unlikely — duplicate raised but read doesn't see it.
                logger.error(
                    "DuplicateKeyError on (%s, %s) but get_by_slug returned None",
                    chapter, draft.slug,
                )
                raise
            decided_by = "namer_join_on_dup"
            outcome = "joined_existing"
            target_pid = existing.pattern_id
            await pattern_repo.increment_member_count(target_pid)

        await assignment_repo.upsert(
            question_id=question.question_id,
            pattern_id=target_pid,
            confidence=draft.confidence,
            rationale=draft.rationale,
            decided_by=decided_by,
        )
        return ProposeOrJoinResult(
            outcome=outcome,
            pattern_id=target_pid,
            confidence=draft.confidence,
            rationale=draft.rationale,
            decided_by=decided_by,
        )


# ---------------------------------------------------------------------------
# The pipeline — bundles every collaborator the per-question algorithm needs.
# ---------------------------------------------------------------------------


class Pipeline:
    def __init__(
        self,
        *,
        pattern_repo: PatternRepository,
        assignment_repo: AssignmentRepository,
        checkpoint_repo: CheckpointRepository,
        lock_mgr: ChapterLockManager,
        run_id: str,
    ) -> None:
        self.pattern_repo = pattern_repo
        self.assignment_repo = assignment_repo
        self.checkpoint_repo = checkpoint_repo
        self.lock_mgr = lock_mgr
        self.run_id = run_id

        self.stage1 = Stage1ChunkClassifierAgent()
        self.stage2 = Stage2ReducerAgent()
        self.match_only = MatchOnlyReducerAgent()
        self.namer = PatternNamerAgent()

    async def process(self, question: CleanedQuestion) -> str:
        """Return the pattern_id assigned to this question, or "" on failure."""
        # ── Step 1: snapshot catalog ─────────────────────────────────────
        patterns = await self.pattern_repo.list_for_chapter(question.chapter)
        patterns_by_id = {p.pattern_id: p for p in patterns}

        target_pattern_id: str = ""

        if patterns:
            # ── Step 2: chunk ───────────────────────────────────────────
            chunks = chunk_patterns(patterns, CHUNK_SIZE)

            # ── Step 3: stage-1 fan-out ─────────────────────────────────
            stage1_verdicts = await run_stage1_fanout(
                agent=self.stage1, question=question, chunks=chunks,
            )
            matches = [
                v for v in stage1_verdicts
                if v.verdict == "match"
                and v.pattern_id
                and v.confidence >= STAGE1_MIN_CONFIDENCE
            ]

            # ── Step 4: reduce ──────────────────────────────────────────
            winner_pid: str = ""
            winner_confidence = 0.0
            winner_evidence = ""
            winner_decided_by = ""

            if len(matches) == 1:
                v = matches[0]
                winner_pid = v.pattern_id or ""
                winner_confidence = v.confidence
                winner_evidence = v.evidence
                winner_decided_by = "stage1"
            elif len(matches) > 1:
                s2 = await self.stage2.run(question, matches, patterns_by_id)
                if (
                    s2.verdict == "match"
                    and s2.pattern_id
                    and s2.confidence >= STAGE2_MIN_CONFIDENCE
                ):
                    winner_pid = s2.pattern_id
                    winner_confidence = s2.confidence
                    winner_evidence = s2.evidence
                    winner_decided_by = "stage2"

            if winner_pid:
                # ── Step 6 (match path): upsert assignment ──────────────
                await self.assignment_repo.upsert(
                    question_id=question.question_id,
                    pattern_id=winner_pid,
                    confidence=winner_confidence,
                    rationale=winner_evidence,
                    decided_by=winner_decided_by,
                )
                await self.pattern_repo.increment_member_count(winner_pid)
                target_pattern_id = winner_pid
                metrics.record_outcome("matched")
                logger.info(
                    "Question %s → %s (matched via %s, conf=%.2f)",
                    question.question_id, winner_pid, winner_decided_by,
                    winner_confidence,
                )

        if not target_pattern_id:
            # ── Step 5: propose-or-join (under chapter lock) ────────────
            # Namer sees the snapshot catalog so it can reuse an existing
            # pattern (echo its slug) instead of minting a near-duplicate.
            draft = await self.namer.run(question, patterns)
            if draft is None:
                logger.warning(
                    "Namer returned None for %s; skipping assignment.",
                    question.question_id,
                )
                return ""

            result = await propose_or_join(
                question=question,
                draft=draft,
                lock_mgr=self.lock_mgr,
                pattern_repo=self.pattern_repo,
                assignment_repo=self.assignment_repo,
                match_only_agent=self.match_only,
            )
            target_pattern_id = result.pattern_id
            metrics.record_outcome(result.outcome)
            logger.info(
                "Question %s → %s (outcome=%s)",
                question.question_id, target_pattern_id, result.outcome,
            )

        # ── Step 7: checkpoint ──────────────────────────────────────────
        await self.checkpoint_repo.mark_processed(
            question_id=question.question_id, run_id=self.run_id,
        )
        return target_pattern_id


async def process_one_question(pipeline: Pipeline, question: CleanedQuestion) -> str:
    """Convenience wrapper for jobs/. Catches and logs unexpected errors so one
    bad question doesn't kill the whole run."""
    try:
        return await pipeline.process(question)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline crashed on %s: %s", question.question_id, exc)
        return ""


# ---------------------------------------------------------------------------
# Semaphore-bounded async worker pool over the question stream. One process,
# N async workers, each running pipeline.process.
# ---------------------------------------------------------------------------


async def run_worker_pool(
    *,
    questions: AsyncIterator[CleanedQuestion],
    worker: Callable[[CleanedQuestion], Awaitable[str]],
    concurrency: int,
    on_progress: Callable[[CleanedQuestion, str], None] | None = None,
) -> int:
    """Iterate the async question stream, processing up to `concurrency` at a
    time. Returns the count of questions successfully processed."""
    sem = asyncio.Semaphore(concurrency)
    in_flight: set[asyncio.Task] = set()
    processed = 0

    async def _wrap(q: CleanedQuestion) -> None:
        nonlocal processed
        async with sem:
            try:
                pid = await worker(q)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Worker crashed for %s: %s", q.question_id, exc)
                pid = ""
            processed += 1
            if on_progress:
                try:
                    on_progress(q, pid)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("on_progress callback raised: %s", exc)

    async for q in questions:
        task = asyncio.create_task(_wrap(q))
        in_flight.add(task)
        task.add_done_callback(in_flight.discard)
        # Don't let in_flight balloon unbounded — wait if too many queued.
        while len(in_flight) >= concurrency * 2:
            done, _ = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)

    if in_flight:
        await asyncio.gather(*in_flight, return_exceptions=True)

    return processed
