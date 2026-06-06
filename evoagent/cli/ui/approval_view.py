"""Approval widget using prompt_toolkit for arrow-key selection."""

from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth


@dataclass
class ApprovalChoice:
    label: str
    value: str
    description: str = ""


APPROVAL_STYLE = Style.from_dict({
    "frame": "#5b6478",
    "title": "#7dd3fc bold",
    "cmd": "#e5e9f0",
    "selected": "bg:#2a3142 #7dd3fc bold",
    "normal": "#8b93a7",
    "desc": "#5b6478",
    "risk.low": "#86efac",
    "risk.medium": "#fcd34d",
    "risk.high": "#fca5a5 bold",
    "info": "#8b93a7",
})


def _clip(text: str, width: int) -> str:
    """Clip text to a display width, adding an ellipsis when needed."""
    text = str(text).replace("\n", " ")
    if get_cwidth(text) <= width:
        return text
    out = ""
    for ch in text:
        if get_cwidth(out + ch + "…") > width:
            return out + "…"
        out += ch
    return out


def _pad_fragments(fragments, width: int):
    """Right-pad formatted fragments to an exact display width."""
    plain = "".join(text for _, text in fragments)
    pad = max(0, width - get_cwidth(plain))
    return fragments + [("class:frame", " " * pad)]


def render_approval_fragments(
    action: str,
    command: str,
    description: str = "",
    risk: str = "medium",
    *,
    selected: int = 0,
    width: int = 80,
):
    """Return prompt_toolkit formatted fragments for a complete approval frame."""
    risk_key = risk if risk in ("low", "medium", "high") else "medium"
    choices = [
        ApprovalChoice("Yes", "yes", "approve this action once"),
        ApprovalChoice("Yes, and don't ask again", "remember",
                       "skip future prompts for this pattern"),
        ApprovalChoice("No", "no", "deny and let the agent try another approach"),
    ]
    width = max(44, min(width, 88))
    inner = width - 2
    body_w = inner - 4

    def line(parts=None):
        parts = parts or []
        return (
            [("class:frame", "│  ")]
            + _pad_fragments(parts, body_w)
            + [("class:frame", "  │"), ("", "\n")]
        )

    title = " Permission required "
    left = max(1, (inner - get_cwidth(title)) // 2)
    right = inner - get_cwidth(title) - left
    fragments = [
        ("class:frame", "╭" + "─" * left),
        ("class:title", title),
        ("class:frame", "─" * right + "╮"),
        ("", "\n"),
    ]

    fragments.extend(line([
        ("class:title", _clip(action, max(12, body_w - 18))),
        ("class:frame", "  ["),
        (f"class:risk.{risk_key}", f"{risk_key} risk"),
        ("class:frame", "]"),
    ]))

    cmd = str(command).replace("\n", " ")
    first = _clip(cmd, body_w)
    fragments.extend(line([("class:cmd", first)]))
    rest = cmd[len(first.rstrip("…")):].lstrip()
    if rest:
        fragments.extend(line([("class:cmd", _clip(rest, body_w))]))

    if description:
        fragments.extend(line([("class:desc", _clip(description, body_w))]))
    fragments.extend(line())

    for i, c in enumerate(choices):
        sel = i == selected
        prefix = "❯ " if sel else "  "
        style = "class:selected" if sel else "class:normal"
        choice_text = _clip(
            f"{prefix}{i + 1}. {c.label}   {c.description}",
            body_w,
        )
        fragments.extend(line([(style, choice_text)]))

    fragments.extend([
        ("class:frame", "╰" + "─" * inner + "╯"),
    ])
    return fragments


async def prompt_approval(action: str, command: str, description: str = "",
                          risk: str = "medium") -> str:
    """Show an arrow-key navigable approval prompt.

    Returns 'yes', 'remember', or 'no'.
    """
    choices = [
        ApprovalChoice("Yes", "yes", "approve this action once"),
        ApprovalChoice("Yes, and don't ask again", "remember",
                       "skip future prompts for this pattern"),
        ApprovalChoice("No", "no", "deny and let the agent try another approach"),
    ]
    selected = [0]
    def get_text():
        try:
            cols = get_app().output.get_size().columns
        except Exception:
            cols = 80
        return render_approval_fragments(
            action, command, description, risk,
            selected=selected[0],
            width=cols - 2,
        )

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

    content = Window(
        content=FormattedTextControl(get_text),
        always_hide_cursor=False,
        wrap_lines=False,
    )
    app = Application(layout=Layout(HSplit([content])), key_bindings=kb,
                      style=APPROVAL_STYLE, full_screen=False)

    await app.run_async()
    return done[0] or "no"


def render_approval(action: str, command: str, description: str = "",
                    risk: str = "medium"):
    """Backward compatibility wrapper for approval UI rendering."""
    return {"action": action, "command": command, "description": description, "risk": risk}


def get_approval_choice(prompt) -> str:
    """Backward compatibility wrapper for approval UI choice handling."""
    # Prompt object from legacy UI is not supported here.
    # Use prompt_approval directly instead for current interactive flows.
    raise NotImplementedError("Use prompt_approval() instead of get_approval_choice()")
