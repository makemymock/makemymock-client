"""LLM access for the mining agents.

Every agent is a single-shot, strict-JSON reducer (no tool use, no streaming),
so they all funnel through one helper: `chat_json`. It wraps the backend's
Vertex AI client (`modules.solverx.llm`) — the same ADC auth, the same model
IDs — and adds the two things the agents need on top:

  * the OpenAI-shape system+user message the agents think in, and
  * a per-agent metrics record (call count + latency) for the run summary.

`disable_thinking=True` on every call is deliberate: these are structured-output
reducers, not reasoning chains, so Gemini's invisible thinking tokens are pure
overhead — exactly the case the SolverX client added the flag for.
"""

from __future__ import annotations

import time

from modules.solverx.llm import LLMError, chat_json as _vertex_chat_json
from modules.pattern_miner.metrics import metrics

__all__ = ["LLMError", "chat_json"]


async def chat_json(
    prompt: str,
    *,
    agent: str,
    model: str,
    system: str = "",
    temperature: float = 0.1,
    max_tokens: int = 2000,
) -> str:
    """Run one strict-JSON completion and return the raw text.

    `agent` is only a label for the metrics row. Raises `LLMError` (re-exported
    from the SolverX client) on any transport / auth / quota failure so callers
    can fall back to a "none" verdict.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    t0 = time.monotonic()
    try:
        text = await _vertex_chat_json(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_mime="application/json",
            disable_thinking=True,
        )
        metrics.record_llm_call(
            agent=agent, ok=True, latency_ms=int((time.monotonic() - t0) * 1000),
        )
        return text
    except Exception:
        metrics.record_llm_call(
            agent=agent, ok=False, latency_ms=int((time.monotonic() - t0) * 1000),
        )
        raise
