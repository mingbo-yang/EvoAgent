"""Tests for Planner."""

import pytest

from evoagent.models.factory import MockLLMProvider
from evoagent.planning.planner import Planner
from evoagent.planning.schema import ActionType, Plan


@pytest.fixture
def planner():
    mock = MockLLMProvider(fixed_text='{"risk_level":"low","steps":[{"goal":"Step 1","action_type":"tool","tool_name":"read_file","arguments":{"path":"test.txt"},"expected_result":"content"},{"goal":"Finish","action_type":"finish"}]}')
    return Planner(llm=mock)


@pytest.mark.asyncio
async def test_planner_parses_valid_json(planner):
    plan = await planner.plan("Read test.txt", [{"function": {"name": "read_file"}}])
    assert isinstance(plan, Plan)
    assert len(plan.steps) >= 2
    assert plan.steps[0].action_type == ActionType.TOOL
    assert plan.steps[0].tool_name == "read_file"


@pytest.mark.asyncio
async def test_planner_adds_finish_step():
    mock = MockLLMProvider(fixed_text='{"risk_level":"low","steps":[{"goal":"Do something","action_type":"tool","tool_name":"list_directory","arguments":{"path":"."}}]}')
    p = Planner(llm=mock)
    plan = await p.plan("do it", [])
    assert plan.steps[-1].action_type == ActionType.FINISH


@pytest.mark.asyncio
async def test_planner_respects_max_steps():
    """Plan should not exceed max_steps."""
    mock = MockLLMProvider(fixed_text='{"risk_level":"low","steps":[' +
        ','.join([f'{{"goal":"Step {i}","action_type":"tool","tool_name":"echo"}}' for i in range(20)]) +
        ']}')
    p = Planner(llm=mock, max_steps=3)
    plan = await p.plan("many steps", [])
    assert len(plan.steps) <= 4  # truncated + finish step


@pytest.mark.asyncio
async def test_planner_handles_json_in_code_block():
    mock = MockLLMProvider(fixed_text='```json\n{"risk_level":"medium","steps":[{"goal":"Check it","action_type":"tool","tool_name":"grep","arguments":{"pattern":"test"}},{"goal":"Done","action_type":"finish"}]}\n```')
    p = Planner(llm=mock)
    plan = await p.plan("search", [{"function": {"name": "grep"}}])
    assert plan.steps[0].tool_name == "grep"


@pytest.mark.asyncio
async def test_planner_invalid_json_fallback():
    """Invalid JSON should trigger PlanningError or fallback."""
    mock = MockLLMProvider(fixed_text="not json at all")
    p = Planner(llm=mock)
    from evoagent.core.errors import PlanningError
    with pytest.raises((ValueError, PlanningError)):
        await p.plan("test", [])
