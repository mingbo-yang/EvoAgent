"""prompt_toolkit PromptSession with keybindings, history, and bottom toolbar."""

from evoagent.cli.ui.completion import SlashCompleter
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

PROMPT_STYLE = Style.from_dict({
    "prompt": "#00ffff bold",
    "mode": "#ffff00",
    "model": "#888888",
    "separator": "#00ffff",
    "toolbar": "bg:#333333 #ffffff",
})


def create_prompt_session(mode: str = "default", model_label: str = "deepseek:chat",
                          history_path: str = ".evoagent/history",
                          bottom_text: str = "") -> PromptSession:
    mode_colors = {"default": "ansicyan", "plan": "ansiyellow", "auto": "ansimagenta"}
    mode_color = mode_colors.get(mode, "ansicyan")

    prompt_text = [
        ("class:prompt", "EvoAgent"),
        ("", "["),
        ("fg:" + mode_color, mode),
        ("", "]"),
        ("class:model", "[" + model_label[:20] + "]"),
        ("class:separator", " ❯ "),
    ]

    bindings = KeyBindings()

    @bindings.add("enter")
    def _enter(event):
        """Enter submits the input."""
        event.app.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _esc_enter(event):
        """Esc+Enter inserts newline."""
        event.app.current_buffer.insert_text("\n")

    @bindings.add("c-j")
    def _cj(event):
        """Ctrl+J inserts newline."""
        event.app.current_buffer.insert_text("\n")

    @bindings.add("c-d")
    def _cd(event):
        if not event.app.current_buffer.text:
            event.app.exit(result="/exit")
        else:
            # Delete forward on non-empty input
            event.app.current_buffer.cut_right()

    @bindings.add("c-o")
    def _co(event):
        """Ctrl+O: toggle verbose/compact."""
        event.app.exit(result="/toggle_verbose")

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

    def _toolbar():
        return [("class:toolbar", bottom_text or f"{mode} · {model_label[:20]}")]

    return PromptSession(
        message=prompt_text, style=PROMPT_STYLE, completer=SlashCompleter(),
        key_bindings=bindings, history=history, multiline=False,
        wrap_lines=False, bottom_toolbar=_toolbar,
    )
