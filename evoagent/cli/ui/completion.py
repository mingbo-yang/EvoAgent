"""Slash command completer for prompt_toolkit."""

from prompt_toolkit.completion import Completer, Completion, PathCompleter

COMMANDS = {
    "/mode": "Switch runtime mode",
    "/model": "Switch model/provider",
    "/plan": "Show or manage current plan",
    "/help": "Show all commands",
    "/status": "Show session status",
    "/sessions": "List saved sessions",
    "/resume": "Resume a session",
    "/new": "Start a new session",
    "/clear": "Clear conversation history",
    "/exit": "Save and exit",
    "/quit": "Save and exit",
    "/compact": "Compact context window",
    "/verbose": "Toggle verbose mode",
    "/debug": "Toggle debug mode",
    "/diff": "Show file diff",
    "/cost": "Show usage and cost",
    "/tokens": "Show context usage",
    "/tools": "List available tools",
    "/permissions": "Show permission rules",
}

MODE_OPTIONS = ["default", "plan", "auto"]
_path_completer = PathCompleter(expanduser=True)


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        # Slash commands
        if text.startswith("/mode "):
            for opt in MODE_OPTIONS:
                if opt.startswith(text.split()[-1] if len(text.split()) > 1 else ""):
                    yield Completion(opt, start_position=-len(text.split()[-1]) if " " in text else 0)
            return
        if text.startswith("/"):
            for cmd, desc in COMMANDS.items():
                if cmd.startswith(text):
                    yield Completion(cmd, display_meta=desc)
            return
        # Path completion for non-command input
        word = text.split()[-1] if text.split() else text
        if "/" in word or word.startswith(".") or word.startswith("~"):
            yield from _path_completer.get_completions(document, complete_event)
