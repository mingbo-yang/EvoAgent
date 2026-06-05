"""Diff view — display file changes."""


def render_diff_summary(files: list[str]) -> str:
    """Show a simple diff summary for changed files."""
    if not files:
        return "No changed files."
    lines = ["Changed files:"]
    for f in files:
        lines.append(f"  • {f}")
    return "\n".join(lines)


def render_diff(path: str, diff_text: str) -> str:
    """Render a unified diff for a single file."""
    if not diff_text:
        return f"No changes in {path}."
    lines = [f"─── {path}"]
    for line in diff_text.split("\n")[:40]:
        if line.startswith("+"):
            lines.append(f"  {line}")
        elif line.startswith("-"):
            lines.append(f"  {line}")
        elif line.startswith("@@"):
            lines.append(f"  {line}")
        else:
            lines.append(f"    {line}")
    if len(diff_text.split("\n")) > 40:
        lines.append("  ... (more lines)")
    return "\n".join(lines)
