"""Tests for the full Agent loop."""

import tempfile
from pathlib import Path

import pytest

from evoagent.core.result import AgentResult
from evoagent.logging.trace import TraceRecorder
from evoagent.models.factory import MockLLMProvider
from evoagent.planning.critic import Critic
from evoagent.planning.executor import Executor
from evoagent.planning.loop import AgentLoop
from evoagent.planning.planner import Planner
from evoagent.tools.builtin import create_builtin_registry


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def loop(workspace):
    plan_json = '{"risk_level":"low","steps":[{"goal":"List files","action_type":"tool","tool_name":"list_directory","arguments":{"path":"."},"expected_result":"files listed"},{"goal":"Done","action_type":"finish"}]}'
    planner_mock = MockLLMProvider(fixed_text=plan_json)
    executor_mock = MockLLMProvider(fixed_text="executing")

    planner = Planner(llm=planner_mock)
    registry = create_builtin_registry(workspace)
    executor = Executor(tool_registry=registry, llm=executor_mock)
    critic = Critic(mode="rule")

    return AgentLoop(
        tool_registry=registry,
        planner=planner,
        executor=executor,
        critic=critic,
    )


@pytest.mark.asyncio
async def test_agent_loop_completes_simple_task(loop, workspace):
    (workspace / "test.txt").write_text("data")
    result = await loop.run("List files")
    assert isinstance(result, AgentResult)
    assert result.success
    assert result.steps_taken >= 1
    assert result.run_id


@pytest.mark.asyncio
async def test_agent_loop_max_steps(workspace):
    """Agent should stop at max_steps."""
    plan_json = '{"risk_level":"low","steps":[' + \
        ','.join([f'{{"goal":"Step {i}","action_type":"tool","tool_name":"echo","arguments":{{"command":"echo {i}"}}}}' for i in range(20)]) + \
        ']}'
    planner_mock = MockLLMProvider(fixed_text=plan_json)
    registry = create_builtin_registry(workspace)
    executor = Executor(tool_registry=registry)
    critic = Critic(mode="rule")

    loop = AgentLoop(
        tool_registry=registry,
        planner=Planner(llm=planner_mock),
        executor=executor,
        critic=critic,
        max_steps=3,
    )
    result = await loop.run("many steps")
    assert result.steps_taken <= 4  # 3 executed + 1 counted before break


@pytest.mark.asyncio
async def test_agent_loop_tool_error_recorded(workspace):
    """Tool errors should be recorded in state."""
    plan_json = '{"risk_level":"low","steps":[{"goal":"Bad tool","action_type":"tool","tool_name":"bash","arguments":{"command":"nonexistent_command_xyz"},"expected_result":"error"},{"goal":"Done","action_type":"finish"}]}'
    planner_mock = MockLLMProvider(fixed_text=plan_json)
    registry = create_builtin_registry(workspace)
    executor = Executor(tool_registry=registry)

    loop = AgentLoop(
        tool_registry=registry,
        planner=Planner(llm=planner_mock),
        executor=executor,
        critic=Critic(mode="rule"),
    )
    result = await loop.run("bad task")
    assert result.state is not None
    assert len(result.state.tool_results) >= 1


@pytest.mark.asyncio
async def test_agent_loop_with_trace_recorder(workspace):
    """TraceRecorder should log events during a run."""
    plan_json = '{"risk_level":"low","steps":[{"goal":"List","action_type":"tool","tool_name":"list_directory","arguments":{"path":"."},"expected_result":"ok"},{"goal":"Done","action_type":"finish"}]}'
    planner_mock = MockLLMProvider(fixed_text=plan_json)
    registry = create_builtin_registry(workspace)
    executor = Executor(tool_registry=registry)

    with tempfile.TemporaryDirectory() as trace_dir:
        recorder = TraceRecorder(Path(trace_dir))
        loop = AgentLoop(
            tool_registry=registry,
            planner=Planner(llm=planner_mock),
            executor=executor,
            critic=Critic(mode="rule"),
            trace_recorder=recorder,
        )
        result = await loop.run("trace test")
        assert result.success
        assert result.run_id

        events = recorder.get_events()
        assert len(events) >= 1
        recorder.close()


@pytest.mark.asyncio
async def test_agent_result_has_final_answer(loop, workspace):
    (workspace / "x.txt").write_text("ok")
    result = await loop.run("read file")
    assert result.final_answer is not None


@pytest.mark.asyncio
async def test_memory_injected_into_planner(workspace):
    """When memory_store has relevant memories, Planner sees them in context."""
    from evoagent.memory.schema import MemoryItem, MemoryType
    from evoagent.memory.sqlite_store import SQLiteMemoryStore

    store = SQLiteMemoryStore()
    store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="User likes Python scripts",
                         importance=1.0))

    # Create a simple agent with memory store
    from evoagent.core.agent import Agent
    mock = MockLLMProvider(fixed_text='{"risk_level":"low","steps":[{"goal":"Do task with memory","action_type":"finish"}]}')
    from evoagent.models.router import ModelRouter
    router = ModelRouter(providers={"planner": mock, "default": mock})
    tools = create_builtin_registry(workspace)
    agent = Agent(model_router=router, tool_registry=tools, workspace=workspace, memory_store=store)
    # run triggers memory retrieval
    result = await agent.run("Python script")
    assert result is not None
    # memory_context should be set
    assert "Relevant Memories" in agent._memory_context
    store.close()
