"""Tests for conversation module and multi-turn execution."""

from pathlib import Path

import pytest
from evoagent.conversation.runtime import ConversationRuntime
from evoagent.conversation.schema import AgentMode
from evoagent.conversation.session import ConversationSession
from evoagent.conversation.store import SessionStore
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
    store.save(s)

    loaded = store.load(s.session_id)
    assert loaded is not None
    assert loaded.mode == AgentMode.PLAN


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
