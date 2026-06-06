"""Tests for ProviderRegistry and ModelRegistry."""

import os

from evoagent.models.provider_registry import ProviderDefinition, ProviderRegistry
from evoagent.models.registry import ModelDefinition, ModelRegistry


def test_provider_registry_defaults():
    pr = ProviderRegistry()
    assert pr.get("deepseek") is not None
    assert pr.get("openai") is not None
    assert pr.get("ollama") is not None


def test_provider_registry_is_configured():
    pr = ProviderRegistry()
    # Ollama doesn't need API key
    assert pr.is_configured("ollama") is True
    # DeepSeek needs key — may or may not be set
    assert pr.is_configured("deepseek") == bool(os.getenv("DEEPSEEK_API_KEY"))


def test_provider_registry_custom():
    pr = ProviderRegistry()
    pr.register(ProviderDefinition(id="test", adapter_type="openai_compatible",
                                    api_key_env="TEST_KEY", base_url="http://localhost:8000/v1"))
    assert pr.get("test") is not None


def test_model_registry_canonical():
    mr = ModelRegistry()
    m = ModelDefinition(provider="deepseek", model_id="deepseek-chat")
    mr.register(m)
    assert mr.get("deepseek/deepseek-chat") is not None


def test_model_registry_alias():
    mr = ModelRegistry()
    mr.add_alias("pro", "deepseek/deepseek-chat")
    assert mr.resolve("pro") == "deepseek/deepseek-chat"


def test_model_registry_alias_collision():
    mr = ModelRegistry()
    mr.add_alias("pro", "deepseek/deepseek-chat")
    result = mr.add_alias("pro", "openai/gpt-4o")
    assert result is None  # collision


def test_model_registry_resolve_direct():
    mr = ModelRegistry()
    resolved = mr.resolve("deepseek/deepseek-chat")
    assert resolved == "deepseek/deepseek-chat"


def test_make_model_config_invalid_selection_returns_none():
    from evoagent.cli.interactive import _make_model_config
    from evoagent.config.loader import load_config
    provider_registry = ProviderRegistry()
    model_registry = ModelRegistry()
    config = load_config()

    assert _make_model_config("unknown-model", provider_registry, model_registry, config) is None
    assert _make_model_config("", provider_registry, model_registry, config) is None


def test_model_registry_favorites():
    mr = ModelRegistry()
    mr.add_favorite("deepseek/deepseek-chat")
    mr.mark_recent("deepseek/deepseek-chat")
    assert "deepseek/deepseek-chat" in mr.get_recent()


def test_model_registry_refresh_is_noop():
    mr = ModelRegistry()
    mr.refresh()
    assert mr.get_recent() == []
