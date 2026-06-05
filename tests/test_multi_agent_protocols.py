"""Tests for multi-agent protocols."""

import pytest

from evoagent.models.factory import MockLLMProvider
from evoagent.models.router import ModelRouter
from evoagent.multi_agent.base import RoleAgent, RoleAgentConfig
from evoagent.multi_agent.protocols import (
    DebateProtocol,
    PipelineProtocol,
    SupervisorProtocol,
)


@pytest.fixture
def agents():
    mock = MockLLMProvider(fixed_text="Agent output")
    router = ModelRouter(providers={"planner": mock, "executor": mock, "critic": mock, "default": mock})
    return {
        "Planner": RoleAgent(RoleAgentConfig(name="Planner", role="planner", system_prompt="Plan.", model_role="planner"), model_router=router),
        "Coder": RoleAgent(RoleAgentConfig(name="Coder", role="coder", system_prompt="Code.", model_role="executor"), model_router=router),
        "Tester": RoleAgent(RoleAgentConfig(name="Tester", role="tester", system_prompt="Test.", model_role="executor"), model_router=router),
        "Critic": RoleAgent(RoleAgentConfig(name="Critic", role="critic", system_prompt="Review.", model_role="critic"), model_router=router),
        "Manager": RoleAgent(RoleAgentConfig(name="Manager", role="manager", system_prompt="Manage.", model_role="planner"), model_router=router),
    }


@pytest.mark.asyncio
async def test_pipeline_protocol(agents):
    protocol = PipelineProtocol(order=["Planner", "Coder", "Critic"])
    result = await protocol.run("Build a web app", agents)
    assert result.success
    assert len(result.agent_outputs) >= 3
    assert len(result.messages) >= 3


@pytest.mark.asyncio
async def test_pipeline_missing_agent(agents):
    protocol = PipelineProtocol(order=["Planner", "Nonexistent"])
    result = await protocol.run("test", agents)
    assert result.success  # Skips missing, still works


@pytest.mark.asyncio
async def test_debate_protocol(agents):
    protocol = DebateProtocol(judge_name="Critic")
    result = await protocol.run("Best database?", agents)
    assert result.success
    assert "Critic" in result.agent_outputs


@pytest.mark.asyncio
async def test_supervisor_protocol(agents):
    protocol = SupervisorProtocol(manager_name="Manager")
    result = await protocol.run("Organize the project", agents)
    assert result.success
    assert "Manager" in result.agent_outputs
    assert len(result.messages) >= 1
