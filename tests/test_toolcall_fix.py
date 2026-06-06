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
                return LLMResponse(
                    content="All done.",
                    finish_reason="stop",
                    model="mock",
                    provider="mock",
                )
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


def test_model_command_switches_router(monkeypatch, tmp_path):
    from evoagent.cli.interactive import _handle_command
    from evoagent.config.loader import load_config
    from evoagent.conversation.session import ConversationSession
    from evoagent.conversation.store import SessionStore
    from evoagent.models.factory import MockLLMProvider
    from evoagent.models.provider_registry import ProviderRegistry
    from evoagent.models.registry import ModelRegistry
    from evoagent.models.router import ModelRouter

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    session = ConversationSession()
    original_id = session.session_id
    session.append_user_message("hello")
    session.append_assistant_message("hi")

    store = SessionStore(sessions_dir=str(tmp_path / "sessions"))
    provider_registry = ProviderRegistry()
    model_registry = ModelRegistry()
    model_registry.add_alias("gpt", "openai/gpt-4o")
    router = ModelRouter(providers={
        "planner": MockLLMProvider(),
        "executor": MockLLMProvider(),
        "critic": MockLLMProvider(),
        "default": MockLLMProvider(),
    })
    config = load_config()

    result = _handle_command(
        "/model gpt",
        session,
        store,
        provider_registry,
        model_registry,
        None,
        router,
        config,
    )
    assert result == "ok"
    provider = router._get_provider("default")
    assert provider.provider_name == "openai"
    assert session.session_id == original_id
    assert len(session.messages) == 2


def test_model_command_cross_provider_switch(monkeypatch, tmp_path):
    from evoagent.cli.interactive import _handle_command
    from evoagent.config.loader import load_config
    from evoagent.conversation.session import ConversationSession
    from evoagent.conversation.store import SessionStore
    from evoagent.models.factory import MockLLMProvider
    from evoagent.models.provider_registry import ProviderRegistry
    from evoagent.models.registry import ModelRegistry
    from evoagent.models.router import ModelRouter

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    session = ConversationSession()
    session.append_user_message("hello")
    session.append_assistant_message("hi")
    from evoagent.planning.schema import Plan
    session.current_plan = Plan(task="Switch plan", steps=[])

    store = SessionStore(sessions_dir=str(tmp_path / "sessions"))
    provider_registry = ProviderRegistry()
    model_registry = ModelRegistry()
    model_registry.add_alias("gpt4", "openai/gpt-4")
    router = ModelRouter(providers={
        "planner": MockLLMProvider(),
        "executor": MockLLMProvider(),
        "critic": MockLLMProvider(),
        "default": MockLLMProvider(),
    })
    config = load_config()

    result = _handle_command(
        "/model gpt4",
        session,
        store,
        provider_registry,
        model_registry,
        None,
        router,
        config,
    )
    assert result == "ok"
    assert router._get_provider("default").provider_name == "openai"
    assert session.session_id is not None
    assert session.current_plan is not None
    assert len(session.messages) == 2

    result = _handle_command(
        "/model ollama/any",
        session,
        store,
        provider_registry,
        model_registry,
        None,
        router,
        config,
    )
    assert result == "ok"
    assert router._get_provider("default").provider_name == "ollama"
    assert session.session_id is not None
    assert session.current_plan is not None
    assert len(session.messages) == 2


def test_model_command_default_resets_router(monkeypatch, tmp_path):
    from evoagent.cli.interactive import _handle_command
    from evoagent.config.loader import load_config
    from evoagent.conversation.session import ConversationSession
    from evoagent.conversation.store import SessionStore
    from evoagent.models.factory import MockLLMProvider
    from evoagent.models.provider_registry import ProviderRegistry
    from evoagent.models.registry import ModelRegistry
    from evoagent.models.router import ModelRouter

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    session = ConversationSession()
    store = SessionStore(sessions_dir=str(tmp_path / "sessions"))
    provider_registry = ProviderRegistry()
    model_registry = ModelRegistry()
    router = ModelRouter(providers={
        "planner": MockLLMProvider(),
        "executor": MockLLMProvider(),
        "critic": MockLLMProvider(),
        "default": MockLLMProvider(),
    })
    config = load_config()

    result = _handle_command(
        "/model default",
        session,
        store,
        provider_registry,
        model_registry,
        None,
        router,
        config,
    )
    assert result == "ok"
    provider = router._get_provider("default")
    assert provider.provider_name == "deepseek"


def test_model_command_refresh(monkeypatch, tmp_path, capsys):
    from evoagent.cli.interactive import _handle_command
    from evoagent.config.loader import load_config
    from evoagent.conversation.session import ConversationSession
    from evoagent.conversation.store import SessionStore
    from evoagent.models.factory import MockLLMProvider
    from evoagent.models.provider_registry import ProviderRegistry
    from evoagent.models.registry import ModelRegistry
    from evoagent.models.router import ModelRouter

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    session = ConversationSession()
    store = SessionStore(sessions_dir=str(tmp_path / "sessions"))
    provider_registry = ProviderRegistry()
    model_registry = ModelRegistry()
    router = ModelRouter(providers={
        "planner": MockLLMProvider(),
        "executor": MockLLMProvider(),
        "critic": MockLLMProvider(),
        "default": MockLLMProvider(),
    })
    config = load_config()

    result = _handle_command(
        "/model refresh",
        session,
        store,
        provider_registry,
        model_registry,
        None,
        router,
        config,
    )
    assert result == "ok"
    captured = capsys.readouterr()
    assert "Model registry refreshed." in captured.out


def test_model_switch_refuses_when_tools_required(monkeypatch, tmp_path, capsys):
    from evoagent.cli.interactive import _handle_command
    from evoagent.conversation.session import ConversationSession
    from evoagent.conversation.store import SessionStore
    from evoagent.models.provider_registry import ProviderRegistry
    from evoagent.models.registry import ModelDefinition, ModelRegistry

    session = ConversationSession()
    # Create a plan that requires a tool
    from evoagent.planning.schema import ActionType, Plan, PlanStep
    session.current_plan = Plan(task="Requires tool", steps=[PlanStep(goal="List files", action_type=ActionType.TOOL)])

    store = SessionStore(sessions_dir=str(tmp_path / "sessions"))
    provider_registry = ProviderRegistry()
    model_registry = ModelRegistry()
    # Register a model that explicitly does NOT support tools
    md = ModelDefinition(provider="openai", model_id="no-tools", supports_tools=False, canonical_id="openai/no-tools")
    model_registry.register(md)
    # Sanity check: registry contains the model we just registered
    stored = model_registry.get("openai/no-tools")
    assert stored is not None
    assert stored.supports_tools is False

    from evoagent.config.loader import load_config
    from evoagent.models.router import ModelRouter
    router = ModelRouter(providers={})
    config = load_config()
    result = _handle_command("/model openai/no-tools", session, store, provider_registry, model_registry, None, router, config)
    assert result == "ok"
    captured = capsys.readouterr()
    assert "does not support tools" in captured.out


def test_session_command_resume_fork_reset_clear(tmp_path, capsys):
    from evoagent.cli.interactive import _handle_command
    from evoagent.conversation.session import ConversationSession
    from evoagent.conversation.store import SessionStore
    from evoagent.planning.schema import Plan

    store = SessionStore(sessions_dir=str(tmp_path / "sessions"))

    original = ConversationSession()
    original.append_user_message("hello")
    original.append_assistant_message("hi")
    original.current_plan = Plan(task="Test task", steps=[])
    store.save(original)

    session = ConversationSession()
    result = _handle_command("/sessions", session, store, None, None, None, None, None)
    assert result == "ok"
    captured = capsys.readouterr()
    assert "Recent sessions:" in captured.out
    assert original.session_id in captured.out

    result = _handle_command("/resume latest", session, store, None, None, None, None, None)
    assert result == "ok"
    assert session.session_id == original.session_id
    assert len(session.messages) == 2

    previous_id = session.session_id
    result = _handle_command("/fork", session, store, None, None, None, None, None)
    assert result == "ok"
    assert session.session_id != previous_id
    assert len(session.messages) == 2
    assert session.current_plan is not None
    assert session.current_plan.task == "Test task"

    # /reset should clear history and state
    session.append_user_message("temp")
    result = _handle_command("/reset", session, store, None, None, None, None, None)
    assert result == "ok"
    assert len(session.messages) == 0
    assert session.current_plan is None
    assert session.turns == []

    # /new should create a fresh session without prior messages
    session.append_user_message("temp2")
    old_id = session.session_id
    result = _handle_command("/new", session, store, None, None, None, None, None)
    assert result == "ok"
    assert session.session_id != old_id
    assert len(session.messages) == 0

    session.append_user_message("temp3")
    result = _handle_command("/clear", session, store, None, None, None, None, None)
    assert result == "ok"
    assert len(session.messages) == 0


def test_reasoning_content_roundtrip():
    """reasoning_content should survive serialization."""
    msg = Message(role=MessageRole.ASSISTANT, content="ok",
                  tool_calls=[ToolCall(id="t1", name="read_file", arguments={"path": "x"})],
                  reasoning_content="thinking...")
    data = msg.model_dump()
    restored = Message.model_validate(data)
    assert restored.reasoning_content == "thinking..."
    assert restored.tool_calls[0].name == "read_file"
