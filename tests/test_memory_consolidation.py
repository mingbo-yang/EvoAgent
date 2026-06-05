"""Tests for MemoryConsolidator and MemoryEvolution."""

import tempfile
from pathlib import Path

import pytest

from evoagent.memory.consolidation import MemoryConsolidator
from evoagent.memory.evolution import MemoryEvolution
from evoagent.memory.schema import MemoryItem, MemoryType
from evoagent.memory.sqlite_store import SQLiteMemoryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = SQLiteMemoryStore(Path(tmp) / "test.sqlite")
        yield s
        s.close()


def test_consolidate_merges_similar(store):
    store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="list files in directory",
                         importance=0.5, success_count=1))
    store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="list directory files",
                         importance=0.5, success_count=2))

    c = MemoryConsolidator(store, similarity_threshold=0.4)
    merges = c.consolidate()
    assert merges >= 1  # They should be similar enough to merge


def test_update_stats_success(store):
    item = store.add(MemoryItem(memory_type=MemoryType.PROCEDURAL, content="do X", importance=0.5, success_count=0))
    c = MemoryConsolidator(store)
    c.update_stats(item.id, success=True)
    updated = store.get(item.id)
    assert updated is not None
    assert updated.success_count == 1
    assert updated.importance > 0.5


def test_update_stats_failure(store):
    item = store.add(MemoryItem(memory_type=MemoryType.PROCEDURAL, content="do Y", importance=0.5, failure_count=0))
    c = MemoryConsolidator(store)
    c.update_stats(item.id, success=False)
    updated = store.get(item.id)
    assert updated is not None
    assert updated.failure_count == 1
    assert updated.importance < 0.5


def test_evolution_boost_success(store):
    store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="Created Python script successfully", importance=0.5, success_count=0))
    evolver = MemoryEvolution(store)
    updated = evolver.evolve_memories(recent_successes=["Python script"])
    assert len(updated) >= 1
    assert updated[0].success_count >= 1


def test_evolution_penalize_failure(store):
    store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="Failed to delete files", importance=0.5, failure_count=0, confidence=0.8))
    evolver = MemoryEvolution(store)
    updated = evolver.evolve_memories(recent_failures=["delete files"])
    assert len(updated) >= 1
    assert updated[0].confidence < 0.8
