"""Thin async Vertex AI (Gemini) client used by the SolverX pipeline.

Uses the unified `google-genai` SDK in Vertex AI mode. Authentication
is discovered automatically via Application Default Credentials (ADC) —
on developer machines that comes from
`gcloud auth application-default login`; on Cloud Run / GKE the runtime
identity is bound automatically. No JSON key needs to live on disk.

Two entrypoints, signatures designed so the service layer can pass the
exact model ID for each agent in the pipeline (Pro / Flash / Flash-Lite):

  * `chat_json(messages, *, model, …)`   — non-streaming → str
  * `chat_stream(messages, *, model, …)` — async generator → str deltas

Both raise `LLMError` on transport / auth / quota failures so the
orchestrator can fall back gracefully.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from typing import Any, AsyncIterator, Optional

from google import genai
from google.genai import types as genai_types

from config.settings import settings
from core.usage_events import get_usage_context, record_event

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised on any Vertex AI failure (transport, auth, quota, …)."""


# ---------------------------------------------------------------------------
# Client singleton.
# Built lazily so importing this module never fails — useful when running
# unrelated CLI commands on a machine that hasn't run `gcloud auth …` yet.
# ---------------------------------------------------------------------------

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GCP_PROJECT_ID:
            raise LLMError(
                "GCP_PROJECT_ID is not configured. Set it in backend/.env"
            )
        try:
            _client = genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=settings.GCP_LOCATION or "global",
            )
        except Exception as exc:  # noqa: BLE001 — opaque SDK init failure
            raise LLMError(f"Vertex AI client init failed: {exc}") from exc
    return _client


# ---------------------------------------------------------------------------
# OpenAI → Gemini message converter.
#
# The service layer was originally built around OpenAI's chat-completion
# shape (role: system|user|assistant, content: str | [{type:…, …}]).
# Rather than rewrite every call site, we accept that shape here and
# translate it on the way to Vertex AI:
#   * `system` messages → concatenated into `system_instruction`
#   * `assistant` role  → `model` (Gemini's name for the same thing)
#   * text/image_url content parts → google-genai `Part` objects
# ---------------------------------------------------------------------------

# A `data:image/...;base64,...` URL — what the frontend uploads through
# the multimodal text-and-image SolverX flow.
_DATA_URL_RE = re.compile(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.+)$")


def _part_from_image_data_url(url: str) -> genai_types.Part:
    m = _DATA_URL_RE.match(url)
    if not m:
        raise LLMError(
            "Unsupported image URL — expected data:image/...;base64,…"
        )
    mime, b64 = m.group(1), m.group(2)
    return genai_types.Part.from_bytes(
        data=base64.b64decode(b64),
        mime_type=mime,
    )


def _to_parts(content: Any) -> list[genai_types.Part]:
    """Convert OpenAI-style `content` (str or list of parts) → Gemini Parts."""
    if content is None:
        return [genai_types.Part.from_text(text="")]
    if isinstance(content, str):
        return [genai_types.Part.from_text(text=content)]
    parts: list[genai_types.Part] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append(genai_types.Part.from_text(text=str(item)))
            continue
        ptype = item.get("type")
        if ptype == "text":
            parts.append(genai_types.Part.from_text(text=item.get("text", "")))
        elif ptype == "image_url":
            url = (item.get("image_url") or {}).get("url", "")
            if url:
                parts.append(_part_from_image_data_url(url))
        else:
            # Unknown part type — keep the conversation alive by
            # stringifying. Logging keeps the surprise visible.
            logger.debug("Unknown content part type %r, stringifying", ptype)
            parts.append(genai_types.Part.from_text(text=str(item)))
    return parts or [genai_types.Part.from_text(text="")]


def _convert_messages(
    messages: list[dict[str, Any]],
) -> tuple[Optional[str], list[genai_types.Content]]:
    """Split incoming messages into (system_instruction, gemini_contents).

    Multiple system messages are concatenated with a blank line. Roles
    `assistant` and `model` both map to `model`; everything else maps
    to `user`.
    """
    system_chunks: list[str] = []
    contents: list[genai_types.Content] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            c = m.get("content")
            if isinstance(c, str):
                system_chunks.append(c)
            elif isinstance(c, list):
                for item in c:
                    if isinstance(item, dict) and item.get("type") == "text":
                        system_chunks.append(item.get("text", ""))
            continue
        gemini_role = "model" if role in ("assistant", "model") else "user"
        contents.append(
            genai_types.Content(
                role=gemini_role,
                parts=_to_parts(m.get("content")),
            )
        )
    system_instruction = "\n\n".join(s for s in system_chunks if s) or None
    return system_instruction, contents


def _build_config(
    *,
    system_instruction: Optional[str],
    temperature: float,
    max_tokens: Optional[int],
    response_mime: Optional[str] = None,
    disable_thinking: bool = False,
) -> genai_types.GenerateContentConfig:
    kwargs: dict[str, Any] = {"temperature": temperature}
    if max_tokens:
        kwargs["max_output_tokens"] = max_tokens
    if response_mime:
        kwargs["response_mime_type"] = response_mime
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    if disable_thinking:
        # Gemini 2.5/3.x models default to "extended thinking" — invisible
        # reasoning tokens that count against `max_output_tokens`. For
        # recipe-following tasks (SVG / TikZ generation) thinking is pure
        # overhead and frequently consumes the entire budget, leaving the
        # response empty. Force budget=0 to make the model emit text
        # directly. `include_thoughts=False` is belt-and-braces.
        kwargs["thinking_config"] = genai_types.ThinkingConfig(
            thinking_budget=0,
            include_thoughts=False,
        )
    return genai_types.GenerateContentConfig(**kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def chat_json(
    messages: list[dict[str, Any]],
    *,
    model: str,
    temperature: float = 0.3,
    max_tokens: Optional[int] = 1500,
    response_mime: Optional[str] = None,
    disable_thinking: bool = False,
) -> str:
    """Non-streaming call. Returns the model's text content.

    `response_mime="application/json"` puts the model in strict-JSON mode.
    `disable_thinking=True` turns off Gemini's extended-thinking budget —
    use it for recipe-following tasks (e.g. SVG / TikZ generation) where
    invisible reasoning tokens would otherwise eat the whole budget and
    leave the response empty.
    """
    started = time.monotonic()
    try:
        client = _get_client()
        sys_instr, contents = _convert_messages(messages)
        cfg = _build_config(
            system_instruction=sys_instr,
            temperature=temperature,
            max_tokens=max_tokens,
            response_mime=response_mime,
            disable_thinking=disable_thinking,
        )
        res = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=cfg,
        )
        # Surface finish_reason + usage_metadata + text length on every
        # call. Lets "why was the response empty?" be a one-line glance
        # at the log instead of guesswork.
        try:
            candidates = getattr(res, "candidates", None) or []
            finish = (
                getattr(candidates[0], "finish_reason", None)
                if candidates else None
            )
            usage = getattr(res, "usage_metadata", None)
            logger.info(
                "Vertex AI chat_json (%s) finish_reason=%s usage=%s text_len=%d",
                model,
                finish,
                usage,
                len(res.text or ""),
            )
        except Exception:  # noqa: BLE001 — diagnostics only
            pass
        await _record_call(
            model=model,
            usage_metadata=getattr(res, "usage_metadata", None),
            started=started,
            status="ok",
        )
        return res.text or ""
    except LLMError:
        await _record_call(model=model, usage_metadata=None, started=started,
                           status="error", error="LLMError")
        raise
    except Exception as exc:  # noqa: BLE001 — opaque SDK errors
        logger.warning("Vertex AI non-stream error (%s): %s", model, exc)
        await _record_call(model=model, usage_metadata=None, started=started,
                           status="error", error=str(exc)[:200])
        raise LLMError(f"Vertex AI error: {exc}") from exc


async def chat_stream(
    messages: list[dict[str, Any]],
    *,
    model: str,
    temperature: float = 0.5,
    max_tokens: Optional[int] = 6000,
) -> AsyncIterator[str]:
    """Streaming call. Yields content deltas as they arrive.

    The SDK returns an async iterator of `GenerateContentResponse`
    chunks; each `.text` is the next slice of generated text.
    """
    started = time.monotonic()
    last_chunk = None
    try:
        client = _get_client()
        sys_instr, contents = _convert_messages(messages)
        cfg = _build_config(
            system_instruction=sys_instr,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        stream = await client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config=cfg,
        )
        async for chunk in stream:
            last_chunk = chunk
            text = getattr(chunk, "text", None)
            if text:
                yield text

        # Surface why the stream ended. If `finish_reason` is anything
        # other than "STOP" the model didn't finish on its own (truncated
        # by MAX_TOKENS, killed by SAFETY, RECITATION, etc.) and we need
        # to know to fix budgets / prompts.
        try:
            candidates = getattr(last_chunk, "candidates", None) or []
            if candidates:
                finish_reason = getattr(candidates[0], "finish_reason", None)
                usage = getattr(last_chunk, "usage_metadata", None)
                if finish_reason and str(finish_reason).split(".")[-1] not in ("STOP", "FINISH_REASON_STOP"):
                    logger.warning(
                        "Vertex AI stream (%s) ended with finish_reason=%s usage=%s",
                        model,
                        finish_reason,
                        usage,
                    )
                else:
                    logger.info(
                        "Vertex AI stream (%s) finished normally; usage=%s",
                        model,
                        usage,
                    )
        except Exception:  # noqa: BLE001 — diagnostics only
            pass
        await _record_call(
            model=model,
            usage_metadata=getattr(last_chunk, "usage_metadata", None),
            started=started,
            status="ok",
        )
    except LLMError:
        await _record_call(model=model, usage_metadata=None, started=started,
                           status="error", error="LLMError")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vertex AI stream error (%s): %s", model, exc)
        await _record_call(model=model, usage_metadata=None, started=started,
                           status="error", error=str(exc)[:200])
        raise LLMError(f"Vertex AI stream error: {exc}") from exc


async def _record_call(
    *,
    model: str,
    usage_metadata: Any,
    started: float,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Pull token counts off the Vertex usage_metadata object and write a
    usage_events row via whatever context was set up by the caller.
    No-op if the caller didn't open a `usage_context(...)`."""
    ctx = get_usage_context()
    if not ctx:
        return
    prompt = getattr(usage_metadata, "prompt_token_count", 0) or 0
    out = getattr(usage_metadata, "candidates_token_count", 0) or 0
    await record_event(
        ctx["db"],
        source=ctx.get("source") or "solverx",
        user_id=ctx.get("user_id"),
        model=model,
        input_tokens=int(prompt),
        output_tokens=int(out),
        duration_ms=int((time.monotonic() - started) * 1000),
        status=status,
        error=error,
        extra=ctx.get("extra") or {},
    )
