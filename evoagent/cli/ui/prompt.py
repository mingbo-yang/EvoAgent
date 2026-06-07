"""prompt_toolkit PromptSession with a dynamic, polished prompt + toolbar."""

from collections.abc import Callable
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from evoagent.cli.ui.completion import SlashCompleter

_MODE_COLORS = {"default": "#7dd3fc", "plan": "#fcd34d", "auto": "#c4b5fd"}

PROMPT_STYLE = Style.from_dict({
    "arrow": "#7dd3fc bold",
    "mode.default": "#7dd3fc bold",
    "mode.plan": "#fcd34d bold",
    "mode.auto": "#c4b5fd bold",
    "pad": "",
    # Pure, single-colour bottom toolbar: no rainbow accents, no wrapping.
    "bottom-toolbar": "bg:#1b1f2a #b8c0d4",
})


def _clip_to_width(text: str, width: int) -> str:
    """Clip text to display width, preserving a single-line toolbar."""
    if get_cwidth(text) <= width:
        return text
    out = ""
    for ch in text:
        if get_cwidth(out + ch + "…") > width:
            return out + "…"
        out += ch
    return out


def render_toolbar_text(model: str, status: str = "", width: int = 80) -> str:
    """Return a width-fitted, single-colour toolbar string.

    Layout is intentionally two-sided:
    left  = model + optional session status
    right = keyboard hints

    The gap between them expands/contracts with terminal width, so wide
    terminals look spacious while narrow terminals degrade gracefully instead
    of cramming every token together.
    """
    width = max(20, width)
    if width < 60:
        status = ""
    hint_variants = [
        "↑↓ history   ↵ send   esc esc quit   /help",
        "↑↓ history   ↵ send   esc esc",
        "↑↓ history   ↵ send",
        "↑↓   ↵   esc",
        "↑↓",
        "",
    ]

    # Reserve more room for model/status on wide terminals, less on narrow ones.
    model_budget = max(10, min(34, width // 3))
    status_budget = max(0, min(28, width // 4))

    for hints in hint_variants:
        left = f"model {_clip_to_width(model, model_budget)}"
        if status:
            left += f"  ·  {_clip_to_width(status, status_budget)}"
        right = hints

        if right:
            min_gap = 4 if width >= 72 else 2
            total = get_cwidth(left) + min_gap + get_cwidth(right) + 2
            if total <= width:
                gap = " " * (width - get_cwidth(left) - get_cwidth(right) - 2)
                return f" {left}{gap}{right} "
        else:
            text = f" {left} "
            if get_cwidth(text) <= width:
                return text + " " * (width - get_cwidth(text))

    # Extremely narrow: model only.
    text = " " + _clip_to_width(f"model {model}", width - 2) + " "
    return text + " " * max(0, width - get_cwidth(text))


def create_prompt_session(
    get_mode: Callable[[], str] | None = None,
    get_model: Callable[[], str] | None = None,
    get_status: Callable[[], str] | None = None,
    history_path: str = ".evoagent/history",
    *,
    mode: str = "default",
    model_label: str = "deepseek:chat",
    bottom_text: str = "",
) -> PromptSession:
    """Create the interactive prompt.

    Prefer the ``get_*`` callables so the prompt and toolbar reflect live state
    (mode / model / context) without recreating the session. The static
    ``mode`` / ``model_label`` / ``bottom_text`` keyword arguments remain
    supported for backward compatibility.
    """
    _mode = get_mode or (lambda: mode)
    _model = get_model or (lambda: model_label)
    _status = get_status or (lambda: bottom_text)

    def _message():
        m = _mode()
        cls = f"class:mode.{m}" if m in _MODE_COLORS else "class:mode.default"
        # Column-0 prompt: a single mode-coloured arrow marks each user turn so
        # the input and the assistant reply share the same left edge.
        return [(cls, "❯ ")]

    def _toolbar():
        try:
            width = get_app().output.get_size().columns
        except Exception:
            width = 80
        return [("class:bottom-toolbar",
                 render_toolbar_text(_model(), _status(), width))]

    bindings = KeyBindings()

    @bindings.add("tab")
    def _tab(event):
        event.app.current_buffer.complete_next()

    @bindings.add("up")
    def _up(event):
        """Browse backward through input history."""
        event.current_buffer.history_backward()

    @bindings.add("down")
    def _down(event):
        """Browse forward through input history."""
        event.current_buffer.history_forward()

    @bindings.add("enter")
    def _enter(event):
        event.app.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _esc_enter(event):
        event.app.current_buffer.insert_text("\n")

    @bindings.add("c-j")
    def _cj(event):
        event.app.current_buffer.insert_text("\n")

    @bindings.add("c-d")
    def _cd(event):
        if not event.app.current_buffer.text:
            event.app.exit(result="/exit")
        else:
            event.app.current_buffer.delete()

    @bindings.add("c-o")
    def _co(event):
        event.app.exit(result="/toggle_verbose")

    @bindings.add("escape")
    def _esc(event):
        event.app.exit(result="/escape")

    @bindings.add("c-c")
    def _cc(event):
        if event.app.current_buffer.text:
            event.app.current_buffer.text = ""
        else:
            event.app.exit(result="/interrupt")

    try:
        Path(history_path).parent.mkdir(parents=True, exist_ok=True)
        history = FileHistory(history_path)
    except Exception:
        history = None

    return PromptSession(
        message=_message, style=PROMPT_STYLE, completer=SlashCompleter(),
        key_bindings=bindings, history=history, multiline=False,
        wrap_lines=False, bottom_toolbar=_toolbar, output=_create_safe_output(),
    )


def _create_safe_output():
    try:
        return create_output()
    except Exception:
        return DummyOutput()
