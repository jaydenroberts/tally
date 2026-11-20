"""
Coverage for the two provider streaming paths in app/providers.py.

No network. The SDK client classes are replaced with fakes that replay
scripted events built from the SDKs' OWN event types, so a breaking change
to an SDK event shape fails here rather than in a user's chat:

* Anthropic: ``client.messages.stream(**kw)`` is an async context manager
  yielding ``RawContentBlockDeltaEvent`` (text / input-json deltas) and
  ``ParsedContentBlockStopEvent`` (carries the finished ``content_block``).
* OpenAI-compatible: ``await client.chat.completions.create(**kw)`` returns
  an async iterator of ``ChatCompletionChunk``; tool calls arrive as
  fragments keyed by ``index`` and are flushed on ``finish_reason ==
  "tool_calls"`` — or at end of stream for Ollama-style backends that never
  send that finish reason.
"""
import asyncio
import json

import anthropic
import openai
import pytest
from anthropic.lib.streaming import ParsedContentBlockStopEvent
from anthropic.types import (
    InputJSONDelta,
    RawContentBlockDeltaEvent,
    TextDelta,
    ToolUseBlock,
)
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import (
    Choice,
    ChoiceDelta,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)

from app import providers

TOOL = "\x00TOOL:"

OPENAI_STYLE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_spending",
        "description": "Spending by category",
        "parameters": {"type": "object", "properties": {"month": {"type": "string"}}},
    },
}


def collect(agen):
    async def _run():
        return [chunk async for chunk in agen]
    return asyncio.run(_run())


def split_output(chunks):
    text = [c for c in chunks if not c.startswith(TOOL)]
    tools = [json.loads(c[len(TOOL):]) for c in chunks if c.startswith(TOOL)]
    return text, tools


@pytest.fixture()
def provider_env(monkeypatch):
    def _set(provider="anthropic", key="", model="", base_url=""):
        monkeypatch.setattr(providers, "AI_PROVIDER", provider)
        monkeypatch.setattr(providers, "AI_API_KEY", key)
        monkeypatch.setattr(providers, "AI_MODEL", model)
        monkeypatch.setattr(providers, "AI_BASE_URL", base_url)
    return _set


# ---------------------------------------------------------------------------
# Anthropic fakes
# ---------------------------------------------------------------------------

def a_text(index, text):
    return RawContentBlockDeltaEvent(
        type="content_block_delta", index=index,
        delta=TextDelta(type="text_delta", text=text),
    )


def a_json(index, partial):
    return RawContentBlockDeltaEvent(
        type="content_block_delta", index=index,
        delta=InputJSONDelta(type="input_json_delta", partial_json=partial),
    )


def a_stop_tool(index, tool_id, name, tool_input):
    return ParsedContentBlockStopEvent.model_construct(
        type="content_block_stop", index=index,
        content_block=ToolUseBlock(type="tool_use", id=tool_id, name=name, input=tool_input),
    )


def install_fake_anthropic(monkeypatch, events):
    record = {}

    class _Stream:
        def __init__(self, evts):
            self._evts = evts

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def __aiter__(self):
            async def _gen():
                for e in self._evts:
                    yield e
            return _gen()

    class _Messages:
        def stream(self, **kwargs):
            record["stream_kwargs"] = kwargs
            return _Stream(events)

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            record["client_kwargs"] = kwargs
            self.messages = _Messages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeAsyncAnthropic)
    return record


def test_anthropic_text_deltas_in_order_and_one_tool_sentinel(monkeypatch, provider_env):
    provider_env("anthropic", key="not-a-real-key")
    rec = install_fake_anthropic(monkeypatch, [
        a_text(0, "You spent "),
        a_text(0, "less "),
        a_text(0, "this month."),
        # Input JSON streams in fragments; the SDK accumulates it into the
        # stop event's content_block. Fragments must never leak as text.
        a_json(1, '{"mon'),
        a_json(1, 'th": "2026'),
        a_json(1, '-05"}'),
        a_stop_tool(1, "toolu_1", "get_spending", {"month": "2026-05"}),
    ])

    out = collect(providers._stream_anthropic(
        [{"role": "user", "content": "hi"}], [OPENAI_STYLE_TOOL], "SYS",
    ))
    text, tools = split_output(out)

    assert text == ["You spent ", "less ", "this month."]
    assert tools == [{"id": "toolu_1", "name": "get_spending", "input": {"month": "2026-05"}}]
    assert out[-1].startswith(TOOL)

    assert rec["client_kwargs"] == {"api_key": "not-a-real-key"}
    kw = rec["stream_kwargs"]
    assert kw["system"] == "SYS"
    assert kw["model"] == "claude-sonnet-4-6"
    # OpenAI-style tool definitions are converted to Anthropic's schema.
    assert kw["tools"] == [{
        "name": "get_spending",
        "description": "Spending by category",
        "input_schema": OPENAI_STYLE_TOOL["function"]["parameters"],
    }]


def test_anthropic_omits_empty_tools_and_honours_model(monkeypatch, provider_env):
    provider_env("anthropic", key="not-a-real-key", model="claude-test-model")
    rec = install_fake_anthropic(monkeypatch, [a_text(0, "ok")])

    out = collect(providers._stream_anthropic([{"role": "user", "content": "hi"}], [], "S"))

    assert out == ["ok"]
    assert "tools" not in rec["stream_kwargs"]
    assert rec["stream_kwargs"]["model"] == "claude-test-model"


# ---------------------------------------------------------------------------
# OpenAI-compatible fakes
# ---------------------------------------------------------------------------

def o_chunk(content=None, tool_calls=None, finish_reason=None):
    return ChatCompletionChunk(
        id="chatcmpl-test", object="chat.completion.chunk", created=0, model="m",
        choices=[Choice(
            index=0, finish_reason=finish_reason,
            delta=ChoiceDelta(content=content, tool_calls=tool_calls),
        )],
    )


def o_tool(index, tool_id=None, name=None, arguments=None):
    return ChoiceDeltaToolCall(
        index=index, id=tool_id, type="function" if tool_id else None,
        function=ChoiceDeltaToolCallFunction(name=name, arguments=arguments),
    )


def install_fake_openai(monkeypatch, chunks):
    record = {}

    class _Completions:
        async def create(self, **kwargs):
            record["create_kwargs"] = kwargs

            async def _gen():
                for c in chunks:
                    yield c
            return _gen()

    class _Chat:
        completions = _Completions()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            record["client_kwargs"] = kwargs
            self.chat = _Chat()

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    return record


THREE_FRAGMENT_TOOL = [
    o_chunk(tool_calls=[o_tool(0, tool_id="call_1", name="get_spending", arguments='{"mo')]),
    o_chunk(tool_calls=[o_tool(0, arguments='nth": "20')]),
    o_chunk(tool_calls=[o_tool(0, arguments='26-05"}')]),
]


def test_openai_text_then_tool_split_over_three_fragments(monkeypatch, provider_env):
    provider_env("openai", key="not-a-real-key")
    rec = install_fake_openai(monkeypatch, [
        o_chunk(content="Let me "),
        o_chunk(content="check."),
        *THREE_FRAGMENT_TOOL,
        o_chunk(finish_reason="tool_calls"),
    ])

    out = collect(providers._stream_openai(
        [{"role": "user", "content": "hi"}], [OPENAI_STYLE_TOOL], "SYS",
    ))
    text, tools = split_output(out)

    assert text == ["Let me ", "check."]
    assert tools == [{"id": "call_1", "name": "get_spending", "input": {"month": "2026-05"}}]
    assert len([c for c in out if c.startswith(TOOL)]) == 1

    assert rec["client_kwargs"] == {"api_key": "not-a-real-key"}
    kw = rec["create_kwargs"]
    assert kw["stream"] is True
    assert kw["model"] == "gpt-4o"
    assert kw["messages"][0] == {"role": "system", "content": "SYS"}
    assert kw["messages"][1:] == [{"role": "user", "content": "hi"}]
    assert kw["tools"] == [OPENAI_STYLE_TOOL]
    assert kw["tool_choice"] == "auto"


def test_ollama_flushes_tool_call_without_finish_reason(monkeypatch, provider_env):
    provider_env("ollama", key="", base_url="http://ollama.example.invalid:11434/v1")
    install_fake_openai(monkeypatch, [*THREE_FRAGMENT_TOOL])  # stream ends, no finish_reason

    out = collect(providers._stream_openai([{"role": "user", "content": "hi"}], [OPENAI_STYLE_TOOL], ""))
    _, tools = split_output(out)

    assert tools == [{"id": "call_1", "name": "get_spending", "input": {"month": "2026-05"}}]


def test_openai_unparseable_arguments_fall_back_to_raw(monkeypatch, provider_env):
    provider_env("openai", key="not-a-real-key")
    install_fake_openai(monkeypatch, [
        o_chunk(tool_calls=[o_tool(0, tool_id="call_x", name="get_spending", arguments="{not json")]),
        o_chunk(finish_reason="tool_calls"),
    ])

    _, tools = split_output(collect(providers._stream_openai([], [OPENAI_STYLE_TOOL], "")))

    assert tools == [{"id": "call_x", "name": "get_spending", "input": {"raw": "{not json"}}]


def test_openai_base_url_routing_and_placeholder_key(monkeypatch, provider_env):
    provider_env("ollama", key="", model="llama-test", base_url="http://ollama.example.invalid:11434/v1")
    rec = install_fake_openai(monkeypatch, [o_chunk(content="hi")])

    out = collect(providers._stream_openai([{"role": "user", "content": "hi"}], [], ""))

    assert out == ["hi"]
    assert rec["client_kwargs"] == {
        "api_key": "ollama",
        "base_url": "http://ollama.example.invalid:11434/v1",
    }
    assert rec["create_kwargs"]["model"] == "llama-test"
    assert "tools" not in rec["create_kwargs"]
    assert "tool_choice" not in rec["create_kwargs"]


def test_openai_without_base_url_does_not_send_one(monkeypatch, provider_env):
    provider_env("openai", key="not-a-real-key")
    rec = install_fake_openai(monkeypatch, [o_chunk(content="x")])

    collect(providers._stream_openai([], [], ""))

    assert "base_url" not in rec["client_kwargs"]


def test_openai_skips_chunks_without_choices(monkeypatch, provider_env):
    provider_env("openai", key="not-a-real-key")
    empty = ChatCompletionChunk(
        id="c", object="chat.completion.chunk", created=0, model="m", choices=[],
    )
    install_fake_openai(monkeypatch, [empty, o_chunk(content="after")])

    assert collect(providers._stream_openai([], [], "")) == ["after"]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("provider,expected", [
    ("anthropic", "anthropic"),
    ("openai", "openai"),
    ("ollama", "openai"),
    ("something-else", "anthropic"),  # unknown falls back to the default branch
])
def test_stream_chat_dispatches_by_provider(monkeypatch, provider_env, provider, expected):
    provider_env(provider)
    seen = {}

    def _branch(name):
        async def _fake(messages, tools, system):
            seen["branch"] = name
            seen["args"] = (messages, tools, system)
            yield f"from-{name}"
        return _fake

    monkeypatch.setattr(providers, "_stream_anthropic", _branch("anthropic"))
    monkeypatch.setattr(providers, "_stream_openai", _branch("openai"))

    msgs = [{"role": "user", "content": "hi"}]
    out = collect(providers.stream_chat(msgs, None, "SYS"))

    assert out == [f"from-{expected}"]
    assert seen["branch"] == expected
    assert seen["args"] == (msgs, [], "SYS")  # tools=None normalised to []
