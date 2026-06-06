"""BaseLLMProvider — abstract interface for all model providers."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel

from evoagent.models.schema import LLMRequest, LLMResponse, StreamEvent


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers.

    Every model provider (DeepSeek, OpenAI, LiteLLM, local)
    must implement this interface. Agent runtime code only
    depends on this ABC, never on concrete providers.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier (e.g. 'deepseek', 'openai')."""
        ...

    @abstractmethod
    async def chat(self, request: LLMRequest) -> LLMResponse:
        """Send a chat completion request and return the response.

        Args:
            request: The LLM request with messages, tools, etc.

        Returns:
            A standardized LLMResponse.
        """
        ...

    @abstractmethod
    async def structured_chat(
        self, request: LLMRequest, schema: type[BaseModel]
    ) -> BaseModel:
        """Send a request and parse the response into a Pydantic model.

        Args:
            request: The LLM request (should request JSON output).
            schema: The Pydantic model to parse into.

        Returns:
            An instance of the given schema.
        """
        ...

    @abstractmethod
    async def stream_chat(
        self, request: LLMRequest
    ) -> AsyncIterator[str]:
        """Send a request and stream text chunks.

        Args:
            request: The LLM request.

        Yields:
            Text chunks as they arrive.
        """
        ...

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion as structured events.

        Yields incremental ``text``/``reasoning`` deltas and fully-assembled
        ``tool_call`` events, then a terminal ``done`` event carrying the
        complete :class:`LLMResponse` (content, tool_calls, usage,
        finish_reason).

        This default implementation falls back to a single non-streaming
        ``chat()`` call so every provider supports the structured-streaming
        interface; providers that support server-sent events override it to
        deliver true token-level streaming with tool_call assembly.
        """
        response = await self.chat(request)
        if response.reasoning_content:
            yield StreamEvent(type="reasoning", delta=response.reasoning_content)
        if response.content:
            yield StreamEvent(type="text", delta=response.content)
        for tc in response.tool_calls or []:
            yield StreamEvent(type="tool_call", tool_call=tc)
        yield StreamEvent(type="done", response=response)
