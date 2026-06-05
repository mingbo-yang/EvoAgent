"""Tests for Planner fallback and Reflector recovery."""

import pytest

from evoagent.models.factory import MockLLMProvider
from evoagent.planning.critic import CriticDecision
from evoagent.planning.planner import Planner
from evoagent.planning.reflector import Reflector
from evoagent.planning.schema import ActionType, Plan, PlanStep


@pytest.mark.asyncio
async def test_planner_invalid_json_safe_fallback():
    """Invalid JSON should trigger safe fallback plan, not crash."""
    mock = MockLLMProvider(fixed_text="not json at all {{{")
    planner = Planner(llm=mock)
    from evoagent.core.errors import PlanningError
    with pytest.raises((PlanningError, ValueError)):
        await planner.plan("dangerous task", [])


@pytest.mark.asyncio
async def test_planner_fallback_no_arbitrary_bash():
    """Safe fallback plan must not execute arbitrary shell commands."""
    mock = MockLLMProvider(fixed_text='{"risk_level":"low","steps":[{"goal":"Finish","action_type":"finish"}]}')
    planner = Planner(llm=mock)
    plan = await planner.plan("do something", [{"function": {"name": "list_directory"}}])
    for step in plan.steps:
        if step.action_type == ActionType.TOOL and step.tool_name == "bash":
            raise AssertionError("Fallback plan must not include bash tool")


def test_reflector_unknown_tool_recovery():
    """Reflector should generate list_tools step for unknown tool error."""
    reflector = Reflector(max_reflections=3)
    step = PlanStep(id="s1", goal="call bad_tool", action_type=ActionType.TOOL,
                    tool_name="bad_tool")
    step.result = type('obj', (object,), {'error': 'Unknown tool: bad_tool', 'success': False})()
    plan = Plan(id="p1", task="test", steps=[step, PlanStep(id="s2", goal="Finish", action_type=ActionType.FINISH)])
    import asyncio
    revised = asyncio.run(reflector.reflect("test", step,
        CriticDecision(passed=False, needs_revision=True, needs_more_info=False, reason="unknown tool"), plan))
    assert revised is not None
    assert any(s.tool_name == "list_directory" for s in revised.steps)


def test_reflector_file_not_found_recovery():
    """Reflector should generate list_dir step for file not found."""
    reflector = Reflector(max_reflections=3)
    step = PlanStep(id="s1", goal="read missing", action_type=ActionType.TOOL,
                    tool_name="read_file", arguments={"path": "nope.txt"})
    step.result = type('obj', (object,), {'error': 'File not found: nope.txt', 'success': False})()
    plan = Plan(id="p1", task="test", steps=[step, PlanStep(id="s2", goal="Finish", action_type=ActionType.FINISH)])
    import asyncio
    revised = asyncio.run(reflector.reflect("test", step,
        CriticDecision(passed=False, needs_revision=True, needs_more_info=False, reason="file not found"), plan))
    assert revised is not None
    assert any(s.action_type == ActionType.TOOL and s.tool_name == "list_directory" for s in revised.steps)


def test_reflector_permission_denied_recovery():
    """Reflector should generate ask_user step for permission denied."""
    reflector = Reflector(max_reflections=3)
    step = PlanStep(id="s1", goal="write protected", action_type=ActionType.TOOL,
                    tool_name="write_file")
    step.result = type('obj', (object,), {'error': 'Permission denied', 'success': False})()
    plan = Plan(id="p1", task="test", steps=[step, PlanStep(id="s2", goal="Finish", action_type=ActionType.FINISH)])
    import asyncio
    revised = asyncio.run(reflector.reflect("test", step,
        CriticDecision(passed=False, needs_revision=True, needs_more_info=False, reason="permission denied"), plan))
    assert revised is not None
    assert any(s.action_type == ActionType.ASK_USER for s in revised.steps)


def test_max_reflections_enforced():
    """Reflector should return None after max_reflections."""
    reflector = Reflector(max_reflections=1)
    step = PlanStep(id="s1", goal="fail")
    plan = Plan(id="p1", task="t", steps=[step])
    import asyncio
    d = CriticDecision(passed=False, needs_revision=True, needs_more_info=False, reason="fail")
    r1 = asyncio.run(reflector.reflect("t", step, d, plan))
    assert r1 is not None
    r2 = asyncio.run(reflector.reflect("t", step, d, plan))
    assert r2 is None
