"""Robust text-editing core shared by the file-editing tools.

LLMs frequently get whitespace and indentation slightly wrong when quoting
``old_text``. A strict exact-substring replace then fails. This module layers
progressively more tolerant matching strategies and supports applying several
edits atomically (all-or-nothing) across one or many files.

We deliberately use fuzzy *search/replace* blocks rather than line-numbered
unified diffs: models reliably reproduce surrounding code but routinely emit
wrong ``@@`` line numbers, so search/replace applies far more often.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field


@dataclass
class EditResult:
    """Outcome of computing a single edit against file content."""

    success: bool
    new_content: str = ""
    count: int = 0
    strategy: str = ""  # exact | trailing-ws | strip-ws
    error: str = ""
    hint: str = ""


def _find_line_blocks(content_lines: list[str], old_lines: list[str], normalize) -> list[int]:
    """Return start indices where ``old_lines`` matches under ``normalize``."""
    norm_old = [normalize(line) for line in old_lines]
    norm_content = [normalize(line) for line in content_lines]
    n, m = len(norm_content), len(norm_old)
    if m == 0:
        return []
    starts: list[int] = []
    for i in range(0, n - m + 1):
        if norm_content[i:i + m] == norm_old:
            starts.append(i)
    return starts


def _closest_hint(content: str, old_text: str) -> str:
    """Build a short hint pointing at the most similar region in the file."""
    first = next((ln for ln in old_text.split("\n") if ln.strip()), "")
    if not first:
        return ""
    lines = content.split("\n")
    best = difflib.get_close_matches(first, lines, n=1, cutoff=0.6)
    if best:
        idx = lines.index(best[0]) + 1
        return f"Closest line in file (line {idx}): {best[0]!r}"
    return ""


def compute_edit(content: str, old_text: str, new_text: str,
                 replace_all: bool = False) -> EditResult:
    """Compute the result of one search/replace edit with fuzzy fallback.

    Strategies, tried in order:
      1. exact    — literal substring replace.
      2. trailing-ws — match ignoring trailing whitespace per line.
      3. strip-ws — match ignoring leading+trailing whitespace per line.

    For (2) and (3), ``new_text`` is inserted verbatim in place of the matched
    line span. Returns an :class:`EditResult`; ``success=False`` carries a hint.
    """
    # ── Strategy 1: exact substring ──────────────────────────────────
    exact_count = content.count(old_text)
    if exact_count > 0:
        if not replace_all and exact_count > 1:
            return EditResult(False, error=(
                f"old_text found {exact_count} times. Use replace_all=true "
                "or add surrounding context to make it unique."))
        new_content = content.replace(old_text, new_text) if replace_all \
            else content.replace(old_text, new_text, 1)
        return EditResult(True, new_content, exact_count if replace_all else 1, "exact")

    # Fuzzy line strategies operate on lines; drop one trailing newline so a
    # quoted block ending in "\n" doesn't require matching an empty line.
    old_for_lines = old_text[:-1] if old_text.endswith("\n") else old_text
    content_lines = content.split("\n")
    old_lines = old_for_lines.split("\n")
    new_lines = new_text.split("\n")

    for strategy, normalize in (
        ("trailing-ws", lambda s: s.rstrip()),
        ("strip-ws", lambda s: s.strip()),
    ):
        starts = _find_line_blocks(content_lines, old_lines, normalize)
        if not starts:
            continue
        if not replace_all and len(starts) > 1:
            return EditResult(False, error=(
                f"old_text matches {len(starts)} locations (ignoring whitespace). "
                "Use replace_all=true or add context to make it unique."))
        m = len(old_lines)
        # Apply from last to first so earlier indices stay valid.
        result_lines = list(content_lines)
        for i in sorted(starts, reverse=True):
            result_lines[i:i + m] = new_lines
        return EditResult(True, "\n".join(result_lines), len(starts), strategy)

    return EditResult(False, error="old_text not found in file.",
                      hint=_closest_hint(content, old_text))


@dataclass
class Edit:
    """A single search/replace edit."""

    old_text: str
    new_text: str
    replace_all: bool = False


def apply_edits(content: str, edits: list[Edit]) -> tuple[bool, str, list[str], str]:
    """Apply a sequence of edits to one file's content atomically.

    Each edit is applied to the running content. If any edit fails, the whole
    operation fails and the original content is left unchanged.

    Returns:
        (success, new_content, strategies, error)
    """
    current = content
    strategies: list[str] = []
    for idx, e in enumerate(edits):
        res = compute_edit(current, e.old_text, e.new_text, e.replace_all)
        if not res.success:
            msg = f"edit #{idx + 1} failed: {res.error}"
            if res.hint:
                msg += f" ({res.hint})"
            return False, content, strategies, msg
        current = res.new_content
        strategies.append(res.strategy)
    return True, current, strategies, ""


@dataclass
class FileEdits:
    """A group of edits targeting a single file path."""

    path: str
    edits: list[Edit] = field(default_factory=list)


def compute_multifile(read_fn, file_edits: list[FileEdits]) -> tuple[bool, dict[str, str], str]:
    """Compute new content for several files atomically (no writes here).

    Args:
        read_fn: callable(path) -> current file content (raises on missing).
        file_edits: per-file edit groups.

    Returns:
        (success, {path: new_content}, error). On failure, the dict is empty so
        the caller writes nothing.
    """
    results: dict[str, str] = {}
    for fe in file_edits:
        try:
            content = read_fn(fe.path)
        except Exception as exc:
            return False, {}, f"{fe.path}: {exc}"
        ok, new_content, _strategies, error = apply_edits(content, fe.edits)
        if not ok:
            return False, {}, f"{fe.path}: {error}"
        results[fe.path] = new_content
    return True, results, ""
