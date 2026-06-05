"""Tests for MemoryWriter."""

import tempfile
from pathlib import Path

import pytest

from evoagent.core.state import RunStatus, RuntimeState
from evoagent.memory.schema import MemoryType
from evoagent.memory.sqlite_store import SQLiteMemoryStore
from evoagent.memory.writer import MemoryWriter


@pytest.fixture
def writer():
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLiteMemoryStore(Path(tmp) / "test.sqlite")
        w = MemoryWriter(store)
        yield w
        store.close()


def test_write_from_successful_run(writer):
    state = RuntimeState(run_id="run_1", task="List files", status=RunStatus.SUCCEEDED)
    assert hasattr(state, "add_step_result")
    results = writer.write_from_run(state, success=True)
    assert len(results) >= 1
    assert results[0].memory_type == MemoryType.EPISODIC
    assert results[0].source_run_id == "run_1"


def test_write_from_failed_run(writer):
    state = RuntimeState(run_id="run_2", task="Delete files", status=RunStatus.FAILED)
    state.add_error("Permission denied")
    results = writer.write_from_run(state, success=False)
    assert len(results) >= 2  # episodic + reflection
    types = [r.memory_type for r in results]
    assert MemoryType.EPISODIC in types
    assert MemoryType.REFLECTION in types
    for r in results:
        assert r.source_run_id == "run_2"
