"""Thin async Groq client.

Groq is OpenAI-compatible at `/openai/v1`, so we just hit
`/chat/completions` with the usual payload. We don't pull in the `groq`
or `openai` SDK — those are heavy dependencies for two endpoints, and
httpx (already in requirements) gives us first-class async streaming.

Two entrypoints:
  * `chat_json()`       — non-streaming, returns the assistant string.
  * `chat_stream()`     — async generator that yields content deltas as
                          they arrive over SSE.

Both raise `LLMError` on transport / auth failures so the service can
fall back gracefully (we keep the conversation responsive even when the
free tier rate-limits or 5xxs).
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from config.settings import settings
from modules.solverx.constants import (
    GROQ_BASE_URL,
    GROQ_REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not settings.GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not configured.")
    return {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }


def _payload(
    messages: list[dict[str, Any]],
    *,
    temperature: float,
    max_tokens: int | None,
    stream: bool,
    response_format: dict | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": settings.GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if max_tokens:
        # Groq names this `max_completion_tokens`; the older `max_tokens`
        # is still accepted but deprecated. Use the current name.
        body["max_completion_tokens"] = max_tokens
    if response_format:
        body["response_format"] = response_format
    return body


async def chat_json(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.3,
    max_tokens: int | None = 1500,
) -> str:
    """Non-streaming call. Returns the assistant message content."""
    url = f"{GROQ_BASE_URL}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=GROQ_REQUEST_TIMEOUT) as client:
            res = await client.post(
                url,
                headers=_headers(),
                json=_payload(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                ),
            )
        if res.status_code >= 400:
            logger.warning(
                "Groq non-stream error %s: %s", res.status_code, res.text[:500]
            )
            raise LLMError(f"Groq responded {res.status_code}")
        data = res.json()
        return data["choices"][0]["message"]["content"]
    except httpx.HTTPError as exc:
        raise LLMError(f"Groq transport error: {exc}") from exc


async def chat_stream(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.5,
    max_tokens: int | None = 4000,
) -> AsyncIterator[str]:
    """Streaming call. Yields content deltas as they arrive.

    Groq sends SSE in the standard OpenAI shape:
        data: {"choices":[{"delta":{"content":"hello"},...}]}
        data: [DONE]
    """
    url = f"{GROQ_BASE_URL}/chat/completions"
    timeout = httpx.Timeout(GROQ_REQUEST_TIMEOUT, read=None)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                url,
                headers=_headers(),
                json=_payload(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                ),
            ) as res:
                if res.status_code >= 400:
                    body = await res.aread()
                    logger.warning(
                        "Groq stream error %s: %s",
                        res.status_code, body[:500].decode(errors="replace"),
                    )
                    raise LLMError(f"Groq responded {res.status_code}")

                async for line in res.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {}).get("content")
                    if delta:
                        yield delta
    except httpx.HTTPError as exc:
        raise LLMError(f"Groq transport error: {exc}") from exc
