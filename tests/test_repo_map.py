"""Tests for RepoMap."""

import tempfile
from pathlib import Path

import pytest

from evoagent.code.repo_map import RepoMap


@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.py").write_text("def hello():\n    return 'world'\n\nclass Greeter:\n    pass\n")
        (root / "utils.py").write_text("def helper():\n    pass\n")
        (root / "README.md").write_text("# Project")
        (root / ".git").mkdir()
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "cache.pyc").write_text("x")
        yield root


def test_repo_map_scan(repo):
    rm = RepoMap()
    summary = rm.scan(repo)
    assert summary.file_count >= 2
    paths = [f.path for f in summary.files]
    assert "main.py" in paths


def test_repo_map_skips_dirs(repo):
    rm = RepoMap()
    summary = rm.scan(repo)
    paths = [f.path for f in summary.files]
    assert not any(".git" in p for p in paths)
    assert not any("__pycache__" in p for p in paths)


def test_repo_map_extract_symbols(repo):
    rm = RepoMap()
    symbols = rm.extract_symbols(repo / "main.py")
    assert "def hello" in symbols
    assert "class Greeter" in symbols


def test_repo_map_summarize(repo):
    rm = RepoMap()
    s = rm.summarize(repo)
    assert "main.py" in s
    assert "Files:" in s
