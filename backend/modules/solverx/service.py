"""SolverX orchestrator.

Two LLM calls per question (plan → solve-streamed), interleaved with
status messages and a personalised-insight pass that reads the
student's existing mock-test analytics. The whole flow is exposed as a
single async-generator that the controller wraps in a Server-Sent
Events response.

Wire-protocol emitted to the client:

    event: status      data: {"phase": "...", "message": "..."}
    event: topic       data: {"subject": "...", "chapter": "...", ...}
    event: block       data: {"type": "...", "title": "...", "content": "..."}
    event: insights    data: {"items": [{"headline": "...", "detail": "..."}]}
    event: done        data: {"conversation_id": "...", "message_id": "..."}
    event: error       data: {"message": "..."}

The frontend `solverxService.streamSolve` listens for these events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.solverx.constants import (
    MODE_SOLVE,
    MODE_THEORY,
    STATUS_MESSAGES,
    THEORY_STATUS_MESSAGES,
)
from modules.solverx.llm import LLMError, chat_json, chat_stream
from modules.solverx.model import new_conversation_doc, new_message_doc
from modules.solverx.prompts import (
    BLOCK_CLOSE,
    BLOCK_OPEN,
    DIAGRAM_DRAFT_SYSTEM_PROMPT,
    DIAGRAM_POLISH_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    THEORY_PLAN_SYSTEM_PROMPT,
    diagram_draft_user_message,
    diagram_polish_user_message,
    plan_user_message,
    solve_system_prompt,
    solve_user_message,
    theory_system_prompt,
    theory_user_message,
)
from modules.solverx.repository import SolverXRepository

logger = logging.getLogger(__name__)


# Matches `[[BLOCK type=foo title="Bar"]]`. Title is optional.
_BLOCK_HEADER_RE = re.compile(
    r"\[\[BLOCK\s+type=([A-Za-z_]+)(?:\s+title=\"([^\"]*)\")?\s*\]\]"
)


# --------------------------------------------------------------------------
# JSON-extraction tolerance
# --------------------------------------------------------------------------

def _parse_plan_json(raw: str) -> dict[str, Any]:
    """Strip code fences and pull the first JSON object out of the text.

    Gemma occasionally wraps the JSON in ```json ... ``` fences despite
    being told not to. Cheaper to tolerate than to retry.
    """
    raw = raw.strip()
    # Strip surrounding ```json ... ``` if present.
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # Find the outermost {...} block.
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}


# --------------------------------------------------------------------------
# SSE helpers
# --------------------------------------------------------------------------

def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------
# Insight pass — reads existing mock-test analytics, never calls the LLM.
# --------------------------------------------------------------------------

async def _gather_personalisation(
    db: AsyncIOMotorDatabase, user_oid: ObjectId, topic_info: dict
) -> tuple[list[dict], str]:
    """Return (insights_for_client, personalisation_note_for_prompt).

    The note is folded into the SOLVE-stage system prompt so the model
    can lean weak/strong without us spending a separate LLM call.
    """
    try:
        # Local import to keep mock_test's heavy engine out of cold start.
        from modules.mock_test.service import MockTestService
        overview = await MockTestService(db).get_overview(user_oid)
    except Exception as exc:
        logger.debug("Personalisation lookup skipped: %s", exc)
        return [], ""

    items: list[dict] = []
    note_parts: list[str] = []

    accuracy_pct = getattr(overview, "overall_accuracy_pct", None)
    if accuracy_pct is not None and getattr(overview, "total_tests", 0) > 0:
        items.append({
            "headline": f"Overall accuracy: {accuracy_pct:.0f}%",
            "detail": (
                f"Across {overview.total_tests} mock tests "
                f"and {overview.total_questions} questions attempted."
            ),
            "accuracy_pct": float(accuracy_pct),
        })
        note_parts.append(
            f"Student overall accuracy is {accuracy_pct:.0f}% "
            f"over {overview.total_tests} tests."
        )

    weakest = list(getattr(overview, "weakest_topics", []) or [])[:3]
    if weakest:
        names = ", ".join(getattr(t, "topic_name", "") or "" for t in weakest if t)
        if names:
            items.append({
                "headline": "Focus areas to revisit",
                "detail": f"Weakest topics recently: {names}.",
            })
            note_parts.append(
                f"Weakest recent topics: {names}. If your explanation "
                "touches any of them, lean a little more intuitive."
            )

    # Topic-specific match: did the student already attempt this topic?
    topic_name = (topic_info.get("topic") or "").lower().strip()
    if topic_name:
        for t in (getattr(overview, "weakest_topics", []) or []):
            tn = (getattr(t, "topic_name", "") or "").lower().strip()
            if tn and tn == topic_name:
                acc = getattr(t, "accuracy_pct", 0.0)
                items.append({
                    "headline": "Heads up on this topic",
                    "detail": (
                        f"Your accuracy on {t.topic_name} is "
                        f"{acc:.0f}% — extra care here."
                    ),
                    "accuracy_pct": float(acc),
                })
                note_parts.append(
                    f"Student has weak accuracy ({acc:.0f}%) on this exact topic "
                    f"({t.topic_name}). Be especially patient."
                )
                break

    return items, " ".join(note_parts)


# --------------------------------------------------------------------------
# SVG extraction (defensive — the model sometimes adds preamble or a fence)
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"^\s*```(?:svg|html|xml)?\s*\n([\s\S]*?)\n```\s*$", re.IGNORECASE
)


def _extract_svg(raw: str) -> str | None:
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
    return text[start:end + 6]


async def _generate_diagram(
    *,
    question_text: str,
    topic_info: dict,
    image_data_url: Optional[str],
    user_content_fn,
) -> str | None:
    """Two-stage diagram pipeline: draft → polish.

    The draft agent produces a first-pass SVG with the strict style
    rules + worked example baked into its system prompt. The polish
    agent reviews that draft against the question and ships a corrected
    version. Both calls are non-streaming and short (~600 tokens).

    `user_content_fn` is `_user_content` from the service; we pass the
    multimodal content shape so the agent benefits from any uploaded
    image (e.g. a screenshot of the original textbook figure).
    """
    # ---- Draft ----
    try:
        draft_raw = await chat_json(
            [
                {"role": "system", "content": DIAGRAM_DRAFT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": user_content_fn(
                        diagram_draft_user_message(question_text, topic_info),
                        image_data_url,
                    ),
                },
            ],
            temperature=0.4,
            max_tokens=1200,
        )
    except LLMError as exc:
        logger.warning("Diagram draft failed: %s", exc)
        return None

    draft_svg = _extract_svg(draft_raw)
    if not draft_svg:
        return None

    # ---- Polish ----
    try:
        polish_raw = await chat_json(
            [
                {"role": "system", "content": DIAGRAM_POLISH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": user_content_fn(
                        diagram_polish_user_message(question_text, draft_svg),
                        image_data_url,
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=1400,
        )
    except LLMError as exc:
        # If polish fails, the draft is still useful — ship that.
        logger.warning("Diagram polish failed, falling back to draft: %s", exc)
        return draft_svg

    polished_svg = _extract_svg(polish_raw)
    # If polish produced something obviously broken, fall back to the
    # draft rather than a regression.
    return polished_svg or draft_svg


# --------------------------------------------------------------------------
# Streaming block parser
# --------------------------------------------------------------------------

async def _stream_blocks_from_llm(
    stream: AsyncIterator[str],
) -> AsyncIterator[dict[str, str]]:
    """Consume a streaming LLM response and yield a dict per completed
    block. Buffer everything between [[BLOCK …]] and [[END]]."""
    buf = ""
    open_match: re.Match | None = None
    block_start_idx: int = -1

    async for delta in stream:
        buf += delta
        # Look for new opens / closes in a loop in case multiple blocks
        # arrive in the same chunk.
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
            yield {
                "type": open_match.group(1),
                "title": open_match.group(2) or "",
                "content": content,
            }
            # Reset for the next block.
            buf = buf[close_pos + len(BLOCK_CLOSE):]
            open_match = None
            block_start_idx = -1


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------

class SolverXService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = SolverXRepository(db)

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

    # ------------------------------------------------------------------
    # Public: streaming solve + theory pipelines
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
        async for evt in self._run_pipeline(
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
        async for evt in self._run_pipeline(
            user_oid=user_oid,
            question_text=question_text,
            complexity_mode=complexity_mode,
            conversation_id=conversation_id,
            mode=MODE_THEORY,
            image_data_url=image_data_url,
        ):
            yield evt

    # ------------------------------------------------------------------
    # Pipeline (shared between solve + theory; prompts differ)
    # ------------------------------------------------------------------

    @staticmethod
    def _user_content(text: str, image_data_url: Optional[str]) -> Any:
        """Build the OpenAI-compatible `content` field.

        Plain string when there's no image (cheaper to encode, matches the
        majority case). When an image is attached we switch to the list-of-
        parts form — Llama 4 Scout via Groq accepts the same `image_url`
        shape OpenAI's vision endpoints use.
        """
        if not image_data_url:
            return text
        return [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]

    async def _run_pipeline(
        self,
        *,
        user_oid: ObjectId,
        question_text: str,
        complexity_mode: str,
        conversation_id: Optional[str],
        mode: str,
        image_data_url: Optional[str] = None,
    ) -> AsyncIterator[str]:
        is_theory = mode == MODE_THEORY
        status_script = THEORY_STATUS_MESSAGES if is_theory else STATUS_MESSAGES

        # Persist conversation + user message up front so the UI's
        # history list updates even if the LLM call fails mid-flight.
        try:
            conv_oid, created = await self._ensure_conversation(
                conversation_id=conversation_id,
                user_oid=user_oid,
                mode=mode,
                first_question=question_text,
            )
            await self.repo.create_message(
                new_message_doc(
                    conversation_id=conv_oid,
                    role="user",
                    text=question_text,
                    complexity_mode=complexity_mode,
                )
            )
            await self.repo.touch_conversation(
                conv_oid, last_preview=question_text, increment_messages=1
            )
            yield _sse(
                "conversation",
                {"conversation_id": str(conv_oid), "created": created},
            )
        except Exception as exc:
            logger.exception("Failed to persist conversation: %s", exc)
            yield _sse("error", {"message": "Could not start conversation."})
            return

        try:
            # ---- PLAN ----
            yield _sse("status", {"phase": "plan", "message": status_script["plan_start"]})
            plan_system = THEORY_PLAN_SYSTEM_PROMPT if is_theory else PLAN_SYSTEM_PROMPT
            try:
                plan_raw = await chat_json(
                    [
                        {"role": "system", "content": plan_system},
                        {
                            "role": "user",
                            "content": self._user_content(
                                plan_user_message(question_text),
                                image_data_url,
                            ),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=600,
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
                "visual_needed": bool(plan.get("visual_needed", False)),
            }
            yield _sse("topic", topic_payload)
            yield _sse("status", {"phase": "plan_done", "message": status_script["plan_done"]})

            # ---- DIAGRAM (background, parallel with solve) ----
            # Kick off the Visual Reasoning + Refactor pipeline now so it
            # runs alongside the solve stream — by the time the steps
            # finish streaming, the diagram is usually ready.
            diagram_task: Optional[asyncio.Task] = None
            if topic_payload["visual_needed"] or image_data_url:
                diagram_task = asyncio.create_task(
                    _generate_diagram(
                        question_text=question_text,
                        topic_info=topic_payload,
                        image_data_url=image_data_url,
                        user_content_fn=self._user_content,
                    )
                )
                yield _sse(
                    "status",
                    {"phase": "diagram_draft", "message": status_script["diagram_draft"]},
                )

            # ---- INSIGHTS (no LLM call) ----
            yield _sse("status", {"phase": "insight", "message": status_script["insight"]})
            insights, personalisation_note = await _gather_personalisation(
                self.db, user_oid, topic_payload,
            )
            if insights:
                yield _sse("insights", {"items": insights})

            # ---- SOLVE (streamed) ----
            yield _sse("status", {"phase": "solve", "message": status_script["solve_start"]})
            plan_steps = list(plan.get("plan_steps") or [])

            if is_theory:
                solve_sys = theory_system_prompt(
                    plan_steps=plan_steps,
                    complexity_mode=complexity_mode,
                    personalisation_note=personalisation_note,
                )
                solve_user = theory_user_message(question_text)
            else:
                solve_sys = solve_system_prompt(
                    plan_steps=plan_steps,
                    complexity_mode=complexity_mode,
                    personalisation_note=personalisation_note,
                )
                solve_user = solve_user_message(question_text)

            collected_blocks: list[dict[str, str]] = []
            try:
                raw_stream = chat_stream(
                    [
                        {"role": "system", "content": solve_sys},
                        {
                            "role": "user",
                            "content": self._user_content(solve_user, image_data_url),
                        },
                    ],
                    temperature=0.6,
                    max_tokens=4000,
                )
                progress_announced = False
                async for block in _stream_blocks_from_llm(raw_stream):
                    # The dedicated Visual Reasoning agent owns diagram
                    # generation now. If the solve model still emits a
                    # `diagram` block despite being told not to, drop it
                    # — its quality is markedly lower than the agent's.
                    if block.get("type") == "diagram":
                        continue
                    if not progress_announced and len(collected_blocks) >= 1:
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
                    # Tiny breather so the client UI gets to paint between
                    # bursts that arrive in the same network frame.
                    await asyncio.sleep(0)
            except LLMError as exc:
                logger.warning("Solve stage failed: %s", exc)
                yield _sse(
                    "error",
                    {"message": "The reasoning engine is busy. Please retry in a moment."},
                )
                if diagram_task is not None:
                    diagram_task.cancel()
                return

            # ---- DIAGRAM (await the background task started after plan) ----
            if diagram_task is not None:
                yield _sse(
                    "status",
                    {"phase": "diagram_polish", "message": status_script["diagram_polish"]},
                )
                try:
                    svg_markup = await diagram_task
                except Exception as exc:
                    logger.warning("Diagram task crashed: %s", exc)
                    svg_markup = None
                if svg_markup:
                    diagram_block = {
                        "type": "diagram",
                        "title": "Diagram",
                        "content": svg_markup,
                    }
                    collected_blocks.append(diagram_block)
                    yield _sse("block", diagram_block)

            # ---- Persist assistant message ----
            assistant_text = "\n\n".join(b.get("content", "") for b in collected_blocks)
            msg_oid = await self.repo.create_message(
                new_message_doc(
                    conversation_id=conv_oid,
                    role="assistant",
                    text=assistant_text,
                    blocks=collected_blocks,
                    topic=topic_payload,
                    insights=insights,
                    complexity_mode=complexity_mode,
                )
            )
            await self.repo.touch_conversation(
                conv_oid,
                last_preview=assistant_text or question_text,
                increment_messages=1,
            )

            yield _sse(
                "done",
                {
                    "conversation_id": str(conv_oid),
                    "message_id": str(msg_oid),
                    "block_count": len(collected_blocks),
                },
            )
        except Exception as exc:
            logger.exception("SolverX pipeline crashed: %s", exc)
            yield _sse("error", {"message": "Something went wrong on our side. Please retry."})

    # ------------------------------------------------------------------
    # Non-streaming list / detail
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
        self, conv_id: str, user_oid: ObjectId,
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
                    "created_at": m["created_at"],
                }
                for m in messages
            ],
        }
