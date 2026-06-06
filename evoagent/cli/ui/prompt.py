"""prompt_toolkit PromptSession with a dynamic, polished prompt + toolbar."""

from collections.abc import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from evoagent.cli.ui.completion import SlashCompleter

_MODE_COLORS = {"default": "#7dd3fc", "plan": "#fcd34d", "auto": "#c4b5fd"}

PROMPT_STYLE = Style.from_dict({
    "arrow": "#7dd3fc bold",
    "mode.default": "#7dd3fc bold",
    "mode.plan": "#fcd34d bold",
    "mode.auto": "#c4b5fd bold",
    "pad": "",
    # bottom toolbar
    "bottom-toolbar": "bg:#1b1f2a #8b93a7",
    "tb.key": "bg:#1b1f2a #5b6478",
    "tb.val": "bg:#1b1f2a #7dd3fc",
    "tb.sep": "bg:#1b1f2a #3b4252",
    "tb.dim": "bg:#1b1f2a #8b93a7",
    "tb.hint": "bg:#1b1f2a #5b6478",
})


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
        return [
            ("class:pad", "  "),
            (cls, m),
            ("class:arrow", "  ❯ "),
        ]

    def _toolbar():
        parts = [
            ("class:bottom-toolbar", "  "),
            ("class:tb.key", "model "),
            ("class:tb.val", _model()[:28]),
        ]
        status = _status()
        if status:
            parts += [("class:tb.sep", "   ·   "), ("class:tb.dim", status)]
        parts += [
            ("class:tb.sep", "      "),
            ("class:tb.hint", "↵ send   esc esc quit   /help"),
        ]
        return parts

    bindings = KeyBindings()

    @bindings.add("tab")
    def _tab(event):
        event.app.current_buffer.complete_next()

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
            event.app.current_buffer.cut_right()

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
        history = FileHistory(history_path)
    except Exception:
        history = None

    return PromptSession(
        message=_message, style=PROMPT_STYLE, completer=SlashCompleter(),
        key_bindings=bindings, history=history, multiline=False,
        wrap_lines=False, bottom_toolbar=_toolbar,
    )
