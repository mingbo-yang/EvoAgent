"""Error view — clean error display with secret redaction."""

import re

from evoagent.core.ids import generate_id

_SECRET_PATTERNS = [
    (re.compile(r'(api_key|apikey|api-key)\s*[:=]\s*["\']?([^"\'&\s]+)', re.IGNORECASE), "api_key"),
    (re.compile(r'Authorization\s*[:=]\s*["\']?(Bearer\s+)?([^"\'&\s]+)', re.IGNORECASE), "auth"),
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), "sk_key"),
    (re.compile(r'password\s*[:=]\s*["\']?([^"\'&\s]+)', re.IGNORECASE), "password"),
    (re.compile(r'secret\s*[:=]\s*["\']?([^"\'&\s]+)', re.IGNORECASE), "secret"),
]


def redact_secrets(text: str) -> str:
    """Redact API keys, tokens, and passwords from text."""
    for pattern, _ in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def render_error(exception: Exception, debug: bool = False) -> str:
    """Render a clean error message.

    Args:
        exception: The caught exception.
        debug: If True, include full traceback (still redacted).

    Returns:
        Formatted error string.
    """
    error_id = generate_id("err")
    msg = redact_secrets(str(exception))

    lines = [
        "✗ Turn failed",
        f"  {msg[:200]}",
        f"  Error ID: {error_id}",
    ]
    if not debug:
        lines.append("  Run /debug to see details.")
    else:
        import traceback
        tb = traceback.format_exc()
        lines.append(f"\n  {redact_secrets(tb)[:2000]}")

    return "\n".join(lines)
