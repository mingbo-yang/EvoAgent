"""Tests for PatchManager."""

import tempfile
from pathlib import Path

import pytest

from evoagent.code.patch import PatchManager


@pytest.fixture
def pm():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "test.py").write_text("old content")
        yield PatchManager(root)


def test_edit_file(pm):
    result = pm.edit_file("test.py", "old", "new")
    assert "Replaced" in result
    content = (pm.workspace / "test.py").read_text()
    assert "new content" in content


def test_edit_file_not_found(pm):
    result = pm.edit_file("nope.py", "x", "y")
    assert "not found" in result


def test_write_file(pm):
    result = pm.write_file("new.py", "print(1)")
    assert "Written" in result
    assert (pm.workspace / "new.py").exists()


def test_changed_files(pm):
    pm.edit_file("test.py", "old", "new")
    assert len(pm.changed_files()) >= 1


def test_rollback(pm):
    pm.edit_file("test.py", "old", "new")
    result = pm.rollback_last()
    assert "Rolled back" in result
    content = (pm.workspace / "test.py").read_text()
    assert "old content" in content
