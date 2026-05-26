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
# Insight pass — reads mock-test analytics, never calls the LLM.
# ---------------------------------------------------------------------------


async def _gather_personalisation(
    db: AsyncIOMotorDatabase,
    user_oid: ObjectId,
    topic_info: dict,
) -> tuple[list[dict], str]:
    try:
        from modules.mock_test.service import MockTestService

        overview = await MockTestService(db).get_overview(user_oid)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Personalisation lookup skipped: %s", exc)
        return [], ""

    items: list[dict] = []
    note_parts: list[str] = []

    accuracy_pct = getattr(overview, "overall_accuracy_pct", None)
    if accuracy_pct is not None and getattr(overview, "total_tests", 0) > 0:
        items.append(
            {
                "headline": f"Overall accuracy: {accuracy_pct:.0f}%",
                "detail": (
                    f"Across {overview.total_tests} mock tests and "
                    f"{overview.total_questions} questions attempted."
                ),
                "accuracy_pct": float(accuracy_pct),
            }
        )
        note_parts.append(
            f"Student overall accuracy is {accuracy_pct:.0f}% "
            f"over {overview.total_tests} tests."
        )

    weakest = list(getattr(overview, "weakest_topics", []) or [])[:3]
    if weakest:
        names = ", ".join(
            getattr(t, "topic_name", "") or "" for t in weakest if t
        )
        if names:
            items.append(
                {
                    "headline": "Focus areas to revisit",
                    "detail": f"Weakest topics recently: {names}.",
                }
            )
            note_parts.append(
                f"Weakest recent topics: {names}. If your explanation "
                "touches any of them, lean a little more intuitive."
            )

    topic_name = (topic_info.get("topic") or "").lower().strip()
    if topic_name:
        for t in getattr(overview, "weakest_topics", []) or []:
            tn = (getattr(t, "topic_name", "") or "").lower().strip()
            if tn and tn == topic_name:
                acc = getattr(t, "accuracy_pct", 0.0)
                items.append(
                    {
                        "headline": "Heads up on this topic",
                        "detail": (
                            f"Your accuracy on {t.topic_name} is "
                            f"{acc:.0f}% — extra care here."
                        ),
                        "accuracy_pct": float(acc),
                    }
                )
                note_parts.append(
                    f"Student has weak accuracy ({acc:.0f}%) on this exact "
                    f"topic ({t.topic_name}). Be especially patient."
                )
                break

    return items, " ".join(note_parts)


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
    """If `content` contains nested `[[BLOCK type=diagram_pending …]]`
    placeholders, split the parent block into alternating
    (parent-text, diagram, parent-text, …) emissions so the diagram
    appears at roughly the right spot in the transcript.

    If no nested diagrams are found, returns a single-element list with
    the parent block as-is.
    """
    matches = list(_NESTED_DIAGRAM_RE.finditer(content))
    if not matches:
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
    for m in matches:
        emit_parent_chunk(content[cursor : m.start()])
        out.append(
            _build_block_from_match(
                "diagram_pending",
                m.group("attrs") or "",
                "",
            )
        )
        cursor = m.end()
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

        # ---- INSIGHTS (no LLM) ----
        yield _sse(
            "status", {"phase": "insight", "message": status_script["insight"]}
        )
        insights, personalisation_note = await _gather_personalisation(
            self.db, user_oid, topic_payload
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

                # Drop a bare `diagram` block — only `diagram_pending` is
                # honoured in the new protocol.
                if btype == "diagram":
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
