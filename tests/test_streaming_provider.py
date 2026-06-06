"""Tests for P1.6 real streaming with SSE tool_call assembly."""

import pytest

from evoagent.core.message import Message, MessageRole
from evoagent.models.factory import MockLLMProvider
from evoagent.models.openai_compatible import OpenAICompatibleProvider
from evoagent.models.schema import LLMRequest, ModelConfig


class _FakeStreamResp:
    def __init__(self, lines, status=200):
        self.status_code = status
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln

    async def aread(self):
        return b"error body"


class _FakeClient:
    is_closed = False

    def __init__(self, lines, status=200):
        self._lines = lines
        self._status = status

    def stream(self, method, url, json=None):
        return _FakeStreamResp(self._lines, self._status)


def _provider(monkeypatch, lines, status=200):
    monkeypatch.setenv("DUMMY_KEY", "x")
    cfg = ModelConfig(provider="deepseek", base_url="https://api.example/v1",
                      api_key_env="DUMMY_KEY")
    p = OpenAICompatibleProvider(cfg)
    p._client = _FakeClient(lines, status)
    return p


def _req():
    return LLMRequest(messages=[Message(role=MessageRole.USER, content="hi")])


@pytest.mark.asyncio
async def test_stream_text_deltas_and_done(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        'data: {"choices":[{"delta":{"content":" world"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}',
        "data: [DONE]",
    ]
    p = _provider(monkeypatch, lines)
    events = [ev async for ev in p.stream(_req())]
    texts = [e.delta for e in events if e.type == "text"]
    assert texts == ["Hello", " world"]
    done = events[-1]
    assert done.type == "done"
    assert done.response.content == "Hello world"
    assert done.response.finish_reason == "stop"
    assert done.response.usage["total_tokens"] == 5
    assert not done.response.tool_calls


@pytest.mark.asyncio
async def test_stream_assembles_fragmented_tool_call(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        '"function":{"name":"get_weather","arguments":""}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"{\\"city\\":"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"\\"NYC\\"}"}}]}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    p = _provider(monkeypatch, lines)
    events = [ev async for ev in p.stream(_req())]
    tool_events = [e for e in events if e.type == "tool_call"]
    assert len(tool_events) == 1
    tc = tool_events[0].tool_call
    assert tc.name == "get_weather"
    assert tc.arguments == {"city": "NYC"}
    assert tc.id == "call_1"
    done = events[-1]
    assert done.type == "done"
    assert done.response.tool_calls[0].name == "get_weather"
    assert done.response.tool_calls[0].arguments == {"city": "NYC"}
    assert done.response.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_stream_assembles_multiple_tool_calls(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"a",'
        '"function":{"name":"foo","arguments":"{}"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"b",'
        '"function":{"name":"bar","arguments":"{}"}}]}}]}',
        "data: [DONE]",
    ]
    p = _provider(monkeypatch, lines)
    events = [ev async for ev in p.stream(_req())]
    names = [e.tool_call.name for e in events if e.type == "tool_call"]
    assert names == ["foo", "bar"]


@pytest.mark.asyncio
async def test_stream_chat_yields_only_text(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"A"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"x",'
        '"function":{"name":"t","arguments":"{}"}}]}}]}',
        'data: {"choices":[{"delta":{"content":"B"}}]}',
        "data: [DONE]",
    ]
    p = _provider(monkeypatch, lines)
    chunks = [c async for c in p.stream_chat(_req())]
    assert chunks == ["A", "B"]


@pytest.mark.asyncio
async def test_stream_reasoning_delta(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"thinking..."}}]}',
        'data: {"choices":[{"delta":{"content":"answer"}}]}',
        "data: [DONE]",
    ]
    p = _provider(monkeypatch, lines)
    events = [ev async for ev in p.stream(_req())]
    reasoning = [e.delta for e in events if e.type == "reasoning"]
    assert reasoning == ["thinking..."]
    assert events[-1].response.reasoning_content == "thinking..."


@pytest.mark.asyncio
async def test_base_default_stream_wraps_chat():
    """A provider without SSE support still supports structured streaming."""
    provider = MockLLMProvider(fixed_text="hello from mock")
    events = [ev async for ev in provider.stream(_req())]
    assert events[0].type == "text"
    assert events[0].delta == "hello from mock"
    assert events[-1].type == "done"
    assert events[-1].response.content == "hello from mock"
