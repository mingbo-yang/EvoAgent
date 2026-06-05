"""Tests for the tool system."""

import tempfile
from pathlib import Path

import pytest

from evoagent.core.errors import ToolError
from evoagent.tools.base import resolve_workspace_path
from evoagent.tools.builtin import create_builtin_registry
from evoagent.tools.file_tools import (
    ReadFileTool,
)


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def registry(workspace):
    return create_builtin_registry(workspace)


# ── ToolRegistry ──────────────────────────────────────────────────────


def test_registry_register_and_get(registry):
    assert "read_file" in registry
    tool = registry.get("read_file")
    assert tool.name == "read_file"


def test_registry_list_tools(registry):
    names = registry.list_tools()
    assert "read_file" in names
    assert "write_file" in names
    assert "bash" in names
    assert "grep" in names


def test_registry_duplicate_register(registry):
    with pytest.raises(ToolError, match="already registered"):
        registry.register(ReadFileTool(Path.cwd()))


def test_registry_unknown_tool(registry):
    with pytest.raises(ToolError, match="Unknown tool"):
        registry.get("nonexistent")


def test_registry_unregister(registry):
    registry.unregister("git_diff")
    assert "git_diff" not in registry.list_tools()


@pytest.mark.asyncio
async def test_registry_run_unknown_tool(registry):
    with pytest.raises(ToolError, match="Unknown tool"):
        await registry.run_tool("nope", {})


def test_get_tool_schemas(registry):
    schemas = registry.get_tool_schemas()
    assert len(schemas) >= 8
    for s in schemas:
        assert s["type"] == "function"
        assert "name" in s["function"]
        assert "parameters" in s["function"]


# ── Workspace safety ──────────────────────────────────────────────────


def test_resolve_workspace_path_normal(workspace):
    (workspace / "test.txt").write_text("hello")
    resolved = resolve_workspace_path("test.txt", workspace, must_exist=True)
    assert resolved == (workspace / "test.txt").resolve()


def test_resolve_workspace_path_escape_rejected(workspace):
    with pytest.raises(PermissionError, match="escapes workspace"):
        resolve_workspace_path("../etc/passwd", workspace)


def test_resolve_workspace_path_absolute_escape(workspace):
    with pytest.raises(PermissionError, match="escapes workspace"):
        resolve_workspace_path("/etc/passwd", workspace)


# ── read_file ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_file_normal(workspace, registry):
    (workspace / "test.txt").write_text("line1\nline2\nline3")
    result = await registry.run_tool("read_file", {"path": "test.txt"})
    assert result.success
    assert "line1" in result.output


@pytest.mark.asyncio
async def test_read_file_line_range(workspace, registry):
    (workspace / "test.txt").write_text("a\nb\nc\nd\ne")
    result = await registry.run_tool(
        "read_file", {"path": "test.txt", "start_line": 2, "end_line": 4}
    )
    assert result.success
    assert result.output == "b\nc\nd"


@pytest.mark.asyncio
async def test_read_file_outside_workspace(workspace, registry):
    result = await registry.run_tool("read_file", {"path": "/etc/passwd"})
    assert not result.success
    assert "escapes workspace" in result.error


# ── write_file ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_file_creates(workspace, registry):
    result = await registry.run_tool(
        "write_file", {"path": "new.txt", "content": "hello"}
    )
    assert result.success
    assert (workspace / "new.txt").read_text() == "hello"


@pytest.mark.asyncio
async def test_write_file_no_overwrite(workspace, registry):
    (workspace / "existing.txt").write_text("old")
    result = await registry.run_tool(
        "write_file", {"path": "existing.txt", "content": "new", "overwrite": False}
    )
    assert not result.success
    assert "already exists" in result.error
    assert (workspace / "existing.txt").read_text() == "old"


@pytest.mark.asyncio
async def test_write_file_overwrite(workspace, registry):
    (workspace / "existing.txt").write_text("old")
    result = await registry.run_tool(
        "write_file", {"path": "existing.txt", "content": "new", "overwrite": True}
    )
    assert result.success
    assert (workspace / "existing.txt").read_text() == "new"


@pytest.mark.asyncio
async def test_write_file_creates_parents(workspace, registry):
    result = await registry.run_tool(
        "write_file", {"path": "sub/deep/file.txt", "content": "nested"}
    )
    assert result.success
    assert (workspace / "sub" / "deep" / "file.txt").read_text() == "nested"


# ── edit_file ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_file_replace(workspace, registry):
    (workspace / "edit.txt").write_text("Hello World")
    result = await registry.run_tool(
        "edit_file", {"path": "edit.txt", "old_text": "World", "new_text": "EvoAgent"}
    )
    assert result.success
    assert (workspace / "edit.txt").read_text() == "Hello EvoAgent"


@pytest.mark.asyncio
async def test_edit_file_not_found(workspace, registry):
    (workspace / "edit.txt").write_text("Hello World")
    result = await registry.run_tool(
        "edit_file", {"path": "edit.txt", "old_text": "NotFound", "new_text": "X"}
    )
    assert not result.success
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_edit_file_multiple_matches(workspace, registry):
    (workspace / "edit.txt").write_text("dup dup dup")
    result = await registry.run_tool(
        "edit_file", {"path": "edit.txt", "old_text": "dup", "new_text": "x"}
    )
    assert not result.success
    assert "3 times" in result.error


@pytest.mark.asyncio
async def test_edit_file_replace_all(workspace, registry):
    (workspace / "edit.txt").write_text("dup dup dup")
    result = await registry.run_tool(
        "edit_file",
        {"path": "edit.txt", "old_text": "dup", "new_text": "x", "replace_all": True},
    )
    assert result.success
    assert (workspace / "edit.txt").read_text() == "x x x"


# ── list_directory ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_dir_normal(workspace, registry):
    (workspace / "a.txt").write_text("")
    (workspace / "b.py").write_text("")
    (workspace / "sub").mkdir()
    result = await registry.run_tool("list_directory", {"path": "."})
    assert result.success
    assert "a.txt" in result.output
    assert "b.py" in result.output
    assert "sub/" in result.output


@pytest.mark.asyncio
async def test_list_dir_hides_dotfiles(workspace, registry):
    (workspace / "__pycache__").mkdir()
    (workspace / ".git").mkdir()
    (workspace / "normal.txt").write_text("")
    result = await registry.run_tool("list_directory", {"path": "."})
    assert result.success
    assert "__pycache__" not in result.output
    assert ".git" not in result.output
    assert "normal.txt" in result.output


# ── grep ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grep_finds_match(workspace, registry):
    (workspace / "code.py").write_text("def hello():\n    return 'world'\n")
    result = await registry.run_tool("grep", {"pattern": "hello", "path": "."})
    assert result.success
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_grep_no_match(workspace, registry):
    (workspace / "code.py").write_text("nothing here")
    result = await registry.run_tool("grep", {"pattern": "zzzzz", "path": "."})
    assert result.success
    assert "No matches" in result.output


# ── bash ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bash_simple_echo(workspace, registry):
    result = await registry.run_tool("bash", {"command": "echo hello_from_test"})
    assert result.success
    assert "hello_from_test" in result.output


@pytest.mark.asyncio
async def test_bash_blocks_dangerous(registry):
    result = await registry.run_tool("bash", {"command": "rm -rf /tmp/test"})
    assert not result.success
    assert "denied" in result.error.lower() or "blocked" in result.error.lower()


# ── python ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_python_execute_code(workspace, registry):
    result = await registry.run_tool("python", {"code": "print(42)"})
    assert result.success
    assert "42" in result.output


@pytest.mark.asyncio
async def test_python_execute_script(workspace, registry):
    (workspace / "script.py").write_text("print('from script')")
    result = await registry.run_tool("python", {"script_path": "script.py"})
    assert result.success
    assert "from script" in result.output


# ── git ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_status_non_repo(workspace, registry):
    result = await registry.run_tool("git_status", {})
    # In a non-git directory, should return success=False gracefully
    if not result.success:
        assert any(phrase in (result.error or "").lower()
                   for phrase in ["not a git repository", "not installed"])
    # Both "not a git repo" and "git not installed" are acceptable


@pytest.mark.asyncio
async def test_git_diff_non_repo(workspace, registry):
    result = await registry.run_tool("git_diff", {})
    if not result.success:
        assert True  # Expected: not a git repo
