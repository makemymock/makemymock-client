"""
Async Groq client for the JEE Recommender agentic layer.

Provides two entrypoints:

  chat_json(prompt, *, model, system)
    — Single-turn call. Returns the model's text response as a string.
      Use for simple completions where no tool use is needed.

  chat_with_tools(messages, tools, *, model, max_tool_rounds)
    — Multi-turn tool-use loop. Executes tool calls by dispatching to
      registered Python callables, appends results, and loops until the
      model stops requesting tools or max_tool_rounds is reached.
      Returns (final_text, list_of_tool_calls_made).

Both raise GroqClientError on API/network failures so callers can
surface them as RecommenderAgentError HTTP 502s.

Authentication: reads GROQ_API_KEY from config.settings.settings.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Optional

from groq import AsyncGroq
from groq import APIError as GroqAPIError

from config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class GroqClientError(RuntimeError):
    """Raised on any Groq API failure (auth, quota, network, malformed response)."""


# ---------------------------------------------------------------------------
# Tool call dispatcher type
# ---------------------------------------------------------------------------

# A tool executor is an async function that accepts (tool_name, args_dict)
# and returns a JSON-serializable result dict.
ToolExecutor = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


# ---------------------------------------------------------------------------
# Lazy singleton client
# ---------------------------------------------------------------------------

_client: Optional[AsyncGroq] = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        if not settings.GROQ_API_KEY:
            raise GroqClientError(
                "GROQ_API_KEY is not set. Add it to backend/.env to use agents."
            )
        _client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def chat_json(
    prompt: str,
    *,
    model: str,
    system: str = "",
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    """
    Single-turn completion. Returns the model's raw text response.

    Use this for lightweight tasks where the model only needs to emit text
    (e.g., interpreting a trend anomaly, generating a short note).
    """
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        logger.info(
            "Groq chat_json model=%s tokens_used=%s",
            model,
            getattr(response.usage, "total_tokens", "?"),
        )
        return text
    except GroqAPIError as exc:
        logger.warning("Groq API error in chat_json: %s", exc)
        raise GroqClientError(f"Groq API error: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected Groq error in chat_json: %s", exc)
        raise GroqClientError(f"Groq unexpected error: {exc}") from exc


async def chat_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    *,
    model: str,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    max_tool_rounds: int = 6,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Agentic tool-use loop.

    Sends messages + tool definitions to the model. If the model requests
    tool calls, executes them via tool_executor, appends results, and loops.
    Stops when the model produces a final text response or max_tool_rounds
    is exhausted.

    Parameters
    ----------
    messages      : OpenAI-style chat messages (system / user / assistant / tool).
    tools         : Groq tool definitions — list of {type: "function", function: {...}}.
    tool_executor : async callable(tool_name, args) → JSON-serializable result.
    model         : Groq model ID.
    max_tool_rounds: Safety limit to prevent infinite loops.

    Returns
    -------
    (final_text, tool_calls_log)
    final_text     — the model's last text response (after all tool rounds).
    tool_calls_log — list of {name, args, result} dicts for debugging/audit.
    """
    client = _get_client()
    conversation = list(messages)
    tool_calls_log: list[dict[str, Any]] = []

    for round_num in range(max_tool_rounds):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=conversation,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                tool_choice="auto",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except GroqAPIError as exc:
            logger.warning("Groq API error in tool round %d: %s", round_num, exc)
            raise GroqClientError(f"Groq API error (round {round_num}): {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise GroqClientError(f"Groq unexpected error (round {round_num}): {exc}") from exc

        choice = response.choices[0]
        assistant_message = choice.message

        logger.info(
            "Groq tool loop round=%d model=%s finish=%s tool_calls=%d tokens=%s",
            round_num,
            model,
            choice.finish_reason,
            len(assistant_message.tool_calls or []),
            getattr(response.usage, "total_tokens", "?"),
        )

        has_tool_calls = bool(assistant_message.tool_calls)

        # finish=length with no tool calls means the JSON response was truncated —
        # raise so the caller's fallback kicks in cleanly.
        if choice.finish_reason == "length" and not has_tool_calls:
            raise GroqClientError(
                f"Model response truncated (finish=length) on round {round_num}. "
                "Increase max_tokens or shorten the prompt."
            )

        # If the model is done, return the final text
        if choice.finish_reason == "stop" or not has_tool_calls:
            return (assistant_message.content or ""), tool_calls_log

        # Append the assistant's tool-call message to conversation
        conversation.append({
            "role": "assistant",
            "content": assistant_message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_message.tool_calls
            ],
        })

        # Execute each tool call and append results
        for tc in assistant_message.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            try:
                result = await tool_executor(tool_name, args)
                result_str = json.dumps(result, default=str)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tool %r raised: %s", tool_name, exc)
                result_str = json.dumps({"error": str(exc)})
                result = {"error": str(exc)}

            tool_calls_log.append({"name": tool_name, "args": args, "result": result})
            conversation.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

    # max_tool_rounds exceeded — return whatever the last assistant message was
    logger.warning("Groq tool loop hit max_tool_rounds=%d for model=%s", max_tool_rounds, model)
    last_content = ""
    for msg in reversed(conversation):
        if msg.get("role") == "assistant" and msg.get("content"):
            last_content = msg["content"]
            break
    return last_content, tool_calls_log
