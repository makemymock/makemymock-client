"""Unit tests for the dedupe merge — no DB, no LLM.

Exercises dedupe_chapter with fake repos + a fake agent so the merge mechanics
(keeper selection, re-point, delete, count recompute, no double merge) are
verified deterministically.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from modules.pattern_miner.dedupe import dedupe_chapter
from modules.pattern_miner.domain import Pattern, PatternSignature


def _pattern(pid: str, name: str, member_count: int) -> Pattern:
    now = datetime.now(timezone.utc)
    return Pattern(
        pattern_id=pid,
        chapter="trig",
        slug=pid,
        name=name,
        description="d",
        signature=PatternSignature(trigger="t", technique="m", why_it_works="w"),
        canonical_question_id="q",
        member_count=member_count,
        created_at=now,
        updated_at=now,
    )


class FakePatternRepo:
    def __init__(self, patterns):
        # preserve insertion order = created_at order
        self._order = [p.pattern_id for p in patterns]
        self._p = {p.pattern_id: p for p in patterns}
        self.deleted: list[str] = []
        self.set_counts: dict[str, int] = {}

    async def list_for_chapter(self, chapter):
        return [self._p[pid] for pid in self._order if pid in self._p]

    async def delete(self, pid):
        existed = pid in self._p
        self._p.pop(pid, None)
        self.deleted.append(pid)
        return existed

    async def set_member_count(self, pid, count):
        self.set_counts[pid] = count


class FakeAssignmentRepo:
    def __init__(self, assignments):
        self.assignments = assignments  # list of {question_id, pattern_id}

    async def repoint(self, *, from_pattern_id, to_pattern_id):
        n = 0
        for a in self.assignments:
            if a["pattern_id"] == from_pattern_id:
                a["pattern_id"] = to_pattern_id
                n += 1
        return n

    async def count_for_pattern(self, pid):
        return sum(1 for a in self.assignments if a["pattern_id"] == pid)


class FakeAgent:
    def __init__(self, same_pairs):
        self.same_pairs = same_pairs  # set[frozenset[str]]

    async def are_same(self, a, b):
        if frozenset({a.pattern_id, b.pattern_id}) in self.same_pairs:
            return True, 0.9, "same trick"
        return False, 0.1, "different"


@pytest.mark.asyncio
async def test_merge_collapses_duplicate_into_larger():
    patterns = [_pattern("p1", "R-method", 5), _pattern("p2", "amplitude", 2),
                _pattern("p3", "half-angle", 1)]
    assignments = (
        [{"question_id": f"a{i}", "pattern_id": "p1"} for i in range(5)]
        + [{"question_id": f"b{i}", "pattern_id": "p2"} for i in range(2)]
        + [{"question_id": "c0", "pattern_id": "p3"}]
    )
    prepo = FakePatternRepo(patterns)
    arepo = FakeAssignmentRepo(assignments)
    agent = FakeAgent({frozenset({"p1", "p2"})})

    merges = await dedupe_chapter("trig", prepo, arepo, agent, apply=True)

    assert merges == 1
    # loser deleted, keeper kept
    assert prepo.deleted == ["p2"]
    # all p2 assignments re-pointed to p1
    assert not any(a["pattern_id"] == "p2" for a in assignments)
    assert sum(1 for a in assignments if a["pattern_id"] == "p1") == 7
    # keeper count recomputed authoritatively from assignments
    assert prepo.set_counts["p1"] == 7
    # untouched pattern survives
    assert "p3" not in prepo.deleted


@pytest.mark.asyncio
async def test_dry_run_changes_nothing():
    patterns = [_pattern("p1", "R-method", 5), _pattern("p2", "amplitude", 2)]
    assignments = [{"question_id": "a0", "pattern_id": "p2"}]
    prepo = FakePatternRepo(patterns)
    arepo = FakeAssignmentRepo(assignments)
    agent = FakeAgent({frozenset({"p1", "p2"})})

    merges = await dedupe_chapter("trig", prepo, arepo, agent, apply=False)

    assert merges == 1  # it reports what it WOULD merge
    assert prepo.deleted == []  # but deletes nothing
    assert assignments[0]["pattern_id"] == "p2"  # and re-points nothing
    assert prepo.set_counts == {}


@pytest.mark.asyncio
async def test_already_merged_pattern_not_reused():
    # p1≈p2 and p2≈p3, but once p2 is merged into p1 it must not be compared again.
    patterns = [_pattern("p1", "a", 3), _pattern("p2", "b", 2), _pattern("p3", "c", 1)]
    assignments = [
        {"question_id": "x", "pattern_id": "p2"},
        {"question_id": "y", "pattern_id": "p3"},
    ]
    prepo = FakePatternRepo(patterns)
    arepo = FakeAssignmentRepo(assignments)
    agent = FakeAgent({frozenset({"p1", "p2"}), frozenset({"p2", "p3"})})

    merges = await dedupe_chapter("trig", prepo, arepo, agent, apply=True)

    # p2 merges into p1. p3 is only "same" as the now-gone p2, so it survives.
    assert merges == 1
    assert prepo.deleted == ["p2"]
    assert "p3" not in prepo.deleted


@pytest.mark.asyncio
async def test_tie_breaks_to_older_pattern():
    # equal member_count → keep the older (earlier in created_at order = p1)
    patterns = [_pattern("p1", "older", 2), _pattern("p2", "newer", 2)]
    assignments = [{"question_id": "z", "pattern_id": "p2"}]
    prepo = FakePatternRepo(patterns)
    arepo = FakeAssignmentRepo(assignments)
    agent = FakeAgent({frozenset({"p1", "p2"})})

    await dedupe_chapter("trig", prepo, arepo, agent, apply=True)

    assert prepo.deleted == ["p2"]  # newer dropped, older kept


class _StubRealRepo:
    """Stand-in for the real PatternRepository the in-memory wrapper delegates
    to on first touch. Always reports an empty chapter."""

    async def list_for_chapter(self, chapter):
        return []


@pytest.mark.asyncio
async def test_inmemory_repos_satisfy_dedupe_interface():
    # Proves the dry-run in-memory repos work end-to-end with dedupe_chapter,
    # which is what `classify_all --dry-run --dedupe` relies on.
    from modules.pattern_miner.domain import PatternDraft
    from modules.pattern_miner.dry_run import (
        InMemoryAssignmentRepository,
        InMemoryPatternRepository,
    )

    prepo = InMemoryPatternRepository(_StubRealRepo())
    arepo = InMemoryAssignmentRepository()

    def _draft(slug, name):
        return PatternDraft(
            slug=slug, name=name, description="d",
            signature=PatternSignature(trigger="t", technique="m", why_it_works="w"),
            confidence=0.7, rationale="r",
        )

    # Build a catalog the way the pipeline would, with assignments.
    for slug, name, qids in [
        ("p-a", "R-method", ["q1", "q2", "q3"]),
        ("p-b", "amplitude", ["q4", "q5"]),
        ("p-c", "half-angle", ["q6"]),
    ]:
        pat = await prepo.create(chapter="trig", canonical_question_id=qids[0], draft=_draft(slug, name))
        for q in qids:
            await arepo.upsert(question_id=q, pattern_id=pat.pattern_id,
                               confidence=0.7, rationale="r", decided_by="namer")
            await prepo.increment_member_count(pat.pattern_id)

    # p-a ≈ p-b (same trick); p-c distinct.
    pa = (await prepo.get_by_slug("trig", "p-a")).pattern_id
    pb = (await prepo.get_by_slug("trig", "p-b")).pattern_id
    agent = FakeAgent({frozenset({pa, pb})})

    merges = await dedupe_chapter("trig", prepo, arepo, agent, apply=True)

    assert merges == 1
    survivors = await prepo.list_for_chapter("trig")
    assert len(survivors) == 2  # 3 → 2
    # p-b folded into p-a; all its assignments re-pointed
    assert await arepo.count_for_pattern(pb) == 0
    assert await arepo.count_for_pattern(pa) == 5  # 3 + 2
    keeper = next(p for p in survivors if p.pattern_id == pa)
    assert keeper.member_count == 5  # recomputed authoritatively
