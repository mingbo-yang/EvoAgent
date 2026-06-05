"""Tests for WorkflowGraph."""

import pytest

from evoagent.core.errors import EvoAgentError
from evoagent.core.state import RuntimeState
from evoagent.workflow.edge import WorkflowEdge
from evoagent.workflow.graph import WorkflowGraph
from evoagent.workflow.node import WorkflowNode


async def _noop(state: RuntimeState, ctx: dict) -> RuntimeState:
    return state


async def _append(state: RuntimeState, ctx: dict) -> RuntimeState:
    state.metadata["visited"] = state.metadata.get("visited", []) + [ctx.get("tag", "?")]
    return state


def test_add_node_and_edge():
    graph = WorkflowGraph()
    graph.add_node(WorkflowNode(name="a", handler=_noop))
    graph.add_node(WorkflowNode(name="b", handler=_noop))
    graph.add_edge(WorkflowEdge(source="a", target="b"))
    graph.set_entrypoint("a")
    graph.set_finish("b")
    graph.validate()  # should not raise


def test_validate_missing_entrypoint():
    graph = WorkflowGraph()
    graph.add_node(WorkflowNode(name="a", handler=_noop))
    with pytest.raises(EvoAgentError, match="entrypoint"):
        graph.validate()


def test_validate_edge_missing_target():
    graph = WorkflowGraph()
    graph.add_node(WorkflowNode(name="a", handler=_noop))
    graph.add_edge(WorkflowEdge(source="a", target="nonexistent"))
    graph.set_entrypoint("a")
    graph.set_finish("a")
    with pytest.raises(EvoAgentError, match="not a registered node"):
        graph.validate()


def test_conditional_edge():
    graph = WorkflowGraph()
    graph.add_node(WorkflowNode(name="a", handler=_noop))
    graph.add_node(WorkflowNode(name="b", handler=_noop))
    graph.add_node(WorkflowNode(name="c", handler=_noop))

    # Conditional: go to b if success, else c
    graph.add_edge(WorkflowEdge(source="a", target="b",
                                condition=lambda s: s.status.value == "succeeded"))
    graph.add_edge(WorkflowEdge(source="a", target="c",
                                condition=lambda s: s.status.value != "succeeded"))

    state = RuntimeState(run_id="t1")
    # Default status is CREATED, so should route to c
    next_node = graph.get_next_node("a", state)
    assert next_node == "c"


def test_get_next_node_no_match():
    graph = WorkflowGraph()
    graph.add_node(WorkflowNode(name="a", handler=_noop))
    # No edges from a
    next_node = graph.get_next_node("a", RuntimeState(run_id="t"))
    assert next_node is None
