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
    for name in ("prompt", "ok", "fail", "running", "done", "dot", "bullet", "spark"):
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
    assert "more lines" in out


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


def test_history_timeline_empty_and_turns():
    from evoagent.conversation.schema import TurnRecord

    c = _console()
    R.history_timeline(c, [])
    assert "No conversation history" in c.file.getvalue()

    c = _console()
    turns = [
        TurnRecord(
            turn_id="t1",
            user_message="How many files?",
            assistant_response="There are 3 files.",
            tool_calls_count=2,
        )
    ]
    R.history_timeline(c, turns)
    out = c.file.getvalue()
    assert "turn 1" in out
    assert "How many files?" in out
    assert "There are 3 files." in out


def test_prompt_history_path_parent_created(tmp_path):
    from evoagent.cli.ui.prompt import create_prompt_session

    history_path = tmp_path / "nested" / "history"
    session = create_prompt_session(
        get_mode=lambda: "default",
        get_model=lambda: "deepseek-chat",
        get_status=lambda: "0 msgs · 0 turns",
        history_path=str(history_path),
    )
    assert session is not None
    assert history_path.parent.exists()


def test_approval_frame_width_with_long_command():
    from prompt_toolkit.utils import get_cwidth

    from evoagent.cli.ui.approval_view import render_approval_fragments

    for width in (44, 54, 72, 88):
        fragments = render_approval_fragments(
            "Approve tool: bash",
            "{'command': 'cd /mnt/huawei/ymb/agent && echo \"=== 本地最新提交 ===\" && "
            "git log --oneline --decorate --stat --all --very-long-argument'}",
            "Run 'bash' in workspace?",
            "medium",
            width=width,
        )
        lines = []
        cur = ""
        for _style, text in fragments:
            if "\n" in text:
                before, *rest = text.split("\n")
                cur += before
                lines.append(cur)
                cur = rest[-1] if rest else ""
            else:
                cur += text
        if cur:
            lines.append(cur)
        widths = {get_cwidth(line) for line in lines}
        assert widths == {width}
        assert lines[0].startswith("╭")
        assert lines[-1].startswith("╰")
