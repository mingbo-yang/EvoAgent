"""Streaming UI tests — verify streaming, reasoning, and activity grouping."""

import tempfile
from pathlib import Path

import pytest

from evoagent.conversation.runtime import ConversationRuntime
from evoagent.conversation.session import ConversationSession
from evoagent.core.message import ToolCall
from evoagent.models.schema import LLMResponse
from evoagent.tools.builtin import create_builtin_registry


class MockStreamProvider:
    provider_name = "mock"
    call = 0

    async def chat(self, request):
        MockStreamProvider.call += 1
        if MockStreamProvider.call == 1:
            tc = ToolCall(id="tc1", name="list_directory", arguments={"path": "."})
            return LLMResponse(content="", tool_calls=[tc], finish_reason="tool_calls",
                               model="mock", provider="mock")
        elif MockStreamProvider.call == 2:
            tc = ToolCall(id="tc2", name="read_file", arguments={"path": "test.txt"})
            return LLMResponse(content="", tool_calls=[tc], finish_reason="tool_calls",
                               model="mock", provider="mock")
        else:
            return LLMResponse(content="Analysis complete. Found files and reviewed content.",
                               finish_reason="stop", model="mock", provider="mock")


@pytest.mark.asyncio
async def test_streaming_yields_chunks():
    """Streaming path yields text chunks."""
    from evoagent.models.router import ModelRouter
    router = ModelRouter(providers={"executor": MockStreamProvider(), "default": MockStreamProvider()})
    MockStreamProvider.call = 0
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "test.txt").write_text("data")
        tools = create_builtin_registry(ws)
        session = ConversationSession(workspace=str(ws))
        runtime = ConversationRuntime(session, router, tools)
        chunks = []
        async for chunk in runtime.handle_user_message_stream("analyze"):
            chunks.append(chunk)
        assert len(chunks) > 0
        assert any("Analysis" in c for c in chunks)


@pytest.mark.asyncio
async def test_reasoning_generated():
    """Public reasoning is generated from tool call patterns."""
    from evoagent.models.router import ModelRouter
    router = ModelRouter(providers={"executor": MockStreamProvider(), "default": MockStreamProvider()})
    MockStreamProvider.call = 0
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "test.txt").write_text("data")
        tools = create_builtin_registry(ws)
        session = ConversationSession(workspace=str(ws))
        runtime = ConversationRuntime(session, router, tools)
        chunks = []
        async for chunk in runtime.handle_user_message_stream("analyze"):
            chunks.append(chunk)
        reasoning = [c for c in chunks if c.startswith("·")]
        assert len(reasoning) > 0
        assert any("Exploring" in r or "Reading" in r for r in reasoning)


@pytest.mark.asyncio
async def test_activity_tool_names_tracked():
    """Tool names are tracked for activity grouping."""
    from evoagent.models.router import ModelRouter
    router = ModelRouter(providers={"executor": MockStreamProvider(), "default": MockStreamProvider()})
    MockStreamProvider.call = 0
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "test.txt").write_text("data")
        tools = create_builtin_registry(ws)
        session = ConversationSession(workspace=str(ws))
        runtime = ConversationRuntime(session, router, tools)
        async for _ in runtime.handle_user_message_stream("analyze"):
            pass
        assert len(runtime._tool_names_this_turn) >= 2
        assert "list_directory" in runtime._tool_names_this_turn
        assert "read_file" in runtime._tool_names_this_turn
