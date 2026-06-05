"""Tests for human interrupt and resume."""

import tempfile
from pathlib import Path

import pytest

from evoagent.core.state import RunStatus, RuntimeState
from evoagent.logging.checkpoint import CheckpointManager
from evoagent.workflow.edge import WorkflowEdge
from evoagent.workflow.graph import WorkflowGraph
from evoagent.workflow.interrupt import (
    InterruptType,
    create_approval_request,
    create_choice_request,
    create_clarification_request,
)
from evoagent.workflow.node import WorkflowNode
from evoagent.workflow.runtime import WorkflowRuntime


async def _interrupt_handler(state: RuntimeState, ctx: dict) -> RuntimeState:
    state.status = RunStatus.WAITING_FOR_HUMAN
    state.metadata["interrupt_reason"] = "Need approval"
    return state


async def _continue_handler(state: RuntimeState, ctx: dict) -> RuntimeState:
    state.metadata["continued"] = True
    return state


@pytest.fixture
def interrupt_graph():
    graph = WorkflowGraph()
    graph.add_node(WorkflowNode(name="start", handler=_interrupt_handler))
    graph.add_node(WorkflowNode(name="continue", handler=_continue_handler))
    graph.add_edge(WorkflowEdge(source="start", target="continue"))
    graph.set_entrypoint("start")
    graph.set_finish("continue")
    return graph


@pytest.mark.asyncio
async def test_node_triggers_waiting_for_human(interrupt_graph):
    runtime = WorkflowRuntime(interrupt_graph)
    state = RuntimeState(run_id="r_int", task="needs approval")
    result = await runtime.run(state)
    assert result.status == RunStatus.WAITING_FOR_HUMAN
    assert "Need approval" in result.metadata.get("interrupt_reason", "")


@pytest.mark.asyncio
async def test_runtime_pauses_on_interrupt(interrupt_graph):
    runtime = WorkflowRuntime(interrupt_graph)
    state = RuntimeState(run_id="r_pause")
    result = await runtime.run(state)
    assert result.status == RunStatus.WAITING_FOR_HUMAN
    # Should NOT have continued to next node
    assert "continued" not in result.metadata


@pytest.mark.asyncio
async def test_resume_interface(interrupt_graph):
    with tempfile.TemporaryDirectory() as tmp:
        chk_mgr = CheckpointManager(Path(tmp))
        runtime = WorkflowRuntime(interrupt_graph, checkpoint_manager=chk_mgr)
        state = RuntimeState(run_id="r_resume")
        result = await runtime.run(state)
        assert result.status == RunStatus.WAITING_FOR_HUMAN

        # Resume should load the checkpoint
        resumed = await runtime.resume("r_resume")
        assert resumed is not None
        assert resumed.status == RunStatus.RUNNING


def test_approval_request():
    req = create_approval_request("delete files", "Deleting temp files")
    assert req.request_type == InterruptType.APPROVAL
    assert "delete files" in req.requested_action


def test_clarification_request():
    req = create_clarification_request("What port should the server use?")
    assert req.request_type == InterruptType.CLARIFICATION


def test_choice_request():
    req = create_choice_request("Select environment", ["dev", "staging", "prod"])
    assert len(req.options) == 3
