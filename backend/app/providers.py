"""
providers.py — Multi-provider AI abstraction for Tally.

Reads configuration from environment variables:
    AI_PROVIDER   — "anthropic" (default) or "openai"
    AI_API_KEY    — API key for the selected provider
    AI_MODEL      — model identifier (e.g. "claude-sonnet-4-6" or "gpt-4o")
    AI_BASE_URL   — optional base URL override (required for Ollama and other
                    OpenAI-compatible endpoints, e.g. "http://localhost:11434/v1")

Both branches expose a single async generator:
    stream_chat(messages, tools, system) -> AsyncIterator[str]

Each yielded string is a text delta suitable for direct SSE forwarding.
Tool call deltas are yielded as JSON-encoded SSE events (type="tool_call").
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any


AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()
# Accept both AI_API_KEY (generic) and ANTHROPIC_API_KEY (provider-specific).
# AI_API_KEY takes precedence if both are set.
AI_API_KEY  = os.getenv("AI_API_KEY") or os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL    = os.getenv("AI_MODEL", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "")


# ---------------------------------------------------------------------------
# Shared type aliases
# ---------------------------------------------------------------------------

# A message dict as used throughout the chat router:
#   {"role": "user"|"assistant"|"tool", "content": str|list}
Message = dict[str, Any]

# A tool definition dict (OpenAI / Anthropic format — both accepted; we
# normalise to the target provider's expected schema inside each branch).
ToolDef = dict[str, Any]


# ---------------------------------------------------------------------------
# Anthropic branch
# ---------------------------------------------------------------------------

async def _stream_anthropic(
    messages: list[Message],
    tools: list[ToolDef],
    system: str,
) -> AsyncIterator[str]:
    """Stream via the official Anthropic Python SDK."""
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "anthropic package is not installed. "
            "Set AI_PROVIDER=openai to use the OpenAI-compatible branch instead."
        ) from exc

    model = AI_MODEL or "claude-sonnet-4-6"
    client = anthropic.AsyncAnthropic(api_key=AI_API_KEY or None)

    # Convert tools from OpenAI-style to Anthropic tool format if needed.
    # Anthropic expects: {name, description, input_schema: {type, properties, required}}
    anthropic_tools: list[dict] = []
    for t in tools:
        if "function" in t:
            fn = t["function"]
            anthropic_tools.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        else:
            # Already Anthropic-style
            anthropic_tools.append(t)

    # Anthropic does not accept an empty tools list — omit the kwarg entirely.
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": 4096,
        "system": system,
        "messages": messages,
    }
    if anthropic_tools:
        kwargs["tools"] = anthropic_tools

    async with client.messages.stream(**kwargs) as stream:
        async for event in stream:
            event_type = getattr(event, "type", None)

            # Text delta
            if event_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta and getattr(delta, "type", None) == "text_delta":
                    yield delta.text

            # Tool use block — yield a structured event so the caller can
            # handle tool execution and continue the conversation.
            elif event_type == "content_block_stop":
                block = getattr(event, "content_block", None)
                if block and getattr(block, "type", None) == "tool_use":
                    yield "\x00TOOL:" + json.dumps({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })


# ---------------------------------------------------------------------------
# OpenAI-compatible branch  (works with OpenAI, Ollama, LM Studio, etc.)
# ---------------------------------------------------------------------------

async def _stream_openai(
    messages: list[Message],
    tools: list[ToolDef],
    system: str,
) -> AsyncIterator[str]:
    """Stream via the official OpenAI Python SDK (also handles Ollama / compatible endpoints)."""
    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "openai package is not installed. "
            "Set AI_PROVIDER=anthropic to use the Anthropic branch instead."
        ) from exc

    model = AI_MODEL or "gpt-4o"

    kwargs: dict[str, Any] = {}
    if AI_API_KEY:
        kwargs["api_key"] = AI_API_KEY
    else:
        # Ollama / local endpoints typically do not require a real key
        kwargs["api_key"] = "ollama"

    if AI_BASE_URL:
        kwargs["base_url"] = AI_BASE_URL

    client = AsyncOpenAI(**kwargs)

    # Prepend system message
    full_messages: list[Message] = [{"role": "system", "content": system}] + messages

    stream_kwargs: dict[str, Any] = {
        "model": model,
        "messages": full_messages,
        "stream": True,
    }
    if tools:
        stream_kwargs["tools"] = tools
        stream_kwargs["tool_choice"] = "auto"

    # Accumulate tool call chunks across deltas
    tool_call_accum: dict[int, dict] = {}

    async for chunk in await client.chat.completions.create(**stream_kwargs):
        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            continue

        delta = choice.delta

        # Text delta
        if delta.content:
            yield delta.content

        # Tool call delta — accumulate fragments
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_call_accum:
                    tool_call_accum[idx] = {
                        "id": "",
                        "name": "",
                        "arguments": "",
                    }
                if tc.id:
                    tool_call_accum[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tool_call_accum[idx]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_call_accum[idx]["arguments"] += tc.function.arguments

        # finish_reason == "tool_calls" signals the end of tool call accumulation
        if choice.finish_reason == "tool_calls":
            for idx in sorted(tool_call_accum):
                tc_data = tool_call_accum[idx]
                try:
                    parsed_input = json.loads(tc_data["arguments"])
                except json.JSONDecodeError:
                    parsed_input = {"raw": tc_data["arguments"]}

                yield "\x00TOOL:" + json.dumps({
                    "id": tc_data["id"],
                    "name": tc_data["name"],
                    "input": parsed_input,
                })
            tool_call_accum.clear()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def stream_chat(
    messages: list[Message],
    tools: list[ToolDef] | None = None,
    system: str = "",
) -> AsyncIterator[str]:
    """
    Stream a chat completion from the configured AI provider.

    Yields text deltas as plain strings.
    Yields tool call events as strings prefixed with the sentinel ``\\x00TOOL:``,
    followed by a JSON payload: ``{"id": ..., "name": ..., "input": {...}}``.

    The caller (routers/chat.py) is responsible for:
    - Forwarding text deltas to the SSE stream.
    - Detecting ``\\x00TOOL:`` sentinels, executing the named tool against the DB,
      and continuing the conversation by appending tool results to ``messages``
      and calling ``stream_chat`` again.

    Args:
        messages:  Conversation history (without the system prompt).
        tools:     Tool definitions in OpenAI function-calling format.
                   Both branches normalise to their provider's expected schema.
        system:    System prompt string.
    """
    tools = tools or []
    if AI_PROVIDER == "openai":
        # Handles OpenAI, Ollama, LM Studio, and other OpenAI-compatible endpoints.
        # Multi-turn tool use is supported (tool_calls + tool_call_id format).
        async for chunk in _stream_openai(messages, tools, system):
            yield chunk
    else:
        # Default: Anthropic. Multi-turn tool use is supported (content block format).
        # NOTE: Gemini is not yet supported — it requires a separate SDK and message
        # schema. To add Gemini, introduce a third AI_PROVIDER branch here and a
        # matching _stream_gemini() function.
        async for chunk in _stream_anthropic(messages, tools, system):
            yield chunk
