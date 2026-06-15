"""One class per agent role.

Every agent follows the same shape — a SYSTEM_PROMPT constant plus an async
`run()` that builds a prompt, makes a single strict-JSON call through
`llm.chat_json`, and parses the reply tolerantly into a typed verdict / draft.
A failed LLM call always degrades to a safe "none" (or `None` for the namer) so
one bad question never derails the batch pass.

    Stage1ChunkClassifierAgent — MATCH/NONE for one chunk of patterns
    Stage2ReducerAgent         — pick the winner among competing stage-1 matches
    MatchOnlyReducerAgent      — in-lock second-chance match before creating
    PatternNamerAgent          — draft a new pattern (or reuse an existing slug)
    PatternDedupeAgent         — are these two patterns the same trick?
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable

from config.settings import settings
from modules.pattern_miner.constants import (
    NAMER_TEMPERATURE,
    STAGE1_TEMPERATURE,
    STAGE2_TEMPERATURE,
    DEDUPE_TEMPERATURE,
)
from modules.pattern_miner.domain import (
    CleanedQuestion,
    MatchOnlyVerdict,
    Pattern,
    PatternDraft,
    PatternSignature,
    Stage1Verdict,
    Stage2Verdict,
)
from modules.pattern_miner.ids import safe_slug
from modules.pattern_miner.llm import LLMError, chat_json
from modules.pattern_miner.prompts import (
    DEDUPE_SYSTEM_PROMPT,
    MATCH_ONLY_SYSTEM_PROMPT,
    NAMER_SYSTEM_PROMPT,
    STAGE1_SYSTEM_PROMPT,
    STAGE2_SYSTEM_PROMPT,
    dedupe_user_prompt,
    match_only_user_prompt,
    namer_user_prompt,
    stage1_user_prompt,
    stage2_user_prompt,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared plumbing — tolerant JSON parsing + prompt formatting.
# ---------------------------------------------------------------------------


def parse_json_tolerant(raw: str) -> dict[str, Any]:
    """Strip ```json fences, find the outermost {...}, decode."""
    if not raw:
        return {}
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse JSON: %s | text=%.200s", exc, s)
        return {}


def format_question(q: CleanedQuestion) -> str:
    return (
        f"Subject: {q.subject}\nChapter: {q.chapter}\nTopic: {q.topic}\n\n"
        f"{q.question_text}\n\n"
        f"Options:\n{q.options_text or '(none — integer answer)'}\n\n"
        f"Correct answer: {q.answer_text}\n\n"
        f"Worked solution:\n{q.explanation_text}"
    )


def format_patterns(patterns: Iterable[Pattern]) -> str:
    blocks: list[str] = []
    for p in patterns:
        blocks.append(
            f"--- pattern_id: {p.pattern_id} ---\n"
            f"Name: {p.name}\n"
            f"Trigger: {p.signature.trigger}\n"
            f"Technique: {p.signature.technique}\n"
            f"Why it works: {p.signature.why_it_works}"
        )
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Stage 1 — one call per chunk, run in parallel.
# ---------------------------------------------------------------------------


class Stage1ChunkClassifierAgent:
    SYSTEM_PROMPT = STAGE1_SYSTEM_PROMPT

    async def run(
        self,
        question: CleanedQuestion,
        chunk_patterns: list[Pattern],
    ) -> Stage1Verdict:
        if not chunk_patterns:
            return Stage1Verdict(verdict="none")

        prompt = stage1_user_prompt(
            question_text=format_question(question),
            patterns_block=format_patterns(chunk_patterns),
        )

        try:
            raw = await chat_json(
                prompt,
                agent="stage1",
                model=settings.GEMINI_MODEL_FLASH,
                system=self.SYSTEM_PROMPT,
                temperature=STAGE1_TEMPERATURE,
                max_tokens=2500,
            )
        except LLMError as exc:
            logger.warning("Stage1 LLM failed for %s: %s", question.question_id, exc)
            return Stage1Verdict(verdict="none")

        parsed = parse_json_tolerant(raw)
        verdict_str = (parsed.get("verdict") or "none").lower()
        if verdict_str not in ("match", "none"):
            verdict_str = "none"

        pid = parsed.get("pattern_id")
        if verdict_str == "match" and pid:
            valid_ids = {p.pattern_id for p in chunk_patterns}
            if pid not in valid_ids:
                logger.warning(
                    "Stage1 returned unknown pattern_id %s for question %s",
                    pid, question.question_id,
                )
                return Stage1Verdict(verdict="none")

        return Stage1Verdict(
            verdict=verdict_str,  # type: ignore[arg-type]
            pattern_id=pid if verdict_str == "match" else None,
            confidence=float(parsed.get("confidence", 0.0) or 0.0),
            evidence=str(parsed.get("evidence", "") or "")[:300],
        )


# ---------------------------------------------------------------------------
# Stage 2 — winner-picker among competing stage-1 matches.
# ---------------------------------------------------------------------------


class Stage2ReducerAgent:
    SYSTEM_PROMPT = STAGE2_SYSTEM_PROMPT

    async def run(
        self,
        question: CleanedQuestion,
        stage1_matches: list[Stage1Verdict],
        patterns_by_id: dict[str, Pattern],
    ) -> Stage2Verdict:
        candidates: list[Pattern] = []
        for v in stage1_matches:
            if v.pattern_id and v.pattern_id in patterns_by_id:
                candidates.append(patterns_by_id[v.pattern_id])
        if not candidates:
            return Stage2Verdict(verdict="none")

        prompt = stage2_user_prompt(
            question_text=format_question(question),
            candidates_block=format_patterns(candidates),
        )

        try:
            raw = await chat_json(
                prompt,
                agent="stage2",
                model=settings.GEMINI_MODEL_FLASH,
                system=self.SYSTEM_PROMPT,
                temperature=STAGE2_TEMPERATURE,
                max_tokens=2500,
            )
        except LLMError as exc:
            logger.warning("Stage2 LLM failed for %s: %s", question.question_id, exc)
            return Stage2Verdict(verdict="none")

        parsed = parse_json_tolerant(raw)
        verdict_str = (parsed.get("verdict") or "none").lower()
        if verdict_str not in ("match", "none"):
            verdict_str = "none"

        pid = parsed.get("pattern_id")
        if verdict_str == "match" and pid not in {p.pattern_id for p in candidates}:
            logger.warning(
                "Stage2 returned unknown pattern_id %s for question %s",
                pid, question.question_id,
            )
            return Stage2Verdict(verdict="none")

        return Stage2Verdict(
            verdict=verdict_str,  # type: ignore[arg-type]
            pattern_id=pid if verdict_str == "match" else None,
            confidence=float(parsed.get("confidence", 0.0) or 0.0),
            evidence=str(parsed.get("evidence", "") or "")[:300],
        )


# ---------------------------------------------------------------------------
# Match-only — the in-lock re-check against the chapter's full current catalog.
# ---------------------------------------------------------------------------


class MatchOnlyReducerAgent:
    SYSTEM_PROMPT = MATCH_ONLY_SYSTEM_PROMPT

    async def run(
        self,
        question: CleanedQuestion,
        candidate_patterns: list[Pattern],
    ) -> MatchOnlyVerdict:
        if not candidate_patterns:
            return MatchOnlyVerdict(verdict="none")

        prompt = match_only_user_prompt(
            question_text=format_question(question),
            candidate_patterns_block=format_patterns(candidate_patterns),
        )

        try:
            raw = await chat_json(
                prompt,
                agent="match_only",
                model=settings.GEMINI_MODEL_FLASH,
                system=self.SYSTEM_PROMPT,
                temperature=STAGE2_TEMPERATURE,
                max_tokens=2000,
            )
        except LLMError as exc:
            logger.warning(
                "MatchOnly LLM failed for %s: %s", question.question_id, exc,
            )
            return MatchOnlyVerdict(verdict="none")

        parsed = parse_json_tolerant(raw)
        verdict_str = (parsed.get("verdict") or "none").lower()
        if verdict_str not in ("match", "none"):
            verdict_str = "none"

        pid = parsed.get("pattern_id")
        if verdict_str == "match" and pid not in {p.pattern_id for p in candidate_patterns}:
            return MatchOnlyVerdict(verdict="none")

        return MatchOnlyVerdict(
            verdict=verdict_str,  # type: ignore[arg-type]
            pattern_id=pid if verdict_str == "match" else None,
            confidence=float(parsed.get("confidence", 0.0) or 0.0),
            evidence=str(parsed.get("evidence", "") or "")[:300],
        )


# ---------------------------------------------------------------------------
# Namer — drafts a new pattern, or reuses an existing one by echoing its slug.
# ---------------------------------------------------------------------------


class PatternNamerAgent:
    SYSTEM_PROMPT = NAMER_SYSTEM_PROMPT

    async def run(
        self,
        question: CleanedQuestion,
        existing_patterns: list[Pattern] | None = None,
    ) -> PatternDraft | None:
        existing_patterns = existing_patterns or []
        existing_block = format_patterns(existing_patterns) if existing_patterns else ""
        existing_slugs = {p.slug for p in existing_patterns}

        prompt = namer_user_prompt(
            question_text=question.question_text,
            explanation_text=question.explanation_text,
            chapter=question.chapter,
            existing_patterns_block=existing_block,
        )

        try:
            raw = await chat_json(
                prompt,
                agent="namer",
                model=settings.GEMINI_MODEL_FLASH,
                system=self.SYSTEM_PROMPT,
                temperature=NAMER_TEMPERATURE,
                max_tokens=4000,
            )
        except LLMError as exc:
            logger.warning(
                "Namer LLM failed for %s: %s", question.question_id, exc,
            )
            return None

        parsed = parse_json_tolerant(raw)
        name = (parsed.get("name") or "").strip()
        description = (parsed.get("description") or "").strip()
        sig_raw = parsed.get("signature") or {}
        matches_existing = bool(parsed.get("matches_existing"))

        # Slug resolution:
        #   * reuse path — the model echoed an existing slug → keep it verbatim
        #     so propose_or_join joins the existing pattern via the dup fallback.
        #   * new path — derive the slug deterministically from the name so the
        #     same name always produces the same slug (don't trust the model's
        #     free-form slug field, which drifts at temperature).
        model_slug = safe_slug(parsed.get("slug") or "")
        if matches_existing and model_slug in existing_slugs:
            slug = model_slug
        else:
            matches_existing = False
            slug = safe_slug(name)

        if not (name and slug and description and sig_raw):
            # Diagnostic — surfaces exactly what the model produced so we can
            # tell empty-reply vs. wrong-shape vs. JSON-fenced-but-content-ok.
            logger.warning(
                "Namer parse failed (q=%s); raw[:400]=%r",
                question.question_id, (raw or "")[:400],
            )
            return None

        try:
            signature = PatternSignature(
                trigger=(sig_raw.get("trigger") or "").strip(),
                technique=(sig_raw.get("technique") or "").strip(),
                why_it_works=(sig_raw.get("why_it_works") or "").strip(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Namer signature invalid: %s", exc)
            return None

        return PatternDraft(
            slug=slug,
            name=name,
            description=description,
            signature=signature,
            confidence=float(parsed.get("confidence", 0.7) or 0.7),
            rationale=(parsed.get("rationale") or "").strip()[:300],
        )


# ---------------------------------------------------------------------------
# Dedupe — pairwise "same trick?" judgement for the periodic merge job.
# ---------------------------------------------------------------------------


def _format_for_dedupe(p: Pattern) -> str:
    return (
        f"pattern_id: {p.pattern_id}\n"
        f"Name: {p.name}\n"
        f"Description: {p.description}\n"
        f"Trigger: {p.signature.trigger}\n"
        f"Technique: {p.signature.technique}\n"
        f"Why it works: {p.signature.why_it_works}"
    )


class PatternDedupeAgent:
    SYSTEM_PROMPT = DEDUPE_SYSTEM_PROMPT

    async def are_same(
        self, pattern_a: Pattern, pattern_b: Pattern,
    ) -> tuple[bool, float, str]:
        prompt = dedupe_user_prompt(
            pattern_a_block=_format_for_dedupe(pattern_a),
            pattern_b_block=_format_for_dedupe(pattern_b),
        )

        try:
            raw = await chat_json(
                prompt,
                agent="dedupe",
                model=settings.GEMINI_MODEL_FLASH,
                system=self.SYSTEM_PROMPT,
                temperature=DEDUPE_TEMPERATURE,
                max_tokens=300,
            )
        except LLMError as exc:
            logger.warning("Dedupe LLM failed for (%s, %s): %s",
                           pattern_a.pattern_id, pattern_b.pattern_id, exc)
            return False, 0.0, "llm failure"

        parsed = parse_json_tolerant(raw)
        same = bool(parsed.get("same", False))
        conf = float(parsed.get("confidence", 0.0) or 0.0)
        reason = str(parsed.get("reason", "") or "")[:300]
        return same, conf, reason
