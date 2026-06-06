"""Polished render helpers for the interactive CLI.

Centralizes the look of tool calls, status lines, response footers, section
headers, and key/value tables so the interactive loop stays clean and the
styling is consistent and easy to evolve.
"""

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
    """Render a tool-call start line: a dim glyph + bold name + faint args."""
    line = Text()
    line.append(f" {sym('running')} ", style="evo.spinner")
    line.append(name, style="evo.tool.name")
    if args:
        line.append("  ", style="")
        line.append(_fmt_args(args), style="evo.tool.args")
    console.print(line)


def tool_done(console: Console, name: str, output: str = "",
              success: bool = True) -> None:
    """Render a tool-call result: status glyph + name, with indented output."""
    glyph = sym("ok") if success else sym("fail")
    style = "evo.success" if success else "evo.error"
    head = Text()
    head.append(f" {glyph} ", style=style)
    head.append(name, style="evo.tool.name")

    body = (output or "").rstrip("\n")
    if not body:
        console.print(head)
        return

    max_w = max(40, (console.width or 80) - 6)
    lines = body.split("\n")
    shown = lines[:_MAX_TOOL_OUT_LINES]
    out = Text()
    bar = sym("tree_bar")
    for ln in shown:
        if len(ln) > max_w:
            ln = ln[:max_w - 1] + "…"
        out.append(f"   {bar} ", style="evo.faint")
        out.append(ln, style="evo.tool.out")
        out.append("\n")
    if len(lines) > _MAX_TOOL_OUT_LINES:
        out.append(f"   {bar} ", style="evo.faint")
        out.append(
            f"… {len(lines)} lines total · /tool last for full output",
            style="evo.faint",
        )
        out.append("\n")
    console.print(Group(head, out))


def activity_summary(console: Console, label: str, tools: list[str]) -> None:
    """Render a grouped activity summary for multi-tool turns."""
    uniq = list(dict.fromkeys(tools))
    line = Text()
    line.append(f" {sym('spark')} ", style="evo.secondary")
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
    """Render the subtle footer beneath an assistant response."""
    parts = [f"{elapsed:.1f}s"]
    if tool_calls:
        parts.append(f"{tool_calls} tool{'s' if tool_calls != 1 else ''}")
    if tokens:
        parts.append(_fmt_tokens(tokens))
    sep = f" {sym('dot')} "
    line = Text("  ")  # left indent, aligns under the response
    line.append(sep.join(parts), style="evo.faint")
    console.print(line)


def reasoning(console: Console, text: str) -> None:
    line = Text()
    line.append(f" {sym('reason')} ", style="evo.faint")
    line.append(text.lstrip("· ").strip(), style="evo.reasoning")
    console.print(line)


def message(console: Console, glyph_name: str, text: str, style: str) -> None:
    """A single-line status message (info/success/warn/error)."""
    line = Text()
    line.append(f" {sym(glyph_name)} ", style=style)
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


def mode_card(console: Console, mode: str) -> None:
    """Confirmation for a mode switch: glyph + arrow + a one-line description."""
    style = {"plan": "evo.plan", "auto": "evo.auto"}.get(mode, "evo.default")
    head = Text()
    head.append(f" {sym('ok')} ", style="evo.success")
    head.append("mode", style="evo.muted")
    head.append(f"  {sym('arrow')}  ", style="evo.faint")
    head.append(mode, style=style)
    desc = Text(f"     {_MODE_DESC.get(mode, '')}", style="evo.faint")
    console.print(head)
    console.print(desc)


def model_card(console: Console, label: str, detail: str = "") -> None:
    """Confirmation for a model switch: glyph + arrow + new model label."""
    head = Text()
    head.append(f" {sym('ok')} ", style="evo.success")
    head.append("model", style="evo.muted")
    head.append(f"  {sym('arrow')}  ", style="evo.faint")
    head.append(label, style="evo.primary")
    console.print(head)
    if detail:
        console.print(Text(f"     {detail}", style="evo.faint"))
