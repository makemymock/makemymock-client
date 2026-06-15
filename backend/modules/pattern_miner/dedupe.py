"""The pairwise dedupe merge over a single chapter.

The live pipeline leans toward joining existing patterns, but a cold start (or
concurrent workers creating before any catalog exists) can still mint two
patterns for the same trick — question B proposes a pattern before question A's
identical pattern exists, so neither could have matched the other. This pass is
the backstop that collapses those.

Strategy: compare every still-live pair via the PatternDedupeAgent (gated by the
cheap local pre-filter). If they're the same trick (confidence ≥
DEDUPE_MIN_CONFIDENCE), merge the smaller (by member_count) into the larger:
  1. Re-point every assignment from loser → keeper.
  2. Delete the loser pattern.
  3. Recompute the keeper's member_count from the assignment collection
     (authoritative — don't trust the running counter).

Lives in its own module because three callers share it: the weekly job, the
dry-run preview, and the unit tests. It's intentionally O(n²) per chapter; the
pre-filter is what keeps the LLM-call count down.
"""

from __future__ import annotations

import logging

from modules.pattern_miner.constants import (
    DEDUPE_MIN_CONFIDENCE,
    DEDUPE_PREFILTER_MIN_SIM,
)
from modules.pattern_miner.prefilter import PatternSimilarity

logger = logging.getLogger(__name__)


async def dedupe_chapter(
    chapter: str,
    pattern_repo,
    assignment_repo,
    agent,
    *,
    apply: bool,
) -> int:
    """Returns the number of merges performed (or, in dry-run, would perform).

    The repo / agent params are duck-typed: the job passes the real
    repositories, the dry-run passes the in-memory ones, and the tests pass
    fakes — all that matters is the handful of methods used below.
    """
    patterns = await pattern_repo.list_for_chapter(chapter)
    if len(patterns) < 2:
        return 0

    # Cheap local pre-filter: only pairs that look textually similar reach the
    # (expensive) dedupe LLM. Turns O(n^2) LLM calls into O(n^2) cheap math +
    # O(candidates) LLM calls. See prefilter.py.
    sim = PatternSimilarity(patterns)

    # Live member counts, kept in sync as we merge (Pattern is frozen, so we
    # track counts in a dict instead of mutating the objects).
    counts = {p.pattern_id: p.member_count for p in patterns}
    merged_away: set[str] = set()
    merges = 0
    compared = 0
    prefiltered = 0

    for i in range(len(patterns)):
        a = patterns[i]
        if a.pattern_id in merged_away:
            continue
        for j in range(i + 1, len(patterns)):
            b = patterns[j]
            if b.pattern_id in merged_away:
                continue

            if sim.score(a, b) < DEDUPE_PREFILTER_MIN_SIM:
                prefiltered += 1
                continue

            compared += 1
            same, conf, reason = await agent.are_same(a, b)
            if not same or conf < DEDUPE_MIN_CONFIDENCE:
                continue

            # Keep the larger pattern; tie → keep the older one (patterns are
            # sorted by created_at asc, so `a` is older than `b`).
            if counts.get(a.pattern_id, 0) >= counts.get(b.pattern_id, 0):
                keep, drop = a, b
            else:
                keep, drop = b, a

            logger.info(
                "Merge%s: %s '%s' (%d) → %s '%s' (%d) in %s [conf=%.2f] %s",
                "" if apply else " [DRY-RUN]",
                drop.pattern_id, drop.name, counts.get(drop.pattern_id, 0),
                keep.pattern_id, keep.name, counts.get(keep.pattern_id, 0),
                chapter, conf, reason,
            )

            if apply:
                moved = await assignment_repo.repoint(
                    from_pattern_id=drop.pattern_id,
                    to_pattern_id=keep.pattern_id,
                )
                await pattern_repo.delete(drop.pattern_id)
                new_count = await assignment_repo.count_for_pattern(keep.pattern_id)
                await pattern_repo.set_member_count(keep.pattern_id, new_count)
                counts[keep.pattern_id] = new_count
                logger.info(
                    "  repointed %d assignment(s); %s now has %d member(s)",
                    moved, keep.pattern_id, new_count,
                )
            else:
                # Dry-run: estimate the merged count so subsequent keep/drop
                # decisions in this chapter use a realistic size.
                counts[keep.pattern_id] = (
                    counts.get(keep.pattern_id, 0) + counts.get(drop.pattern_id, 0)
                )

            merged_away.add(drop.pattern_id)
            merges += 1

            if drop.pattern_id == a.pattern_id:
                # `a` was merged into `b`; stop using `a` as a keeper.
                break

    total_considered = compared + prefiltered
    if total_considered:
        logger.info(
            "Chapter %s: %d pattern(s), %d LLM compare(s), %d pair(s) skipped "
            "by pre-filter (%.0f%% saved)",
            chapter, len(patterns), compared, prefiltered,
            100.0 * prefiltered / total_considered,
        )

    return merges
