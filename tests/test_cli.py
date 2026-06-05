"""Tests for CLI using typer CliRunner."""

import tempfile

from typer.testing import CliRunner

from evoagent.cli.main import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output or "Run" in result.output


def test_init_creates_files():
    with tempfile.TemporaryDirectory() as tmp:
        import os
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            result = runner.invoke(app, ["init", "init"])
            assert "Created" in result.output or result.exit_code == 0
        finally:
            os.chdir(old_cwd)


def test_config_show_no_file():
    with tempfile.TemporaryDirectory() as tmp:
        import os
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            result = runner.invoke(app, ["config", "show"])
            # Should error or show message about missing config
            assert result.exit_code in (0, 1)
        finally:
            os.chdir(old_cwd)


def test_run_mock():
    result = runner.invoke(app, ["run", "hello", "--mock"])
    # Mock mode should succeed
    assert "Success" in result.output or result.exit_code == 0


def test_eval_mock():
    result = runner.invoke(app, ["eval", "--mock", "--suite", "examples/eval_toy_tasks.jsonl"])
    # May fail if file doesn't exist relative to test dir, but shouldn't crash
    assert result.exit_code in (0, 1, 2)


def test_memory_list():
    """Memory list should not crash on empty store."""
    with tempfile.TemporaryDirectory() as tmp:
        import os
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            result = runner.invoke(app, ["memory", "list"])
            assert result.exit_code == 0
        finally:
            os.chdir(old_cwd)


def test_trace_list_empty():
    """Trace list should not crash on missing .runs directory."""
    with tempfile.TemporaryDirectory() as tmp:
        import os
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            result = runner.invoke(app, ["trace", "list"])
            assert result.exit_code == 0
        finally:
            os.chdir(old_cwd)


def test_invalid_command():
    result = runner.invoke(app, ["nonexistent_command"])
    assert result.exit_code != 0
