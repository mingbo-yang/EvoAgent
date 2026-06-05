"""Tests for Executor."""

import tempfile
from pathlib import Path

import pytest

from evoagent.core.state import RunStatus, RuntimeState
from evoagent.models.factory import MockLLMProvider
from evoagent.planning.executor import Executor
from evoagent.planning.schema import ActionType, PlanStep
from evoagent.tools.builtin import create_builtin_registry


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def registry(workspace):
    return create_builtin_registry(workspace)


@pytest.fixture
def executor(registry):
    mock = MockLLMProvider(fixed_text="reasoned response")
    return Executor(tool_registry=registry, llm=mock)


@pytest.mark.asyncio
async def test_executor_list_dir(executor, workspace):
    (workspace / "a.txt").write_text("hello")
    state = RuntimeState(run_id="r1", task="list")
    step = PlanStep(goal="list", action_type=ActionType.TOOL, tool_name="list_directory",
                    arguments={"path": "."})
    result = await executor.execute_step(state, step)
    assert result.success
    assert "a.txt" in str(result.output)


@pytest.mark.asyncio
async def test_executor_read_file(executor, workspace):
    (workspace / "f.txt").write_text("data here")
    state = RuntimeState(run_id="r2", task="read")
    step = PlanStep(goal="read", action_type=ActionType.TOOL, tool_name="read_file",
                    arguments={"path": "f.txt"})
    result = await executor.execute_step(state, step)
    assert result.success
    assert "data here" in str(result.output)


@pytest.mark.asyncio
async def test_executor_unknown_tool(executor):
    state = RuntimeState(run_id="r3", task="bad")
    step = PlanStep(goal="bad", action_type=ActionType.TOOL, tool_name="nonexistent",
                    arguments={})
    result = await executor.execute_step(state, step)
    assert not result.success


@pytest.mark.asyncio
async def test_executor_ask_user(executor):
    state = RuntimeState(run_id="r4", task="ask")
    step = PlanStep(goal="need input", action_type=ActionType.ASK_USER)
    result = await executor.execute_step(state, step)
    assert result.success
    assert state.status == RunStatus.WAITING_FOR_HUMAN


@pytest.mark.asyncio
async def test_executor_finish(executor):
    state = RuntimeState(run_id="r5", task="done")
    step = PlanStep(goal="done", action_type=ActionType.FINISH)
    result = await executor.execute_step(state, step)
    assert result.success
    assert state.status == RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_executor_llm_step(executor):
    state = RuntimeState(run_id="r6", task="think")
    step = PlanStep(goal="reason", action_type=ActionType.LLM)
    result = await executor.execute_step(state, step)
    assert result.success
    assert "reasoned" in str(result.output)
