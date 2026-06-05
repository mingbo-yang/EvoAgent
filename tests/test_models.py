"""Tests for the model provider layer."""

import json

import pytest
from pydantic import BaseModel

from evoagent.core.errors import ModelProviderError
from evoagent.core.message import Message, MessageRole, ToolCall
from evoagent.models.factory import MockLLMProvider, ProviderFactory
from evoagent.models.router import ModelRouter
from evoagent.models.schema import (
    LLMRequest,
    LLMResponse,
    ModelConfig,
    RouterConfig,
)

# ── Schema tests ──────────────────────────────────────────────────────


def test_llm_request_defaults():
    req = LLMRequest()
    assert req.model is None
    assert req.temperature == 0.0
    assert req.stream is False
    assert req.messages == []


def test_llm_request_serialization():
    msg = Message(role=MessageRole.USER, content="hi")
    req = LLMRequest(messages=[msg], model="deepseek-chat", max_tokens=100)
    data = req.model_dump()
    restored = LLMRequest.model_validate(data)
    assert restored.model == "deepseek-chat"
    assert restored.max_tokens == 100
    assert len(restored.messages) == 1


def test_llm_request_with_tools():
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
    req = LLMRequest(tools=tools, tool_choice="auto")
    data = req.model_dump()
    restored = LLMRequest.model_validate(data)
    assert len(restored.tools) == 1
    assert restored.tool_choice == "auto"


def test_llm_response_serialization():
    resp = LLMResponse(
        content="Hello",
        model="deepseek-chat",
        provider="deepseek",
        finish_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    data = resp.model_dump()
    restored = LLMResponse.model_validate(data)
    assert restored.content == "Hello"
    assert restored.usage["total_tokens"] == 15


def test_llm_response_with_tool_calls():
    tc = ToolCall(id="c1", name="read", arguments={"path": "f.txt"})
    resp = LLMResponse(
        content="",
        model="gpt-4",
        provider="openai",
        tool_calls=[tc],
        finish_reason="tool_calls",
    )
    data = resp.model_dump_json()
    restored = LLMResponse.model_validate_json(data)
    assert len(restored.tool_calls) == 1
    assert restored.tool_calls[0].name == "read"


def test_model_config_defaults():
    config = ModelConfig()
    assert config.provider == "deepseek"
    assert config.model == "deepseek-chat"
    assert config.api_key_env == "DEEPSEEK_API_KEY"
    assert config.max_retries == 3


def test_router_config_defaults():
    config = RouterConfig()
    assert config.planner.model == "deepseek-reasoner"
    assert config.executor.model == "deepseek-chat"
    assert config.critic.model == "deepseek-reasoner"
    assert config.default.model == "deepseek-chat"


# ── MockLLMProvider tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_provider_fixed_text():
    mock = MockLLMProvider(fixed_text="Hello, world!")
    resp = await mock.chat(LLMRequest())
    assert resp.content == "Hello, world!"
    assert resp.provider == "mock"
    assert resp.finish_reason == "stop"
    assert resp.tool_calls is None


@pytest.mark.asyncio
async def test_mock_provider_fixed_tool_calls():
    tc = ToolCall(id="t1", name="calculator", arguments={"expr": "1+1"})
    mock = MockLLMProvider(fixed_text="", fixed_tool_calls=[tc])
    resp = await mock.chat(LLMRequest())
    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "calculator"
    assert resp.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_mock_provider_fixed_json():
    class Person(BaseModel):
        name: str
        age: int

    mock = MockLLMProvider(fixed_json={"name": "Alice", "age": 30})
    resp = await mock.chat(LLMRequest())
    parsed = json.loads(resp.content)
    assert parsed["name"] == "Alice"

    # structured_chat
    person = await mock.structured_chat(LLMRequest(), Person)
    assert person.name == "Alice"
    assert person.age == 30


@pytest.mark.asyncio
async def test_mock_provider_provider_name():
    mock = MockLLMProvider()
    assert mock.provider_name == "mock"


# ── ProviderFactory tests ─────────────────────────────────────────────


def test_factory_creates_mock():
    config = ModelConfig(provider="mock")
    provider = ProviderFactory.create(config)
    assert provider.provider_name == "mock"
    assert isinstance(provider, MockLLMProvider)


def test_factory_unknown_provider():
    config = ModelConfig(provider="nonexistent")
    with pytest.raises(ModelProviderError, match="Unknown provider"):
        ProviderFactory.create(config)


def test_factory_litellm_not_implemented():
    config = ModelConfig(provider="litellm")
    with pytest.raises(ModelProviderError, match="not yet implemented"):
        ProviderFactory.create(config)


# ── ModelRouter tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_router_routes_by_role():
    mock_planner = MockLLMProvider(fixed_text="plan")
    mock_executor = MockLLMProvider(fixed_text="execute")

    router = ModelRouter(providers={"planner": mock_planner, "executor": mock_executor})

    resp = await router.chat("planner", LLMRequest())
    assert resp.content == "plan"

    resp = await router.chat("executor", LLMRequest())
    assert resp.content == "execute"


@pytest.mark.asyncio
async def test_router_fallback_to_default():
    mock_default = MockLLMProvider(fixed_text="default")
    router = ModelRouter(providers={"default": mock_default})

    resp = await router.chat("unknown_role", LLMRequest())
    assert resp.content == "default"


@pytest.mark.asyncio
async def test_router_no_provider_raises():
    router = ModelRouter(providers={})
    with pytest.raises(ModelProviderError, match="No provider registered"):
        await router.chat("planner", LLMRequest())


@pytest.mark.asyncio
async def test_router_structured_chat():
    class Result(BaseModel):
        value: int

    mock = MockLLMProvider(fixed_text='{"value": 42}')
    router = ModelRouter(providers={"default": mock})
    result = await router.structured_chat("default", LLMRequest(), Result)
    assert result.value == 42


@pytest.mark.asyncio
async def test_router_register():
    router = ModelRouter()
    mock = MockLLMProvider(fixed_text="registered")
    router.register("custom", mock)
    resp = await router.chat("custom", LLMRequest())
    assert resp.content == "registered"


# ── OpenAICompatibleProvider tests (no network) ───────────────────────


def test_openai_compatible_missing_key():
    """Should raise ModelProviderError when API key env var is empty/missing."""
    config = ModelConfig(
        provider="openai_compatible",
        api_key_env="NONEXISTENT_KEY_12345",
        model="test-model",
    )
    with pytest.raises(ModelProviderError, match="API key not found"):
        ProviderFactory.create(config)


def test_deepseek_provider_defaults():
    """DeepSeekProvider should use sensible defaults from config."""
    # Can't create without a real key, but we can verify config merging
    config = ModelConfig(provider="deepseek", model="custom-model")
    # The default merge should keep deepseek defaults for unset fields
    assert config.model == "custom-model"
    assert config.provider == "deepseek"


# ── ToolCall parsing tests ────────────────────────────────────────────


def test_tool_call_creation_and_serialization():
    tc = ToolCall(
        id="call_abc",
        name="search_files",
        arguments={"keyword": "test", "path": "."},
        raw='{"keyword": "test", "path": "."}',
    )
    assert tc.name == "search_files"
    assert tc.arguments["keyword"] == "test"

    data = tc.model_dump()
    restored = ToolCall.model_validate(data)
    assert restored.raw == '{"keyword": "test", "path": "."}'
    assert restored.metadata == {}


def test_tool_call_list_roundtrip():
    """Tool calls in LLMResponse should survive serialization roundtrip."""
    tcs = [
        ToolCall(id="c1", name="read", arguments={"p": "a.txt"}),
        ToolCall(id="c2", name="write", arguments={"p": "b.txt"}),
    ]
    resp = LLMResponse(
        content="",
        model="test",
        provider="test",
        tool_calls=tcs,
        finish_reason="tool_calls",
    )
    json_str = resp.model_dump_json()
    restored = LLMResponse.model_validate_json(json_str)
    assert len(restored.tool_calls) == 2
    assert restored.tool_calls[1].name == "write"
