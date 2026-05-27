"""SolverX orchestrator.

Routing matrix:

    mode    complexity   →   pipeline
    ─────────────────────────────────────────────────────
    solve   guided       →   _simple_pipeline (Flash, no diagrams)
    solve   deep         →   _deep_pipeline   (Plan → Solve → Diagrams)
    theory  easy         →   _simple_pipeline (Flash, no diagrams)
    theory  deep         →   _deep_pipeline   (Plan → Solve → Diagrams)

Deep mode interleaves diagrams: the solver emits placeholder blocks
inline, the service yields them to the client immediately as
`diagram_pending` blocks, and kicks off the diagram agents in parallel.
When each diagram finishes, a `diagram_ready` SSE event is sent with
the final SVG so the frontend can swap the placeholder.

Wire-protocol emitted to the client:

    event: status          data: {"phase": "...", "message": "..."}
    event: topic           data: {"subject": "...", "chapter": "...", ...}
    event: insights        data: {"items": [{"headline": "...", "detail": "..."}]}
    event: block           data: {"type": "...", "title": "...", "content": "..."}
    event: diagram_ready   data: {"n": 1, "content": "<svg>...</svg>"}
    event: done            data: {"conversation_id": "...", "message_id": "..."}
    event: error           data: {"message": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from config.settings import settings
from modules.solverx.constants import (
    MODE_SOLVE,
    MODE_THEORY,
    SIMPLE_COMPLEXITIES,
    SOLVE_STATUS_MESSAGES,
    THEORY_STATUS_MESSAGES,
)
from modules.solverx.llm import LLMError, chat_json, chat_stream
from modules.solverx.model import new_conversation_doc, new_message_doc
from modules.solverx.prompts import (
    BLOCK_CLOSE,
    DIAGRAM_DRAFT_SYSTEM_PROMPT,
    DIAGRAM_POLISH_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    SIMPLE_SOLVE_SYSTEM_PROMPT,
    SIMPLE_THEORY_SYSTEM_PROMPT,
    THEORY_PLAN_SYSTEM_PROMPT,
    deep_solve_system_prompt,
    deep_solve_user_message,
    deep_theory_system_prompt,
    deep_theory_user_message,
    diagram_draft_user_message,
    diagram_polish_user_message,
    plan_user_message,
    simple_solve_user_message,
    simple_theory_user_message,
)
from modules.solverx.repository import SolverXRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stream parsing — looks for [[BLOCK type=... title="..." ...]] ... [[END]]
# and also captures the new diagram_pending attributes (n, description).
# ---------------------------------------------------------------------------

_BLOCK_HEADER_RE = re.compile(
    r"\[\[BLOCK\s+type=(?P<type>[A-Za-z_]+)"
    r"(?P<attrs>(?:\s+\w+=\"[^\"]*\")*)\s*\]\]"
)
_ATTR_RE = re.compile(r"(\w+)=\"([^\"]*)\"")

# Some models still nest a diagram_pending placeholder inside another
# block's body. When we extract a parent block, scan its content for
# this pattern and pull each occurrence out into its own block so the
# user actually sees the diagram instead of raw `[[BLOCK …]]` text.
# Matches the placeholder header plus an OPTIONAL trailing `[[END]]`
# (the model is inconsistent about emitting it for an empty body).
_NESTED_DIAGRAM_RE = re.compile(
    r"\[\[BLOCK\s+type=diagram_pending"
    r"(?P<attrs>(?:\s+\w+=\"[^\"]*\")*)\s*\]\]"
    r"\s*(?:\[\[END\]\]\s*)?",
    re.DOTALL,
)

# The deep solver occasionally bypasses the diagram_pending placeholder
# flow and just embeds a full <svg>…</svg> directly inside a step block's
# body. The frontend then renders that block as markdown, which escapes
# the SVG into visible XML text. We catch that pattern here and lift the
# SVG out into its own `diagram` block.
_INLINE_SVG_RE = re.compile(
    r"<svg\b[^>]*>[\s\S]*?</svg>",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Plan JSON tolerance — Gemini occasionally wraps JSON in ```json fences
# despite being told not to. Cheaper to strip than retry.
# ---------------------------------------------------------------------------


def _parse_plan_json(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# Personalisation tool — SOLVE + DEEP only.
#
# Pipeline:
#   1. Aggregate the question catalog into a (subject, chapter) list and
#      ask Flash-Lite which chapter the question belongs to (or NONE).
#   2. If a chapter matched, ask Flash-Lite to pick ONE topic from that
#      chapter's topic list (or NONE).
#   3. If both matched, look up the student's mock-test history on that
#      topic via MockTestService:
#        - has prior attempts → ask Flash to write a personalised insight
#          quoting accuracy + priority score + mistake-pattern hypotheses.
#        - no prior attempts   → emit a stock "you haven't practised this
#          topic yet — solve some mock questions on it after" insight.
#   4. If chapter or topic doesn't match → return empty (no insights).
#
# Theory mode never calls this — student wants the concept explained,
# not a personalised performance debrief.
# ---------------------------------------------------------------------------


async def _list_catalog_chapters(
    db: AsyncIOMotorDatabase,
) -> list[dict[str, str]]:
    """Distinct (subject, chapter) pairs from the questions catalog."""
    pipeline = [
        {"$match": {"subject": {"$ne": None}, "chapter": {"$ne": None}}},
        {"$group": {"_id": {"subject": "$subject", "chapter": "$chapter"}}},
        {"$sort": {"_id.subject": 1, "_id.chapter": 1}},
    ]
    out: list[dict[str, str]] = []
    async for row in db["questions"].aggregate(pipeline):
        k = row.get("_id") or {}
        s = (k.get("subject") or "").strip()
        c = (k.get("chapter") or "").strip()
        if s and c:
            out.append({"subject": s, "chapter": c})
    return out


async def _list_catalog_topics_in_chapter(
    db: AsyncIOMotorDatabase, subject: str, chapter: str,
) -> list[str]:
    """Distinct topic names under one (subject, chapter)."""
    raw = await db["questions"].distinct(
        "topic", {"subject": subject, "chapter": chapter},
    )
    return sorted(t.strip() for t in raw if isinstance(t, str) and t.strip())


def _content_with_optional_image(
    text: str, image_data_url: Optional[str],
) -> Any:
    """Multimodal content helper — mirrors `SolverXService._user_content`
    but lives at module level for the matcher helpers below."""
    if not image_data_url:
        return text
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]


async def _match_chapter_for_question(
    *,
    question_text: str,
    chapters: list[dict[str, str]],
    image_data_url: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Ask Flash-Lite to map a question to one chapter. Returns
    (subject, chapter) or (None, None) when no clean match.

    The image (when the student attached a screenshot) is forwarded
    in — otherwise the matcher only sees the fallback typed text
    ("Solve / explain the attached image.") and has to return null."""
    if not chapters:
        return None, None
    listing = "\n".join(f"- {c['subject']} / {c['chapter']}" for c in chapters)
    prompt = (
        "You match a student's question to ONE chapter in our catalog, or "
        "say it doesn't fit any. The question may be typed text, an "
        "attached image (screenshot of a problem), or both — use whichever "
        "is present.\n\n"
        f"Available chapters (format: subject / chapter):\n{listing}\n\n"
        f"Question (typed text — may be empty or generic if the real "
        f"question is in the image):\n{question_text.strip()}\n\n"
        "Reply with STRICT JSON only — no fences:\n"
        '{"subject": "<exact subject from the list, or null>", '
        '"chapter": "<exact chapter from the list, or null>"}\n\n'
        "If the question doesn't clearly belong to ANY listed chapter, "
        "set both fields to null."
    )
    try:
        raw = await chat_json(
            [{
                "role": "user",
                "content": _content_with_optional_image(prompt, image_data_url),
            }],
            model=settings.GEMINI_MODEL_FLASH_LITE,
            temperature=0.1,
            max_tokens=200,
            response_mime="application/json",
            disable_thinking=True,
        )
    except LLMError as exc:
        logger.debug("Chapter-match LLM failed: %s", exc)
        return None, None
    parsed = _parse_plan_json(raw)
    subj = parsed.get("subject")
    chap = parsed.get("chapter")
    if not isinstance(subj, str) or not isinstance(chap, str):
        return None, None
    subj = subj.strip()
    chap = chap.strip()
    if not subj or not chap:
        return None, None
    # Defensive: ensure the model returned something from the actual list.
    for c in chapters:
        if c["subject"].lower() == subj.lower() and c["chapter"].lower() == chap.lower():
            return c["subject"], c["chapter"]
    return None, None


async def _match_topic_in_chapter(
    *,
    question_text: str,
    chapter: str,
    topics: list[str],
    image_data_url: Optional[str] = None,
) -> Optional[str]:
    """Ask Flash-Lite to pick the single best-matching topic, or None.
    Image is forwarded when present so image-only questions still match."""
    if not topics:
        return None
    listing = "\n".join(f"- {t}" for t in topics)
    prompt = (
        f"From the topics listed under '{chapter}', pick the ONE that best "
        "matches the student's question. Pick exactly one — or say none "
        "if no topic genuinely matches. The question may be typed text, "
        "an attached image (screenshot), or both.\n\n"
        f"Topics:\n{listing}\n\n"
        f"Question (typed text — may be empty / generic):\n"
        f"{question_text.strip()}\n\n"
        "Reply with STRICT JSON only — no fences:\n"
        '{"topic": "<exact topic name from the list, or null>"}'
    )
    try:
        raw = await chat_json(
            [{
                "role": "user",
                "content": _content_with_optional_image(prompt, image_data_url),
            }],
            model=settings.GEMINI_MODEL_FLASH_LITE,
            temperature=0.1,
            max_tokens=160,
            response_mime="application/json",
            disable_thinking=True,
        )
    except LLMError as exc:
        logger.debug("Topic-match LLM failed: %s", exc)
        return None
    parsed = _parse_plan_json(raw)
    t = parsed.get("topic")
    if not isinstance(t, str) or not t.strip():
        return None
    t = t.strip()
    for cand in topics:
        if cand.lower() == t.lower():
            return cand
    return None


async def _llm_personalised_insight(
    *,
    question_text: str,
    topic_name: str,
    chapter_name: str,
    accuracy_pct: float,
    attempts: int,
    correct: int,
    priority_score: float,
) -> tuple[list[dict], str]:
    """Ask Flash to write a short personalised insight grounded in the
    student's actual numbers on this topic."""
    summary = (
        f"Topic: {topic_name}\n"
        f"Chapter: {chapter_name}\n"
        f"Total attempts on this topic: {attempts}\n"
        f"Correct answers: {correct}\n"
        f"Accuracy: {accuracy_pct:.1f}%\n"
        f"Priority score (higher = needs more work): {priority_score:.2f}"
    )
    prompt = (
        "You are an analytics-aware tutor. Given a student's prior mock-test "
        "performance on a topic and the new question they're trying to solve, "
        "write a SHORT personalised insight (1 or 2 items max).\n\n"
        f"PERFORMANCE:\n{summary}\n\n"
        f"NEW QUESTION (same topic):\n{question_text.strip()}\n\n"
        "Each insight item must:\n"
        "  * cite the student's accuracy AND priority score by their actual numbers\n"
        "  * guess a likely mistake pattern based on the metrics\n"
        "  * suggest ONE concrete way to improve\n"
        "If accuracy is very high (>80%), the first item can validate them.\n\n"
        "Reply with STRICT JSON — no fences:\n"
        "{\n"
        '  "items": [\n'
        '    {"headline": "<short headline, max 7 words>", '
        '"detail": "<1-2 sentences citing the actual numbers>"}\n'
        "  ],\n"
        '  "tutor_note": "<one short sentence for the solver agent describing what to emphasise>"\n'
        "}"
    )
    try:
        raw = await chat_json(
            [{"role": "user", "content": prompt}],
            model=settings.GEMINI_MODEL_FLASH,
            temperature=0.4,
            max_tokens=500,
            response_mime="application/json",
            disable_thinking=True,
        )
    except LLMError as exc:
        logger.warning("Personalised-insight LLM failed: %s", exc)
        # Fall back to a templated insight so the student still sees something.
        return (
            [{
                "headline": f"On {topic_name}: {accuracy_pct:.0f}% accuracy",
                "detail": (
                    f"Across {attempts} mock-test attempts on {topic_name}, "
                    f"you're at {accuracy_pct:.0f}% accuracy and a priority "
                    f"score of {priority_score:.2f}. Extra care on this one."
                ),
                "accuracy_pct": float(accuracy_pct),
            }],
            f"Student accuracy on {topic_name} is {accuracy_pct:.0f}% "
            f"({attempts} attempts). Be patient and explicit.",
        )
    parsed = _parse_plan_json(raw)
    items_raw = parsed.get("items") or []
    items: list[dict] = []
    for it in items_raw[:2]:
        if not isinstance(it, dict):
            continue
        headline = (it.get("headline") or "").strip()
        detail = (it.get("detail") or "").strip()
        if not headline or not detail:
            continue
        items.append({"headline": headline, "detail": detail})
    if not items:
        items = [{
            "headline": f"On {topic_name}: {accuracy_pct:.0f}% accuracy",
            "detail": (
                f"Across {attempts} attempts you sit at "
                f"{accuracy_pct:.0f}% accuracy here. Take this one slowly."
            ),
        }]
    note = (parsed.get("tutor_note") or "").strip()
    return items, note


async def _gather_personalisation_for_solve(
    db: AsyncIOMotorDatabase,
    user_oid: ObjectId,
    question_text: str,
    image_data_url: Optional[str] = None,
) -> tuple[list[dict], str]:
    """Full pipeline: chapter-match → topic-match → student history →
    LLM insight. Returns ([], "") whenever any stage produces no signal,
    so callers can simply skip the insight panel in that case.

    `image_data_url` is forwarded to the chapter/topic matchers so
    screenshot-only questions still classify."""
    try:
        chapters = await _list_catalog_chapters(db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Catalog chapter listing failed: %s", exc)
        return [], ""
    if not chapters:
        return [], ""

    subject, chapter = await _match_chapter_for_question(
        question_text=question_text,
        chapters=chapters,
        image_data_url=image_data_url,
    )
    if not subject or not chapter:
        # Question is outside the catalog — nothing personalised to add.
        return [], ""

    try:
        topics = await _list_catalog_topics_in_chapter(db, subject, chapter)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Topic listing failed: %s", exc)
        return [], ""

    topic = await _match_topic_in_chapter(
        question_text=question_text,
        chapter=chapter,
        topics=topics,
        image_data_url=image_data_url,
    )
    if not topic:
        return [], ""

    # Look up this student's history on the matched topic.
    try:
        from modules.mock_test.service import MockTestService

        topics_resp = await MockTestService(db).get_topic_analytics(user_oid)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Topic analytics lookup failed: %s", exc)
        return [], ""

    matched_ta = None
    norm_topic = topic.lower().strip()
    for t in getattr(topics_resp, "topics", []) or []:
        if (getattr(t, "topic_name", "") or "").lower().strip() == norm_topic:
            matched_ta = t
            break

    if matched_ta is None:
        # Topic exists in the catalog but the student hasn't attempted any
        # questions on it yet — encourage them to practise.
        items = [{
            "headline": f"Start practising {topic}",
            "detail": (
                f"You haven't attempted any mock-test questions on {topic} "
                f"({chapter}) yet. After this walkthrough, take a focused "
                "mock test on this topic — that's where the recommender "
                "starts tuning to you."
            ),
        }]
        note = (
            f"Student has no prior practice on {topic}. After solving, "
            "remind them to take a mock test on this topic."
        )
        return items, note

    return await _llm_personalised_insight(
        question_text=question_text,
        topic_name=getattr(matched_ta, "topic_name", topic),
        chapter_name=getattr(matched_ta, "chapter_name", chapter),
        accuracy_pct=float(getattr(matched_ta, "accuracy_pct", 0.0)),
        attempts=int(getattr(matched_ta, "attempts", 0)),
        correct=int(getattr(matched_ta, "correct", 0)),
        priority_score=float(getattr(matched_ta, "priority_score", 0.0)),
    )


# ---------------------------------------------------------------------------
# SVG extraction (defensive — the model sometimes adds a preamble or fence).
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"^\s*```(?:svg|html|xml)?\s*\n([\s\S]*?)\n```\s*$", re.IGNORECASE
)


def _extract_svg(raw: str) -> Optional[str]:
    if not raw:
        return None
    text = raw.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    lo = text.lower()
    start = lo.find("<svg")
    end = lo.rfind("</svg>")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 6]


async def _generate_diagram(
    *,
    description: str,
    topic_info: dict,
) -> Optional[str]:
    """Two-stage diagram pipeline: draft → polish.

    Both stages run on `GEMINI_MODEL_DIAGRAM` (Flash by default). SVG
    generation is more about following a layout recipe than deep
    reasoning, so Flash handles it well at a fraction of Pro's cost
    and latency — keeps Deep solves snappy when a figure is needed.
    """
    diagram_model = settings.GEMINI_MODEL_DIAGRAM
    try:
        draft_raw = await chat_json(
            [
                {"role": "system", "content": DIAGRAM_DRAFT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": diagram_draft_user_message(description, topic_info),
                },
            ],
            model=diagram_model,
            temperature=0.4,
            max_tokens=1500,
            # Disable thinking — SVG generation is recipe-following, not
            # reasoning. Otherwise Gemini's invisible thinking tokens
            # consume the entire budget and the response comes back empty.
            disable_thinking=True,
        )
    except LLMError as exc:
        logger.warning("Diagram draft failed: %s", exc)
        return None

    draft_svg = _extract_svg(draft_raw)
    if not draft_svg:
        return None

    try:
        polish_raw = await chat_json(
            [
                {"role": "system", "content": DIAGRAM_POLISH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": diagram_polish_user_message(description, draft_svg),
                },
            ],
            model=diagram_model,
            temperature=0.2,
            max_tokens=1600,
            disable_thinking=True,
        )
    except LLMError as exc:
        logger.warning("Diagram polish failed, returning draft: %s", exc)
        return draft_svg

    polished = _extract_svg(polish_raw)
    return polished or draft_svg


# ---------------------------------------------------------------------------
# Streaming block parser
# ---------------------------------------------------------------------------


def _build_block_from_match(
    block_type: str,
    header_attrs: str,
    content: str,
) -> dict[str, Any]:
    """Convert a regex match's pieces into the canonical block dict."""
    attrs: dict[str, str] = {}
    for k, v in _ATTR_RE.findall(header_attrs or ""):
        attrs[k] = v
    block: dict[str, Any] = {
        "type": block_type,
        "title": attrs.pop("title", ""),
        "content": content,
    }
    if attrs:
        block["extra"] = attrs
    return block


def _split_out_nested_diagrams(
    parent_type: str,
    parent_attrs: str,
    content: str,
) -> list[dict[str, Any]]:
    """Split a parent block whose content contains EITHER:

        * a `[[BLOCK type=diagram_pending …]]` placeholder, OR
        * a literal inline `<svg>…</svg>` blob

    into alternating (parent-text, diagram, parent-text, …) emissions so
    each artifact lands as its own block in the transcript.

    Placeholders become `diagram_pending` blocks (the existing async
    diagram-agent flow takes over). Inline SVGs become `diagram` blocks
    whose `content` IS the SVG markup — the frontend renders them
    immediately, no extra round-trip needed.

    If nothing matches, returns a single-element list with the parent
    block as-is.
    """
    # Build a unified list of (start, end, kind, payload) interruptions.
    interruptions: list[tuple[int, int, str, str]] = []
    for m in _NESTED_DIAGRAM_RE.finditer(content):
        interruptions.append(
            (m.start(), m.end(), "pending", m.group("attrs") or ""),
        )
    for m in _INLINE_SVG_RE.finditer(content):
        interruptions.append((m.start(), m.end(), "svg", m.group(0)))
    interruptions.sort(key=lambda t: t[0])

    if not interruptions:
        return [_build_block_from_match(parent_type, parent_attrs, content.strip())]

    out: list[dict[str, Any]] = []
    parent_title_used = False

    def emit_parent_chunk(text: str) -> None:
        nonlocal parent_title_used
        text = text.strip()
        if not text:
            return
        # Only the first parent-chunk carries the original title; the
        # follow-up chunks (after each diagram) are continuations.
        chunk_attrs = parent_attrs if not parent_title_used else ""
        out.append(_build_block_from_match(parent_type, chunk_attrs, text))
        parent_title_used = True

    cursor = 0
    for start, end, kind, payload in interruptions:
        emit_parent_chunk(content[cursor:start])
        if kind == "pending":
            out.append(
                _build_block_from_match("diagram_pending", payload, ""),
            )
        else:  # "svg" — emit a real diagram block carrying the SVG markup.
            out.append({
                "type": "diagram",
                "title": "Diagram",
                "content": payload.strip(),
            })
        cursor = end
    emit_parent_chunk(content[cursor:])

    return out


async def _stream_blocks_from_llm(
    stream: AsyncIterator[str],
) -> AsyncIterator[dict[str, Any]]:
    """Consume a streaming LLM response and yield a dict per completed
    block. Captures arbitrary `key="value"` attrs so `diagram_pending`
    can carry `n` and `description`.

    Defensive against the model nesting a `diagram_pending` placeholder
    inside a parent block: `_split_out_nested_diagrams` pulls those out
    and yields them as standalone blocks at the right position.
    """
    buf = ""
    open_match: Optional[re.Match] = None
    block_start_idx = -1

    async for delta in stream:
        buf += delta
        while True:
            if open_match is None:
                m = _BLOCK_HEADER_RE.search(buf)
                if not m:
                    break
                open_match = m
                block_start_idx = m.end()
            close_pos = buf.find(BLOCK_CLOSE, block_start_idx)
            if close_pos == -1:
                break
            content = buf[block_start_idx:close_pos].strip("\n").strip()

            for blk in _split_out_nested_diagrams(
                open_match.group("type"),
                open_match.group("attrs") or "",
                content,
            ):
                # Don't ship empty fragments (e.g. parent had nothing
                # but a nested diagram and a trailing newline).
                if not blk.get("content") and blk["type"] != "diagram_pending":
                    continue
                yield blk

            buf = buf[close_pos + len(BLOCK_CLOSE) :]
            open_match = None
            block_start_idx = -1


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SolverXService:
    # Cap how much prior chat we replay. Six messages = three turns;
    # diagrams are stripped (token-heavy, useless to the LLM).
    _HISTORY_MAX_MESSAGES = 6
    _HISTORY_TEXT_BUDGET = 2400

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = SolverXRepository(db)

    # ------------------------------------------------------------------
    # Conversation lifecycle helpers
    # ------------------------------------------------------------------

    async def _ensure_conversation(
        self,
        *,
        conversation_id: Optional[str],
        user_oid: ObjectId,
        mode: str,
        first_question: str,
    ) -> tuple[ObjectId, bool]:
        if conversation_id:
            existing = await self.repo.get_conversation(conversation_id, user_oid)
            if existing is not None:
                return existing["_id"], False
        title = first_question.strip().split("\n", 1)[0][:80] or "New conversation"
        oid = await self.repo.create_conversation(
            new_conversation_doc(user_id=user_oid, mode=mode, title=title)
        )
        return oid, True

    async def _build_history(self, conv_oid: ObjectId) -> list[dict]:
        docs = await self.repo.list_messages_for_conversation(conv_oid)
        if not docs:
            return []
        recent = docs[-self._HISTORY_MAX_MESSAGES :]
        out: list[dict] = []
        for d in recent:
            role = d.get("role")
            if role not in ("user", "assistant"):
                continue
            if role == "assistant":
                blocks = d.get("blocks") or []
                non_diagram = [
                    b for b in blocks
                    if b.get("type") not in ("diagram", "diagram_pending")
                ]
                text = "\n\n".join(
                    (b.get("title") + ": " if b.get("title") else "")
                    + (b.get("content") or "")
                    for b in non_diagram
                ).strip()
                if not text:
                    text = (d.get("text") or "").strip()
            else:
                text = (d.get("text") or "").strip()
            if not text:
                continue
            if len(text) > self._HISTORY_TEXT_BUDGET:
                text = text[: self._HISTORY_TEXT_BUDGET] + " …"
            out.append({"role": role, "content": text})
        return out

    # ------------------------------------------------------------------
    # Multimodal content builder (text + optional image)
    # ------------------------------------------------------------------

    @staticmethod
    def _user_content(text: str, image_data_url: Optional[str]) -> Any:
        if not image_data_url:
            return text
        return [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]

    # ------------------------------------------------------------------
    # Public entrypoints
    # ------------------------------------------------------------------

    async def stream_solve(
        self,
        *,
        user_oid: ObjectId,
        question_text: str,
        complexity_mode: str,
        conversation_id: Optional[str],
        image_data_url: Optional[str] = None,
    ) -> AsyncIterator[str]:
        async for evt in self._dispatch(
            user_oid=user_oid,
            question_text=question_text,
            complexity_mode=complexity_mode,
            conversation_id=conversation_id,
            mode=MODE_SOLVE,
            image_data_url=image_data_url,
        ):
            yield evt

    async def stream_theory(
        self,
        *,
        user_oid: ObjectId,
        question_text: str,
        complexity_mode: str,
        conversation_id: Optional[str],
        image_data_url: Optional[str] = None,
    ) -> AsyncIterator[str]:
        async for evt in self._dispatch(
            user_oid=user_oid,
            question_text=question_text,
            complexity_mode=complexity_mode,
            conversation_id=conversation_id,
            mode=MODE_THEORY,
            image_data_url=image_data_url,
        ):
            yield evt

    # ------------------------------------------------------------------
    # Dispatcher — routes by (mode, complexity) → simple vs deep path.
    # Conversation + user-message persistence is shared.
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        *,
        user_oid: ObjectId,
        question_text: str,
        complexity_mode: str,
        conversation_id: Optional[str],
        mode: str,
        image_data_url: Optional[str],
    ) -> AsyncIterator[str]:
        is_theory = mode == MODE_THEORY
        is_simple = complexity_mode in SIMPLE_COMPLEXITIES
        status_script = THEORY_STATUS_MESSAGES if is_theory else SOLVE_STATUS_MESSAGES

        # Persist conversation + user message up front so the history list
        # updates even if generation fails mid-flight.
        try:
            conv_oid, created = await self._ensure_conversation(
                conversation_id=conversation_id,
                user_oid=user_oid,
                mode=mode,
                first_question=question_text,
            )
            history_messages: list[dict] = (
                [] if created else await self._build_history(conv_oid)
            )
            await self.repo.create_message(
                new_message_doc(
                    conversation_id=conv_oid,
                    role="user",
                    text=question_text,
                    complexity_mode=complexity_mode,
                    image_data_url=image_data_url,
                )
            )
            await self.repo.touch_conversation(
                conv_oid, last_preview=question_text, increment_messages=1
            )
            yield _sse(
                "conversation",
                {"conversation_id": str(conv_oid), "created": created},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to persist conversation: %s", exc)
            yield _sse("error", {"message": "Could not start conversation."})
            return

        try:
            if is_simple:
                async for evt in self._simple_pipeline(
                    conv_oid=conv_oid,
                    question_text=question_text,
                    complexity_mode=complexity_mode,
                    is_theory=is_theory,
                    image_data_url=image_data_url,
                    history_messages=history_messages,
                    status_script=status_script,
                ):
                    yield evt
            else:
                async for evt in self._deep_pipeline(
                    user_oid=user_oid,
                    conv_oid=conv_oid,
                    question_text=question_text,
                    complexity_mode=complexity_mode,
                    is_theory=is_theory,
                    image_data_url=image_data_url,
                    history_messages=history_messages,
                    status_script=status_script,
                ):
                    yield evt
        except Exception as exc:  # noqa: BLE001
            logger.exception("SolverX pipeline crashed: %s", exc)
            yield _sse(
                "error",
                {"message": "Something went wrong on our side. Please retry."},
            )

    # ------------------------------------------------------------------
    # SIMPLE pipeline — single Flash streaming call. No plan, no diagrams,
    # no insights pass. Used for Guided Solve and Easy Theory.
    # ------------------------------------------------------------------

    async def _simple_pipeline(
        self,
        *,
        conv_oid: ObjectId,
        question_text: str,
        complexity_mode: str,
        is_theory: bool,
        image_data_url: Optional[str],
        history_messages: list[dict],
        status_script: dict,
    ) -> AsyncIterator[str]:
        sys_prompt = (
            SIMPLE_THEORY_SYSTEM_PROMPT if is_theory else SIMPLE_SOLVE_SYSTEM_PROMPT
        )
        user_msg_fn = (
            simple_theory_user_message if is_theory else simple_solve_user_message
        )
        yield _sse(
            "status",
            {"phase": "simple_start", "message": status_script["simple_solve_start"]},
        )

        collected: list[dict] = []
        try:
            raw_stream = chat_stream(
                [
                    {"role": "system", "content": sys_prompt},
                    *history_messages,
                    {
                        "role": "user",
                        "content": self._user_content(
                            user_msg_fn(question_text), image_data_url
                        ),
                    },
                ],
                model=settings.GEMINI_MODEL_FLASH,
                temperature=0.4,
                max_tokens=3500,
            )
            async for block in _stream_blocks_from_llm(raw_stream):
                # Simple paths must never emit diagrams; if the model
                # slips one in, drop it.
                if block.get("type") in ("diagram", "diagram_pending"):
                    continue
                collected.append(block)
                yield _sse("block", block)
                await asyncio.sleep(0)
        except LLMError as exc:
            logger.warning("Simple solve stage failed: %s", exc)
            yield _sse(
                "error",
                {"message": "The reasoning engine is busy. Please retry in a moment."},
            )
            return

        assistant_text = "\n\n".join(b.get("content", "") for b in collected)
        msg_oid = await self.repo.create_message(
            new_message_doc(
                conversation_id=conv_oid,
                role="assistant",
                text=assistant_text,
                blocks=collected,
                topic=None,
                insights=[],
                complexity_mode=complexity_mode,
            )
        )
        await self.repo.touch_conversation(
            conv_oid, last_preview=assistant_text or question_text, increment_messages=1
        )
        yield _sse(
            "done",
            {
                "conversation_id": str(conv_oid),
                "message_id": str(msg_oid),
                "block_count": len(collected),
            },
        )

    # ------------------------------------------------------------------
    # DEEP pipeline — Plan → Solve (streamed) → Diagrams (parallel, interleaved).
    # Used for Deep Reasoning and Deep Explanation.
    # ------------------------------------------------------------------

    async def _deep_pipeline(
        self,
        *,
        user_oid: ObjectId,
        conv_oid: ObjectId,
        question_text: str,
        complexity_mode: str,
        is_theory: bool,
        image_data_url: Optional[str],
        history_messages: list[dict],
        status_script: dict,
    ) -> AsyncIterator[str]:
        # ---- PLAN (Flash-Lite, JSON) ----
        yield _sse(
            "status", {"phase": "plan", "message": status_script["plan_start"]}
        )
        plan_system = THEORY_PLAN_SYSTEM_PROMPT if is_theory else PLAN_SYSTEM_PROMPT
        try:
            plan_raw = await chat_json(
                [
                    {"role": "system", "content": plan_system},
                    *history_messages,
                    {
                        "role": "user",
                        "content": self._user_content(
                            plan_user_message(question_text), image_data_url
                        ),
                    },
                ],
                model=settings.GEMINI_MODEL_FLASH_LITE,
                temperature=0.2,
                max_tokens=800,
                response_mime="application/json",
            )
        except LLMError as exc:
            logger.warning("Plan stage failed: %s", exc)
            plan_raw = ""

        plan = _parse_plan_json(plan_raw)
        topic_payload = {
            "subject": plan.get("subject"),
            "chapter": plan.get("chapter"),
            "topic": plan.get("topic"),
            "subtopic": plan.get("subtopic"),
            "difficulty": plan.get("difficulty"),
            "visual_needed": any(
                s.get("needs_diagram")
                for s in plan.get("plan_steps", [])
                if isinstance(s, dict)
            ),
        }
        yield _sse("topic", topic_payload)
        yield _sse(
            "status", {"phase": "plan_done", "message": status_script["plan_done"]}
        )

        # ---- INSIGHTS ----
        # Theory mode skips the personalisation panel entirely — the
        # student wants to understand the concept, not be told their
        # accuracy stats. The chapter/topic matcher is solve-deep only.
        insights: list[dict] = []
        personalisation_note = ""
        if not is_theory:
            yield _sse(
                "status",
                {"phase": "insight", "message": status_script["insight"]},
            )
            insights, personalisation_note = (
                await _gather_personalisation_for_solve(
                    self.db,
                    user_oid,
                    question_text,
                    image_data_url=image_data_url,
                )
            )
            if insights:
                yield _sse("insights", {"items": insights})

        # ---- SOLVE (Pro, streamed) ----
        yield _sse(
            "status", {"phase": "solve", "message": status_script["solve_start"]}
        )
        plan_steps = list(plan.get("plan_steps") or [])
        if is_theory:
            solve_sys = deep_theory_system_prompt(
                plan_steps=plan_steps,
                personalisation_note=personalisation_note,
            )
            solve_user = deep_theory_user_message(question_text)
        else:
            solve_sys = deep_solve_system_prompt(
                plan_steps=plan_steps,
                personalisation_note=personalisation_note,
            )
            solve_user = deep_solve_user_message(question_text)

        # In-flight diagram tasks, keyed by `n`. Started as the solver
        # emits placeholders; awaited and emitted as `diagram_ready`
        # events when ready.
        diagram_tasks: dict[int, asyncio.Task] = {}
        # Buffer of completed diagrams keyed by `n` — flushed into the
        # transcript at `done` time so persisted history contains the
        # final SVGs (not just the placeholders).
        completed_diagrams: dict[int, str] = {}

        collected_blocks: list[dict] = []
        progress_announced = False
        try:
            raw_stream = chat_stream(
                [
                    {"role": "system", "content": solve_sys},
                    *history_messages,
                    {
                        "role": "user",
                        "content": self._user_content(solve_user, image_data_url),
                    },
                ],
                model=settings.GEMINI_MODEL_PRO,
                temperature=0.5,
                # Generous ceiling. Gemini 2.5 Pro is a thinking model:
                # a chunk of this budget is spent on internal reasoning
                # tokens that never reach the user, so the visible
                # output is smaller than the limit suggests. With 16k
                # we comfortably fit 5–10 step blocks + diagrams even
                # when half the budget evaporates into thoughts.
                max_tokens=16000,
            )
            async for block in _stream_blocks_from_llm(raw_stream):
                btype = block.get("type")

                # Diagram placeholder → fire-and-forget background task,
                # yield the placeholder to the client immediately.
                if btype == "diagram_pending":
                    extra = block.get("extra") or {}
                    try:
                        n = int(extra.get("n", "0"))
                    except (TypeError, ValueError):
                        n = len(diagram_tasks) + 1
                    description = extra.get("description", "").strip()
                    if not description or n in diagram_tasks:
                        # Bad placeholder — skip silently rather than ship
                        # a useless loading slot.
                        continue
                    block["extra"] = {"n": n, "description": description}
                    collected_blocks.append(block)
                    yield _sse("block", block)
                    diagram_tasks[n] = asyncio.create_task(
                        _generate_diagram(
                            description=description,
                            topic_info=topic_payload,
                        )
                    )
                    continue

                # Bare `diagram` block — the solver emitted a full SVG
                # directly instead of using the diagram_pending → diagram_ready
                # async flow. Honor it as long as the content actually
                # contains an <svg> blob the frontend can render.
                if btype == "diagram":
                    raw = (block.get("content") or "").strip()
                    if "<svg" in raw.lower() and "</svg>" in raw.lower():
                        collected_blocks.append(block)
                        yield _sse("block", block)
                    continue

                if not progress_announced and len(collected_blocks) >= 2:
                    progress_announced = True
                    yield _sse(
                        "status",
                        {
                            "phase": "solve_progress",
                            "message": status_script["solve_progress"],
                        },
                    )

                collected_blocks.append(block)
                yield _sse("block", block)
                await asyncio.sleep(0)
        except LLMError as exc:
            logger.warning("Deep solve stage failed: %s", exc)
            yield _sse(
                "error",
                {"message": "The reasoning engine is busy. Please retry in a moment."},
            )
            for t in diagram_tasks.values():
                t.cancel()
            return

        # ---- Drain diagram tasks. As each completes, emit a
        #      `diagram_ready` event so the frontend can swap the
        #      pending placeholder for the real SVG.
        #
        # Each task is wrapped in `asyncio.wait_for(..., timeout=90)` —
        # if the LLM hangs (slow region, quota throttling, network
        # blip) we don't want the frontend to spin forever. On timeout
        # OR error, we still emit a `diagram_ready` event with
        # `content: null` so the frontend can clear the placeholder.
        if diagram_tasks:
            yield _sse(
                "status",
                {
                    "phase": "diagram_polish",
                    "message": status_script["diagram_polish"],
                },
            )

            DIAGRAM_TIMEOUT_SECONDS = 90.0

            async def _await_with_timeout(n: int, task: asyncio.Task):
                try:
                    svg = await asyncio.wait_for(
                        asyncio.shield(task),
                        timeout=DIAGRAM_TIMEOUT_SECONDS,
                    )
                    return n, svg
                except asyncio.TimeoutError:
                    logger.warning("Diagram n=%s timed out", n)
                    task.cancel()
                    return n, None
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Diagram n=%s failed: %s", n, exc)
                    return n, None

            wrappers = [
                asyncio.create_task(_await_with_timeout(n, t))
                for n, t in diagram_tasks.items()
            ]
            remaining = list(wrappers)
            while remaining:
                done, _pend = await asyncio.wait(
                    remaining, return_when=asyncio.FIRST_COMPLETED
                )
                for w in done:
                    remaining.remove(w)
                    try:
                        n_done, svg = w.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Diagram wrapper crashed: %s", exc)
                        continue
                    if svg:
                        completed_diagrams[n_done] = svg
                        yield _sse(
                            "diagram_ready", {"n": n_done, "content": svg}
                        )
                    else:
                        # Failed or timed out — tell the frontend so it
                        # clears the spinner instead of hanging.
                        yield _sse(
                            "diagram_ready", {"n": n_done, "content": None}
                        )

        # ---- Persist assistant message ----
        # Replace any diagram_pending entries in the saved transcript
        # with the finalised `diagram` blocks so reopened conversations
        # render the figures immediately (no need to re-run the agent).
        final_blocks: list[dict] = []
        for b in collected_blocks:
            if b.get("type") == "diagram_pending":
                n = (b.get("extra") or {}).get("n")
                svg = completed_diagrams.get(n) if n is not None else None
                if svg:
                    final_blocks.append(
                        {
                            "type": "diagram",
                            "title": b.get("title") or "Diagram",
                            "content": svg,
                            "extra": {"n": n} if n is not None else {},
                        }
                    )
                # Drop the placeholder if no SVG materialised — better
                # to show nothing than a permanent loading state.
                continue
            final_blocks.append(b)

        assistant_text = "\n\n".join(b.get("content", "") for b in final_blocks)
        msg_oid = await self.repo.create_message(
            new_message_doc(
                conversation_id=conv_oid,
                role="assistant",
                text=assistant_text,
                blocks=final_blocks,
                topic=topic_payload,
                insights=insights,
                complexity_mode=complexity_mode,
            )
        )
        await self.repo.touch_conversation(
            conv_oid, last_preview=assistant_text or question_text, increment_messages=1
        )
        yield _sse(
            "done",
            {
                "conversation_id": str(conv_oid),
                "message_id": str(msg_oid),
                "block_count": len(final_blocks),
            },
        )

    # ------------------------------------------------------------------
    # Non-streaming list / detail / delete
    # ------------------------------------------------------------------

    async def list_conversations(self, user_oid: ObjectId) -> dict:
        docs = await self.repo.list_conversations_for_user(user_oid)
        items = [
            {
                "id": str(d["_id"]),
                "mode": d.get("mode", "solve"),
                "title": d.get("title", ""),
                "last_message_preview": d.get("last_message_preview", ""),
                "message_count": int(d.get("message_count", 0)),
                "created_at": d["created_at"],
                "updated_at": d["updated_at"],
            }
            for d in docs
        ]
        return {"items": items}

    async def get_conversation_detail(
        self, conv_id: str, user_oid: ObjectId
    ) -> Optional[dict]:
        conv = await self.repo.get_conversation(conv_id, user_oid)
        if conv is None:
            return None
        messages = await self.repo.list_messages_for_conversation(conv["_id"])
        return {
            "id": str(conv["_id"]),
            "mode": conv.get("mode", "solve"),
            "title": conv.get("title", ""),
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "messages": [
                {
                    "id": str(m["_id"]),
                    "role": m["role"],
                    "text": m.get("text", ""),
                    "blocks": m.get("blocks", []),
                    "topic": m.get("topic"),
                    "insights": m.get("insights", []),
                    "complexity_mode": m.get("complexity_mode"),
                    "image_data_url": m.get("image_data_url"),
                    "created_at": m["created_at"],
                }
                for m in messages
            ],
        }

    async def delete_conversation(self, conv_id: str, user_oid: ObjectId) -> bool:
        return await self.repo.delete_conversation(conv_id, user_oid)
