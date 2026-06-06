"""DeepSeekProvider — DeepSeek-specific provider with sensible defaults."""

from evoagent.models.openai_compatible import OpenAICompatibleProvider
from evoagent.models.schema import ModelConfig


class DeepSeekProvider(OpenAICompatibleProvider):
    """Provider for DeepSeek's OpenAI-compatible API.

    Sets DeepSeek defaults automatically:
    - base_url: https://api.deepseek.com/v1
    - api_key_env: DEEPSEEK_API_KEY
    - model: deepseek-chat

    Also supports deepseek-reasoner for reasoning-heavy tasks.
    """

    DEEPSEEK_DEFAULTS = ModelConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        temperature=0.0,
        max_tokens=4096,
        timeout=60,
        max_retries=3,
    )

    def __init__(self, config: ModelConfig | None = None):
        """Initialize with optional config override.

        Args:
            config: Config overrides. Merged onto DeepSeek defaults.
        """
        merged = self.DEEPSEEK_DEFAULTS.model_copy()
        if config:
            for field_name in config.__class__.model_fields:
                value = getattr(config, field_name)
                if value is not None:
                    setattr(merged, field_name, value)
        super().__init__(merged)
