"""Slash command completer for prompt_toolkit."""

from prompt_toolkit.completion import Completer, Completion

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
}

MODE_OPTIONS = ["default", "plan", "auto"]


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/mode "):
            for opt in MODE_OPTIONS:
                if opt.startswith(text.split()[-1] if len(text.split()) > 1 else ""):
                    yield Completion(opt, start_position=-len(text.split()[-1]) if " " in text else 0)
            return
        for cmd, desc in COMMANDS.items():
            if cmd.startswith(text):
                yield Completion(cmd, display_meta=desc)
