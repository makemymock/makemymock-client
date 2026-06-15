"""Main classification pass — runs the pipeline over every PYQ that hasn't been
processed yet.

Usage (from the backend root):
    python -m modules.pattern_miner.jobs.classify_all [--chapter <name>] [--subject <name>]
                                                       [--limit <n>] [--dry-run] [--verbose] [--dedupe]

--dry-run     do NOT touch the DB for writes. Reads still happen (so we see
              existing patterns if any), but every pattern/assignment/checkpoint
              write goes to an in-memory store. Patterns created during the run
              ARE visible to subsequent questions in the same run — so matching
              is exercised end-to-end without side effects.
--verbose     pretty-print each question's decision path. Implied by --dry-run.
--dedupe      after a --dry-run, preview the merge over the in-memory catalog.

When --dry-run is set and --limit is omitted, defaults to --limit 100.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any, AsyncIterator, Optional

from modules.pattern_miner.constants import WORKER_COUNT
from modules.pattern_miner.db import (
    close_client,
    ensure_indexes,
    get_pattern_miner_db,
)
from modules.pattern_miner.domain import CleanedQuestion
from modules.pattern_miner.dry_run import (
    InMemoryAssignmentRepository,
    InMemoryCheckpointRepository,
    InMemoryPatternRepository,
)
from modules.pattern_miner.ids import generate_run_id
from modules.pattern_miner.jobs import configure_job_logging
from modules.pattern_miner.metrics import metrics
from modules.pattern_miner.pipeline import (
    ChapterLockManager,
    Pipeline,
    process_one_question,
    run_worker_pool,
)
from modules.pattern_miner.preprocessing import normalize_raw_question, should_skip
from modules.pattern_miner.repository import (
    AssignmentRepository,
    CheckpointRepository,
    PatternRepository,
    QuestionRepository,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pretty verbose printer
# ---------------------------------------------------------------------------


class _VerbosePrinter:
    """Streams a one-screen summary per question.

    In dry-run mode this is wired to look up the just-written assignment in the
    in-memory AssignmentRepository so it can show the decided_by + rationale.
    """

    def __init__(
        self,
        in_mem_assignments: InMemoryAssignmentRepository | None,
        in_mem_patterns: InMemoryPatternRepository | None = None,
    ) -> None:
        self._assignments = in_mem_assignments
        self._patterns = in_mem_patterns
        self._counts = {
            "stage1": 0,
            "stage2": 0,
            "match_only_lock": 0,
            "namer": 0,
            "namer_join_on_dup": 0,
            "skipped": 0,
        }
        self._n = 0

    def on_question(self, q: CleanedQuestion, pattern_id: str) -> None:
        self._n += 1
        chap = q.chapter[:32]
        topic = (q.topic or "")[:32]
        head = f"\n[{self._n:>3}] {q.question_id}  {chap} / {topic}  (year {q.year})"
        snippet = (q.question_text or "").strip().replace("\n", " ")[:140]

        if not pattern_id:
            self._counts["skipped"] += 1
            print(f"{head}\n     → SKIPPED (pipeline returned no pattern)")
            print(f"     Q: {snippet}")
            return

        decided_by, confidence, rationale = self._lookup(q.question_id)
        if decided_by in self._counts:
            self._counts[decided_by] += 1

        outcome_label = {
            "stage1": "MATCH (stage-1 single winner)",
            "stage2": "MATCH (stage-2 reducer)",
            "match_only_lock": "JOINED existing pattern (full-catalog re-check inside lock)",
            "namer": "CREATED new pattern",
            "namer_join_on_dup": "JOINED existing (slug race)",
        }.get(decided_by, decided_by or "unknown")

        pattern_name = self._name_for(pattern_id)
        print(f"{head}")
        print(f"     decision: {outcome_label}  (conf={confidence:.2f})")
        print(f"     pattern: {pattern_name or '(name unavailable)'}")
        print(f"     pattern_id: {pattern_id}")
        print(f"     rationale: {rationale[:200]}")
        print(f"     Q: {snippet}")

    def _name_for(self, pattern_id: str) -> str:
        if self._patterns is None or not pattern_id:
            return ""
        return self._patterns.name_for(pattern_id) or ""

    def _lookup(self, question_id: str) -> tuple[str, float, str]:
        if self._assignments is None:
            return "", 0.0, ""
        for a in reversed(self._assignments.assignments):
            if a["question_id"] == question_id:
                return a["decided_by"], a["confidence"], a["rationale"]
        return "", 0.0, ""

    def final_summary(
        self,
        *,
        processed: int,
        patterns_created: int,
        chapter_breakdown: dict[str, int] | None = None,
        created_patterns: list | None = None,
    ) -> None:
        bar = "=" * 60
        print(f"\n{bar}\nDRY-RUN SUMMARY\n{bar}")
        print(f"Questions processed: {processed}")
        print(f"Patterns created:    {patterns_created}")
        print("Decisions by path:")
        for k, v in self._counts.items():
            print(f"  {k:<22}: {v}")
        if chapter_breakdown:
            print("\nNew patterns by chapter:")
            for chap, n in sorted(chapter_breakdown.items(), key=lambda x: -x[1]):
                print(f"  {chap[:40]:<40} {n}")
        if created_patterns:
            # List the actual pattern names — the quickest way to eyeball
            # whether the catalog is over-fragmenting into near-duplicates.
            print("\nNew pattern names (watch for near-duplicates):")
            by_chapter: dict[str, list[str]] = {}
            for p in created_patterns:
                by_chapter.setdefault(p.chapter, []).append(p.name)
            for chap in sorted(by_chapter):
                print(f"  {chap}:")
                for nm in by_chapter[chap]:
                    print(f"    - {nm}")
        print(f"\nMetrics: {metrics.snapshot()}")
        print(bar)


# ---------------------------------------------------------------------------
# Question stream
# ---------------------------------------------------------------------------


async def _question_stream(
    question_repo: QuestionRepository,
    *,
    chapter: Optional[str],
    subject: Optional[str],
    skip_ids: set[str],
    limit: Optional[int],
) -> AsyncIterator[CleanedQuestion]:
    yielded = 0
    async for raw in question_repo.iterate(
        chapter=chapter, subject=subject, skip_question_ids=skip_ids,
    ):
        skip, reason = should_skip(raw)
        if skip:
            logger.debug("Skipping %s — %s", raw.get("question_id"), reason)
            continue
        yield normalize_raw_question(raw)
        yielded += 1
        if limit and yielded >= limit:
            return


# ---------------------------------------------------------------------------
# In-memory dedupe preview (dry-run only)
# ---------------------------------------------------------------------------


async def _dryrun_dedupe(
    in_mem_patterns: InMemoryPatternRepository,
    in_mem_assignments: InMemoryAssignmentRepository,
) -> None:
    """Run the dedupe merge over the in-memory catalog this dry-run built, so
    you can see the collapse without writing to Mongo first.

    O(n²) dedupe LLM calls per chapter — keep --limit / --chapter small."""
    from modules.pattern_miner.agents import PatternDedupeAgent
    from modules.pattern_miner.dedupe import dedupe_chapter

    agent = PatternDedupeAgent()
    chapters = await in_mem_patterns.distinct_chapters()

    async def _total() -> int:
        n = 0
        for c in chapters:
            n += len(await in_mem_patterns.list_for_chapter(c))
        return n

    before = await _total()
    bar = "=" * 60
    print(f"\n{bar}\nIN-MEMORY DEDUPE PREVIEW\n{bar}")
    print(f"Patterns before dedupe: {before}")

    total_merges = 0
    for chap in chapters:
        total_merges += await dedupe_chapter(
            chap, in_mem_patterns, in_mem_assignments, agent, apply=True,
        )

    after = before - total_merges
    print(f"Merges performed:       {total_merges}")
    print(f"Patterns after dedupe:  {after}")
    survivors: dict[str, list[str]] = {}
    for chap in await in_mem_patterns.distinct_chapters():
        for p in await in_mem_patterns.list_for_chapter(chap):
            survivors.setdefault(chap, []).append(f"{p.name} ({p.member_count})")
    print("\nSurviving patterns (name (members)):")
    for chap in sorted(survivors):
        print(f"  {chap}:")
        for nm in survivors[chap]:
            print(f"    - {nm}")
    print(bar)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _load_processed_ids(repo: CheckpointRepository) -> set[str]:
    ids = await repo.list_processed_ids()
    logger.info("Resume: %d question_ids already processed", len(ids))
    return ids


async def _amain(args: argparse.Namespace) -> None:
    run_id = generate_run_id()
    configure_job_logging(run_id=run_id)
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    logger.info("classify_all start run_id=%s mode=%s", run_id, mode)

    # The miner's data lives on the PYQ cluster (see modules/pattern_miner/db.py).
    # Live runs ensure indexes up front; a dry-run reads only and writes nothing
    # (pattern/assignment/checkpoint writes go to the in-memory repos below).
    db = get_pattern_miner_db()
    if not args.dry_run:
        await ensure_indexes(db)
    try:
        question_repo = QuestionRepository(db)

        # ── Repos: real or in-memory ────────────────────────────────────────
        pattern_repo: Any
        assignment_repo: Any
        checkpoint_repo: Any
        in_mem_assignments: InMemoryAssignmentRepository | None = None
        in_mem_patterns: InMemoryPatternRepository | None = None

        if args.dry_run:
            in_mem_patterns = InMemoryPatternRepository(PatternRepository(db))
            in_mem_assignments = InMemoryAssignmentRepository()
            pattern_repo = in_mem_patterns
            assignment_repo = in_mem_assignments
            checkpoint_repo = InMemoryCheckpointRepository()
        else:
            pattern_repo = PatternRepository(db)
            assignment_repo = AssignmentRepository(db)
            checkpoint_repo = CheckpointRepository(db)

        lock_mgr = ChapterLockManager()
        pipeline = Pipeline(
            pattern_repo=pattern_repo,
            assignment_repo=assignment_repo,
            checkpoint_repo=checkpoint_repo,
            lock_mgr=lock_mgr,
            run_id=run_id,
        )

        skip_ids = (
            set() if args.dry_run else await _load_processed_ids(checkpoint_repo)
        )

        # ── Limit defaulting ────────────────────────────────────────────────
        effective_limit = args.limit
        if args.dry_run and effective_limit is None:
            effective_limit = 100

        stream = _question_stream(
            question_repo,
            chapter=args.chapter,
            subject=args.subject,
            skip_ids=skip_ids,
            limit=effective_limit,
        )

        # ── Verbose printer ─────────────────────────────────────────────────
        verbose = args.verbose or args.dry_run
        printer = (
            _VerbosePrinter(in_mem_assignments, in_mem_patterns) if verbose else None
        )

        async def worker(q: CleanedQuestion) -> str:
            return await process_one_question(pipeline, q)

        def on_progress(q: CleanedQuestion, pid: str) -> None:
            if printer:
                printer.on_question(q, pid)

        print(
            f"\nRunning {mode}: chapter={args.chapter or 'ALL'} "
            f"subject={args.subject or 'ALL'} limit={effective_limit or 'UNLIMITED'} "
            f"workers={WORKER_COUNT}\n"
        )
        processed = await run_worker_pool(
            questions=stream,
            worker=worker,
            concurrency=WORKER_COUNT,
            on_progress=on_progress,
        )

        if printer:
            chapter_breakdown: dict[str, int] = {}
            if in_mem_patterns is not None:
                for p in in_mem_patterns.created:
                    chapter_breakdown[p.chapter] = chapter_breakdown.get(p.chapter, 0) + 1
            printer.final_summary(
                processed=processed,
                patterns_created=len(in_mem_patterns.created) if in_mem_patterns else 0,
                chapter_breakdown=chapter_breakdown,
                created_patterns=in_mem_patterns.created if in_mem_patterns else [],
            )

        # ── Optional in-memory dedupe pass (dry-run only) ───────────────────
        # Lets you preview the merge over the catalog this run just built,
        # without touching Mongo. WARNING: O(n²) LLM calls per chapter.
        if args.dry_run and args.dedupe and in_mem_patterns is not None:
            await _dryrun_dedupe(in_mem_patterns, in_mem_assignments)

        logger.info(
            "classify_all done run_id=%s mode=%s processed=%d metrics=%s",
            run_id, mode, processed, metrics.snapshot(),
        )
    finally:
        await close_client()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", default=None)
    parser.add_argument("--subject", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write to the DB. Use in-memory repos so the run is "
             "side-effect-free but still exercises matching/joining/proposing.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Pretty-print each question's decision. Implied by --dry-run.",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="After a --dry-run, run the dedupe merge over the in-memory "
             "catalog to preview the collapse (O(n^2) extra LLM calls; "
             "keep --limit/--chapter small).",
    )
    args = parser.parse_args()
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
