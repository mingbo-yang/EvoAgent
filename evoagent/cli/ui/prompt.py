"""prompt_toolkit PromptSession setup with keybindings and history."""

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
})


def create_prompt_session(mode: str = "default", model_label: str = "deepseek:chat",
                          history_path: str = ".evoagent/history") -> PromptSession:
    """Create a prompt_toolkit PromptSession with EvoAgent styling.

    Args:
        mode: Agent mode (default/plan/auto).
        model_label: Provider:model label for prompt.
        history_path: Path to history file.

    Returns:
        Configured PromptSession.
    """
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

    @bindings.add("c-d")
    def _(event):
        """Ctrl+D: exit after saving."""
        event.app.exit(result="/exit")

    @bindings.add("c-c")
    def _(event):
        """Ctrl+C: interrupt current turn."""
        if event.app.current_buffer.text:
            event.app.current_buffer.text = ""
        else:
            event.app.exit(result="/interrupt")

    try:
        history = FileHistory(history_path)
    except Exception:
        history = None

    return PromptSession(
        message=prompt_text,
        style=PROMPT_STYLE,
        completer=SlashCompleter(),
        key_bindings=bindings,
        history=history,
        multiline=False,
    )
