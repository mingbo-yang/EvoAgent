"""Tests for SkillUsageTracker and SkillEvolution."""

import tempfile
from pathlib import Path

import pytest

from evoagent.skills.evolution import SkillEvolution
from evoagent.skills.registry import SkillRegistry
from evoagent.skills.schema import Skill
from evoagent.skills.usage import SkillUsageTracker


@pytest.fixture
def registry():
    r = SkillRegistry()
    r.register(Skill(name="debug", description="Debug", triggers=["pytest"]))
    r.register(Skill(name="review", description="Review", triggers=["review"]))
    return r


def test_record_usage(registry):
    with tempfile.TemporaryDirectory() as tmp:
        tracker = SkillUsageTracker(registry, Path(tmp) / "usage.json")
        tracker.record_usage("debug", success=True, task="fix bug")

        s = registry.get("debug")
        assert s is not None
        assert s.success_count == 1


def test_save_and_load_stats(registry):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "usage.json"
        tracker = SkillUsageTracker(registry, path)
        tracker.record_usage("debug", success=True)
        tracker.record_usage("review", success=False)
        tracker.save()

        loaded = tracker.load_stats()
        assert len(loaded) == 2
        assert loaded[0]["skill"] == "debug"
        assert loaded[0]["success"] is True


def test_evolution_high_success(registry):
    for _ in range(5):
        registry.update_usage("debug", success=True)
    evolver = SkillEvolution(registry)
    modified = evolver.evolve()
    assert "debug" in modified
    s = registry.get("debug")
    assert s is not None
    assert s.metadata.get("priority") == "high"


def test_evolution_low_success(registry):
    for _ in range(5):
        registry.update_usage("review", success=False)
    evolver = SkillEvolution(registry)
    modified = evolver.evolve()
    assert "review" in modified
    s = registry.get("review")
    assert s is not None
    assert s.metadata.get("priority") == "low"
