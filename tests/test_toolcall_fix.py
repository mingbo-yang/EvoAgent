"""Tests for ToolCall normalization and multi-turn tool loop."""

import tempfile
from pathlib import Path

import pytest

from evoagent.conversation.runtime import ConversationRuntime
from evoagent.conversation.session import ConversationSession
from evoagent.core.message import Message, MessageRole, ToolCall
from evoagent.models.router import ModelRouter
from evoagent.models.schema import LLMResponse
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.sandbox.schema import PermissionDecision
from evoagent.tools.builtin import create_builtin_registry


def test_toolcall_normalize_wire_format():
    """Provider wire format should be normalized to internal format."""
    wire = {
        "id": "call_123",
        "type": "function",
        "function": {
            "name": "list_directory",
            "arguments": '{"path": "."}',
        },
    }
    tc = ToolCall.model_validate(wire)
    assert tc.id == "call_123"
    assert tc.name == "list_directory"
    assert tc.arguments == {"path": "."}


def test_toolcall_normalize_internal_passthrough():
    """Internal format should pass through unchanged."""
    internal = {"id": "call_456", "name": "read_file", "arguments": {"path": "test.txt"}}
    tc = ToolCall.model_validate(internal)
    assert tc.id == "call_456"
    assert tc.name == "read_file"


def test_toolcall_invalid_json_arguments():
    """Invalid JSON in function.arguments should not crash."""
    wire = {"id": "c1", "function": {"name": "bad", "arguments": "{{{not json"}}
    tc = ToolCall.model_validate(wire)
    assert tc.name == "bad"
    assert tc.arguments == {}
    assert tc.raw == "{{{not json"


def test_toolcall_dict_arguments():
    """Dict arguments should be preserved and converted."""
    wire = {"id": "c1", "function": {"name": "tool", "arguments": {"a": 1}}}
    tc = ToolCall.model_validate(wire)
    assert tc.arguments == {"a": 1}


@pytest.mark.asyncio
async def test_multi_tool_loop_no_validation_error():
    """Multi-turn tool calls should not produce Pydantic ValidationError."""
    call_count = 0
    class MockProvider:
        provider_name = "mock"
        async def chat(self, request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                tc = ToolCall(id="tc1", name="list_directory", arguments={"path": "."})
                return LLMResponse(content="", tool_calls=[tc], finish_reason="tool_calls",
                                   model="mock", provider="mock")
            elif call_count == 2:
                tc = ToolCall(id="tc2", name="read_file", arguments={"path": "test.txt"})
                return LLMResponse(content="", tool_calls=[tc], finish_reason="tool_calls",
                                   model="mock", provider="mock")
            else:
                return LLMResponse(content="All done.", finish_reason="stop", model="mock", provider="mock")
    router = ModelRouter(providers={"executor": MockProvider(), "default": MockProvider()})
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "test.txt").write_text("hello")
        tools = create_builtin_registry(ws)
        session = ConversationSession(workspace=str(ws))
        runtime = ConversationRuntime(session, router, tools)

        response = await runtime.handle_user_message("test")
        assert "done" in response.lower()
        assert call_count == 3


def test_permission_deny_blocks():
    """DENY should block dangerous shell commands."""
    policy = PermissionPolicy()
    result = policy.check("shell", "rm -rf /")
    assert result == PermissionDecision.DENY


def test_permission_allow_runs():
    """ALLOW should permit read-only tools."""
    policy = PermissionPolicy()
    result = policy.check("tool", "list_directory")
    assert result in (PermissionDecision.ALLOW, PermissionDecision.ASK)


@pytest.mark.asyncio
async def test_cli_exception_recovery():
    """CLI should not crash on ValidationError."""
    from evoagent.cli.interactive import _handle_command
    result = _handle_command("/help", ConversationSession(), None)
    assert result == "ok"


def test_reasoning_content_roundtrip():
    """reasoning_content should survive serialization."""
    msg = Message(role=MessageRole.ASSISTANT, content="ok",
                  tool_calls=[ToolCall(id="t1", name="read_file", arguments={"path": "x"})],
                  reasoning_content="thinking...")
    data = msg.model_dump()
    restored = Message.model_validate(data)
    assert restored.reasoning_content == "thinking..."
    assert restored.tool_calls[0].name == "read_file"
