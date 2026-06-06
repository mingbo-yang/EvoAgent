"""Tests for P2 observability tracing."""

import pytest

from evoagent.core.agent import Agent
from evoagent.core.message import Message, MessageRole, ToolCall
from evoagent.core.react import ReActEngine
from evoagent.models.base import BaseLLMProvider
from evoagent.models.router import ModelRouter
from evoagent.models.schema import LLMResponse
from evoagent.observability import Tracer
from evoagent.tools.builtin import create_builtin_registry


class ScriptedProvider(BaseLLMProvider):
    def __init__(self, responses):
        self._responses = list(responses)

    @property
    def provider_name(self):
        return "scripted"

    async def chat(self, request):
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="done", model="m", finish_reason="stop")

    async def structured_chat(self, request, schema):  # pragma: no cover
        raise NotImplementedError

    async def stream_chat(self, request):  # pragma: no cover
        yield "done"


def _router(provider):
    return ModelRouter(providers={"executor": provider, "default": provider})


def test_tracer_records_span_with_duration():
    tracer = Tracer()
    with tracer.span("unit", foo="bar") as sp:
        sp.attributes["extra"] = 1
    spans = tracer.finished_spans
    assert len(spans) == 1
    assert spans[0].name == "unit"
    assert spans[0].attributes["foo"] == "bar"
    assert spans[0].attributes["extra"] == 1
    assert spans[0].status == "ok"
    assert spans[0].duration_ms >= 0


def test_tracer_records_error_status():
    tracer = Tracer()
    with pytest.raises(ValueError):
        with tracer.span("boom"):
            raise ValueError("kaboom")
    sp = tracer.finished_spans[0]
    assert sp.status == "error"
    assert "kaboom" in sp.error


@pytest.mark.asyncio
async def test_engine_emits_llm_and_tool_spans(tmp_path):
    provider = ScriptedProvider([
        LLMResponse(content="", model="m", tool_calls=[
            ToolCall(id="c1", name="list_directory", arguments={"path": "."}),
        ], usage={"prompt_tokens": 12, "completion_tokens": 3}),
        LLMResponse(content="done", model="m", finish_reason="stop",
                    usage={"prompt_tokens": 20, "completion_tokens": 5}),
    ])
    registry = create_builtin_registry(tmp_path)
    tracer = Tracer()
    engine = ReActEngine(_router(provider), registry, ask_fallback="allow", tracer=tracer)
    await engine.run_turn([Message(role=MessageRole.USER, content="list")])
    llm_spans = tracer.spans_named("llm.chat")
    tool_spans = tracer.spans_named("tool.execute")
    assert len(llm_spans) == 2
    assert llm_spans[0].attributes["prompt_tokens"] == 12
    assert len(tool_spans) == 1
    assert tool_spans[0].attributes["tool"] == "list_directory"
    assert tool_spans[0].attributes["success"] is True


@pytest.mark.asyncio
async def test_tool_span_marks_failure(tmp_path):
    provider = ScriptedProvider([
        LLMResponse(content="", model="m", tool_calls=[
            ToolCall(id="c1", name="read_file", arguments={"path": "missing.xyz"}),
        ]),
        LLMResponse(content="recovered", model="m", finish_reason="stop"),
    ])
    registry = create_builtin_registry(tmp_path)
    tracer = Tracer()
    engine = ReActEngine(_router(provider), registry, ask_fallback="allow", tracer=tracer)
    await engine.run_turn([Message(role=MessageRole.USER, content="read")])
    tool_spans = tracer.spans_named("tool.execute")
    assert len(tool_spans) == 1
    # read of a missing file fails -> success attribute False.
    assert tool_spans[0].attributes["success"] is False


@pytest.mark.asyncio
async def test_agent_run_emits_agent_span(tmp_path):
    provider = ScriptedProvider([
        LLMResponse(content="hi", model="m", finish_reason="stop"),
    ])
    registry = create_builtin_registry(tmp_path)
    tracer = Tracer()
    agent = Agent(model_router=_router(provider), tool_registry=registry,
                  workspace=tmp_path, tracer=tracer)
    await agent.run("say hi")
    assert tracer.spans_named("agent.run")
    assert tracer.spans_named("llm.chat")


def test_untraced_engine_has_no_overhead(tmp_path):
    # _span returns a no-op context manager when no tracer is set.
    engine = ReActEngine(_router(ScriptedProvider([])), create_builtin_registry(tmp_path))
    with engine._span("x", a=1) as sp:
        assert sp is None


def test_otel_bridge_exports_real_spans():
    """When the OpenTelemetry SDK is installed, spans reach a real exporter."""
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    tracer = Tracer(use_otel=True)
    with tracer.span("llm.chat", model="deepseek-chat") as sp:
        sp.attributes["prompt_tokens"] = 7

    provider.force_flush()
    exported = exporter.get_finished_spans()
    assert any(s.name == "llm.chat" for s in exported)
    attrs = next(dict(s.attributes) for s in exported if s.name == "llm.chat")
    assert attrs["model"] == "deepseek-chat"
    assert attrs["prompt_tokens"] == 7
