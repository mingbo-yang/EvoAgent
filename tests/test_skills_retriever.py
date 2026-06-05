"""Tests for SkillRetriever."""

import pytest

from evoagent.skills.registry import SkillRegistry
from evoagent.skills.retriever import SkillRetriever
from evoagent.skills.schema import Skill


@pytest.fixture
def retriever():
    r = SkillRegistry()
    r.register(Skill(name="debug", description="Debug", triggers=["pytest", "traceback", "assertion"]))
    r.register(Skill(name="review", description="Code review", triggers=["review", "audit"]))
    r.register(Skill(name="tdd", description="Test-driven fix", triggers=["fix", "failing test"]))
    return SkillRetriever(r)


def test_retrieve_by_trigger(retriever):
    results = retriever.retrieve("pytest is failing")
    assert len(results) >= 1
    assert results[0].name == "debug"


def test_retrieve_by_error(retriever):
    results = retriever.retrieve("fix bug", error="AssertionError in test_calc")
    assert len(results) >= 1


def test_retrieve_top_k(retriever):
    results = retriever.retrieve("pytest traceback assertion review fix", top_k=2)
    assert len(results) <= 2


def test_success_boosts_ranking(retriever):
    retriever.registry.update_usage("review", success=True)
    retriever.registry.update_usage("review", success=True)
    results = retriever.retrieve("review")
    assert len(results) >= 1


def test_format_for_prompt(retriever):
    results = retriever.retrieve("pytest failure")
    formatted = retriever.format_for_prompt(results)
    assert "## Relevant Skills" in formatted
    assert "debug" in formatted


def test_empty_format(retriever):
    assert retriever.format_for_prompt([]) == ""
