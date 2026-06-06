"""Tests for the model-facing run_tests tool (P0.5)."""

import sys

import pytest

from evoagent.tools.builtin import create_builtin_registry
from evoagent.tools.testing import RunTestsTool, _parse_counts


def _write_passing_suite(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")


def _write_failing_suite(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n\n"
        "def test_bad():\n    assert 1 + 1 == 3\n", encoding="utf-8")


def test_parse_counts():
    counts = _parse_counts("= 2 failed, 5 passed, 1 error in 0.30s =")
    assert counts == {"failed": 2, "passed": 5, "error": 1}


@pytest.mark.asyncio
async def test_run_tests_passing(tmp_path):
    _write_passing_suite(tmp_path)
    tool = RunTestsTool(tmp_path)
    res = await tool.run(command=f"{sys.executable} -m pytest -q", timeout=120)
    assert res.success
    assert res.output.startswith("PASS")
    assert res.metadata["counts"].get("passed") == 1
    assert res.metadata["failing"] == []


@pytest.mark.asyncio
async def test_run_tests_failing_reports_node(tmp_path):
    _write_failing_suite(tmp_path)
    tool = RunTestsTool(tmp_path)
    res = await tool.run(command=f"{sys.executable} -m pytest -q", timeout=120)
    assert not res.success
    assert res.output.startswith("FAIL")
    assert res.metadata["counts"].get("failed") == 1
    assert any("test_bad" in node for node in res.metadata["failing"])
    assert "Tests failed" in (res.error or "")


@pytest.mark.asyncio
async def test_run_tests_rejects_non_test_command(tmp_path):
    tool = RunTestsTool(tmp_path)
    res = await tool.run(command="rm -rf /", timeout=10)
    assert not res.success
    assert "recognised test runners" in (res.error or "")


@pytest.mark.asyncio
async def test_run_tests_rejects_shell_chaining(tmp_path):
    tool = RunTestsTool(tmp_path)
    res = await tool.run(command="pytest && rm -rf /", timeout=10)
    assert not res.success
    assert "shell operators" in (res.error or "")


@pytest.mark.asyncio
async def test_run_tests_directed(tmp_path):
    _write_failing_suite(tmp_path)
    tool = RunTestsTool(tmp_path)
    # Run only the passing node id — directed run should pass.
    res = await tool.run(
        command=f"{sys.executable} -m pytest -q test_sample.py::test_ok",
        timeout=120)
    assert res.success
    assert res.metadata["counts"].get("passed") == 1


@pytest.mark.asyncio
async def test_run_tests_registered_by_default(tmp_path):
    reg = create_builtin_registry(tmp_path)
    assert "run_tests" in reg.list_tools()


@pytest.mark.asyncio
async def test_run_tests_disabled(tmp_path):
    reg = create_builtin_registry(tmp_path, enable_tests=False)
    assert "run_tests" not in reg.list_tools()
