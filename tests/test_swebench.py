"""Tests for the SWE-bench-style harness and evaluator."""

import subprocess
from pathlib import Path

import pytest

from evoagent.eval.swebench import (
    Prediction,
    SWEBenchEvaluator,
    SWEBenchHarness,
    SWEBenchInstance,
    git_diff,
    load_instances,
    resolved_rate,
)


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _make_repo(tmp_path: Path) -> Path:
    """A tiny git repo with a buggy add() and a failing test."""
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")  # BUG: minus
    (repo / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@example.com"], repo)
    _git(["config", "user.name", "tester"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "initial (buggy)"], repo)
    return repo


class _FixingAgent:
    """Fake agent that fixes the bug by rewriting calc.py."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)

    async def run(self, task: str):
        (self.workspace / "calc.py").write_text("def add(a, b):\n    return a + b\n")
        return None


class _NoopAgent:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)

    async def run(self, task: str):
        return None


def _instance(repo: Path) -> SWEBenchInstance:
    return SWEBenchInstance(
        instance_id="calc-1",
        workspace=repo,
        problem_statement="add(a, b) returns a - b but should return a + b.",
        fail_to_pass=["test_calc.py"],
    )


def test_git_diff_captures_changes(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    diff = git_diff(repo)
    assert "calc.py" in diff
    assert "+    return a + b" in diff


@pytest.mark.asyncio
async def test_harness_produces_patch(tmp_path):
    repo = _make_repo(tmp_path)
    harness = SWEBenchHarness(lambda ws: _FixingAgent(ws), model_name="evoagent-test")
    pred = await harness.run_instance(_instance(repo))
    assert pred.instance_id == "calc-1"
    assert pred.model_name_or_path == "evoagent-test"
    assert "return a + b" in pred.model_patch


@pytest.mark.asyncio
async def test_fix_patch_resolves_instance(tmp_path):
    repo = _make_repo(tmp_path)
    inst = _instance(repo)
    harness = SWEBenchHarness(lambda ws: _FixingAgent(ws))
    pred = await harness.run_instance(inst)
    result = SWEBenchEvaluator().evaluate(inst, pred)
    assert result.patch_applied
    assert result.fail_to_pass_ok
    assert result.resolved


@pytest.mark.asyncio
async def test_noop_agent_does_not_resolve(tmp_path):
    repo = _make_repo(tmp_path)
    inst = _instance(repo)
    harness = SWEBenchHarness(lambda ws: _NoopAgent(ws))
    pred = await harness.run_instance(inst)
    result = SWEBenchEvaluator().evaluate(inst, pred)
    # No change -> the failing test still fails on a clean checkout.
    assert not result.resolved
    assert not result.fail_to_pass_ok


def test_save_and_load_predictions(tmp_path):
    repo = _make_repo(tmp_path)
    preds = [Prediction("calc-1", "evoagent", "the-diff")]
    out = tmp_path / "preds.jsonl"
    SWEBenchHarness.save_predictions(preds, out)
    loaded = [line for line in out.read_text().splitlines() if line]
    assert len(loaded) == 1
    assert "calc-1" in loaded[0]

    # load_instances roundtrip
    import json
    inst_file = tmp_path / "instances.jsonl"
    inst_file.write_text(json.dumps({
        "instance_id": "calc-1", "workspace": str(repo),
        "problem_statement": "fix add", "fail_to_pass": ["test_calc.py"],
    }) + "\n")
    instances = load_instances(inst_file)
    assert len(instances) == 1
    assert instances[0].instance_id == "calc-1"
    assert instances[0].fail_to_pass == ["test_calc.py"]


def test_resolved_rate():
    from evoagent.eval.swebench import EvalResult
    rs = [EvalResult("a", resolved=True), EvalResult("b", resolved=False)]
    assert resolved_rate(rs) == 0.5
    assert resolved_rate([]) == 0.0
