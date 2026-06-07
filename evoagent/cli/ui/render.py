"""Polished render helpers for the interactive CLI.

Centralizes the look of tool calls, status lines, response footers, section
headers, and key/value tables so the interactive loop stays clean and the
styling is consistent and easy to evolve.
"""

import shutil

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style
from rich.console import Console, Group
from rich.text import Text

from evoagent.cli.ui.symbols import sym

_MAX_TOOL_OUT_LINES = 6


def _fmt_args(args: dict) -> str:
    parts = []
    for k, v in list(args.items())[:3]:
        sval = str(v).replace("\n", " ")
        if len(sval) > 32:
            sval = sval[:31] + "…"
        parts.append(f"{k}={sval}")
    return ", ".join(parts)


def tool_running(console: Console, name: str, args: dict | None = None) -> None:
    """Render a running tool line (column 0): spinner glyph + name + args."""
    line = Text()
    line.append(f"{sym('running')} ", style="evo.spinner")
    line.append(name, style="evo.tool.name")
    if args:
        line.append("  ")
        line.append(_fmt_args(args), style="evo.tool.args")
    console.print(line)


def _body_block(output: str, console: Console) -> Text:
    """Copilot-style indented output block: '  │ line' with a collapse note."""
    out = Text()
    body = (output or "").rstrip("\n")
    if not body:
        return out
    max_w = max(40, (console.width or 80) - 4)
    lines = body.split("\n")
    bar = sym("tree_bar")
    for ln in lines[:_MAX_TOOL_OUT_LINES]:
        if len(ln) > max_w:
            ln = ln[:max_w - 1] + "…"
        out.append(f"  {bar} ", style="evo.faint")
        out.append(ln, style="evo.tool.out")
        out.append("\n")
    extra = len(lines) - _MAX_TOOL_OUT_LINES
    if extra > 0:
        out.append(f"  {bar} ", style="evo.faint")
        out.append(f"+{extra} more lines · /tool last", style="evo.faint")
        out.append("\n")
    return out


def tool_done(console: Console, name: str, output: str = "",
              success: bool = True) -> None:
    """Render a finished tool call, Copilot-style.

    A filled status dot + tool name header at column 0, followed by an indented
    ``│``-prefixed output preview that collapses long output to '+N more lines'.
    """
    dot_style = "evo.success" if success else "evo.error"
    head = Text()
    head.append(f"{sym('done')} ", style=dot_style)
    head.append(name, style="evo.tool.name")
    body = _body_block(output, console)
    if body.plain:
        console.print(Group(head, body))
    else:
        console.print(head)


def activity_summary(console: Console, label: str, tools: list[str]) -> None:
    """Render a grouped activity summary for multi-tool turns (column 0)."""
    uniq = list(dict.fromkeys(tools))
    line = Text()
    line.append(f"{sym('spark')} ", style="evo.secondary")
    line.append(label, style="evo.secondary")
    line.append(f"  {', '.join(uniq[:3])}", style="evo.muted")
    if len(tools) > 3:
        line.append(f" +{len(tools) - 3} more", style="evo.faint")
    console.print(line)


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M tokens"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k tokens"
    return f"{n} tokens"


def response_footer(console: Console, elapsed: float, tool_calls: int = 0,
                    tokens: int | None = None) -> None:
    """Render the subtle footer beneath an assistant response (column 0)."""
    parts = [f"{elapsed:.1f}s"]
    if tool_calls:
        parts.append(f"{tool_calls} tool{'s' if tool_calls != 1 else ''}")
    if tokens:
        parts.append(_fmt_tokens(tokens))
    sep = f" {sym('dot')} "
    console.print(Text(sep.join(parts), style="evo.faint"))


def reasoning(console: Console, text: str) -> None:
    line = Text()
    line.append(f"{sym('reason')} ", style="evo.faint")
    line.append(text.lstrip("· ").strip(), style="evo.reasoning")
    console.print(line)


def message(console: Console, glyph_name: str, text: str, style: str) -> None:
    """A single-line status message (info/success/warn/error) at column 0."""
    line = Text()
    line.append(f"{sym(glyph_name)} ", style=style)
    line.append(text, style=style if glyph_name in ("fail", "warn") else "evo.text")
    console.print(line)


def info(console: Console, text: str) -> None:
    message(console, "info", text, "evo.accent")


def success(console: Console, text: str) -> None:
    message(console, "ok", text, "evo.success")


def warn(console: Console, text: str) -> None:
    message(console, "warn", text, "evo.warning")


def error(console: Console, text: str) -> None:
    message(console, "fail", text, "evo.error")


def section(console: Console, title: str) -> None:
    """A small section header used by /status, /help, etc."""
    console.print(Text(f"{title}", style="evo.heading"))


def kv(console: Console, rows: list[tuple[str, str]], indent: int = 1) -> None:
    """Render aligned key/value rows."""
    from rich.table import Table
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="evo.key", justify="left", min_width=10)
    grid.add_column(style="evo.value")
    pad = " " * indent
    for k, v in rows:
        grid.add_row(pad + k, str(v))
    console.print(grid)


def history_timeline(console: Console, turns: list, limit: int = 10) -> None:
    """Render recent conversation turns as a compact Copilot-style timeline."""
    if not turns:
        info(console, "No conversation history yet.")
        return

    shown = turns[-limit:]
    for idx, turn in enumerate(shown, 1):
        q = (getattr(turn, "user_message", "") or "").replace("\n", " ").strip()
        a = (getattr(turn, "assistant_response", "") or "").replace("\n", " ").strip()
        tools = getattr(turn, "tool_calls_count", 0) or 0
        if len(q) > max(40, console.width - 10):
            q = q[: max(39, console.width - 11)] + "…"
        if len(a) > max(40, console.width - 10):
            a = a[: max(39, console.width - 11)] + "…"

        head = Text()
        head.append(f"{sym('done')} ", style="evo.accent")
        head.append(f"turn {idx}", style="evo.heading")
        if tools:
            head.append(f"  {tools} tool{'s' if tools != 1 else ''}", style="evo.faint")
        console.print(head)

        body = Text()
        body.append(f"  {sym('tree_bar')} ", style="evo.faint")
        body.append("Q ", style="evo.key")
        body.append(q or "(empty)", style="evo.value")
        body.append("\n")
        body.append(f"  {sym('tree_bar')} ", style="evo.faint")
        body.append("A ", style="evo.key")
        body.append(a or "(no answer recorded)", style="evo.muted")
        console.print(body)


# ── Live tool spinner ─────────────────────────────────────────────────

_MODE_DESC = {
    "default": "Read, decide, and act autonomously with your approval on risky steps.",
    "plan": "Inspect first, propose a plan, and ask before editing files.",
    "auto": "Execute autonomously end-to-end; deny rules still apply.",
}


class LiveToolReporter:
    """Shows an in-place animated spinner while a tool runs, then a result line.

    On ``start`` a Rich status spinner appears (``⠋ name args``); on ``finish``
    the spinner is cleared and replaced by a ``✓``/``✗`` result line with the
    (truncated) tool output. Used by the interactive loop's tool event hook.
    """

    def __init__(self, console: Console):
        self.console = console
        self._status = None

    def start(self, name: str, args: dict | None = None) -> None:
        label = Text()
        label.append(name, style="evo.tool.name")
        if args:
            label.append("  ")
            label.append(_fmt_args(args), style="evo.tool.args")
        try:
            self._status = self.console.status(
                label, spinner="dots", spinner_style="evo.spinner"
            )
            self._status.start()
        except Exception:
            self._status = None
            tool_running(self.console, name, args)

    def finish(self, name: str, output: str = "", success: bool = True) -> None:
        if self._status is not None:
            try:
                self._status.stop()
            except Exception:
                pass
            self._status = None
        tool_done(self.console, name, output, success=success)

    def clear(self) -> None:
        """Stop any active spinner without printing a result line."""
        if self._status is not None:
            try:
                self._status.stop()
            except Exception:
                pass
            self._status = None


class ThinkingReporter:
    """Safe thinking spinner for the model-latency gap.

    This uses prompt_toolkit's output layer (not direct ``sys.stdout`` writes)
    to draw the toolbar, so it behaves like prompt_toolkit's own prompt
    toolbar. If a real terminal output is not available, it degrades to a normal
    Rich status line and does not attempt cursor movement.
    """

    def __init__(self, console: Console, get_model, get_status):
        self.console = console
        self.get_model = get_model
        self.get_status = get_status
        self._status = None
        self._output = None
        self._toolbar_visible = False

    def start(self) -> None:
        if self._status is not None:
            return
        try:
            label = Text()
            label.append("thinking", style="evo.reasoning")
            label.append("  ·  ", style="evo.faint")
            label.append(self.get_model(), style="evo.muted")
            status = self.get_status()
            if status:
                label.append("  ·  ", style="evo.faint")
                label.append(status, style="evo.faint")
            self._status = self.console.status(
                label, spinner="dots", spinner_style="evo.spinner"
            )
            self._status.start()
            self._draw_bottom_toolbar()
        except Exception:
            self._status = None
            # Fallback: show a stable line rather than failing the turn.
            self.console.print(Text("thinking", style="evo.reasoning"))

    def stop(self) -> None:
        if self._status is not None:
            try:
                self._status.stop()
            except Exception:
                pass
            self._status = None
        self._clear_bottom_toolbar()

    def _supports_pinned_toolbar(self) -> bool:
        if not self.console.is_terminal:
            return False
        try:
            output = create_output()
            # PlainTextOutput has the methods but intentionally does not emit
            # terminal controls. It also cannot keep a bottom toolbar pinned.
            if output.__class__.__name__ == "PlainTextOutput":
                return False
            self._output = output
            return True
        except Exception:
            return False

    def _draw_bottom_toolbar(self) -> None:
        if not self._supports_pinned_toolbar():
            return
        from evoagent.cli.ui.prompt import render_toolbar_text

        output = self._output
        size = shutil.get_terminal_size((self.console.width or 80, 24))
        # Vt100_Output.cursor_goto emits ESC[{row};{column}H directly, so the
        # coordinates are 1-based. Use the terminal's last row and column 1.
        row = max(1, size.lines)
        text = render_toolbar_text(self.get_model(), self.get_status(), size.columns)
        try:
            # Use prompt_toolkit's output primitives for cursor movement and
            # text rendering. CSI s/u (save/restore cursor) is the modern form;
            # avoid DEC ESC7/ESC8 which some terminals show as literal text.
            output.write_raw("\x1b[s")
            output.cursor_goto(row, 1)
            output.erase_end_of_line()
            print_formatted_text(
                FormattedText([("class:bottom-toolbar", text)]),
                style=Style.from_dict({"bottom-toolbar": "bg:#1b1f2a #b8c0d4"}),
                output=output,
                end="",
            )
            output.write_raw("\x1b[u")
            output.flush()
            self._toolbar_visible = True
        except Exception:
            self._toolbar_visible = False

    def _clear_bottom_toolbar(self) -> None:
        if not self._toolbar_visible or self._output is None:
            return
        try:
            size = shutil.get_terminal_size((self.console.width or 80, 24))
            row = max(1, size.lines)
            self._output.write_raw("\x1b[s")
            self._output.cursor_goto(row, 1)
            self._output.erase_end_of_line()
            self._output.write_raw("\x1b[u")
            self._output.flush()
        except Exception:
            pass
        self._toolbar_visible = False


def mode_card(console: Console, mode: str) -> None:
    """Confirmation for a mode switch: glyph + arrow + a one-line description."""
    style = {"plan": "evo.plan", "auto": "evo.auto"}.get(mode, "evo.default")
    head = Text()
    head.append(f"{sym('ok')} ", style="evo.success")
    head.append("mode", style="evo.muted")
    head.append(f"  {sym('arrow')}  ", style="evo.faint")
    head.append(mode, style=style)
    desc = Text(f"  {sym('tree_bar')} {_MODE_DESC.get(mode, '')}", style="evo.faint")
    console.print(head)
    console.print(desc)


def model_card(console: Console, label: str, detail: str = "") -> None:
    """Confirmation for a model switch: glyph + arrow + new model label."""
    head = Text()
    head.append(f"{sym('ok')} ", style="evo.success")
    head.append("model", style="evo.muted")
    head.append(f"  {sym('arrow')}  ", style="evo.faint")
    head.append(label, style="evo.primary")
    console.print(head)
    if detail:
        console.print(Text(f"  {sym('tree_bar')} {detail}", style="evo.faint"))
