"""File tools — read, write, edit, and list directory contents."""

from pathlib import Path

from pydantic import BaseModel, Field

from evoagent.core.ids import generate_id
from evoagent.tools.base import (
    _DEFAULT_HIDDEN_DIRS,
    BaseTool,
    RiskLevel,
    resolve_workspace_path,
)
from evoagent.tools.schema import ToolResult

# ── Input schemas ─────────────────────────────────────────────────────


class ReadFileInput(BaseModel):
    path: str = Field(..., description="File path relative to workspace.")
    start_line: int | None = Field(default=None, description="First line to read (1-indexed).")
    end_line: int | None = Field(default=None, description="Last line to read (1-indexed).")
    max_chars: int = Field(default=50000, description="Maximum characters to return.")


class WriteFileInput(BaseModel):
    path: str = Field(..., description="File path relative to workspace.")
    content: str = Field(..., description="Content to write.")
    overwrite: bool = Field(default=False, description="Whether to overwrite an existing file.")


class EditFileInput(BaseModel):
    path: str = Field(..., description="File path relative to workspace.")
    old_text: str = Field(..., description="Text to find and replace. Matching tolerates "
                          "trailing/leading whitespace differences if an exact match fails.")
    new_text: str = Field(..., description="Text to substitute in place of old_text.")
    replace_all: bool = Field(default=False, description="Replace all occurrences.")


class SingleEdit(BaseModel):
    old_text: str = Field(..., description="Text to find.")
    new_text: str = Field(..., description="Replacement text.")
    replace_all: bool = Field(default=False, description="Replace all occurrences.")


class MultiEditInput(BaseModel):
    path: str = Field(..., description="File path relative to workspace.")
    edits: list[SingleEdit] = Field(..., description="Edits applied in order, atomically. "
                                    "If any edit fails, the file is left unchanged.")


class PatchFileEdits(BaseModel):
    path: str = Field(..., description="File path relative to workspace.")
    edits: list[SingleEdit] = Field(..., description="Search/replace edits for this file.")


class ApplyPatchInput(BaseModel):
    files: list[PatchFileEdits] = Field(..., description="Per-file edit groups applied "
                                       "atomically across ALL files: either every file's "
                                       "edits apply or none are written.")


class ListDirInput(BaseModel):
    path: str = Field(default=".", description="Directory path relative to workspace.")
    recursive: bool = Field(default=False, description="Whether to list recursively.")
    max_entries: int = Field(default=200, description="Maximum entries to return.")


# ── Tools ─────────────────────────────────────────────────────────────


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a file from the workspace. Supports line ranges and character limits."
    input_schema = ReadFileInput
    risk_level = RiskLevel.LOW

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def run(self, path: str, start_line: int | None = None,
                  end_line: int | None = None, max_chars: int = 50000) -> ToolResult:
        resolved = resolve_workspace_path(path, self.workspace, must_exist=True)
        if resolved.is_dir():
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False,
                error=f"Path is a directory, not a file: {resolved}",
            )
        try:
            content = resolved.read_text(encoding="utf-8")
            if start_line is not None or end_line is not None:
                lines = content.split("\n")
                s = (start_line or 1) - 1
                e = end_line or len(lines)
                content = "\n".join(lines[s:e])
            if len(content) > max_chars:
                content = content[:max_chars] + "\n... (truncated)"
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=True,
                output=content,
                metadata={"path": str(resolved), "chars": len(content)},
            )
        except Exception as e:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False, error=str(e),
            )


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write content to a file in the workspace. Creates parent directories automatically."
    input_schema = WriteFileInput
    risk_level = RiskLevel.MEDIUM

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def run(self, path: str, content: str, overwrite: bool = False) -> ToolResult:
        try:
            resolved = resolve_workspace_path(path, self.workspace)
            if resolved.exists() and not overwrite:
                return ToolResult(
                    call_id=generate_id("call"), name=self.name, success=False,
                    error=f"File already exists: {resolved}. Use overwrite=true to replace.",
                )
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=True,
                output=f"Written {len(content)} chars to {resolved}",
                metadata={"path": str(resolved), "chars": len(content)},
            )
        except Exception as e:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False, error=str(e),
            )


class EditFileTool(BaseTool):
    name = "edit_file"
    description = ("Find and replace text in a file. old_text must be unique unless "
                   "replace_all=true. If an exact match fails, matching falls back to "
                   "tolerating trailing/leading whitespace differences.")
    input_schema = EditFileInput
    risk_level = RiskLevel.MEDIUM

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def run(self, path: str, old_text: str, new_text: str,
                  replace_all: bool = False) -> ToolResult:
        from evoagent.tools.editing import compute_edit
        try:
            resolved = resolve_workspace_path(path, self.workspace, must_exist=True)
            content = resolved.read_text(encoding="utf-8")
            res = compute_edit(content, old_text, new_text, replace_all)
            if not res.success:
                err = res.error
                if res.hint:
                    err += f" {res.hint}"
                return ToolResult(
                    call_id=generate_id("call"), name=self.name, success=False,
                    error=f"{err} (in {resolved})",
                )
            resolved.write_text(res.new_content, encoding="utf-8")
            note = "" if res.strategy == "exact" else f" (matched via {res.strategy})"
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=True,
                output=f"Replaced {res.count} occurrence(s) in {resolved}{note}",
                metadata={"path": str(resolved), "replacements": res.count,
                          "strategy": res.strategy},
            )
        except Exception as e:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False, error=str(e),
            )


class MultiEditTool(BaseTool):
    name = "multi_edit"
    description = ("Apply several find/replace edits to a single file atomically, in order. "
                   "If any edit fails, the file is left completely unchanged. Use this for "
                   "multiple related changes to one file.")
    input_schema = MultiEditInput
    risk_level = RiskLevel.MEDIUM

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def run(self, path: str, edits: list) -> ToolResult:
        from evoagent.tools.editing import Edit, apply_edits
        try:
            resolved = resolve_workspace_path(path, self.workspace, must_exist=True)
            content = resolved.read_text(encoding="utf-8")
            edit_objs = [Edit(old_text=e["old_text"], new_text=e["new_text"],
                              replace_all=e.get("replace_all", False))
                         if isinstance(e, dict)
                         else Edit(old_text=e.old_text, new_text=e.new_text,
                                   replace_all=getattr(e, "replace_all", False))
                         for e in edits]
            if not edit_objs:
                return ToolResult(call_id=generate_id("call"), name=self.name,
                                  success=False, error="No edits provided.")
            ok, new_content, strategies, error = apply_edits(content, edit_objs)
            if not ok:
                return ToolResult(call_id=generate_id("call"), name=self.name,
                                  success=False, error=f"{error} (in {resolved})")
            resolved.write_text(new_content, encoding="utf-8")
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=True,
                output=f"Applied {len(edit_objs)} edit(s) to {resolved}",
                metadata={"path": str(resolved), "edits": len(edit_objs),
                          "strategies": strategies},
            )
        except Exception as e:
            return ToolResult(call_id=generate_id("call"), name=self.name,
                              success=False, error=str(e))


class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = ("Apply find/replace edits across MULTIPLE files atomically. Either every "
                   "file's edits apply cleanly or nothing is written. Use this for changes "
                   "that must land together (e.g. renaming a symbol across files).")
    input_schema = ApplyPatchInput
    risk_level = RiskLevel.MEDIUM

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def run(self, files: list) -> ToolResult:
        from evoagent.tools.editing import Edit, FileEdits, compute_multifile

        def _to_edits(raw) -> list:
            out = []
            for e in raw:
                if isinstance(e, dict):
                    out.append(Edit(old_text=e["old_text"], new_text=e["new_text"],
                                    replace_all=e.get("replace_all", False)))
                else:
                    out.append(Edit(old_text=e.old_text, new_text=e.new_text,
                                    replace_all=getattr(e, "replace_all", False)))
            return out

        try:
            # Resolve all paths first (containment + existence) so a bad path
            # aborts before any write.
            file_edits: list = []
            resolved_map: dict[str, Path] = {}
            for f in files:
                path = f["path"] if isinstance(f, dict) else f.path
                raw_edits = f["edits"] if isinstance(f, dict) else f.edits
                resolved = resolve_workspace_path(path, self.workspace, must_exist=True)
                resolved_map[path] = resolved
                file_edits.append(FileEdits(path=path, edits=_to_edits(raw_edits)))
            if not file_edits:
                return ToolResult(call_id=generate_id("call"), name=self.name,
                                  success=False, error="No files provided.")

            def read_fn(path: str) -> str:
                return resolved_map[path].read_text(encoding="utf-8")

            ok, new_contents, error = compute_multifile(read_fn, file_edits)
            if not ok:
                return ToolResult(call_id=generate_id("call"), name=self.name,
                                  success=False, error=f"Patch not applied: {error}")
            # All edits computed successfully — now write atomically.
            for path, content in new_contents.items():
                resolved_map[path].write_text(content, encoding="utf-8")
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=True,
                output=f"Applied patch to {len(new_contents)} file(s): "
                       + ", ".join(str(resolved_map[p]) for p in new_contents),
                metadata={"files": [str(resolved_map[p]) for p in new_contents]},
            )
        except Exception as e:
            return ToolResult(call_id=generate_id("call"), name=self.name,
                              success=False, error=str(e))


class ListDirTool(BaseTool):
    name = "list_directory"
    description = "List files and directories in a workspace directory. Hidden dirs (.git, __pycache__, etc.) are excluded by default."
    input_schema = ListDirInput
    risk_level = RiskLevel.LOW

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def run(self, path: str = ".", recursive: bool = False,
                  max_entries: int = 200) -> ToolResult:
        try:
            resolved = resolve_workspace_path(path, self.workspace, must_exist=True)
            if not resolved.is_dir():
                return ToolResult(
                    call_id=generate_id("call"), name=self.name, success=False,
                    error=f"Not a directory: {resolved}",
                )
            entries: list[str] = []
            if recursive:
                for p in sorted(resolved.rglob("*")):
                    if any(part in _DEFAULT_HIDDEN_DIRS for part in p.parts):
                        continue
                    rel = p.relative_to(resolved)
                    suffix = "/" if p.is_dir() else ""
                    entries.append(f"{rel}{suffix}")
            else:
                for p in sorted(resolved.iterdir()):
                    if p.name in _DEFAULT_HIDDEN_DIRS:
                        continue
                    suffix = "/" if p.is_dir() else ""
                    entries.append(f"{p.name}{suffix}")

            if len(entries) > max_entries:
                total = len(entries)
                entries = entries[:max_entries]
                entries.append(f"... ({total} total, showing first {max_entries})")

            output = "\n".join(entries) if entries else "(empty directory)"
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=True,
                output=output, metadata={"path": str(resolved), "count": len(entries)},
            )
        except Exception as e:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False, error=str(e),
            )
