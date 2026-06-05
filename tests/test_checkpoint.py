"""Tests for CheckpointManager and DiffRecorder."""

import tempfile
from pathlib import Path

import pytest

from evoagent.core.state import RuntimeState
from evoagent.logging.checkpoint import CheckpointManager
from evoagent.logging.diff import DiffRecorder

# ── CheckpointManager ─────────────────────────────────────────────────


@pytest.fixture
def chk_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def chk_mgr(chk_dir):
    return CheckpointManager(chk_dir)


def test_save_and_load_checkpoint(chk_mgr):
    state = RuntimeState(run_id="run_1", task="test task")
    _ = chk_mgr.save_checkpoint(state, name="before_edit")

    loaded = chk_mgr.load_checkpoint("run_1")
    assert loaded is not None
    assert loaded.state is not None
    assert loaded.state.task == "test task"


def test_load_latest_checkpoint(chk_mgr):
    s1 = RuntimeState(run_id="run_1", task="first")
    s2 = RuntimeState(run_id="run_1", task="second")
    chk_mgr.save_checkpoint(s1, name="first")
    chk_mgr.save_checkpoint(s2, name="second")

    loaded = chk_mgr.load_checkpoint("run_1")
    assert loaded is not None
    assert loaded.state is not None
    assert loaded.state.task == "second"


def test_load_by_checkpoint_id(chk_mgr):
    s1 = RuntimeState(run_id="run_1", task="first")
    chk1 = chk_mgr.save_checkpoint(s1, name="one")
    chk_mgr.save_checkpoint(RuntimeState(run_id="run_1", task="second"), name="two")

    loaded = chk_mgr.load_checkpoint("run_1", checkpoint_id=chk1.id)
    assert loaded is not None
    assert loaded.state is not None
    assert loaded.state.task == "first"


def test_load_nonexistent_returns_none(chk_mgr):
    assert chk_mgr.load_checkpoint("nonexistent") is None


def test_list_checkpoints(chk_mgr):
    chk_mgr.save_checkpoint(RuntimeState(run_id="run_1", task="a"))
    chk_mgr.save_checkpoint(RuntimeState(run_id="run_1", task="b"))

    chks = chk_mgr.list_checkpoints("run_1")
    assert len(chks) == 2


def test_checkpoint_state_roundtrip(chk_mgr):
    """RuntimeState should be fully recoverable from checkpoint."""
    state = RuntimeState(
        run_id="run_1",
        task="complex task",
        errors=["err1", "err2"],
        metadata={"key": "value"},
    )
    assert hasattr(state, "add_tool_result")  # verify helper exists
    chk = chk_mgr.save_checkpoint(state)

    loaded = chk_mgr.load_checkpoint("run_1", checkpoint_id=chk.id)
    assert loaded is not None
    assert loaded.state is not None
    assert loaded.state.errors == ["err1", "err2"]


# ── DiffRecorder ──────────────────────────────────────────────────────


@pytest.fixture
def patches_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def test_generate_diff(patches_dir):
    recorder = DiffRecorder(patches_dir)
    diff = recorder.generate_diff("hello\nworld\n", "hello\nEvoAgent\n", "test.txt")
    assert "-world" in diff or "-world\n" in diff
    assert "+EvoAgent" in diff


def test_generate_diff_no_changes(patches_dir):
    recorder = DiffRecorder(patches_dir)
    diff = recorder.generate_diff("same", "same", "f.txt")
    assert diff == ""


def test_record_diff_saves_file(patches_dir):
    recorder = DiffRecorder(patches_dir)
    result = recorder.record_diff("old", "new", "main.py", step_id="step_1")
    assert result is not None
    patch_file = patches_dir / "step_1_main.py.patch"
    assert patch_file.exists()
    content = patch_file.read_text()
    assert "-old" in content or "-old\n" in content
    assert "+new" in content


def test_record_diff_no_changes_returns_none(patches_dir):
    recorder = DiffRecorder(patches_dir)
    result = recorder.record_diff("same", "same", "f.txt")
    assert result is None


def test_contains_changes():
    assert DiffRecorder.contains_changes("-removed\n+added\n")
    assert not DiffRecorder.contains_changes(" unchanged\n")
    assert DiffRecorder.contains_changes("@@ -1 +1 @@\n+new\n")


# ── RuntimeState helpers ──────────────────────────────────────────────


def test_runtime_state_touch():
    state = RuntimeState(task="t")
    old = state.updated_at
    state.touch()
    assert state.updated_at != old


def test_runtime_state_add_error():
    state = RuntimeState(task="t")
    state.add_error("something went wrong")
    assert "something went wrong" in state.errors


def test_runtime_state_save_load_json(tmp_path):
    state = RuntimeState(run_id="run_x", task="test")
    path = tmp_path / "state.json"
    state.save_json(str(path))
    loaded = RuntimeState.load_json(str(path))
    assert loaded.run_id == "run_x"
    assert loaded.task == "test"
