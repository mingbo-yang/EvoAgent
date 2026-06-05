"""Plan view — display and approve execution plans."""


def render_plan(steps: list[str], files: list[str] | None = None,
                risks: list[str] | None = None) -> str:
    """Render a plan as a numbered list with optional files and risks.

    Args:
        steps: Plan step descriptions.
        files: Files likely affected.
        risks: Potential risks.
    """
    lines = ["Plan:"]
    for i, step in enumerate(steps, 1):
        lines.append(f"  {i}. {step}")
    if files:
        lines.append("\nFiles:")
        for f in files:
            lines.append(f"  • {f}")
    if risks:
        lines.append("\nRisks:")
        for r in risks:
            lines.append(f"  • {r}")
    lines.append("\n  1. Execute plan")
    lines.append("  2. Modify plan")
    lines.append("  3. Cancel")
    return "\n".join(lines)


def get_plan_choice() -> str:
    """Get user choice for plan action. Returns 'execute', 'modify', or 'cancel'."""
    try:
        choice = input("Choice (1/2/3): ").strip()
    except (EOFError, KeyboardInterrupt):
        return "cancel"
    if choice == "1":
        return "execute"
    if choice == "2":
        return "modify"
    return "cancel"
