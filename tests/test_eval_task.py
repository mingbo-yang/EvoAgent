"""Tests for EvalTask and DatasetLoader."""

import tempfile
from pathlib import Path

import pytest

from evoagent.eval.datasets import DatasetLoader
from evoagent.eval.task import EvalTask


def test_eval_task_serialization():
    task = EvalTask(task_id="t1", instruction="Say hello", task_type="text")
    data = task.model_dump()
    assert data["task_id"] == "t1"
    restored = EvalTask.model_validate(data)
    assert restored.instruction == "Say hello"


def test_load_jsonl():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"task_id":"a","instruction":"Task A"}\n')
        f.write('{"task_id":"b","instruction":"Task B"}\n')
        p = f.name
    tasks = DatasetLoader.load_jsonl(p)
    assert len(tasks) == 2
    assert tasks[0].task_id == "a"
    Path(p).unlink()


def test_load_jsonl_invalid():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("not json\n")
        p = f.name
    with pytest.raises(ValueError, match="invalid"):
        DatasetLoader.load_jsonl(p)
    Path(p).unlink()


def test_save_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.jsonl"
        tasks = [EvalTask(task_id="x", instruction="X")]
        DatasetLoader.save_jsonl(tasks, path)
        loaded = DatasetLoader.load_jsonl(path)
        assert len(loaded) == 1


def test_validate_duplicates():
    tasks = [EvalTask(task_id="dup", instruction="a"), EvalTask(task_id="dup", instruction="b")]
    warnings = DatasetLoader.validate(tasks)
    assert any("Duplicate" in w for w in warnings)
