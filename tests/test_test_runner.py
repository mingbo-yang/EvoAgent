"""Tests for CodeTestRunner and Diagnostics."""

import tempfile
from pathlib import Path

import pytest

from evoagent.code.diagnostics import Diagnostics
from evoagent.code.test_runner import CodeTestRunner


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Create a passing test
        (root / "test_pass.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
        (root / "test_fail.py").write_text("def test_bad():\n    assert 1 == 2\n")
        yield root


def test_runner_passing(workspace):
    runner = CodeTestRunner(workspace)
    result = runner.run("python -m pytest test_pass.py -q")
    assert result.success


def test_runner_failing(workspace):
    runner = CodeTestRunner(workspace)
    result = runner.run("python -m pytest test_fail.py -q")
    assert not result.success


def test_runner_timeout(workspace):
    runner = CodeTestRunner(workspace)
    result = runner.run("sleep 3", timeout=1)
    assert not result.success
    assert "timed out" in result.stderr.lower()


def test_parse_failure():
    output = """
============================= test session starts ==============================
tests/test_calc.py::test_divide FAILED
=========================== short test summary info ============================
FAILED tests/test_calc.py::test_divide - AssertionError: assert...
    """
    summary = Diagnostics.parse_failure(output)
    assert "test_divide" in summary


def test_extract_error_summary():
    output = "line1\nline2\nValueError: bad value\nline4"
    summary = Diagnostics.extract_error_summary(output)
    assert "ValueError" in summary


def test_identify_likely_files():
    output = 'File "/app/calc.py", line 10, in divide\n    return a / b'
    files = Diagnostics.identify_likely_files(output)
    assert any("calc.py" in f for f in files)
