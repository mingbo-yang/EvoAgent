"""Tests for TraceRecorder."""

import json
import tempfile
from pathlib import Path

import pytest

from evoagent.core.result import AgentResult
from evoagent.core.state import RuntimeState
from evoagent.logging.trace import TraceRecorder


@pytest.fixture
def trace_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def recorder(trace_dir):
    rec = TraceRecorder(trace_dir)
    yield rec
    rec.close()


def test_start_run_creates_directory(recorder, trace_dir):
    run_id = recorder.start_run("Test task")
    run_dir = trace_dir / run_id
    assert run_dir.exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "metadata.json").exists()
    assert (run_dir / "patches").is_dir()
    assert (run_dir / "artifacts").is_dir()


def test_events_jsonl_has_run_started(recorder):
    recorder.start_run("Test")
    events = recorder.get_events()
    assert len(events) >= 1
    assert events[0].event_type.value == "run_started"


def test_save_and_load_state(recorder):
    recorder.start_run("Test")
    state = RuntimeState(task="Test", run_id=recorder.get_current_run_id())
    recorder.save_state(state)

    loaded = recorder.load_state()
    assert loaded is not None
    assert loaded.task == "Test"


def test_save_final_result(recorder):
    recorder.start_run("Test")
    result = AgentResult(run_id=recorder.get_current_run_id() or "", task="Test",
                         success=True, final_answer="Done")
    recorder.save_final_result(result)

    run_dir = recorder.get_current_dir()
    assert run_dir is not None
    assert (run_dir / "final_result.json").exists()

    saved = json.loads((run_dir / "final_result.json").read_text())
    assert saved["success"] is True


def test_log_helper(recorder):
    recorder.start_run("Test")
    evt = recorder.log("tool_call_started", payload={"tool": "read_file"}, step_id="step_1")
    assert evt is not None
    assert evt.step_id == "step_1"

    events = recorder.get_events()
    assert len(events) == 2  # RUN_STARTED + our event


def test_get_current_run_id(recorder):
    assert recorder.get_current_run_id() is None
    rid = recorder.start_run("T")
    assert recorder.get_current_run_id() == rid


def test_list_runs(recorder, trace_dir):
    recorder.start_run("Task A")
    rec2 = TraceRecorder(trace_dir)
    rec2.start_run("Task B")
    rec2.close()

    runs = recorder.list_runs()
    assert len(runs) == 2


def test_get_latest_run_dir(recorder, trace_dir):
    import time
    recorder.start_run("First")
    time.sleep(0.1)
    rec2 = TraceRecorder(trace_dir)
    rec2.start_run("Second")
    rec2.close()

    latest = recorder.get_latest_run_dir()
    assert latest is not None
