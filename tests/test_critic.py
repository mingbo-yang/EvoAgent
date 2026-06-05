"""Tests for Critic and Reflector."""

import pytest

from evoagent.models.factory import MockLLMProvider
from evoagent.planning.critic import Critic, CriticDecision
from evoagent.planning.reflector import Reflector
from evoagent.planning.schema import ActionType, Plan, PlanStep


@pytest.fixture
def critic():
    return Critic(mode="rule")


@pytest.mark.asyncio
async def test_critic_rule_passed(critic):
    """Rule-based critic should pass successful steps."""
    step = PlanStep(goal="test", expected_result="success")
    from evoagent.core.state import StepResult
    result = StepResult(step_id=step.id, success=True, output="ok")
    decision = await critic.evaluate("test task", step, result)
    assert decision.passed
    assert not decision.needs_revision
    assert decision.confidence == 1.0


@pytest.mark.asyncio
async def test_critic_rule_failed(critic):
    """Rule-based critic should flag failed steps."""
    step = PlanStep(goal="test")
    from evoagent.core.state import StepResult
    result = StepResult(step_id=step.id, success=False, error="oops")
    decision = await critic.evaluate("test task", step, result)
    assert not decision.passed
    assert decision.needs_revision


@pytest.mark.asyncio
async def test_critic_llm_mode():
    """LLM critic parses JSON response."""
    mock = MockLLMProvider(fixed_text='{"passed":false,"needs_revision":true,"needs_more_info":false,"reason":"bad output","suggested_action":"retry","confidence":0.3}')
    c = Critic(llm=mock, mode="llm")
    step = PlanStep(goal="x")
    from evoagent.core.state import StepResult
    result = StepResult(step_id=step.id, success=False, error="fail")
    decision = await c.evaluate("task", step, result)
    assert not decision.passed
    assert decision.needs_revision
    assert decision.reason == "bad output"


def test_critic_decision_serializable():
    d = CriticDecision(passed=True, needs_revision=False, needs_more_info=False,
                       reason="ok", suggested_action=None, confidence=0.9)
    data = d.to_dict()
    assert data["passed"] is True
    assert data["confidence"] == 0.9


# ── Reflector ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reflector_rule_based():
    """Rule-based reflector skips failed step."""
    r = Reflector(max_reflections=3)
    step = PlanStep(id="s1", goal="failed step")
    plan = Plan(id="p1", task="test", steps=[step, PlanStep(id="s2", goal="finish", action_type=ActionType.FINISH)])
    from evoagent.planning.critic import CriticDecision
    decision = CriticDecision(passed=False, needs_revision=True, needs_more_info=False, reason="fail")
    revised = await r.reflect("task", step, decision, plan)
    assert revised is not None
    assert len(revised.steps) >= 1


@pytest.mark.asyncio
async def test_reflector_max_reflections():
    """Reflector should stop after max_reflections."""
    r = Reflector(max_reflections=1)
    step = PlanStep(id="s1", goal="fail")
    plan = Plan(id="p1", task="t", steps=[step])
    from evoagent.planning.critic import CriticDecision
    decision = CriticDecision(passed=False, needs_revision=True, needs_more_info=False, reason="fail")
    # First reflection works
    r1 = await r.reflect("t", step, decision, plan)
    assert r1 is not None
    # Second should return None (max reached)
    r2 = await r.reflect("t", step, decision, plan)
    assert r2 is None
