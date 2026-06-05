"""Activity view — group multiple tool calls into a single activity."""


def render_activity_group(title: str, tool_calls: list[dict], expanded: bool = False) -> str:
    """Render an activity group (collapsed or expanded).

    Args:
        title: Activity title (e.g. "Explore EvoAgent codebase").
        tool_calls: List of {"name": ..., "output": ...} dicts.
        expanded: Whether to show all tool calls.
    """
    lines = [f"● {title}"]
    if not tool_calls:
        return lines[0]

    if expanded or len(tool_calls) <= 4:
        for tc in tool_calls:
            out = tc.get("output", "")[:80].replace("\n", " ")
            lines.append(f"  {tc.get('name', '?')}: {out}")
    else:
        for tc in tool_calls[:3]:
            out = tc.get("output", "")[:60].replace("\n", " ")
            lines.append(f"  {tc.get('name', '?')}: {out}")
        lines.append(f"  … +{len(tool_calls) - 3} more tool uses (Ctrl+O to expand)")
    return "\n".join(lines)
