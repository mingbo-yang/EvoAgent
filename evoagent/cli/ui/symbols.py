"""Centralized UI glyphs with a safe ASCII fallback.

A consistent icon set is a big part of a polished CLI. Unicode glyphs are used
when the terminal can encode them; otherwise plain-ASCII equivalents are
substituted so output never turns into mojibake or raises encode errors.
"""

import sys

_UNICODE = {
    "prompt": "❯",
    "running": "◐",
    "done": "●",
    "ok": "✓",
    "fail": "✗",
    "warn": "▲",
    "info": "•",
    "bullet": "•",
    "arrow": "→",
    "reason": "·",
    "spark": "✦",
    "dot": "·",
    "tree_mid": "├─",
    "tree_end": "╰─",
    "tree_bar": "│",
}

_ASCII = {
    "prompt": ">",
    "running": "*",
    "done": "*",
    "ok": "+",
    "fail": "x",
    "warn": "!",
    "info": "-",
    "bullet": "-",
    "arrow": "->",
    "reason": ".",
    "spark": "*",
    "dot": ".",
    "tree_mid": "|-",
    "tree_end": "`-",
    "tree_bar": "|",
}

_UNICODE_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_ASCII_SPINNER_FRAMES = ("-", "\\", "|", "/")


def _supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in enc


_SET = _UNICODE if _supports_unicode() else _ASCII


def sym(name: str) -> str:
    """Return a glyph by name, ASCII-safe when the terminal can't encode it."""
    return _SET.get(name, "")


def spinner_frames() -> tuple[str, ...]:
    """Return terminal-safe frames for lightweight in-place activity animation."""
    return _UNICODE_SPINNER_FRAMES if _SET is _UNICODE else _ASCII_SPINNER_FRAMES
