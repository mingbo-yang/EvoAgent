"""Deterministic-first code retrieval.

A :class:`CodeRetriever` builds a searchable index of a workspace using
deterministic signals only:

1. symbol-aware chunking — Python files are split into class/function chunks
   (with line ranges) via ``ast``; module-level code and non-Python text files
   fall back to line-window chunks;
2. keyword scoring — chunks are indexed with the inverted-index
   :class:`KeywordRetriever`; file path and symbol names are folded into the
   indexed text (and split on ``_``/camelCase) so they are weighted;
3. ranking — results are ordered by keyword score with a small deterministic
   bonus when query terms appear in the symbol name or path.

Embeddings/vector search are intentionally *not* used here: this layer is the
deterministic foundation the roadmap calls for. An optional embedding stage can
be layered on top by callers that need it.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from evoagent.code.repo_map import SKIP_DIRS
from evoagent.retrieval.keyword import KeywordRetriever

_TEXT_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".md",
              ".txt", ".rst", ".toml", ".cfg", ".ini", ".yaml", ".yml"}
_MAX_FILE_BYTES = 1_000_000


@dataclass
class CodeChunk:
    path: str
    start_line: int
    end_line: int
    kind: str  # "function" | "class" | "module" | "text"
    name: str
    text: str
    score: float = 0.0

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


def _split_identifier(name: str) -> list[str]:
    """Split a symbol/path token into sub-words (snake_case + camelCase)."""
    parts = re.split(r"[_\W]+", name)
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        out.extend(re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", p) or [p])
    return [w.lower() for w in out]


def _py_chunks(path: str, source: str) -> list[CodeChunk]:
    """Symbol-aware chunks for a Python file (top-level defs/classes + module)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _text_chunks(path, source)
    lines = source.splitlines()
    chunks: list[CodeChunk] = []
    covered: set[int] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start) or start
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            text = "\n".join(lines[start - 1:end])
            chunks.append(CodeChunk(path, start, end, kind, node.name, text))
            covered.update(range(start, end + 1))
    # Module-level leftovers (imports, constants) grouped into contiguous runs.
    run_start: int | None = None
    for i in range(1, len(lines) + 1):
        has_code = i not in covered and lines[i - 1].strip()
        if has_code and run_start is None:
            run_start = i
        elif not has_code and run_start is not None:
            text = "\n".join(lines[run_start - 1:i - 1])
            if text.strip():
                chunks.append(CodeChunk(path, run_start, i - 1, "module", "", text))
            run_start = None
    if run_start is not None:
        text = "\n".join(lines[run_start - 1:len(lines)])
        if text.strip():
            chunks.append(CodeChunk(path, run_start, len(lines), "module", "", text))
    return chunks


def _text_chunks(path: str, source: str, window: int = 80, overlap: int = 20) -> list[CodeChunk]:
    """Line-window chunks for non-Python / unparseable files."""
    lines = source.splitlines()
    if not lines:
        return []
    chunks: list[CodeChunk] = []
    step = max(1, window - overlap)
    pos = 0
    while pos < len(lines):
        end = min(pos + window, len(lines))
        text = "\n".join(lines[pos:end])
        if text.strip():
            chunks.append(CodeChunk(path, pos + 1, end, "text", "", text))
        if end >= len(lines):
            break
        pos += step
    return chunks


class CodeRetriever:
    """Deterministic code-chunk index over a workspace."""

    def __init__(self, workspace: str | Path, max_files: int = 600):
        self.workspace = Path(workspace).resolve()
        self.max_files = max_files
        self._kw = KeywordRetriever()
        self._chunks: dict[str, CodeChunk] = {}
        self._built = False

    def build_index(self) -> int:
        """Scan, chunk, and index the workspace. Returns the chunk count."""
        self._kw.clear()
        self._chunks.clear()
        items: list[dict] = []
        count = 0
        for fp in sorted(self.workspace.rglob("*")):
            if any(part in SKIP_DIRS for part in fp.parts):
                continue
            if not fp.is_file() or fp.suffix.lower() not in _TEXT_EXTS:
                continue
            try:
                if fp.stat().st_size > _MAX_FILE_BYTES:
                    continue
                source = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            count += 1
            if count > self.max_files:
                break
            rel = str(fp.relative_to(self.workspace))
            file_chunks = (_py_chunks(rel, source) if fp.suffix == ".py"
                           else _text_chunks(rel, source))
            for idx, ch in enumerate(file_chunks):
                cid = f"{ch.location}#{idx}"
                self._chunks[cid] = ch
                # Fold path + symbol-name sub-words into the indexed text so
                # they contribute to keyword scoring (path/name matters most).
                header_tokens = _split_identifier(rel) + _split_identifier(ch.name)
                header = " ".join(header_tokens)
                items.append({"id": cid, "text": f"{header}\n{header}\n{ch.text}"})
        self._kw.add_items(items)
        self._built = True
        return len(self._chunks)

    def search(self, query: str, top_k: int = 8) -> list[CodeChunk]:
        """Return the top_k most relevant code chunks for a query."""
        if not self._built:
            self.build_index()
        if not query.strip():
            return []
        raw = self._kw.search(query, top_k=top_k * 3)
        query_words = set(_split_identifier(query)) | {
            w.lower() for w in re.findall(r"\w+", query)
        }
        scored: list[CodeChunk] = []
        for hit in raw:
            ch = self._chunks.get(hit["id"])
            if ch is None:
                continue
            bonus = 0.0
            name_words = set(_split_identifier(ch.name))
            path_words = set(_split_identifier(ch.path))
            if query_words & name_words:
                bonus += 3.0
            if query_words & path_words:
                bonus += 1.0
            ch.score = float(hit["score"]) + bonus
            scored.append(ch)
        scored.sort(key=lambda c: (c.score, -c.start_line), reverse=True)
        return scored[:top_k]
