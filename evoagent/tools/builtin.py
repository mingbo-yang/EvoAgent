"""Built-in tools — factory to create a ToolRegistry with all default tools."""

from pathlib import Path

from evoagent.tools.file_tools import (
    ApplyPatchTool,
    EditFileTool,
    ListDirTool,
    MultiEditTool,
    ReadFileTool,
    WriteFileTool,
)
from evoagent.tools.git_tools import GitDiffTool, GitStatusTool
from evoagent.tools.python_tools import PythonTool
from evoagent.tools.registry import ToolRegistry
from evoagent.tools.search_tools import GrepTool
from evoagent.tools.shell_tools import BashTool


def create_builtin_registry(workspace: Path, auto_approve: bool = False) -> ToolRegistry:
    """Create a ToolRegistry populated with all built-in tools.

    Args:
        workspace: The workspace root directory for file operations.
        auto_approve: When True, the bash tool executes commands that the
            policy marks ASK without an extra approval step. Set this only in
            contexts that already gate approval at a higher layer (e.g. the
            interactive CLI runtime). Autonomous callers should leave it False
            so ASK commands are refused rather than silently executed.

    Returns:
        ToolRegistry with read_file, write_file, edit_file,
        list_directory, grep, bash, python, git_status, git_diff.
    """
    registry = ToolRegistry(workspace=workspace)
    registry.register(ReadFileTool(workspace))
    registry.register(WriteFileTool(workspace))
    registry.register(EditFileTool(workspace))
    registry.register(MultiEditTool(workspace))
    registry.register(ApplyPatchTool(workspace))
    registry.register(ListDirTool(workspace))
    registry.register(GrepTool(workspace))
    registry.register(BashTool(workspace, auto_approve=auto_approve))
    registry.register(PythonTool(workspace))
    registry.register(GitStatusTool(workspace))
    registry.register(GitDiffTool(workspace))
    return registry
