"""Tests for WorkflowRuntime."""

import tempfile
from pathlib import Path

import pytest

from evoagent.core.state import RunStatus, RuntimeState
from evoagent.logging.checkpoint import CheckpointManager
from evoagent.workflow.edge import WorkflowEdge
from evoagent.workflow.graph import WorkflowGraph
from evoagent.workflow.node import WorkflowNode
from evoagent.workflow.runtime import WorkflowRuntime


async def _tag(state: RuntimeState, ctx: dict) -> RuntimeState:
    tag = ctx.get("tag", "?")
    state.metadata["tags"] = state.metadata.get("tags", []) + [tag]
    return state


async def _failing(state: RuntimeState, ctx: dict) -> RuntimeState:
    raise ValueError("node failure")


async def _slow(state: RuntimeState, ctx: dict) -> RuntimeState:
    state.metadata["slow"] = True
    return state


@pytest.fixture
def simple_graph():
    graph = WorkflowGraph()
    graph.add_node(WorkflowNode(name="start", handler=_tag))
    graph.add_node(WorkflowNode(name="middle", handler=_tag))
    graph.add_node(WorkflowNode(name="end", handler=_tag))
    graph.add_edge(WorkflowEdge(source="start", target="middle"))
    graph.add_edge(WorkflowEdge(source="middle", target="end"))
    graph.set_entrypoint("start")
    graph.set_finish("end")
    return graph


@pytest.mark.asyncio
async def test_runtime_a_to_b_to_end(simple_graph):
    runtime = WorkflowRuntime(simple_graph)
    state = RuntimeState(run_id="r1", task="test")
    result = await runtime.run(state, context={"tag": "executed"})
    assert result.status == RunStatus.SUCCEEDED
    assert result.metadata.get("tags") == ["executed", "executed", "executed"]


@pytest.mark.asyncio
async def test_runtime_max_steps(simple_graph):
    runtime = WorkflowRuntime(simple_graph, max_steps=2)
    state = RuntimeState(run_id="r2")
    result = await runtime.run(state, context={"tag": "x"})
    assert any("Max steps" in e for e in result.errors)


@pytest.mark.asyncio
async def test_runtime_node_exception_captured():
    graph = WorkflowGraph()
    graph.add_node(WorkflowNode(name="bad", handler=_failing))
    graph.add_node(WorkflowNode(name="safe", handler=_tag))
    graph.add_edge(WorkflowEdge(source="bad", target="safe"))
    graph.set_entrypoint("bad")
    graph.set_finish("safe")

    runtime = WorkflowRuntime(graph)
    state = RuntimeState(run_id="r3")
    result = await runtime.run(state)
    assert len(result.errors) >= 1
    assert "Node 'bad' failed" in result.errors[0]


@pytest.mark.asyncio
async def test_runtime_saves_checkpoint(simple_graph):
    with tempfile.TemporaryDirectory() as tmp:
        chk_mgr = CheckpointManager(Path(tmp))
        runtime = WorkflowRuntime(simple_graph, checkpoint_manager=chk_mgr, save_checkpoints=True)
        state = RuntimeState(run_id="r4", task="test")
        result = await runtime.run(state, context={"tag": "chk"})
        assert result.status == RunStatus.SUCCEEDED

        chks = chk_mgr.list_checkpoints("r4")
        assert len(chks) >= 2  # at least start and middle checkpoints
