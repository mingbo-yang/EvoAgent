"""Responsive layout tests — verify UI renders without crashing."""

import io
import sys

from evoagent.cli.ui.banner import render_banner, render_simple_startup


def test_banner_returns_panel():
    panel = render_banner("v0.5.0", "deepseek:v4-pro", "default", "/ws", 8)
    assert panel is not None


def test_banner_narrow_no_crash():
    """Banner should render without exception even at narrow width."""
    # Banner auto-detects terminal width; just verify it doesn't crash
    panel = render_banner("v0.5.0", "deepseek:v4-pro", "default", "/ws", 5)
    assert panel is not None


def test_banner_tiny_no_crash():
    """Banner at 40 columns should not crash."""
    panel = render_banner("v0.5.0", "d:v4", "auto", "/w", 2)
    assert panel is not None


def test_simple_startup_no_tty():
    """Non-TTY startup prints version and mode."""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        render_simple_startup("v0.5.0", "deepseek:chat", "plan")
        output = sys.stdout.getvalue()
        assert "v0.5.0" in output
        assert "plan" in output
    finally:
        sys.stdout = old_stdout


def test_banner_all_modes_no_exception():
    """Banner renders for all AgentMode values."""
    for mode in ["default", "plan", "auto"]:
        panel = render_banner("v0.5.0", "deepseek:chat", mode, "/ws", 8)
        assert panel is not None


def test_banner_version_displayed():
    """Banner includes version number."""
    panel = render_banner("v0.5.0", "deepseek:chat", "default", "/ws", 8)
    title = str(panel.title) if hasattr(panel, 'title') else ""
    assert "0.5.0" in title


def test_banner_tracks_width():
    """Banner width follows the provided width and caps at a readable maximum."""
    import io

    from rich.cells import cell_len
    from rich.console import Console

    from evoagent.cli.ui.theme import EVO_THEME

    def _border_width(w):
        c = Console(theme=EVO_THEME, force_terminal=True, width=w, file=io.StringIO())
        c.print(render_banner("v1.0.0", "deepseek-chat", "default", "/ws", 8,
                              width=w))
        import re
        plain = re.sub(r"\x1b\[[0-9;]*m", "", c.file.getvalue())
        top = next(ln for ln in plain.splitlines() if ln.startswith("╭"))
        return cell_len(top)

    narrow = _border_width(64)
    wide = _border_width(96)
    capped = _border_width(140)
    assert narrow == 64
    assert wide == 96
    assert capped == 110  # readability cap
