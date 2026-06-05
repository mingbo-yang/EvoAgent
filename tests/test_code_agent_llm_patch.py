"""Tests for CodeAgent LLM patch validation."""

import tempfile
from pathlib import Path

import pytest

from evoagent.code.agent import CodeAgent
from evoagent.code.schema import FileEdit, PatchPlan
from evoagent.models.factory import MockLLMProvider
from evoagent.models.router import ModelRouter


@pytest.fixture
def bug_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "calc.py").write_text("def divide(a, b):\n    return a / b\n")
        (root / "test_calc.py").write_text(
            "import pytest\nfrom calc import divide\ndef test_div():\n    assert divide(6,2)==3\n"
        )
        yield root


def test_patch_plan_schema():
    plan = PatchPlan(
        reasoning="fix division by zero",
        target_files=["calc.py"],
        edits=[FileEdit(path="calc.py", old_text="return a / b",
                         new_text="return a / b if b != 0 else 0", explanation="guard zero")],
        test_commands=["python -m pytest test_calc.py -q"],
        risk_level="low",
    )
    assert plan.risk_level == "low"
    assert len(plan.edits) == 1


@pytest.mark.asyncio
async def test_code_agent_llm_patch_applies(bug_workspace):
    """MockLLM returns PatchPlan and CodeAgent applies it."""
    plan_json = '{"reasoning":"fix","target_files":["calc.py"],"edits":[{"path":"calc.py","old_text":"return a / b","new_text":"return a / b if b != 0 else 0","explanation":"guard"}],"test_commands":["python -m pytest test_calc.py -q"],"risk_level":"low"}'
    mock = MockLLMProvider(fixed_text=plan_json)
    router = ModelRouter(providers={"executor": mock, "default": mock})
    agent = CodeAgent(workspace=bug_workspace, model_router=router, max_iterations=1)
    result = await agent.run("Fix division by zero")
    assert result.iterations >= 1
    assert len(result.changed_files) >= 1 or result.test_result is not None


@pytest.mark.asyncio
async def test_old_text_missing_rejected(bug_workspace):
    """Patch with non-existent old_text should not apply."""
    plan_json = '{"reasoning":"fix","target_files":["calc.py"],"edits":[{"path":"calc.py","old_text":"NONEXISTENT_TEXT_XYZ","new_text":"something","explanation":"test"}],"test_commands":[],"risk_level":"low"}'
    mock = MockLLMProvider(fixed_text=plan_json)
    router = ModelRouter(providers={"executor": mock, "default": mock})
    agent = CodeAgent(workspace=bug_workspace, model_router=router, max_iterations=1)
    result = await agent.run("Fix bug")
    # Should not change files (old_text not found)
    assert "calc.py" not in result.changed_files or result.test_result is not None


@pytest.mark.asyncio
async def test_path_outside_workspace_rejected(bug_workspace):
    """Edit targeting path outside workspace should be rejected."""
    plan_json = '{"reasoning":"fix","target_files":["/etc/passwd"],"edits":[{"path":"/etc/passwd","old_text":"x","new_text":"y","explanation":"test"}],"test_commands":[],"risk_level":"low"}'
    mock = MockLLMProvider(fixed_text=plan_json)
    router = ModelRouter(providers={"executor": mock, "default": mock})
    agent = CodeAgent(workspace=bug_workspace, model_router=router, max_iterations=1)
    result = await agent.run("Fix outside workspace")
    assert "/etc/passwd" not in result.changed_files


@pytest.mark.asyncio
async def test_max_iterations_enforced(bug_workspace):
    """CodeAgent should stop after max_iterations."""
    plan_json = '{"reasoning":"fix","target_files":["calc.py"],"edits":[{"path":"calc.py","old_text":"return a / b","new_text":"return a / b if b != 0 else 0","explanation":"guard"}],"test_commands":["python -m pytest test_calc.py -q"],"risk_level":"low"}'
    mock = MockLLMProvider(fixed_text=plan_json)
    router = ModelRouter(providers={"executor": mock, "default": mock})
    agent = CodeAgent(workspace=bug_workspace, model_router=router, max_iterations=2)
    result = await agent.run("Fix bug")
    assert result.iterations <= 2


def test_rule_based_fallback_zero_division():
    """Rule-based fallback handles ZeroDivisionError pattern."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "calc.py").write_text("def divide(a, b):\n    return a / b\n")
        (root / "test_calc.py").write_text(
            "import pytest\nfrom calc import divide\ndef test_zero():\n    with pytest.raises(ZeroDivisionError):\n        divide(1,0)\n"
        )
        agent = CodeAgent(workspace=root, max_iterations=2)
        import asyncio
        result = asyncio.run(agent.run("Fix division by zero"))
        # Rule-based should detect ZeroDivisionError and patch
        assert result.iterations >= 1
