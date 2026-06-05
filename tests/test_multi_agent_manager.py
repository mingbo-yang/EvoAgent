"""Tests for MultiAgentManager."""

import pytest

from evoagent.core.errors import EvoAgentError
from evoagent.models.factory import MockLLMProvider
from evoagent.models.router import ModelRouter
from evoagent.multi_agent.base import RoleAgent, RoleAgentConfig
from evoagent.multi_agent.manager import MultiAgentManager
from evoagent.multi_agent.protocols import PipelineProtocol


@pytest.fixture
def manager():
    mock = MockLLMProvider(fixed_text="Manager output")
    router = ModelRouter(providers={"planner": mock, "executor": mock, "default": mock})
    mgr = MultiAgentManager()
    mgr.register("Planner", RoleAgent(
        RoleAgentConfig(name="Planner", role="planner", system_prompt="Plan.", model_role="planner"),
        model_router=router,
    ))
    mgr.register("Coder", RoleAgent(
        RoleAgentConfig(name="Coder", role="coder", system_prompt="Code.", model_role="executor"),
        model_router=router,
    ))
    return mgr


def test_manager_register_and_get(manager):
    agent = manager.get("Planner")
    assert agent.name == "Planner"


def test_manager_unknown_agent(manager):
    with pytest.raises(EvoAgentError, match="not registered"):
        manager.get("Nonexistent")


def test_manager_list_agents(manager):
    names = manager.list_agents()
    assert "Planner" in names
    assert "Coder" in names


@pytest.mark.asyncio
async def test_manager_run_pipeline(manager):
    protocol = PipelineProtocol(order=["Planner", "Coder"])
    result = await manager.run("Test task", protocol)
    assert result.success
    assert result.final_answer
    assert len(result.messages) >= 2
