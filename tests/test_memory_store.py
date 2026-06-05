"""Tests for SQLiteMemoryStore."""

import tempfile
from pathlib import Path

import pytest

from evoagent.memory.schema import MemoryItem, MemoryType
from evoagent.memory.sqlite_store import SQLiteMemoryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = SQLiteMemoryStore(Path(tmp) / "test.sqlite")
        yield s
        s.close()


def test_add_and_get(store):
    item = MemoryItem(memory_type=MemoryType.EPISODIC, content="Test memory")
    added = store.add(item)
    assert added.id

    fetched = store.get(added.id)
    assert fetched is not None
    assert fetched.content == "Test memory"


def test_search_keyword(store):
    store.add(MemoryItem(memory_type=MemoryType.SEMANTIC, content="Python is a programming language"))
    store.add(MemoryItem(memory_type=MemoryType.PROCEDURAL, content="Use git status to check changes"))
    results = store.search("python", top_k=5)
    assert len(results) >= 1
    assert any("Python" in r.content for r in results)


def test_search_by_type(store):
    store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="episodic item"))
    store.add(MemoryItem(memory_type=MemoryType.SEMANTIC, content="semantic item"))
    results = store.search("item", memory_types=[MemoryType.SEMANTIC], top_k=5)
    assert len(results) >= 1
    assert all(r.memory_type == MemoryType.SEMANTIC for r in results)


def test_update(store):
    item = store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="old", importance=0.3))
    updated = store.update(item.id, importance=0.9, content="new")
    assert updated.importance == 0.9
    assert updated.content == "new"


def test_delete(store):
    item = store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="to delete"))
    assert store.delete(item.id)
    assert store.get(item.id) is None
    assert not store.delete("nonexistent")


def test_list_by_type(store):
    store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="e1"))
    store.add(MemoryItem(memory_type=MemoryType.EPISODIC, content="e2"))
    store.add(MemoryItem(memory_type=MemoryType.SEMANTIC, content="s1"))
    epis = store.list(memory_type=MemoryType.EPISODIC)
    assert len(epis) == 2
    all_items = store.list()
    assert len(all_items) == 3


def test_metadata_json(store):
    item = MemoryItem(memory_type=MemoryType.EPISODIC, content="meta test",
                      metadata={"key": "value", "nested": {"a": 1}})
    added = store.add(item)
    fetched = store.get(added.id)
    assert fetched is not None
    assert fetched.metadata["key"] == "value"
    assert fetched.metadata["nested"]["a"] == 1
