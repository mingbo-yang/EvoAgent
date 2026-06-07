"""Persistent prompt_toolkit TUI for EvoAgent interactive chat.

Unlike the legacy loop (PromptSession for input, then Rich for output), this
keeps the prompt, transcript, thinking/tool events, and bottom toolbar in one
long-lived prompt_toolkit Application. The toolbar is therefore a real fixed
layout row, not something redrawn with terminal cursor hacks.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import time
from collections.abc import Callable
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (
    ConditionalContainer,
    Dimension,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from evoagent.cli.ui.completion import SlashCompleter
from evoagent.cli.ui.prompt import render_toolbar_text
from evoagent.cli.ui.symbols import sym

_MAX_LINES = 2000
_TOOL_PREVIEW_LINES = 6


class InteractiveTUI:
    """A persistent terminal UI with a fixed bottom toolbar."""

    def __init__(
        self,
        *,
        session,
        runtime,
        store,
        event_bus,
        command_handler: Callable[[str], str],
        get_model: Callable[[], str],
    ):
        self.session = session
        self.runtime = runtime
        self.store = store
        self.event_bus = event_bus
        self.command_handler = command_handler
        self.get_model = get_model
        self.state = "idle"  # idle | thinking | running
        self._lines: list[list[tuple[str, str]]] = []
        self._app: Application | None = None
        self._welcome_visible = True
        self._approval: dict | None = None
        self._scroll_offset = 0

        Path(".evoagent").mkdir(parents=True, exist_ok=True)
        self.buffer = Buffer(
            completer=SlashCompleter(),
            complete_while_typing=False,
            history=FileHistory(".evoagent/history"),
            accept_handler=self._accept,
            multiline=False,
            enable_history_search=True,
            read_only=Condition(lambda: self._approval is not None),
        )

    async def run(self) -> None:
        self._append_banner()
        self._subscribe_events()
        app = self._build_app()
        self._app = app
        await app.run_async()

    # ── App/layout ───────────────────────────────────────────────────
    def _build_app(self) -> Application:
        transcript = Window(
            FormattedTextControl(lambda: FormattedText(self._render_transcript())),
            wrap_lines=True,
            height=Dimension(weight=1),
            always_hide_cursor=True,
        )
        input_win = Window(
            BufferControl(buffer=self.buffer),
            height=1,
            get_line_prefix=lambda _ln, _wrap: self._prompt_prefix(),
        )
        input_top_rule = Window(
            FormattedTextControl(lambda: FormattedText(self._input_rule(" input "))),
            height=1,
            style="class:input.rule",
        )
        input_bottom_rule = Window(
            FormattedTextControl(lambda: FormattedText(self._input_rule(""))),
            height=1,
            style="class:input.rule",
        )
        toolbar = Window(
            FormattedTextControl(lambda: FormattedText(self._toolbar())),
            height=1,
            style="class:bottom-toolbar",
        )
        kb = KeyBindings()

        @kb.add("tab")
        def _tab(event):
            if self._approval is not None:
                return
            event.current_buffer.complete_next()

        @kb.add("up")
        def _up(event):
            if self._approval is not None:
                self._approval["selected"] = (self._approval["selected"] - 1) % 3
                event.app.invalidate()
                return
            event.current_buffer.history_backward()

        @kb.add("down")
        def _down(event):
            if self._approval is not None:
                self._approval["selected"] = (self._approval["selected"] + 1) % 3
                event.app.invalidate()
                return
            event.current_buffer.history_forward()

        @kb.add("enter")
        def _enter(event):
            if self._approval is not None:
                self._approval_resolve(["yes", "remember", "no"][self._approval["selected"]])
                return
            event.current_buffer.validate_and_handle()

        @kb.add("1")
        @kb.add("2")
        @kb.add("3")
        def _approval_number(event):
            if self._approval is None:
                event.current_buffer.insert_text(event.data)
                return
            idx = int(event.data) - 1
            self._approval["selected"] = idx
            self._approval_resolve(["yes", "remember", "no"][idx])

        @kb.add("c-c")
        def _ctrl_c(event):
            if self._approval is not None:
                self._approval_resolve("no")
                return
            if event.app.current_buffer.text:
                event.app.current_buffer.text = ""
            elif self.state != "idle":
                self._append("evo.warning", f"{sym('warn')} interrupt requested")
            else:
                event.app.exit()

        @kb.add("c-d")
        def _ctrl_d(event):
            if not event.app.current_buffer.text:
                event.app.exit()
            else:
                event.app.current_buffer.delete()

        @kb.add("escape")
        def _esc(event):
            if self._approval is not None:
                self._approval_resolve("no")
                return
            if self.state == "idle" and not event.app.current_buffer.text:
                event.app.exit()

        @kb.add(Keys.ScrollUp)
        @kb.add("pageup")
        def _scroll_up(event):
            self._scroll_offset = min(self._max_scroll(), self._scroll_offset + 5)
            event.app.invalidate()

        @kb.add(Keys.ScrollDown)
        @kb.add("pagedown")
        def _scroll_down(event):
            self._scroll_offset = max(0, self._scroll_offset - 5)
            event.app.invalidate()

        @kb.add("home")
        def _home(event):
            self._scroll_offset = self._max_scroll()
            event.app.invalidate()

        @kb.add("end")
        def _end(event):
            self._scroll_offset = 0
            event.app.invalidate()

        root = HSplit([transcript, input_top_rule, input_win, input_bottom_rule, toolbar])
        approval_win = Window(
            FormattedTextControl(lambda: FormattedText(self._approval_fragments())),
            width=lambda: min(max(48, self._width() - 8), 88),
            height=lambda: self._approval_height(),
            wrap_lines=False,
            style="class:approval",
        )
        container = FloatContainer(
            content=root,
            floats=[
                Float(
                    content=ConditionalContainer(
                        content=approval_win,
                        filter=Condition(lambda: self._approval is not None),
                    ),
                    top=2,
                    # Float.left does not support callables on prompt_toolkit
                    # 3.x; keep a stable left margin and let the width adapt.
                    left=2,
                    width=lambda: min(max(48, self._width() - 8), 88),
                    height=lambda: self._approval_height(),
                    hide_when_covering_content=True,
                )
            ],
        )
        layout = Layout(container, focused_element=input_win)
        return Application(
            layout=layout,
            key_bindings=kb,
            style=_STYLE,
            # Full-screen layout is what makes the bottom toolbar a true fixed
            # terminal-bottom row across input, thinking, tool events and answer
            # rendering. The legacy non-fullscreen loop remains as fallback.
            full_screen=True,
            mouse_support=True,
        )

    def _prompt_prefix(self):
        mode = getattr(self.session.mode, "value", "default")
        cls = f"class:mode.{mode}" if mode in ("default", "plan", "auto") else "class:mode.default"
        return [(cls, "❯ ")]

    def _toolbar(self):
        status = f"{self.state} · {len(self.session.messages)} msgs · {len(self.session.turns)} turns"
        text = render_toolbar_text(self.get_model(), status, self._width())
        return [("class:bottom-toolbar", text)]

    def _approval_width(self) -> int:
        return min(max(48, self._width() - 8), 88)

    def _approval_height(self) -> int:
        return 12 if self._approval is not None else 1

    def _approval_fragments(self):
        if self._approval is None:
            return []
        from evoagent.cli.ui.approval_view import render_approval_fragments

        return render_approval_fragments(
            self._approval["action"],
            self._approval["command"],
            self._approval.get("description", ""),
            self._approval.get("risk", "medium"),
            selected=self._approval["selected"],
            width=self._approval_width(),
        )

    def _approval_resolve(self, value: str) -> None:
        if self._approval is None:
            return
        fut = self._approval.get("future")
        self._approval = None
        if fut is not None and not fut.done():
            fut.set_result(value)
        self._invalidate()

    def _input_rule(self, label: str = ""):
        """Horizontal input-area rule, Copilot-style, width-adaptive."""
        width = self._width()
        if label:
            text = "─" + label
            text += "─" * max(0, width - get_cwidth(text))
        else:
            text = "─" * max(0, width)
        return [("class:input.rule", text)]

    def _width(self) -> int:
        try:
            return self._app.output.get_size().columns if self._app else 80
        except Exception:
            return 80

    # ── Input and runtime ────────────────────────────────────────────
    def _accept(self, buf: Buffer) -> bool:
        text = buf.text.strip()
        buf.reset()
        if text:
            asyncio.create_task(self._handle_input(text))
        return True

    async def _handle_input(self, text: str) -> None:
        if self.state != "idle":
            self._append("evo.warning", f"{sym('warn')} still working; wait for this turn to finish")
            self._invalidate()
            return
        self._scroll_offset = 0
        self._append("evo.user", f"❯ {text}")
        self._append("evo.faint", "")
        self._welcome_visible = False
        self._invalidate()
        if text.startswith("/"):
            await self._handle_command(text)
            return
        await self._handle_user_message(text)

    async def _handle_command(self, text: str) -> None:
        if text in ("/exit", "/quit"):
            self.store.save(self.session)
            if self._app:
                self._app.exit()
            return
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = self.command_handler(text)
        out = buf.getvalue().strip()
        if out:
            for line in out.splitlines():
                self._append("evo.muted", line)
        if result == "exit" and self._app:
            self._app.exit()
        self._invalidate()

    async def _handle_user_message(self, text: str) -> None:
        self.state = "thinking"
        self._append("evo.reasoning", f"{sym('running')} thinking")
        self._invalidate()
        started = time.monotonic()
        assistant_idx: int | None = None
        try:
            async for chunk in self.runtime.handle_user_message_stream(text):
                if chunk.startswith("·"):
                    self._append("evo.reasoning", f"{sym('reason')} {chunk.lstrip('· ').strip()}")
                else:
                    assistant_idx = self._append_assistant_chunk(assistant_idx, chunk)
                self._invalidate()
        except Exception as e:
            self._append("evo.error", f"{sym('fail')} {e}")
        finally:
            elapsed = time.monotonic() - started
            tools = len(getattr(self.runtime, "_tool_names_this_turn", []) or [])
            footer = f"{elapsed:.1f}s"
            if tools:
                footer += f" · {tools} tool{'s' if tools != 1 else ''}"
            self._append("evo.faint", footer)
            self.state = "idle"
            self.store.save(self.session)
            self._invalidate()

    # ── Events ───────────────────────────────────────────────────────
    def _subscribe_events(self) -> None:
        async def on_tool(evt):
            name = evt.payload.get("tool_name", "?")
            if evt.type.value == "tool_call_started":
                self.state = "running"
                args = evt.payload.get("arguments") or {}
                arg_text = _fmt_args(args)
                self._append("evo.tool.name", f"{sym('running')} {name}" + (f"  {arg_text}" if arg_text else ""))
            else:
                ok = evt.type.value != "tool_call_failed"
                output = evt.payload.get("output", "") or ""
                self._append("evo.tool.name", f"{sym('done')} {name}")
                self._append_tool_body(output, ok=ok)
            self._invalidate()

        async def on_approval(evt):
            tool = evt.payload.get("tool_name", "?")
            cmd = str(evt.payload.get("arguments", {}))
            fut = asyncio.get_running_loop().create_future()
            self._approval = {
                "action": f"Approve tool: {tool}",
                "command": cmd,
                "description": f"Run '{tool}' in workspace?",
                "risk": evt.payload.get("risk", "medium"),
                "selected": 0,
                "future": fut,
            }
            self._invalidate()
            return await fut

        self.event_bus.subscribe("approval_requested", on_approval)
        self.event_bus.subscribe("tool_call_started", on_tool)
        self.event_bus.subscribe("tool_call_finished", on_tool)
        self.event_bus.subscribe("tool_call_failed", on_tool)

    # ── Transcript rendering ─────────────────────────────────────────
    def _append_banner(self) -> None:
        self._welcome_visible = True

    def _append(self, style: str, text: str) -> None:
        for line in str(text).splitlines() or [""]:
            self._lines.append([(class_name(style), line)])
        if len(self._lines) > _MAX_LINES:
            self._lines = self._lines[-_MAX_LINES:]

    def _append_assistant_chunk(self, idx: int | None, chunk: str) -> int | None:
        if not chunk:
            return idx
        parts = chunk.split("\n")
        if idx is None:
            self._lines.append(_markdown_line(parts[0]))
            idx = len(self._lines) - 1
        else:
            plain = "".join(text for _style, text in self._lines[idx])
            self._lines[idx] = _markdown_line(plain + parts[0])
        for part in parts[1:]:
            self._lines.append(_markdown_line(part))
            idx = len(self._lines) - 1
        if len(self._lines) > _MAX_LINES:
            drop = len(self._lines) - _MAX_LINES
            self._lines = self._lines[-_MAX_LINES:]
            idx = max(0, idx - drop) if idx is not None else None
        return idx

    def _append_tool_body(self, output: str, ok: bool = True) -> None:
        style = "evo.tool.out" if ok else "evo.error"
        lines = (output or "").splitlines()
        for ln in lines[:_TOOL_PREVIEW_LINES]:
            self._append(style, f"  {sym('tree_bar')} {ln}")
        extra = len(lines) - _TOOL_PREVIEW_LINES
        if extra > 0:
            self._append("evo.faint", f"  {sym('tree_bar')} +{extra} more lines · /tool last")

    def _render_transcript(self):
        fragments = []
        visible = self._visible_lines()
        for line in visible:
            fragments.extend(line)
            fragments.append(("", "\n"))
        return fragments

    def _visible_lines(self) -> list[list[tuple[str, str]]]:
        # Keep the latest activity visible, but render from the top of the
        # transcript window rather than forcing the final line to sit directly
        # above the input/toolbar. This avoids the "reply glued to the bottom"
        # feeling while still showing the current turn.
        try:
            rows = self._app.output.get_size().rows if self._app else 24
        except Exception:
            rows = 24
        transcript_rows = max(6, rows - 6)  # input rules + input + toolbar
        welcome = self._welcome_lines(self._width()) if self._welcome_visible else []
        all_lines = welcome + self._lines
        if not all_lines:
            return []
        end = len(all_lines) - self._scroll_offset
        start = max(0, end - transcript_rows)
        return all_lines[start:end]

    def _max_scroll(self) -> int:
        try:
            rows = self._app.output.get_size().rows if self._app else 24
        except Exception:
            rows = 24
        transcript_rows = max(6, rows - 6)
        total = len((self._welcome_lines(self._width()) if self._welcome_visible else []) + self._lines)
        return max(0, total - transcript_rows)

    def _welcome_lines(self, width: int) -> list[list[tuple[str, str]]]:
        width = max(46, width)
        inner = width - 2

        def pad(text: str) -> str:
            gap = max(0, inner - get_cwidth(text))
            return text + (" " * gap)

        title = " EvoAgent "
        left = max(1, (inner - get_cwidth(title)) // 2)
        right = inner - get_cwidth(title) - left
        top = "╭" + ("─" * left) + title + ("─" * right) + "╮"
        bottom = "╰" + ("─" * inner) + "╯"
        return [
            [("class:evo.faint", top)],
            [("class:evo.heading", "│" + pad("   ✦ · ✦") + "│")],
            [("class:evo.heading", "│" + pad("  ( ◡‿◡ )   EvoAgent  ·  autonomous coding agent") + "│")],
            [("class:evo.secondary", "│" + pad("   ╰─╯") + "│")],
            [("class:evo.faint", "│" + pad("") + "│")],
            [("class:evo.muted", "│" + pad("  Type /help for commands.  ↑/↓ history.  Ctrl+D exits.") + "│")],
            [("class:evo.faint", bottom)],
            [("class:evo.faint", "")],
        ]

    def _invalidate(self) -> None:
        if self._app:
            self._app.invalidate()


def class_name(style: str) -> str:
    return f"class:{style}" if not style.startswith("class:") else style


def _markdown_line(line: str) -> list[tuple[str, str]]:
    """Very small Markdown renderer for prompt_toolkit transcript lines.

    It intentionally covers the common agent-answer surface: headings, bullets,
    code fences, inline code and bold spans. This keeps the persistent TUI
    lightweight while restoring Markdown readability after moving away from
    Rich's Markdown renderer.
    """
    raw = str(line)
    stripped = raw.strip()
    if not stripped:
        return [("class:evo.text", "")]
    if stripped.startswith("```"):
        return [("class:evo.faint", raw)]
    if stripped.startswith("#"):
        text = stripped.lstrip("#").strip()
        return [("class:evo.heading", text)]
    if stripped.startswith(("- ", "* ")):
        return [("class:evo.secondary", "• "), *(_inline_md(stripped[2:]))]
    if stripped[:3].replace(".", "").isdigit() and ". " in stripped[:5]:
        num, rest = stripped.split(". ", 1)
        return [("class:evo.secondary", f"{num}. "), *_inline_md(rest)]
    return _inline_md(raw)


def _inline_md(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        if text.startswith("**", i):
            j = text.find("**", i + 2)
            if j != -1:
                out.append(("class:evo.heading", text[i + 2:j]))
                i = j + 2
                continue
        if text[i] == "`":
            j = text.find("`", i + 1)
            if j != -1:
                out.append(("class:evo.code", text[i + 1:j]))
                i = j + 1
                continue
        # Accumulate plain text until next marker.
        j = len(text)
        for marker in ("**", "`"):
            k = text.find(marker, i + 1)
            if k != -1:
                j = min(j, k)
        out.append(("class:evo.text", text[i:j]))
        i = j
    return out


def _fmt_args(args: dict) -> str:
    bits = []
    for k, v in list((args or {}).items())[:3]:
        s = str(v).replace("\n", " ")
        if len(s) > 28:
            s = s[:27] + "…"
        bits.append(f"{k}={s}")
    return ", ".join(bits)


_STYLE = Style.from_dict({
    "evo.heading": "#7dd3fc bold",
    "evo.text": "#e5e9f0",
    "evo.user": "#e5e9f0",
    "evo.muted": "#8b93a7",
    "evo.faint": "#5b6478",
    "evo.error": "#fca5a5 bold",
    "evo.warning": "#fcd34d",
    "evo.reasoning": "#8b93a7 italic",
    "evo.tool.name": "#7dd3fc bold",
    "evo.tool.out": "#8b93a7",
    "evo.code": "#c4b5fd",
    "mode.default": "#7dd3fc bold",
    "mode.plan": "#fcd34d bold",
    "mode.auto": "#c4b5fd bold",
    "bottom-toolbar": "bg:#1b1f2a #b8c0d4",
    "input.rule": "#3b4252",
})
