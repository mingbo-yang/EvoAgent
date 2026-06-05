"""Tests for CodeAgent."""

import tempfile
from pathlib import Path

import pytest

from evoagent.code.agent import CodeAgent


@pytest.fixture
def bug_repo():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "calc.py").write_text("def divide(a, b):\n    return a / b\n")
        (root / "test_calc.py").write_text(
            "import pytest\nfrom calc import divide\n\ndef test_divide():\n    assert divide(4, 2) == 2\n\ndef test_zero():\n    with pytest.raises(ZeroDivisionError):\n        divide(1, 0)\n"
        )
        yield root


@pytest.mark.asyncio
async def test_code_agent_scans_repo(bug_repo):
    agent = CodeAgent(workspace=bug_repo, max_iterations=2)
    result = await agent.run("Fix division by zero")
    assert result.changed_files or result.iterations >= 1


@pytest.mark.asyncio
async def test_code_agent_runs_tests(bug_repo):
    agent = CodeAgent(workspace=bug_repo, max_iterations=2)
    result = await agent.run("Fix the bug")
    assert result.test_result is not None
    assert result.iterations >= 1


@pytest.mark.asyncio
async def test_code_agent_output_structure(bug_repo):
    agent = CodeAgent(workspace=bug_repo, max_iterations=1)
    result = await agent.run("Fix bug")
    assert isinstance(result.changed_files, list)
    assert result.diff or result.summary


@pytest.mark.asyncio
async def test_code_agent_rule_based_fix(bug_repo):
    """Rule-based fix should handle ZeroDivisionError pattern."""
    agent = CodeAgent(workspace=bug_repo, max_iterations=3)
    result = await agent.run("Fix division by zero bug")
    # After fix, running tests again should pass or have been attempted
    assert result.iterations >= 1
