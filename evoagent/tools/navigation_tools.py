"""Navigation tools — glob, symbol outline, and deterministic code search."""

import ast
import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from evoagent.core.ids import generate_id
from evoagent.tools.base import BaseTool, RiskLevel, resolve_workspace_path
from evoagent.tools.schema import ToolResult

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache",
              "dist", "build", ".eggs", ".mypy_cache", ".ruff_cache"}


class GlobInput(BaseModel):
    pattern: str = Field(
        ...,
        description="Glob pattern relative to the search path, e.g. '**/*.py' or 'src/*.ts'.",
    )
    path: str = Field(default=".", description="Base directory to match within.")
    max_results: int = Field(default=200, description="Maximum file paths to return.")


class GlobTool(BaseTool):
    name = "glob"
    description = (
        "Find files by glob pattern (e.g. '**/*.py'). Returns workspace-relative "
        "paths sorted by most recently modified first. Use this to locate files by "
        "name before reading them."
    )
    input_schema = GlobInput
    risk_level = RiskLevel.LOW

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def run(self, pattern: str, path: str = ".", max_results: int = 200) -> ToolResult:
        try:
            if pattern.startswith("/") or ".." in Path(pattern).parts:
                return ToolResult(
                    call_id=generate_id("call"), name=self.name, success=False,
                    error="Pattern must be relative and may not contain '..' segments.",
                )
            base = resolve_workspace_path(path, self.workspace, must_exist=True)
            base_resolved = base.resolve()
            matches: list[tuple[float, Path]] = []
            for fp in base.glob(pattern):
                if any(part in _SKIP_DIRS for part in fp.parts):
                    continue
                try:
                    resolved = fp.resolve()
                    resolved.relative_to(base_resolved)
                    if not resolved.is_file():
                        continue
                    mtime = resolved.stat().st_mtime
                except (OSError, ValueError):
                    continue
                matches.append((mtime, fp))
            matches.sort(key=lambda t: t[0], reverse=True)
            truncated = len(matches) > max_results
            shown = matches[:max_results]
            rels = [str(p.relative_to(base)) for _, p in shown]
            if not rels:
                return ToolResult(
                    call_id=generate_id("call"), name=self.name, success=True,
                    output="No files matched.",
                    metadata={"pattern": pattern, "matches": 0},
                )
            output = "\n".join(rels)
            if truncated:
                output += f"\n... (showing {max_results} of {len(matches)}; narrow the pattern)"
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=True,
                output=output,
                metadata={"pattern": pattern, "matches": len(matches), "truncated": truncated},
            )
        except (FileNotFoundError, PermissionError) as e:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False, error=str(e),
            )
        except Exception as e:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False, error=str(e),
            )


class OutlineInput(BaseModel):
    path: str = Field(..., description="Path to a Python source file to outline.")


def _format_args(node: ast.arguments) -> str:
    """Render a function's argument list, preserving */ markers and defaults."""
    try:
        return ast.unparse(node)
    except Exception:
        parts: list[str] = []
        posonly = getattr(node, "posonlyargs", [])
        for a in [*posonly, *node.args]:
            parts.append(a.arg)
        if node.vararg:
            parts.append("*" + node.vararg.arg)
        for a in node.kwonlyargs:
            parts.append(a.arg)
        if node.kwarg:
            parts.append("**" + node.kwarg.arg)
        return ", ".join(parts)


def _outline_python(source: str) -> list[str]:
    """Return an indented outline of classes/functions with line numbers."""
    tree = ast.parse(source)
    lines: list[str] = []

    def visit(node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                indent = "  " * depth
                lines.append(
                    f"{indent}{prefix} {child.name}({_format_args(child.args)})  "
                    f"[L{child.lineno}]"
                )
                visit(child, depth + 1)
            elif isinstance(child, ast.ClassDef):
                indent = "  " * depth
                bases = ", ".join(ast.unparse(b) for b in child.bases) if child.bases else ""
                header = f"class {child.name}" + (f"({bases})" if bases else "")
                lines.append(f"{indent}{header}  [L{child.lineno}]")
                visit(child, depth + 1)

    visit(tree, 0)
    return lines


class OutlineTool(BaseTool):
    name = "outline"
    description = (
        "Extract a symbol outline (classes, functions, methods with their line "
        "numbers and signatures) from a Python file. Use this to understand a "
        "file's structure without reading every line."
    )
    input_schema = OutlineInput
    risk_level = RiskLevel.LOW

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def run(self, path: str) -> ToolResult:
        try:
            resolved = resolve_workspace_path(path, self.workspace, must_exist=True)
            if resolved.suffix != ".py":
                return ToolResult(
                    call_id=generate_id("call"), name=self.name, success=False,
                    error=f"Outline currently supports Python files only (got '{resolved.suffix}').",
                )
            source = resolved.read_text(encoding="utf-8", errors="replace")
            try:
                outline = _outline_python(source)
            except SyntaxError as e:
                return ToolResult(
                    call_id=generate_id("call"), name=self.name, success=False,
                    error=f"Could not parse Python file: {e}",
                )
            if not outline:
                return ToolResult(
                    call_id=generate_id("call"), name=self.name, success=True,
                    output="(no top-level classes or functions found)",
                    metadata={"symbols": 0},
                )
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=True,
                output="\n".join(outline), metadata={"symbols": len(outline)},
            )
        except (FileNotFoundError, PermissionError) as e:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False, error=str(e),
            )
        except Exception as e:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False, error=str(e),
            )


class CodeSearchInput(BaseModel):
    query: str = Field(
        ...,
        description="Natural-language or keyword query describing the code to find.",
    )
    top_k: int = Field(default=8, ge=1, le=50, description="Max results to return.")
    refresh: bool = Field(
        default=False, description="Rebuild the index before searching."
    )


class CodeSearchTool(BaseTool):
    name = "code_search"
    description = (
        "Search the codebase for code relevant to a query and return ranked "
        "chunks (file path, line range, symbol). Uses deterministic symbol-aware "
        "chunking plus keyword retrieval — use it to locate where functionality "
        "lives before reading or editing files."
    )
    input_schema = CodeSearchInput
    risk_level = RiskLevel.LOW

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._retriever = None

    async def run(self, query: str, top_k: int = 8, refresh: bool = False) -> ToolResult:
        try:
            from evoagent.retrieval.code_retriever import CodeRetriever

            if self._retriever is None or refresh:
                retriever = CodeRetriever(self.workspace)
                await asyncio.to_thread(retriever.build_index)
                self._retriever = retriever
            hits = await asyncio.to_thread(self._retriever.search, query, top_k)
            if not hits:
                return ToolResult(
                    call_id=generate_id("call"), name=self.name, success=True,
                    output="No relevant code found.",
                    metadata={"query": query, "results": 0},
                )
            blocks: list[str] = []
            for i, ch in enumerate(hits, 1):
                label = f"{ch.kind} {ch.name}".strip()
                snippet = "\n".join(
                    f"    {ln}" for ln in ch.text.splitlines()[:4]
                )
                blocks.append(
                    f"{i}. {ch.location}  ({label})  [score {ch.score:.1f}]\n{snippet}"
                )
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=True,
                output="\n\n".join(blocks),
                metadata={"query": query, "results": len(hits)},
            )
        except Exception as e:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False, error=str(e),
            )
