"""Tests for JSONLEventLogger."""

import json
import tempfile
from pathlib import Path

import pytest

from evoagent.logging.event import Event, EventType
from evoagent.logging.jsonl_logger import JSONLEventLogger


@pytest.fixture
def logger():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    lg = JSONLEventLogger(path)
    yield lg
    lg.close()
    Path(path).unlink(missing_ok=True)


def test_write_and_read_event(logger):
    evt = Event(event_type=EventType.RUN_STARTED, run_id="run_1", payload={"task": "test"})
    logger.log_event(evt)

    events = logger.get_events()
    assert len(events) == 1
    assert events[0].run_id == "run_1"
    assert events[0].event_type == EventType.RUN_STARTED


def test_event_is_valid_json(logger):
    evt = Event(event_type=EventType.TOOL_CALL_FINISHED, run_id="r1", payload={"result": "ok"})
    logger.log_event(evt)

    with open(logger.path) as f:
        line = f.readline().strip()
    data = json.loads(line)
    assert data["run_id"] == "r1"
    assert data["event_type"] == "tool_call_finished"


def test_filter_by_event_type(logger):
    logger.log(EventType.RUN_STARTED, run_id="r1")
    logger.log(EventType.ERROR, run_id="r1", payload={"msg": "fail"})
    logger.log(EventType.RUN_FINISHED, run_id="r1")

    errors = logger.get_events(event_type=EventType.ERROR)
    assert len(errors) == 1
    assert errors[0].event_type == EventType.ERROR


def test_filter_by_run_id(logger):
    logger.log(EventType.RUN_STARTED, run_id="run_a")
    logger.log(EventType.RUN_STARTED, run_id="run_b")
    logger.log(EventType.RUN_FINISHED, run_id="run_a")

    a_events = logger.get_events(run_id="run_a")
    assert len(a_events) == 2
    assert all(e.run_id == "run_a" for e in a_events)


def test_append_mode_works(logger):
    """Multiple log calls should append, not overwrite."""
    logger.log(EventType.RUN_STARTED, run_id="r1")
    logger.log(EventType.ERROR, run_id="r1")
    logger.log(EventType.RUN_FINISHED, run_id="r1")

    events = logger.get_events()
    assert len(events) == 3


def test_get_run_ids(logger):
    logger.log(EventType.RUN_STARTED, run_id="run_x")
    logger.log(EventType.RUN_FINISHED, run_id="run_x")
    logger.log(EventType.RUN_STARTED, run_id="run_y")

    ids = logger.get_run_ids()
    assert ids == {"run_x", "run_y"}


def test_empty_log_returns_empty(logger):
    assert logger.get_events() == []
    assert logger.get_run_ids() == set()


def test_log_returns_event(logger):
    evt = logger.log(EventType.RUN_STARTED, run_id="r1", payload={"x": 1})
    assert isinstance(evt, Event)
    assert evt.run_id == "r1"


def test_context_manager():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    with JSONLEventLogger(path) as lg:
        lg.log(EventType.RUN_STARTED, run_id="ctx_test")
    # File should be closed after context manager
    events = JSONLEventLogger(path).get_events()
    assert len(events) == 1
    Path(path).unlink(missing_ok=True)
