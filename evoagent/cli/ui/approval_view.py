"""Approval widget using prompt_toolkit for arrow-key selection."""

from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style


@dataclass
class ApprovalChoice:
    label: str
    value: str
    description: str = ""


APPROVAL_STYLE = Style.from_dict({
    "selected": "bg:#444444 #ffffff bold",
    "normal": "",
    "title": "bold",
    "info": "#888888",
})


async def prompt_approval(action: str, command: str, description: str = "",
                          risk: str = "medium") -> str:
    """Show an arrow-key navigable approval prompt.

    Returns 'yes', 'remember', or 'no'.
    """
    choices = [
        ApprovalChoice("1. Yes", "yes", "Approve this action once"),
        ApprovalChoice("2. Yes, and remember", "remember", "Skip future prompts for this pattern"),
        ApprovalChoice("3. No", "no", "Deny and let the agent try another approach"),
    ]
    selected = [0]

    def get_text():
        lines = ["─" * 50, f"\n{action}", f"\n  {command}"]
        if description:
            lines.append(f"\n  {description}")
        lines.append("\n")
        for i, c in enumerate(choices):
            prefix = "❯ " if i == selected[0] else "  "
            style = "class:selected" if i == selected[0] else "class:normal"
            lines.append((style, f"{prefix}{c.label}  {c.description}\n"))
        return lines

    kb = KeyBindings()
    done = [None]

    @kb.add("up")
    def _up(event):
        selected[0] = (selected[0] - 1) % len(choices)

    @kb.add("down")
    def _down(event):
        selected[0] = (selected[0] + 1) % len(choices)

    @kb.add("1")
    @kb.add("2")
    @kb.add("3")
    def _number(event):
        num = int(event.data)
        selected[0] = num - 1
        done[0] = choices[num - 1].value
        event.app.exit()

    @kb.add("enter")
    def _enter(event):
        done[0] = choices[selected[0]].value
        event.app.exit()

    @kb.add("escape")
    def _esc(event):
        done[0] = "no"
        event.app.exit()

    @kb.add("c-c")
    def _ctrl_c(event):
        done[0] = "no"
        event.app.exit()

    content = Window(content=FormattedTextControl(get_text), always_hide_cursor=False)
    app = Application(layout=Layout(HSplit([content])), key_bindings=kb,
                      style=APPROVAL_STYLE, full_screen=False)

    await app.run_async()
    return done[0] or "no"
