"""Tests for the dedupe pre-filter (prefilter.py) and its integration into
dedupe_chapter. No DB, no LLM — fully deterministic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from modules.pattern_miner.dedupe import dedupe_chapter
from modules.pattern_miner.domain import Pattern, PatternSignature
from modules.pattern_miner.prefilter import PatternSimilarity


def _pat(pid, name, trigger, technique, why, desc="", members=1) -> Pattern:
    now = datetime.now(timezone.utc)
    return Pattern(
        pattern_id=pid,
        chapter="trig",
        slug=pid,
        name=name,
        description=desc or name,
        signature=PatternSignature(trigger=trigger, technique=technique, why_it_works=why),
        canonical_question_id="q",
        member_count=members,
        created_at=now,
        updated_at=now,
    )


# Two patterns that are clearly the same trick (R-method / amplitude family).
A = _pat(
    "a", "Combine sine and cosine into single amplitude",
    "expression has a sin x plus b cos x",
    "rewrite as R sin(x plus phi) with amplitude R",
    "a linear combination of sine and cosine is one sinusoid",
)
B = _pat(
    "b", "Amplitude bound for linear sine cosine combo",
    "find maximum or minimum of a sin x plus b cos x",
    "amplitude equals sqrt of a squared plus b squared so range is plus minus R",
    "the single sinusoid has amplitude R",
)
# A lexically unrelated pattern (different technique, different words).
C = _pat(
    "c", "Logarithm power rule brings exponent down",
    "logarithm of a quantity raised to a power",
    "move the exponent out as a multiplying coefficient",
    "logarithm is the inverse of exponentiation",
)


def test_same_trick_scores_higher_than_unrelated():
    sim = PatternSimilarity([A, B, C])
    assert sim.score(A, B) > sim.score(A, C)
    assert sim.score(A, B) > sim.score(B, C)


def test_same_trick_clears_threshold_unrelated_does_not():
    sim = PatternSimilarity([A, B, C])
    assert sim.score(A, B) >= 0.20
    assert sim.score(A, C) < 0.20
    assert sim.score(B, C) < 0.20


def test_identical_patterns_score_near_one():
    a2 = _pat("a2", A.name, A.signature.trigger, A.signature.technique,
              A.signature.why_it_works, A.description)
    sim = PatternSimilarity([A, a2])
    assert sim.score(A, a2) > 0.9


def test_idf_discounts_words_common_to_all_patterns():
    # All three share "cosine"; only A/B share the distinctive "amplitude".
    # So the universal word must not, by itself, make everything look similar.
    p1 = _pat("p1", "cosine amplitude method", "cosine amplitude", "cosine amplitude", "cosine amplitude")
    p2 = _pat("p2", "cosine amplitude trick", "cosine amplitude", "cosine amplitude", "cosine amplitude")
    p3 = _pat("p3", "cosine factoring split", "cosine factoring", "cosine factoring", "cosine factoring")
    sim = PatternSimilarity([p1, p2, p3])
    # p1/p2 share the rare "amplitude"; p1/p3 share only the universal "cosine".
    assert sim.score(p1, p2) > sim.score(p1, p3)


class SpyAgent:
    """Records every pair the dedupe LLM is asked about; never merges."""

    def __init__(self):
        self.asked: list[frozenset] = []

    async def are_same(self, a, b):
        self.asked.append(frozenset({a.pattern_id, b.pattern_id}))
        return False, 0.0, "spy"


class _PRepo:
    def __init__(self, patterns):
        self._order = [p.pattern_id for p in patterns]
        self._p = {p.pattern_id: p for p in patterns}

    async def list_for_chapter(self, chapter):
        return [self._p[i] for i in self._order if i in self._p]


class _ARepo:
    async def repoint(self, **kw):  # pragma: no cover - not reached (no merges)
        return 0

    async def count_for_pattern(self, pid):  # pragma: no cover
        return 0


@pytest.mark.asyncio
async def test_prefilter_skips_unrelated_pairs_in_dedupe():
    spy = SpyAgent()
    await dedupe_chapter("trig", _PRepo([A, B, C]), _ARepo(), spy, apply=True)
    # Of the 3 possible pairs (A-B, A-C, B-C) only the similar A-B should reach
    # the LLM; the two unrelated pairs are pre-filtered out.
    assert frozenset({"a", "b"}) in spy.asked
    assert frozenset({"a", "c"}) not in spy.asked
    assert frozenset({"b", "c"}) not in spy.asked
    assert len(spy.asked) == 1
