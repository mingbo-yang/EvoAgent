"""Tests for conversation module and multi-turn execution."""

from pathlib import Path

import pytest

from evoagent.cli.ui.event_bus import EventBus
from evoagent.cli.ui.events import UIEventType
from evoagent.conversation.runtime import ConversationRuntime
from evoagent.conversation.schema import AgentMode
from evoagent.conversation.session import ConversationSession
from evoagent.conversation.store import SessionStore
from evoagent.core.message import Message, MessageRole, ToolCall
from evoagent.models.factory import MockLLMProvider
from evoagent.models.router import ModelRouter
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.tools.builtin import create_builtin_registry


@pytest.fixture
def session():
    return ConversationSession(workspace=".")


@pytest.fixture
def runtime(session):
    mock = MockLLMProvider(fixed_text="OK")
    router = ModelRouter(providers={"planner": mock, "executor": mock, "default": mock})
    tools = create_builtin_registry(Path("."))
    policy = PermissionPolicy()
    return ConversationRuntime(session, router, tools, policy)


def test_session_creation(session):
    assert session.session_id.startswith("sess_")
    assert session.mode == AgentMode.DEFAULT


def test_session_append_messages(session):
    session.append_user_message("hello")
    session.append_assistant_message("hi")
    assert len(session.messages) == 2


def test_session_mode_switch(session):
    session.set_mode(AgentMode.PLAN)
    assert session.mode == AgentMode.PLAN
    session.set_mode(AgentMode.AUTO)
    assert session.mode == AgentMode.AUTO


def test_session_persistence():
    store = SessionStore()
    s = ConversationSession(workspace=".")
    s.set_mode(AgentMode.PLAN)
    s.append_user_message("test")
    s.append_assistant_message("ok")
    s.record_turn("test", "ok")
    s.metadata["foo"] = "bar"
    store.save(s)

    loaded = store.load(s.session_id)
    assert loaded is not None
    assert loaded.mode == AgentMode.PLAN
    assert len(loaded.messages) == 2
    assert loaded.messages[0].content == "test"
    assert loaded.messages[1].content == "ok"
    assert len(loaded.turns) == 1
    assert loaded.metadata["foo"] == "bar"


def test_session_store_list():
    store = SessionStore()
    s1 = ConversationSession()
    s2 = ConversationSession()
    store.save(s1)
    store.save(s2)
    sessions = store.list_sessions()
    assert len(sessions) >= 2


@pytest.mark.asyncio
async def test_runtime_handle_message(runtime):
    response = await runtime.handle_user_message("hello")
    assert isinstance(response, str)
    assert len(runtime.session.messages) >= 2


@pytest.mark.asyncio
async def test_runtime_preserves_session(runtime):
    await runtime.handle_user_message("first")
    await runtime.handle_user_message("second")
    assert len(runtime.session.turns) == 2


@pytest.mark.asyncio
async def test_runtime_mode_affects_behavior(runtime):
    runtime.session.set_mode(AgentMode.AUTO)
    response = await runtime.handle_user_message("do something")
    assert isinstance(response, str)


@pytest.mark.asyncio
async def test_runtime_tool_approval_executes_when_approved(session):
    mock = MockLLMProvider(
        fixed_text="Mock tool call",
        fixed_tool_calls=[ToolCall(name="list_directory", arguments={"path": "."})],
    )
    router = ModelRouter(providers={"planner": mock, "executor": mock, "default": mock})
    tools = create_builtin_registry(Path("."))
    policy = PermissionPolicy()
    event_bus = EventBus()

    async def on_approval(evt):
        if evt.type == UIEventType.APPROVAL_REQUESTED:
            return "yes"
        return None

    event_bus.subscribe(UIEventType.APPROVAL_REQUESTED.value, on_approval)
    runtime = ConversationRuntime(session, router, tools, policy, event_bus=event_bus)

    response = await runtime.handle_user_message("list workspace")
    assert isinstance(response, str)
    assert any(
        m.role.value == "tool" and m.name == "list_directory"
        for m in runtime.session.messages
    )


def _assert_tool_calls_answered(messages: list[Message]) -> None:
    """Every assistant tool_calls turn must be followed by a tool message
    for each tool_call_id, with no orphan tool messages."""
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.role == MessageRole.ASSISTANT and m.tool_calls:
            required = {tc.id for tc in m.tool_calls}
            answered = set()
            j = i + 1
            while j < len(messages) and messages[j].role == MessageRole.TOOL:
                answered.add(messages[j].tool_call_id)
                j += 1
            assert required.issubset(answered), (
                f"unanswered tool_calls: {required - answered}"
            )
            i = j
            continue
        assert m.role != MessageRole.TOOL, "orphan tool message in safe history"
        i += 1


def test_safe_messages_keeps_all_parallel_tool_responses(runtime):
    """Regression: an assistant turn with multiple tool_calls must keep a
    tool response for every tool_call_id (DeepSeek/OpenAI reject partial
    groups with HTTP 400)."""
    s = runtime.session
    s.append_user_message("list and inspect")
    s.messages.append(
        Message(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(id="call_a", name="list_directory", arguments={}),
                ToolCall(id="call_b", name="bash", arguments={}),
            ],
        )
    )
    s.append_tool_message("call_a", "dir listing", "list_directory")
    s.append_tool_message("call_b", "bash output", "bash")

    safe = runtime._safe_messages()
    _assert_tool_calls_answered(safe)
    tool_ids = {m.tool_call_id for m in safe if m.role == MessageRole.TOOL}
    assert tool_ids == {"call_a", "call_b"}


def test_safe_messages_drops_leading_orphan_tool_messages(runtime):
    """A truncation window may start mid-group; leading orphan tool messages
    must be dropped so the request stays valid."""
    s = runtime.session
    s.append_tool_message("orphan_1", "stale", "list_directory")
    s.append_user_message("hello")
    s.append_assistant_message("hi")

    safe = runtime._safe_messages()
    _assert_tool_calls_answered(safe)
    assert all(m.role != MessageRole.TOOL for m in safe)


def test_safe_messages_drops_incomplete_tool_group(runtime):
    """If an assistant tool_calls turn is missing some responses, the whole
    group is dropped rather than sent as an invalid partial group."""
    s = runtime.session
    s.append_user_message("do two things")
    s.messages.append(
        Message(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(id="call_x", name="list_directory", arguments={}),
                ToolCall(id="call_y", name="bash", arguments={}),
            ],
        )
    )
    s.append_tool_message("call_x", "only one answered", "list_directory")

    safe = runtime._safe_messages()
    _assert_tool_calls_answered(safe)
    assert all(not (m.role == MessageRole.ASSISTANT and m.tool_calls) for m in safe)
