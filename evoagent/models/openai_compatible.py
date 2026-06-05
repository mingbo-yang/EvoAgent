"""OpenAICompatibleProvider — generic provider for any OpenAI-compatible API."""

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from evoagent.core.errors import ModelProviderError
from evoagent.core.message import ToolCall
from evoagent.models.base import BaseLLMProvider
from evoagent.models.schema import LLMRequest, LLMResponse, ModelConfig


class OpenAICompatibleProvider(BaseLLMProvider):
    """Provider for any OpenAI-compatible chat completion API.

    Supports:
    - Chat completion with tools
    - JSON mode (via response_format)
    - Structured output parsing
    - Streaming (via async generator)
    - Automatic retry on transient errors
    """

    def __init__(self, config: ModelConfig):
        """Initialize with a ModelConfig.

        Args:
            config: Model configuration (provider, model, base_url, api_key_env, etc.).

        Raises:
            ModelProviderError: If the API key is not found in the environment.
        """
        self._config = config
        self._api_key = os.getenv(config.api_key_env, "")

        if not self._api_key:
            raise ModelProviderError(
                f"API key not found. Set the environment variable "
                f"'{config.api_key_env}' or configure it in evoagent.yaml."
            )

        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(config.timeout),
        )

    @property
    def provider_name(self) -> str:
        return self._config.provider

    # ── Public API ─────────────────────────────────────────────────

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """Send a chat completion request."""
        payload = self._build_payload(request, stream=False)
        raw = await self._send_request(payload)
        return self._parse_response(raw)

    async def structured_chat(
        self, request: LLMRequest, schema: type[BaseModel]
    ) -> BaseModel:
        """Send a request and parse the response into a Pydantic model.

        Forces JSON output mode and parses the result.
        """
        json_request = LLMRequest(
            messages=request.messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=request.tools,
            response_format={"type": "json_object"},
            stream=False,
            metadata=request.metadata,
        )
        response = await self.chat(json_request)
        try:
            return schema.model_validate_json(response.content)
        except Exception as e:
            raise ModelProviderError(
                f"Failed to parse structured response into {schema.__name__}: {e}"
            ) from e

    async def stream_chat(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream text chunks from a chat completion request."""
        payload = self._build_payload(request, stream=True)

        if self._client.is_closed:
            raise ModelProviderError("HTTP client is closed.")

        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise ModelProviderError(
                        f"HTTP {resp.status_code} from {self.provider_name}: {body.decode()[:500]}"
                    )
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPError as e:
            raise ModelProviderError(f"Stream request failed: {e}") from e

    # ── Internal ──────────────────────────────────────────────────

    def _build_payload(self, request: LLMRequest, stream: bool) -> dict[str, Any]:
        """Build the JSON payload for the API call."""
        msgs = []
        for m in request.messages:
            msg: dict[str, Any] = {"role": m.role.value, "content": m.content}
            if m.name:
                msg["name"] = m.name
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]
            msgs.append(msg)

        payload: dict[str, Any] = {
            "model": request.model or self._config.model,
            "messages": msgs,
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = request.tools
        if request.tool_choice:
            payload["tool_choice"] = request.tool_choice
        if request.response_format:
            payload["response_format"] = request.response_format
        return payload

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _send_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a POST request with retry on transient errors."""
        if self._client.is_closed:
            raise ModelProviderError("HTTP client is closed.")

        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as e:
            raise ModelProviderError(f"Request to {self.provider_name} failed: {e}") from e

        if response.status_code == 401 or response.status_code == 403:
            raise ModelProviderError(
                f"Authentication failed for {self.provider_name}. "
                f"Check your {self._config.api_key_env} environment variable."
            )
        if response.status_code != 200:
            raise ModelProviderError(
                f"HTTP {response.status_code} from {self.provider_name}: "
                f"{response.text[:500]}"
            )
        return response.json()

    def _parse_response(self, raw: dict[str, Any]) -> LLMResponse:
        """Parse the raw API response into a standardized LLMResponse."""
        try:
            choice = raw.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content") or ""
            finish_reason = choice.get("finish_reason")

            # Parse tool calls
            tool_calls: list[ToolCall] | None = None
            raw_tool_calls = message.get("tool_calls")
            if raw_tool_calls:
                tool_calls = []
                for tc in raw_tool_calls:
                    func = tc.get("function", {})
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append(
                        ToolCall(
                            id=tc.get("id", ""),
                            name=func.get("name", ""),
                            arguments=args,
                            raw=func.get("arguments", "{}"),
                        )
                    )

            usage = raw.get("usage", {})

            # DeepSeek reasoning_content
            reasoning = message.get("reasoning_content") or raw.get("reasoning_content")

            return LLMResponse(
                content=content,
                model=raw.get("model", self._config.model),
                provider=self.provider_name,
                tool_calls=tool_calls,
                raw=raw,
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                finish_reason=finish_reason,
                reasoning_content=reasoning,
            )
        except Exception as e:
            raise ModelProviderError(
                f"Failed to parse response from {self.provider_name}: {e}"
            ) from e

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
