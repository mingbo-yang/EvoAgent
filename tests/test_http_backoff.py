"""Tests for HTTP retry/backoff in OpenAICompatibleProvider._send_request."""

import httpx
import pytest

from evoagent.core.errors import ModelProviderError
from evoagent.models.openai_compatible import OpenAICompatibleProvider
from evoagent.models.schema import ModelConfig


def _make_provider(monkeypatch, max_retries=3):
    monkeypatch.setenv("TEST_KEY", "sk-test-not-a-real-secret-000000")
    config = ModelConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.example.com/v1",
        api_key_env="TEST_KEY",
        max_retries=max_retries,
    )
    return OpenAICompatibleProvider(config)


def _install_transport(provider, handler):
    transport = httpx.MockTransport(handler)
    provider._client = httpx.AsyncClient(
        base_url=provider._config.base_url.rstrip("/"),
        transport=transport,
    )


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds(monkeypatch):
    provider = _make_provider(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="rate limited")
        return httpx.Response(200, json={"ok": True})

    _install_transport(provider, handler)
    result = await provider._send_request({"messages": []})
    assert result == {"ok": True}
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_retries_on_503_then_succeeds(monkeypatch):
    provider = _make_provider(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"ok": 1})

    _install_transport(provider, handler)
    result = await provider._send_request({"messages": []})
    assert result == {"ok": 1}
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_exhausts_attempts_and_raises(monkeypatch):
    provider = _make_provider(monkeypatch, max_retries=2)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    _install_transport(provider, handler)
    with pytest.raises(ModelProviderError) as exc:
        await provider._send_request({"messages": []})
    # max_retries=2 → 3 attempts total.
    assert calls["n"] == 3
    assert "after 3 attempt" in str(exc.value)


@pytest.mark.asyncio
async def test_auth_error_not_retried(monkeypatch):
    provider = _make_provider(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, text="unauthorized")

    _install_transport(provider, handler)
    with pytest.raises(ModelProviderError) as exc:
        await provider._send_request({"messages": []})
    assert calls["n"] == 1
    assert "Authentication failed" in str(exc.value)


@pytest.mark.asyncio
async def test_other_4xx_not_retried(monkeypatch):
    provider = _make_provider(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    _install_transport(provider, handler)
    with pytest.raises(ModelProviderError):
        await provider._send_request({"messages": []})
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_transport_error_retried(monkeypatch):
    provider = _make_provider(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"ok": True})

    _install_transport(provider, handler)
    result = await provider._send_request({"messages": []})
    assert result == {"ok": True}
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_error_body_is_redacted(monkeypatch):
    provider = _make_provider(monkeypatch, max_retries=0)
    secret_body = "error: api_key=sk-EXAMPLEFAKEKEY00000000000000000000 leaked"

    def handler(request):
        return httpx.Response(500, text=secret_body)

    _install_transport(provider, handler)
    with pytest.raises(ModelProviderError) as exc:
        await provider._send_request({"messages": []})
    assert "sk-EXAMPLEFAKEKEY" not in str(exc.value)


def test_parse_retry_after_seconds():
    assert OpenAICompatibleProvider._parse_retry_after("5") == 5.0
    assert OpenAICompatibleProvider._parse_retry_after(None) is None
    assert OpenAICompatibleProvider._parse_retry_after("not-a-number-or-date") is None
