"""Tests for robust editing core and the edit_file / multi_edit / apply_patch tools (P0.2)."""

import pytest

from evoagent.tools.builtin import create_builtin_registry
from evoagent.tools.editing import Edit, apply_edits, compute_edit

# ── compute_edit fuzzy strategies ────────────────────────────────────────


def test_compute_edit_exact():
    res = compute_edit("hello world", "world", "there")
    assert res.success and res.strategy == "exact"
    assert res.new_content == "hello there"


def test_compute_edit_exact_ambiguous_refused():
    res = compute_edit("a\na\n", "a", "b")
    assert not res.success
    assert "found 2 times" in res.error


def test_compute_edit_exact_replace_all():
    res = compute_edit("a\na\n", "a", "b", replace_all=True)
    assert res.success and res.count == 2
    assert res.new_content == "b\nb\n"


def test_compute_edit_trailing_whitespace_fallback():
    # File has trailing spaces the model didn't include.
    content = "def f():\n    return 1   \n"
    res = compute_edit(content, "def f():\n    return 1\n", "def f():\n    return 2\n")
    assert res.success and res.strategy == "trailing-ws"
    assert "return 2" in res.new_content


def test_compute_edit_leading_indent_fallback():
    # Model quoted the block without the real indentation.
    content = "class A:\n        def m(self):\n            return 1\n"
    old = "def m(self):\n    return 1"
    new = "def m(self):\n    return 42"
    res = compute_edit(content, old, new)
    assert res.success and res.strategy == "strip-ws"
    assert "return 42" in res.new_content


def test_compute_edit_not_found_gives_hint():
    res = compute_edit("alpha\nbeta\ngamma\n", "betta", "x")
    assert not res.success
    assert "not found" in res.error
    assert "Closest line" in res.hint


def test_compute_edit_fuzzy_ambiguous_refused():
    content = "x = 1\nx = 1\n"
    res = compute_edit(content, "x = 1 ", "x = 2")  # trailing ws → fuzzy, 2 matches
    assert not res.success
    assert "matches 2 locations" in res.error


# ── apply_edits atomicity (single file) ──────────────────────────────────


def test_apply_edits_sequential_success():
    content = "one two three"
    ok, new, strat, err = apply_edits(content, [
        Edit("one", "1"), Edit("two", "2"), Edit("three", "3"),
    ])
    assert ok and new == "1 2 3"
    assert err == ""


def test_apply_edits_atomic_rollback_on_failure():
    content = "one two three"
    ok, new, strat, err = apply_edits(content, [
        Edit("one", "1"), Edit("MISSING", "x"),
    ])
    assert not ok
    assert new == content  # unchanged
    assert "edit #2 failed" in err


# ── Tool-level tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_file_tool_fuzzy(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1   \n")  # trailing ws
    reg = create_builtin_registry(tmp_path)
    res = await reg.run_tool("edit_file", {
        "path": "a.py", "old_text": "def f():\n    return 1\n",
        "new_text": "def f():\n    return 2\n",
    })
    assert res.success
    assert "return 2" in f.read_text()


@pytest.mark.asyncio
async def test_multi_edit_atomic_rollback(tmp_path):
    f = tmp_path / "a.txt"
    original = "alpha\nbeta\ngamma\n"
    f.write_text(original)
    reg = create_builtin_registry(tmp_path)
    res = await reg.run_tool("multi_edit", {
        "path": "a.txt",
        "edits": [
            {"old_text": "alpha", "new_text": "ALPHA"},
            {"old_text": "NOPE", "new_text": "x"},  # fails
        ],
    })
    assert not res.success
    assert f.read_text() == original  # unchanged (atomic)


@pytest.mark.asyncio
async def test_multi_edit_success(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("alpha\nbeta\n")
    reg = create_builtin_registry(tmp_path)
    res = await reg.run_tool("multi_edit", {
        "path": "a.txt",
        "edits": [
            {"old_text": "alpha", "new_text": "ALPHA"},
            {"old_text": "beta", "new_text": "BETA"},
        ],
    })
    assert res.success
    assert f.read_text() == "ALPHA\nBETA\n"


@pytest.mark.asyncio
async def test_apply_patch_multifile_atomic_all_or_nothing(tmp_path):
    f1 = tmp_path / "f1.txt"
    f2 = tmp_path / "f2.txt"
    f1.write_text("foo\n")
    f2.write_text("bar\n")
    reg = create_builtin_registry(tmp_path)
    # f2's edit fails → neither file should change.
    res = await reg.run_tool("apply_patch", {
        "files": [
            {"path": "f1.txt", "edits": [{"old_text": "foo", "new_text": "FOO"}]},
            {"path": "f2.txt", "edits": [{"old_text": "MISSING", "new_text": "x"}]},
        ],
    })
    assert not res.success
    assert f1.read_text() == "foo\n"  # unchanged
    assert f2.read_text() == "bar\n"


@pytest.mark.asyncio
async def test_apply_patch_multifile_success(tmp_path):
    f1 = tmp_path / "f1.txt"
    f2 = tmp_path / "f2.txt"
    f1.write_text("foo\n")
    f2.write_text("bar\n")
    reg = create_builtin_registry(tmp_path)
    res = await reg.run_tool("apply_patch", {
        "files": [
            {"path": "f1.txt", "edits": [{"old_text": "foo", "new_text": "FOO"}]},
            {"path": "f2.txt", "edits": [{"old_text": "bar", "new_text": "BAR"}]},
        ],
    })
    assert res.success
    assert f1.read_text() == "FOO\n"
    assert f2.read_text() == "BAR\n"


@pytest.mark.asyncio
async def test_apply_patch_bad_path_aborts(tmp_path):
    f1 = tmp_path / "f1.txt"
    f1.write_text("foo\n")
    reg = create_builtin_registry(tmp_path)
    res = await reg.run_tool("apply_patch", {
        "files": [
            {"path": "f1.txt", "edits": [{"old_text": "foo", "new_text": "FOO"}]},
            {"path": "does_not_exist.txt", "edits": [{"old_text": "a", "new_text": "b"}]},
        ],
    })
    assert not res.success
    assert f1.read_text() == "foo\n"  # first file untouched
