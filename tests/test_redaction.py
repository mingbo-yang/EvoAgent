"""Tests for central secret redaction (evoagent.core.redaction)."""

import json

from evoagent.core.redaction import REDACTED, redact_obj, redact_text


def test_redact_text_openai_key():
    out = redact_text("token is sk-EXAMPLEFAKEKEY00000000000000000000 done")
    assert "sk-EXAMPLE" not in out
    assert REDACTED in out


def test_redact_text_bearer_keeps_trailing_quote():
    # Bearer token redaction must not swallow the closing quote.
    out = redact_text('{"h": "Bearer abc123def456ghi789"}')
    assert "abc123def456" not in out
    # The surrounding JSON structure (quotes/braces) is preserved.
    assert out.endswith('"}')
    assert out.startswith('{"h": "')


def test_redact_text_key_value_keeps_other_fields():
    out = redact_text("api_key=supersecretvalue123, keep=visible")
    assert "supersecretvalue123" not in out
    assert "keep=visible" in out


def test_redact_text_github_aws_slack():
    s = (
        "gh: ghp_abcdefghijklmnopqrstuvwxyz012345 "
        "aws: AKIAIOSFODNN7EXAMPLE "
        "slack: xoxb-123456789012-abcdefghijkl"
    )
    out = redact_text(s)
    assert "ghp_abcdef" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "xoxb-123456789012" not in out


def test_redact_obj_sensitive_keys():
    obj = {"api_key": "anything", "TOKEN": "x", "keep": "value"}
    out = redact_obj(obj)
    assert out["api_key"] == REDACTED
    assert out["TOKEN"] == REDACTED
    assert out["keep"] == "value"


def test_redact_obj_recursive_and_roundtrips():
    obj = {
        "api_key": "sk-1234567890abcdefABCD",
        "nested": {
            "token": "ghp_aaaaaaaaaaaaaaaaaaaaaa1",
            "count": 7,
            "note": "embedded sk-zzzzzzzzzzzzzzzzzzzz token",
        },
        "list": ["clean", "Bearer abcdefghijklmnop"],
    }
    out = redact_obj(obj)
    # Result must serialize and reload as valid JSON (no corruption).
    reloaded = json.loads(json.dumps(out))
    assert reloaded["api_key"] == REDACTED
    assert reloaded["nested"]["token"] == REDACTED
    assert reloaded["nested"]["count"] == 7
    assert "sk-zzzz" not in reloaded["nested"]["note"]
    assert "abcdefghijklmnop" not in reloaded["list"][1]
    assert reloaded["list"][0] == "clean"


def test_redact_obj_preserves_non_string_scalars():
    obj = {"a": 1, "b": True, "c": None, "d": 3.14}
    assert redact_obj(obj) == obj


def test_redact_text_empty():
    assert redact_text("") == ""
    assert redact_text("nothing sensitive here") == "nothing sensitive here"
