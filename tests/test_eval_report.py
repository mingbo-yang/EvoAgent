"""Tests for EvalReport and Regression."""

import tempfile
from pathlib import Path

import pytest

from evoagent.eval.regression import Regression
from evoagent.eval.report import EvalReport
from evoagent.eval.task import EvalResult


@pytest.fixture
def results():
    return [
        EvalResult(task_id="a", run_id="r1", success=True, score=1.0, duration_ms=100),
        EvalResult(task_id="b", run_id="r2", success=False, score=0.0, duration_ms=200, error="fail"),
    ]


def test_markdown_report(results):
    md = EvalReport.to_markdown(results)
    assert "# Eval Report" in md
    assert "Success rate" in md
    assert "✅" in md
    assert "❌" in md


def test_json_report(results):
    j = EvalReport.to_json(results)
    assert '"success_rate"' in j


def test_save_report_md(results):
    with tempfile.TemporaryDirectory() as tmp:
        path = EvalReport.save_report(results, Path(tmp) / "report.md", fmt="md")
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "# Eval Report" in content


def test_save_report_json(results):
    with tempfile.TemporaryDirectory() as tmp:
        path = EvalReport.save_report(results, Path(tmp) / "report.json", fmt="json")
        assert Path(path).exists()


def test_regression_detected(results):
    old = [EvalResult(task_id="a", run_id="r1", success=True, score=1.0)]
    new = [EvalResult(task_id="a", run_id="r2", success=False, score=0.0)]
    reg = Regression.compare(old, new)
    assert reg["regression_detected"]


def test_no_regression(results):
    old = [EvalResult(task_id="a", run_id="r1", success=True, score=1.0)]
    new = [EvalResult(task_id="a", run_id="r2", success=True, score=1.0)]
    reg = Regression.compare(old, new)
    assert not reg["regression_detected"]
