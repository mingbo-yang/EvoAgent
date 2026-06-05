"""Tests for SkillRegistry."""

import pytest

from evoagent.skills.registry import SkillRegistry
from evoagent.skills.schema import Skill


@pytest.fixture
def registry():
    r = SkillRegistry()
    r.register(Skill(name="debug", description="Debug skill", triggers=["pytest failed", "traceback"]))
    r.register(Skill(name="review", description="Review skill", triggers=["code review", "audit"]))
    return r


def test_register_and_get(registry):
    s = registry.get("debug")
    assert s is not None
    assert s.description == "Debug skill"


def test_list(registry):
    names = [s.name for s in registry.list()]
    assert "debug" in names
    assert "review" in names


def test_duplicate_overwrites(registry):
    registry.register(Skill(name="debug", description="Updated debug"))
    s = registry.get("debug")
    assert s is not None
    assert s.description == "Updated debug"


def test_search_by_trigger(registry):
    results = registry.search_by_trigger("pytest failed with traceback")
    assert len(results) >= 1
    assert results[0].name == "debug"


def test_update_usage(registry):
    registry.update_usage("debug", success=True)
    s = registry.get("debug")
    assert s is not None
    assert s.success_count == 1
    assert s.last_used_at is not None

    registry.update_usage("debug", success=False)
    s = registry.get("debug")
    assert s.failure_count == 1
