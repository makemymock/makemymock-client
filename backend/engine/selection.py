"""Layer 5 — question selection (atom-based).

Given:
  - the user's existing attempts on each topic
  - a per-topic quota of how many questions to serve (from Layer 3)
  - a per-topic difficulty mix (from Layer 4)
  - the available question pool for each topic

…choose the actual question IDs. Constraints:

  1. ROTATION: prefer questions never attempted; fall back to "recyclable"
     (attempted > 30 days ago); fall back to "recent" only if desperate.
  2. UNIQUENESS: a question may be tagged to multiple topics, but must
     appear at most once in the test.
  3. DIFFICULTY MIX: respect Layer 4's weights when the pool permits;
     fall back to other difficulties biased toward the primary when not.
  4. CAPACITY: if a topic can't supply its quota, redistribute the shortage
     to topics with surplus, preferring higher-priority topics.
  5. ATOMICITY: a passage of N sub-questions is one indivisible "atom" —
     either all N come together, or none. Atoms are size-aware: an atom
     is only considered when its size fits in the remaining topic budget,
     so the test never overshoots.

This mirrors `fetch_questions_for_all_topics_batch` in services_async.py:517,
plus an atom layer that's our local enhancement over Phase backend.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from engine.config import RECYCLE_THRESHOLD_DAYS
from engine.models import Attempt, PriorityScore, Question
from engine.progression import progression_mix


# ---------------------------------------------------------------------------
# Atom
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Atom:
    """A pickable unit.

    Either a single standalone question (size 1) or a passage group of N
    sub-questions (size N, all-or-nothing). The atom carries its
    difficulty (a passage's difficulty is the parent's, inherited by all
    siblings — homogeneous by construction in our schema).
    """
    size: int
    difficulty: str
    questions: tuple[Question, ...]  # in display order (sub-index for passages)

    @property
    def lead_id(self) -> int:
        return self.questions[0].id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bucket_attempted_questions(
    attempts_for_topic: Iterable[Attempt],
    now: datetime,
) -> tuple[set[int], set[int]]:
    """Split a topic's attempted-question IDs into (recyclable, recent)."""
    recycle_cutoff = now - timedelta(days=RECYCLE_THRESHOLD_DAYS)
    recent_ids: set[int] = set()
    recyclable_ids: set[int] = set()
    by_qid: dict[int, datetime] = {}
    for a in attempts_for_topic:
        prev = by_qid.get(a.question_id)
        if prev is None or a.attempted_at > prev:
            by_qid[a.question_id] = a.attempted_at
    for qid, last in by_qid.items():
        if last > recycle_cutoff:
            recent_ids.add(qid)
        else:
            recyclable_ids.add(qid)
    return recyclable_ids, recent_ids


def _categorize_pools(
    topic_id: int,
    questions: list[Question],
    recyclable_ids: set[int],
    recent_ids: set[int],
) -> dict[str, list[Question]]:
    """Split the candidate pool for one topic into new/recyclable/recent."""
    pools = {"new": [], "recyclable": [], "recent": []}
    attempted = recyclable_ids | recent_ids
    for q in questions:
        if q.id not in attempted:
            pools["new"].append(q)
        elif q.id in recyclable_ids:
            pools["recyclable"].append(q)
        else:
            pools["recent"].append(q)
    return pools


_POOL_RANK = {"new": 0, "recyclable": 1, "recent": 2}
_RANK_TO_POOL = {0: "new", 1: "recyclable", 2: "recent"}


def _atomize_topic_pools(
    topic_pools: dict[str, list[Question]],
) -> dict[str, list[_Atom]]:
    """Convert a topic's per-pool question lists into per-pool atom lists.

    Standalones become 1-question atoms placed in their original pool.
    A passage's sub-questions become ONE atom of size N. If a passage's
    siblings straddle multiple rotation pools (rare — only happens in
    pathological pre-existing data, since atomic serve keeps siblings
    in lockstep), the atom is filed under the WORST pool of any sibling
    (recent ≻ recyclable ≻ new). That's conservative: we'd rather defer
    a partially-recent passage to a worse rotation bucket than serve it
    again too soon.
    """
    standalones_by_pool: dict[str, list[Question]] = {
        "new": [], "recyclable": [], "recent": [],
    }
    passage_subs: dict[int, list[tuple[Question, str]]] = defaultdict(list)

    for pool_status in ("new", "recyclable", "recent"):
        for q in topic_pools[pool_status]:
            if q.passage_id is None:
                standalones_by_pool[pool_status].append(q)
            else:
                passage_subs[q.passage_id].append((q, pool_status))

    atoms_by_pool: dict[str, list[_Atom]] = {
        "new": [], "recyclable": [], "recent": [],
    }
    for pool_status, qs in standalones_by_pool.items():
        for q in qs:
            atoms_by_pool[pool_status].append(_Atom(
                size=1, difficulty=q.difficulty.lower(), questions=(q,),
            ))
    for pid, subs in passage_subs.items():
        worst_rank = max(_POOL_RANK[ps] for _, ps in subs)
        atom_pool = _RANK_TO_POOL[worst_rank]
        group = [q for q, _ in subs]
        group.sort(key=lambda x: x.id)
        atoms_by_pool[atom_pool].append(_Atom(
            size=len(group),
            difficulty=group[0].difficulty.lower(),
            questions=tuple(group),
        ))
    # Stable default order — deterministic when no shuffle seed.
    for pool_status in atoms_by_pool:
        atoms_by_pool[pool_status].sort(key=lambda a: a.lead_id)
    return atoms_by_pool


def _pick_atoms_with_mix(
    atoms: list[_Atom],
    needed: int,
    target_mix: dict[str, float],
    excluded_lead_ids: set[int],
) -> list[_Atom]:
    """Pick atoms (without overshoot) respecting the difficulty mix.

    Difficulty quotas are sized in QUESTION units, not atom units. A
    passage atom of size 5 with difficulty=medium consumes 5 units of
    medium's quota — taking it or not is a single yes/no.

    An atom whose size exceeds the remaining (per-difficulty or overall)
    budget is skipped, never split. This is the non-overshoot guarantee:
    each atom is pickable as a whole, or not at all.

    `atoms` is consumed in the order given by the caller — the caller is
    responsible for shuffling it (or not) before this point. Each atom is
    one item in that order, so a passage of 5 has the same pick frequency
    as one standalone, not 5×.
    """
    if needed <= 0:
        return []

    by_diff = {"easy": [], "medium": [], "hard": []}
    for a in atoms:
        if a.lead_id in excluded_lead_ids:
            continue
        d = a.difficulty if a.difficulty in by_diff else "medium"
        by_diff[d].append(a)

    # Question-unit quotas from the target mix.
    quotas: dict[str, int] = {}
    allocated = 0
    for diff, weight in target_mix.items():
        c = int(needed * weight)
        quotas[diff] = c
        allocated += c
    remainder = needed - allocated
    primary = max(target_mix, key=target_mix.get) if target_mix else "easy"
    if remainder > 0:
        quotas[primary] = quotas.get(primary, 0) + remainder

    chosen: list[_Atom] = []
    picked_lead_ids: set[int] = set()
    total_picked = 0

    # Phase 1 — fill each difficulty bucket up to its quota, atoms taken in
    # iteration order (the caller-provided order, which may be shuffled).
    for diff in ("easy", "medium", "hard"):
        budget = quotas.get(diff, 0)
        if budget <= 0:
            continue
        used = 0
        for a in by_diff[diff]:
            if a.lead_id in picked_lead_ids:
                continue
            if a.size <= budget - used:
                chosen.append(a)
                picked_lead_ids.add(a.lead_id)
                used += a.size
                total_picked += a.size
                if used >= budget:
                    break
        # If an atom of size > budget existed, we leave the bucket
        # under-full and let Phase 2 backfill from elsewhere.

    # Phase 2 — backfill from any difficulty (preferring the primary's
    # fallback order) until we reach `needed`, still respecting size fit.
    if total_picked < needed:
        fallback_order = {
            "easy": ("easy", "medium", "hard"),
            "medium": ("medium", "easy", "hard"),
            "hard": ("hard", "medium", "easy"),
        }[primary]
        for diff in fallback_order:
            for a in by_diff[diff]:
                if a.lead_id in picked_lead_ids:
                    continue
                if total_picked + a.size <= needed:
                    chosen.append(a)
                    picked_lead_ids.add(a.lead_id)
                    total_picked += a.size
                    if total_picked >= needed:
                        break
            if total_picked >= needed:
                break

    return chosen


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def select_questions(
    distribution: dict[int, int],
    priority_scores: dict[int, PriorityScore],
    attempts_by_topic: dict[int, list[Attempt]],
    available_questions: list[tuple[Question, int]],
    target_total: int,
    now: datetime,
    shuffle_seed: int | None = None,
) -> tuple[list[tuple[Question, int]], dict[int, int]]:
    """Return (selected_questions, final_allocation).

    selected_questions: list of (Question, topic_id) — the topic_id is the
        topic this question was *served under* (since a question can be
        tagged to multiple topics). Passage sub-questions appear
        consecutively in sub-index order; the whole group either all
        appears or none does.
    final_allocation: how many questions each topic ended up contributing
        (may differ from `distribution` due to redistribution + overlap).

    Args:
        shuffle_seed: when None (default), atoms are kept in their stable
            lead-id order. When an int, each (pool, topic) atom list is
            shuffled with `random.Random(shuffle_seed)` before selection.
            In production, pass `int(time.time())` or a per-session hash
            so consecutive tests don't replay identical questions.

    Passage proportion is determined naturally by the pool: each atom is
    one item in the shuffled draw, so a passage of N has the same
    pick-frequency as a standalone — never preferred just because it
    fills slots fast. Atoms whose size exceeds the remaining budget are
    skipped (no overshoot).
    """
    if not distribution or target_total <= 0:
        return [], {tid: 0 for tid in distribution}

    topic_ids = list(distribution.keys())
    rng = random.Random(shuffle_seed) if shuffle_seed is not None else None

    # Bucket attempted question IDs per topic.
    topic_status: dict[int, tuple[set[int], set[int]]] = {}
    for tid in topic_ids:
        topic_status[tid] = _bucket_attempted_questions(
            attempts_by_topic.get(tid, []), now,
        )

    # Group available questions by topic.
    pool_by_topic: dict[int, list[Question]] = defaultdict(list)
    seen_in_topic: dict[int, set[int]] = defaultdict(set)
    for q, tid in available_questions:
        if tid in distribution and q.id not in seen_in_topic[tid]:
            pool_by_topic[tid].append(q)
            seen_in_topic[tid].add(q.id)

    # ---- Capacity check + redistribution ----
    available_counts = {tid: len(pool_by_topic[tid]) for tid in topic_ids}
    final_distribution: dict[int, int] = {}
    initially_allocated = 0
    for tid, requested in distribution.items():
        if requested <= 0:
            final_distribution[tid] = 0
            continue
        alloc = min(requested, available_counts.get(tid, 0))
        final_distribution[tid] = alloc
        initially_allocated += alloc

    shortage = target_total - initially_allocated
    if shortage > 0:
        surplus_topics: list[tuple[int, int, float]] = []
        for tid in topic_ids:
            surplus = available_counts.get(tid, 0) - final_distribution[tid]
            if surplus > 0:
                surplus_topics.append((tid, surplus, priority_scores[tid].score))
        surplus_topics.sort(key=lambda x: x[2], reverse=True)
        remaining = shortage
        for tid, surplus, _ in surplus_topics:
            if remaining <= 0:
                break
            extra = min(surplus, remaining)
            final_distribution[tid] += extra
            remaining -= extra

    # ---- Atomize and (optionally) shuffle ----
    # First categorize each topic's pool into new/recyclable/recent (over
    # questions), then collapse passage siblings into atoms.
    atoms_by_topic: dict[int, dict[str, list[_Atom]]] = {}
    for tid in topic_ids:
        recyclable, recent = topic_status[tid]
        per_pool_qs = _categorize_pools(
            tid, pool_by_topic[tid], recyclable, recent,
        )
        atoms_by_topic[tid] = _atomize_topic_pools(per_pool_qs)

    # Shuffle ATOMS within each (topic, pool). Each atom is one item, so a
    # passage doesn't dominate just because it's big — natural proportion.
    if rng is not None:
        for tid in topic_ids:
            for pool_name in ("new", "recyclable", "recent"):
                rng.shuffle(atoms_by_topic[tid][pool_name])

    # ---- Selection ----
    # Walk topics in descending priority — reduces starvation under overlap.
    topic_order = sorted(
        topic_ids, key=lambda t: priority_scores[t].score, reverse=True,
    )

    final_questions: list[tuple[Question, int]] = []
    selected_ids: set[int] = set()
    actual_allocation: dict[int, int] = {tid: 0 for tid in topic_ids}

    for tid in topic_order:
        needed = final_distribution.get(tid, 0)
        if needed <= 0:
            continue
        target_mix = progression_mix(attempts_by_topic.get(tid, []))

        # Drain pools in rotation order: new → recyclable → recent.
        remaining = needed
        for pool_name in ("new", "recyclable", "recent"):
            if remaining <= 0:
                break
            # Atoms whose lead question has been selected via another
            # topic's pass are filtered out (cross-topic overlap dedup).
            excluded = {a.lead_id for a in atoms_by_topic[tid][pool_name]
                        if any(q.id in selected_ids for q in a.questions)}
            picks = _pick_atoms_with_mix(
                atoms_by_topic[tid][pool_name], remaining, target_mix,
                excluded_lead_ids=excluded,
            )
            for atom in picks:
                # Cross-topic guard: any sibling already in via another
                # topic? Skip the whole atom.
                if any(q.id in selected_ids for q in atom.questions):
                    continue
                for q in atom.questions:
                    final_questions.append((q, tid))
                    selected_ids.add(q.id)
                    actual_allocation[tid] += 1
                remaining -= atom.size
                if remaining <= 0:
                    break

    # ---- Final backfill if topic overlap caused under-allocation ----
    # Standalones only here — we'd never start a partial passage in
    # backfill. The atom guarantee holds.
    missing = target_total - len(final_questions)
    if missing > 0:
        for q, tid in available_questions:
            if missing <= 0:
                break
            if q.passage_id is not None:
                continue
            if q.id in selected_ids or tid not in distribution:
                continue
            final_questions.append((q, tid))
            selected_ids.add(q.id)
            actual_allocation[tid] = actual_allocation.get(tid, 0) + 1
            missing -= 1

    return final_questions, actual_allocation


def select_extra_performance_questions(
    selected_topic_ids: Iterable[int],
    user_attempts: list[Attempt],
    available_questions: list[tuple[Question, int]],
    count: int,
    already_selected_ids: set[int],
) -> list[tuple[Question, int]]:
    """Pick extra questions from topics the user has attempted but NOT
    included in this test.

    Standalones only — same atom guarantee as `select_questions`: we
    never insert a stray sub-question of a passage that wasn't fully
    served.

    Mirrors `fetch_extra_performance_questions` in services_async.py:819.
    """
    if count <= 0:
        return []

    selected_topic_ids = set(selected_topic_ids)
    attempted_topic_ids = {a.topic_id for a in user_attempts} - selected_topic_ids
    if not attempted_topic_ids:
        return []

    attempted_qids = {a.question_id for a in user_attempts}

    out: list[tuple[Question, int]] = []
    for q, tid in available_questions:
        if len(out) >= count:
            break
        if q.passage_id is not None:
            continue
        if tid not in attempted_topic_ids:
            continue
        if q.id in attempted_qids:
            continue
        if q.id in already_selected_ids:
            continue
        out.append((q, tid))
        already_selected_ids.add(q.id)
    return out
