"""Built-in tools — factory to create a ToolRegistry with all default tools."""

from pathlib import Path

from evoagent.tools.file_tools import (
    ApplyPatchTool,
    EditFileTool,
    ListDirTool,
    MultiEditTool,
    ReadFileTool,
    UndoLastTool,
    WriteFileTool,
)
from evoagent.tools.git_tools import GitDiffTool, GitStatusTool
from evoagent.tools.navigation_tools import CodeSearchTool, GlobTool, OutlineTool
from evoagent.tools.python_tools import PythonTool
from evoagent.tools.registry import ToolRegistry
from evoagent.tools.search_tools import GrepTool
from evoagent.tools.shell_tools import BashTool
from evoagent.tools.snapshots import WorkspaceSnapshotManager
from evoagent.tools.testing import RunTestsTool
from evoagent.tools.todo_tools import ListTodosTool, TodoStore, WriteTodosTool
from evoagent.tools.web_tools import WebFetchTool, WebSearchTool


def create_builtin_registry(workspace: Path, auto_approve: bool = False,
                            enable_undo: bool = True,
                            enable_todos: bool = True,
                            enable_tests: bool = True,
                            enable_web: bool = True) -> ToolRegistry:
    """Create a ToolRegistry populated with all built-in tools.

    Args:
        workspace: The workspace root directory for file operations.
        auto_approve: When True, the bash tool executes commands that the
            policy marks ASK without an extra approval step. Set this only in
            contexts that already gate approval at a higher layer (e.g. the
            interactive CLI runtime). Autonomous callers should leave it False
            so ASK commands are refused rather than silently executed.
        enable_undo: When True (default), file-modifying tools snapshot the
            prior state of touched files before writing and an ``undo_last``
            tool is registered to roll back the most recent change.
        enable_todos: When True (default), register the ``write_todos`` /
            ``list_todos`` task-list tools backed by a persisted store. The
            store is attached as ``registry.todo_store``.
        enable_tests: When True (default), register the ``run_tests`` tool that
            runs the project's test suite and returns a failure-focused summary
            for the edit -> test -> fix loop.
        enable_web: When True (default), register the ``web_fetch`` and
            ``web_search`` network tools. These are gated by the permission
            policy (``network`` action, high risk) and enforce an egress policy
            that blocks private/loopback targets.

    Returns:
        ToolRegistry with read_file, write_file, edit_file, multi_edit,
        apply_patch, undo_last, write_todos, list_todos, run_tests,
        list_directory, grep, glob, outline, bash, python, git_status,
        git_diff, web_fetch, web_search.
    """
    registry = ToolRegistry(workspace=workspace)
    snapshots = WorkspaceSnapshotManager(workspace) if enable_undo else None
    registry.register(ReadFileTool(workspace))
    registry.register(WriteFileTool(workspace, snapshots=snapshots))
    registry.register(EditFileTool(workspace, snapshots=snapshots))
    registry.register(MultiEditTool(workspace, snapshots=snapshots))
    registry.register(ApplyPatchTool(workspace, snapshots=snapshots))
    if snapshots is not None:
        registry.register(UndoLastTool(workspace, snapshots=snapshots))
    registry.todo_store = None
    if enable_todos:
        store = TodoStore(Path(workspace) / ".evoagent" / "todos.json")
        registry.todo_store = store
        registry.register(WriteTodosTool(store))
        registry.register(ListTodosTool(store))
    registry.register(ListDirTool(workspace))
    registry.register(GrepTool(workspace))
    registry.register(GlobTool(workspace))
    registry.register(OutlineTool(workspace))
    registry.register(CodeSearchTool(workspace))
    if enable_tests:
        registry.register(RunTestsTool(workspace))
    registry.register(BashTool(workspace, auto_approve=auto_approve))
    registry.register(PythonTool(workspace))
    registry.register(GitStatusTool(workspace))
    registry.register(GitDiffTool(workspace))
    if enable_web:
        registry.register(WebFetchTool())
        registry.register(WebSearchTool())
    return registry
