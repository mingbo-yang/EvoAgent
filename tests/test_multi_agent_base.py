"""Tests for RoleAgent."""

import pytest

from evoagent.models.factory import MockLLMProvider
from evoagent.models.router import ModelRouter
from evoagent.multi_agent.base import RoleAgent, RoleAgentConfig


@pytest.fixture
def router():
    mock = MockLLMProvider(fixed_text="Mock response from agent")
    return ModelRouter(providers={"planner": mock, "executor": mock, "critic": mock, "default": mock})


@pytest.mark.asyncio
async def test_role_agent_act(router):
    config = RoleAgentConfig(name="Planner", role="planner", system_prompt="You plan tasks.", model_role="planner")
    agent = RoleAgent(config, model_router=router)
    result = await agent.act("Plan this task", run_id="run_1")
    assert "Mock response" in result


@pytest.mark.asyncio
async def test_role_agent_different_roles(router):
    """Different roles use different model_role settings."""
    planner = RoleAgent(
        RoleAgentConfig(name="Planner", role="planner", system_prompt="Plan.", model_role="planner"),
        model_router=router,
    )
    coder = RoleAgent(
        RoleAgentConfig(name="Coder", role="coder", system_prompt="Code.", model_role="executor"),
        model_router=router,
    )
    p_result = await planner.act("task")
    c_result = await coder.act("task")
    assert "Mock response" in p_result
    assert "Mock response" in c_result


@pytest.mark.asyncio
async def test_role_agent_no_llm():
    agent = RoleAgent(RoleAgentConfig(name="NoLLM", role="test"))
    result = await agent.act("test")
    assert "No LLM" in result


@pytest.mark.asyncio
async def test_role_agent_config_defaults():
    config = RoleAgentConfig(name="Test", role="tester")
    assert config.model_role == "default"
    assert config.memory_enabled is False
    assert config.max_turns == 3
