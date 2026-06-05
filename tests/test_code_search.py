"""Tests for CodeSearch."""

import tempfile
from pathlib import Path

import pytest

from evoagent.code.search import CodeSearch


@pytest.fixture
def searcher():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.py").write_text("def hello_world():\n    return 'hello'\n\nclass Foo:\n    pass\n")
        (root / "notes.txt").write_text("hello from notes")
        yield CodeSearch(root)


def test_search_text(searcher):
    result = searcher.search_text("hello")
    assert "hello" in result


def test_search_symbol(searcher):
    result = searcher.search_symbol("hello_world")
    assert "def hello_world" in result


def test_find_files(searcher):
    files = searcher.find_files("*.py")
    assert any(f.endswith(".py") for f in files)


def test_summarize_file(searcher):
    summary = searcher.summarize_file("main.py")
    assert "main.py" in summary
    assert "hello_world" in summary
