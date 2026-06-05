"""Tests for EvalHarness and Checkers."""


import pytest

from evoagent.eval.checkers import ContainsChecker, RegexChecker, evaluate_check
from evoagent.eval.harness import EvalHarness
from evoagent.eval.task import EvalTask


class MockAgent:
    async def run(self, task: str):
        from evoagent.core.result import AgentResult
        return AgentResult(run_id="mock", task=task, success=True, final_answer="hello world")


@pytest.fixture
def harness():
    return EvalHarness(MockAgent())


@pytest.mark.asyncio
async def test_run_task_success(harness):
    task = EvalTask(task_id="t1", instruction="Say hello", expected_check='{"type":"contains","value":"hello"}')
    result = await harness.run_task(task)
    assert result.success
    assert result.task_id == "t1"


@pytest.mark.asyncio
async def test_run_task_exception_captured(harness):
    """Exception in agent should be captured in result."""
    agent = harness.agent

    async def bad_run(task: str):
        raise RuntimeError("agent crash")
    agent.run = bad_run
    task = EvalTask(task_id="t2", instruction="x")
    result = await harness.run_task(task)
    assert not result.success
    assert result.error is not None


def test_contains_checker():
    assert ContainsChecker.check("hello world", "hello")
    assert not ContainsChecker.check("world", "hello")


def test_regex_checker():
    assert RegexChecker.check("number: 150", r"\d{3}")
    assert not RegexChecker.check("number: 5", r"\d{3}")


def test_evaluate_check_contains():
    assert evaluate_check("hello world", '{"type":"contains","value":"hello"}')


def test_evaluate_check_regex():
    assert evaluate_check("150", '{"type":"regex","value":"1[0-9]{2}"}')


def test_evaluate_check_invalid_json():
    assert not evaluate_check("hello", "not json")
