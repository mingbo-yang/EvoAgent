"""Tests for the redesigned CLI UI helpers (symbols + render)."""

import io

from rich.console import Console

from evoagent.cli.ui import render as R
from evoagent.cli.ui import symbols
from evoagent.cli.ui.banner import render_banner
from evoagent.cli.ui.theme import EVO_THEME


def _console() -> Console:
    return Console(theme=EVO_THEME, force_terminal=True, width=80,
                   file=io.StringIO())


def test_symbols_returns_glyph():
    # Whatever the terminal, every known symbol resolves to a non-empty string.
    for name in ("prompt", "ok", "fail", "running", "dot", "bullet", "spark"):
        assert symbols.sym(name)


def test_symbols_ascii_fallback():
    ascii_set = symbols._ASCII
    assert ascii_set["ok"] == "+"
    assert ascii_set["fail"] == "x"
    # Unknown name resolves to empty string, never raises.
    assert symbols.sym("does-not-exist") == ""


def test_banner_renders_fixed_width_lines():
    """Every bordered line of the banner has the same display width."""
    from rich.cells import cell_len

    c = Console(theme=EVO_THEME, force_terminal=True, width=84, file=io.StringIO())
    c.print(render_banner("v1.0.0", "deepseek:chat", "default", "/ws", 8, "API"))
    raw = c.file.getvalue()
    import re
    plain = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    border_lines = [ln for ln in plain.splitlines() if ln.startswith(("╭", "│", "╰"))]
    widths = {cell_len(ln) for ln in border_lines}
    # All bordered rows share a single consistent display width.
    assert len(widths) == 1


def test_render_tool_running_and_done():
    c = _console()
    R.tool_running(c, "code_search", {"query": "egress"})
    R.tool_done(c, "code_search", "line1\nline2", success=True)
    out = c.file.getvalue()
    assert "code_search" in out
    assert "line1" in out


def test_render_tool_done_failure_glyph():
    c = _console()
    R.tool_done(c, "run_tests", "FAIL", success=False)
    out = c.file.getvalue()
    assert "run_tests" in out


def test_render_tool_output_truncated():
    c = _console()
    big = "\n".join(f"line {i}" for i in range(30))
    R.tool_done(c, "grep", big, success=True)
    out = c.file.getvalue()
    assert "lines total" in out


def test_render_footer_and_messages():
    c = _console()
    R.response_footer(c, 4.2, tool_calls=3, tokens=22434)
    R.info(c, "informational")
    R.success(c, "done")
    R.warn(c, "careful")
    R.error(c, "broken")
    out = c.file.getvalue()
    assert "4.2s" in out
    assert "22.4k tokens" in out
    assert "informational" in out
    assert "broken" in out
    # footer must not start with a stray separator dot
    footer_line = out.splitlines()[0]
    assert not footer_line.lstrip().startswith("·")


def test_render_kv_table():
    c = _console()
    R.kv(c, [("model", "deepseek:chat"), ("mode", "default")])
    out = c.file.getvalue()
    assert "model" in out
    assert "deepseek:chat" in out


def test_mode_card():
    c = _console()
    R.mode_card(c, "plan")
    out = c.file.getvalue()
    assert "mode" in out
    assert "plan" in out
    # includes a one-line description of the mode
    assert "plan" in out and "ask before editing" in out


def test_model_card():
    c = _console()
    R.model_card(c, "deepseek/deepseek-chat", "alias: ds")
    out = c.file.getvalue()
    assert "model" in out
    assert "deepseek/deepseek-chat" in out
    assert "alias: ds" in out


def test_live_tool_reporter_finishes_with_result():
    c = _console()
    rep = R.LiveToolReporter(c)
    rep.start("run_tests", {"command": "pytest -q"})
    rep.finish("run_tests", "FAIL - 1 failed", success=False)
    out = c.file.getvalue()
    assert "run_tests" in out
    assert "FAIL" in out


def test_live_tool_reporter_handles_no_args():
    c = _console()
    rep = R.LiveToolReporter(c)
    rep.start("git_status")
    rep.finish("git_status", "clean", success=True)
    out = c.file.getvalue()
    assert "git_status" in out
