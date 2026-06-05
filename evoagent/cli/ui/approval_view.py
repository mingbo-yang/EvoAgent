"""Approval view — keyboard-selectable approval menu."""


def render_approval(action: str, command: str, description: str = "", risk: str = "medium") -> str:
    """Render a three-option approval prompt.

    Returns the rendered text. The caller handles user selection.
    """
    lines = [
        "─" * 60,
        f"\n{action}",
        f"\n  {command}",
    ]
    if description:
        lines.append(f"\n  {description}")
    lines.append(f"\n  Risk: {risk}")
    lines.append("\n")
    lines.append("  1. Yes — approve this action")
    lines.append("\n  2. Yes, and remember — skip future prompts for this pattern")
    lines.append("\n  3. No — deny and tell the agent to try another approach")
    lines.append("\n" + "─" * 60)
    return "".join(lines)


def get_approval_choice(prompt_text: str) -> str:
    """Simple input-based approval chooser. Returns 'yes', 'remember', or 'no'."""
    print(prompt_text)
    try:
        choice = input("Choice (1/2/3): ").strip()
    except (EOFError, KeyboardInterrupt):
        return "no"
    if choice == "1":
        return "yes"
    if choice == "2":
        return "remember"
    return "no"
