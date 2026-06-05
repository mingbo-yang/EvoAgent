"""Status bar — bottom toolbar showing session state."""

from prompt_toolkit.layout import FormattedTextControl, Window


def create_status_bar(get_mode, get_model, get_ctx_pct=None, get_cost=None):
    """Create a prompt_toolkit bottom toolbar.

    Args:
        get_mode: Callable returning current mode string.
        get_model: Callable returning model label.
        get_ctx_pct: Optional callable returning context percentage.
        get_cost: Optional callable returning cost string.
    """

    def _status_text():
        parts = [
            ("class:mode", get_mode()),
            ("", " · "),
            ("class:model", get_model()),
        ]
        if get_ctx_pct:
            parts.append(("", f" · ctx {get_ctx_pct()}%"))
        if get_cost:
            cost = get_cost()
            if cost:
                parts.append(("", f" · {cost}"))
        return parts

    return Window(
        content=FormattedTextControl(_status_text),
        height=1,
        style="reverse",
    )
