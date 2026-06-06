"""ProviderFactory — creates providers from config, including MockLLMProvider for testing."""

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from evoagent.core.errors import ModelProviderError
from evoagent.core.message import ToolCall
from evoagent.models.base import BaseLLMProvider
from evoagent.models.deepseek import DeepSeekProvider
from evoagent.models.openai_compatible import OpenAICompatibleProvider
from evoagent.models.schema import LLMRequest, LLMResponse, ModelConfig


class MockLLMProvider(BaseLLMProvider):
    """Mock provider for testing — returns fixed responses without network calls.

    Usage:
        mock = MockLLMProvider(
            fixed_text="Hello!",
            fixed_tool_calls=[ToolCall(name="search", arguments={"q":"x"})],
        )
    """

    def __init__(
        self,
        fixed_text: str = "Mock response",
        fixed_tool_calls: list[ToolCall] | None = None,
        fixed_json: dict[str, Any] | None = None,
    ):
        self._fixed_text = fixed_text
        self._fixed_tool_calls = fixed_tool_calls
        self._fixed_json = fixed_json

    @property
    def provider_name(self) -> str:
        return "mock"

    async def chat(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=(
                json.dumps(self._fixed_json, ensure_ascii=False)
                if self._fixed_json
                else self._fixed_text
            ),
            model="mock-model",
            provider="mock",
            tool_calls=self._fixed_tool_calls,
            finish_reason="tool_calls" if self._fixed_tool_calls else "stop",
        )

    async def structured_chat(
        self, request: LLMRequest, schema: type[BaseModel]
    ) -> BaseModel:
        if self._fixed_json:
            return schema.model_validate(self._fixed_json)
        return schema.model_validate_json(self._fixed_text)

    async def stream_chat(self, request: LLMRequest) -> AsyncIterator[str]:
        for word in self._fixed_text.split():
            yield word + " "


class ProviderFactory:
    """Creates provider instances from configuration.

    Supported providers:
    - deepseek: DeepSeekProvider
    - openai_compatible: OpenAICompatibleProvider (generic)
    - mock: MockLLMProvider (for testing)
    - litellm: reserved for future
    """

    @staticmethod
    def create(config: ModelConfig) -> BaseLLMProvider:
        """Create a provider instance from a ModelConfig.

        Args:
            config: Model configuration.

        Returns:
            A BaseLLMProvider instance.

        Raises:
            ModelProviderError: If the provider type is unknown.
        """
        provider_type = getattr(config, "adapter_type", None)
        provider = provider_type.lower() if provider_type else config.provider.lower()

        if provider == "deepseek":
            return DeepSeekProvider(config)

        if provider in (
            "openai",
            "openai_compatible",
            "anthropic",
            "gemini",
            "mistral",
            "xai",
            "ollama",
        ):
            return OpenAICompatibleProvider(config)

        if provider == "mock":
            return MockLLMProvider()

        if provider == "litellm":
            raise ModelProviderError(
                "LiteLLM provider is not yet implemented. "
                "Use 'openai_compatible' with the LiteLLM proxy URL for now."
            )

        raise ModelProviderError(
            f"Unknown provider: '{config.provider}'. "
            "Supported: deepseek, openai_compatible, mock."
        )
