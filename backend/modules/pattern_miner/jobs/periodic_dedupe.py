"""Periodic dedupe pass — pairwise merge within each chapter.

The live pipeline leans toward joining existing patterns, but a cold start (or
concurrent workers creating before any catalog exists) can still mint two
patterns for the same trick. This weekly pass is the backstop that collapses
those; the merge mechanics live in `modules.pattern_miner.dedupe`.

SAFETY: destructive (deletes patterns). Defaults to a DRY RUN that only logs
what it would merge. Pass --apply to actually perform the merges.

Usage (from the backend root):
    python -m modules.pattern_miner.jobs.periodic_dedupe            # dry run (log only)
    python -m modules.pattern_miner.jobs.periodic_dedupe --apply    # perform merges
    python -m modules.pattern_miner.jobs.periodic_dedupe --chapter "Trigonometric Ratios" --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from modules.pattern_miner.agents import PatternDedupeAgent
from modules.pattern_miner.db import close_client, ensure_indexes, get_pattern_miner_db
from modules.pattern_miner.dedupe import dedupe_chapter
from modules.pattern_miner.ids import generate_run_id
from modules.pattern_miner.jobs import configure_job_logging
from modules.pattern_miner.repository import AssignmentRepository, PatternRepository

logger = logging.getLogger(__name__)


async def _amain(args: argparse.Namespace) -> None:
    run_id = generate_run_id()
    configure_job_logging(run_id=run_id)
    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("periodic_dedupe start run_id=%s mode=%s", run_id, mode)

    db = get_pattern_miner_db()
    if args.apply:
        await ensure_indexes(db)
    try:
        pattern_repo = PatternRepository(db)
        assignment_repo = AssignmentRepository(db)
        agent = PatternDedupeAgent()

        if args.chapter:
            chapters = [args.chapter]
        else:
            chapters = await pattern_repo.distinct_chapters()

        total_merges = 0
        for chap in chapters:
            merges = await dedupe_chapter(
                chap, pattern_repo, assignment_repo, agent, apply=args.apply,
            )
            total_merges += merges
            if merges:
                logger.info("Chapter %s: %d merge(s)", chap, merges)

        verb = "merged" if args.apply else "would merge"
        logger.info(
            "periodic_dedupe done run_id=%s mode=%s — %s %d pattern(s) across %d chapter(s)",
            run_id, mode, verb, total_merges, len(chapters),
        )
        if not args.apply and total_merges:
            logger.info("Re-run with --apply to perform these merges.")
    finally:
        await close_client()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform merges. Without this flag the job only logs "
             "what it would merge (safe dry run).",
    )
    parser.add_argument(
        "--chapter",
        default=None,
        help="Limit dedupe to a single chapter (default: all chapters).",
    )
    args = parser.parse_args()
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
