"""
Async Vertex AI (Gemini) client for the JEE Recommender agentic layer.

Mirrors the groq_client interface so agents.py needs only import changes:

  chat_json(prompt, *, model, system, temperature, max_tokens) -> str
  chat_with_tools(messages, tools, tool_executor, *, model, ...) -> (str, [calls])

Uses Application Default Credentials (ADC) — same auth as SolverX/llm.py.
On dev machines: `gcloud auth application-default login`.
On Cloud Run: runtime-bound service account identity.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Optional

from google import genai
from google.genai import types as genai_types

from config.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class GeminiClientError(RuntimeError):
    """Raised on any Vertex AI failure (auth, quota, network, truncation)."""


# ---------------------------------------------------------------------------
# Tool executor type — same contract as groq_client
# ---------------------------------------------------------------------------

ToolExecutor = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


# ---------------------------------------------------------------------------
# Lazy singleton client
# ---------------------------------------------------------------------------

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GCP_PROJECT_ID:
            raise GeminiClientError(
                "GCP_PROJECT_ID is not set. Add it to backend/.env."
            )
        try:
            _client = genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=settings.GCP_LOCATION or "global",
            )
        except Exception as exc:
            raise GeminiClientError(f"Vertex AI client init failed: {exc}") from exc
    return _client


# ---------------------------------------------------------------------------
# OpenAI → Gemini tool schema converter
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, genai_types.Type] = {
    "string":  genai_types.Type.STRING,
    "number":  genai_types.Type.NUMBER,
    "integer": genai_types.Type.INTEGER,
    "boolean": genai_types.Type.BOOLEAN,
    "array":   genai_types.Type.ARRAY,
    "object":  genai_types.Type.OBJECT,
}


def _json_schema_to_gemini(schema: dict[str, Any]) -> genai_types.Schema:
    """Recursively convert a JSON Schema dict to a Gemini Schema."""
    raw_type = schema.get("type", "string")
    gtype = _TYPE_MAP.get(raw_type, genai_types.Type.STRING)
    kwargs: dict[str, Any] = {"type": gtype}

    if "description" in schema:
        kwargs["description"] = schema["description"]

    if gtype == genai_types.Type.OBJECT:
        props_raw = schema.get("properties") or {}
        if props_raw:
            kwargs["properties"] = {
                k: _json_schema_to_gemini(v) for k, v in props_raw.items()
            }
        if schema.get("required"):
            kwargs["required"] = schema["required"]

    elif gtype == genai_types.Type.ARRAY:
        items = schema.get("items")
        if items:
            kwargs["items"] = _json_schema_to_gemini(items)

    return genai_types.Schema(**kwargs)


def _openai_tools_to_gemini(
    tools: list[dict[str, Any]],
) -> list[genai_types.Tool]:
    """Convert OpenAI-style tool definitions to a Gemini Tool list."""
    declarations: list[genai_types.FunctionDeclaration] = []
    for tool in tools:
        fn = tool.get("function", {})
        params_raw = fn.get("parameters") or {}
        params_schema = _json_schema_to_gemini(params_raw) if params_raw else None
        declarations.append(
            genai_types.FunctionDeclaration(
                name=fn["name"],
                description=fn.get("description", ""),
                parameters=params_schema,
            )
        )
    return [genai_types.Tool(function_declarations=declarations)]


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------

def _make_config(
    *,
    system_instruction: Optional[str],
    temperature: float,
    max_tokens: int,
    thinking_budget: int = 0,
    include_thoughts: bool = False,
    tools: Optional[list[genai_types.Tool]] = None,
) -> genai_types.GenerateContentConfig:
    kwargs: dict[str, Any] = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "thinking_config": genai_types.ThinkingConfig(
            thinking_budget=thinking_budget,
            # Only expose thoughts when explicitly requested AND budget is non-zero
            include_thoughts=include_thoughts and thinking_budget > 0,
        ),
    }
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    if tools:
        kwargs["tools"] = tools
    return genai_types.GenerateContentConfig(**kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def chat_json(
    prompt: str,
    *,
    model: str,
    system: str = "",
    temperature: float = 0.2,
    max_tokens: int = 256,
) -> str:
    """
    Single-turn completion. Returns the model's raw text response.

    Thinking is disabled (budget=0) — for selection / scoring tasks
    where invisible reasoning tokens would consume the whole budget.
    """
    contents = [
        genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=prompt)],
        )
    ]
    cfg = _make_config(
        system_instruction=system or None,
        temperature=temperature,
        max_tokens=max_tokens,
        thinking_budget=0,
    )
    try:
        client = _get_client()
        res = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=cfg,
        )
        text = res.text or ""
        logger.info("Gemini chat_json model=%s text_len=%d", model, len(text))
        return text
    except GeminiClientError:
        raise
    except Exception as exc:
        logger.warning("Gemini chat_json error (%s): %s", model, exc)
        raise GeminiClientError(f"Gemini error: {exc}") from exc


async def chat_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    *,
    model: str,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    max_tool_rounds: int = 6,
    thinking_budget: int = 512,
    on_tool_result: Optional[Callable[[int, str, dict, Any], Coroutine[Any, Any, None]]] = None,
    on_thought: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Agentic tool-use loop using Gemini native function calling.

    Converts OpenAI-style tool definitions to Gemini FunctionDeclarations,
    executes tool calls via tool_executor, and loops until the model emits
    a final text response or max_tool_rounds is exhausted.

    Returns (final_text, tool_calls_log).
    """
    # Split messages into system instruction + conversation contents
    system_chunks: list[str] = []
    contents: list[genai_types.Content] = []
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            if m.get("content"):
                system_chunks.append(m["content"])
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append(
            genai_types.Content(
                role=gemini_role,
                parts=[genai_types.Part.from_text(text=m.get("content") or "")],
            )
        )

    system_instruction = "\n\n".join(system_chunks) or None
    gemini_tools = _openai_tools_to_gemini(tools)
    tool_calls_log: list[dict[str, Any]] = []
    client = _get_client()

    for round_num in range(max_tool_rounds):
        cfg = _make_config(
            system_instruction=system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            include_thoughts=on_thought is not None,
            tools=gemini_tools,
        )
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=cfg,
            )
        except Exception as exc:
            raise GeminiClientError(
                f"Gemini API error (round {round_num}): {exc}"
            ) from exc

        if not response.candidates:
            raise GeminiClientError(f"No candidates returned (round {round_num})")

        candidate = response.candidates[0]
        finish_reason = str(getattr(candidate, "finish_reason", "")).split(".")[-1]
        content = candidate.content

        # Separate thought / function-call / text parts
        function_calls: list[Any] = []
        text_parts: list[str] = []
        for part in content.parts or []:
            if getattr(part, "thought", False):
                thought_text = getattr(part, "text", "") or ""
                if thought_text and on_thought:
                    try:
                        await on_thought(thought_text)
                    except Exception as _te:
                        logger.debug("on_thought callback raised: %s", _te)
                continue
            if getattr(part, "function_call", None):
                function_calls.append(part.function_call)
            elif getattr(part, "text", None):
                text_parts.append(part.text)

        logger.info(
            "Gemini tool loop round=%d model=%s finish=%s tool_calls=%d tokens=%s",
            round_num,
            model,
            finish_reason,
            len(function_calls),
            getattr(getattr(response, "usage_metadata", None), "total_token_count", "?"),
        )

        # Truncated with no tool calls — the JSON response was cut off
        if finish_reason == "MAX_TOKENS" and not function_calls:
            raise GeminiClientError(
                f"Response truncated (MAX_TOKENS) on round {round_num}. "
                "Increase max_tokens."
            )

        # No function calls — model produced its final answer
        if not function_calls:
            return "\n".join(text_parts), tool_calls_log

        # Append the model's turn (with function calls) to the conversation
        contents.append(content)

        # Execute every function call, collect results
        response_parts: list[genai_types.Part] = []
        for fc in function_calls:
            tool_name = fc.name
            # fc.args is a dict-like Struct; normalise to plain dict
            try:
                args: dict[str, Any] = (
                    dict(fc.args) if fc.args else {}
                )
            except Exception:
                args = {}

            try:
                result = await tool_executor(tool_name, args)
            except Exception as exc:
                logger.warning("Tool %r raised: %s", tool_name, exc)
                result = {"error": str(exc)}

            # Gemini requires dict for function_response.response
            if not isinstance(result, dict):
                result = {"result": result}

            tool_calls_log.append({"name": tool_name, "args": args, "result": result})
            if on_tool_result:
                try:
                    await on_tool_result(round_num, tool_name, args, result)
                except Exception as _cb_exc:
                    logger.debug("on_tool_result callback raised: %s", _cb_exc)
            response_parts.append(
                genai_types.Part.from_function_response(
                    name=tool_name,
                    response=result,
                )
            )

        # Append tool results as a user turn
        contents.append(
            genai_types.Content(role="user", parts=response_parts)
        )

    # max_tool_rounds exhausted — return whatever text the model last produced
    logger.warning(
        "Gemini tool loop hit max_tool_rounds=%d for model=%s", max_tool_rounds, model
    )
    for c in reversed(contents):
        if getattr(c, "role", "") == "model":
            text = "".join(
                p.text
                for p in (c.parts or [])
                if getattr(p, "text", None) and not getattr(p, "thought", False)
            )
            if text:
                return text, tool_calls_log
    return "", tool_calls_log
