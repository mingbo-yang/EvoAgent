"""ModelRegistry — canonical model IDs, aliases, and capability lookup."""

from typing import Any

from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    input_per_1k: float = 0.0
    output_per_1k: float = 0.0
    cached_input_per_1k: float = 0.0


class ModelDefinition(BaseModel):
    provider: str
    model_id: str
    display_name: str = ""
    canonical_id: str = ""  # f"{provider}/{model_id}"
    aliases: list[str] = Field(default_factory=list)
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_json: bool = True
    supports_thinking: bool = False
    supports_vision: bool = False
    pricing: ModelPricing | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any = None) -> None:
        if not self.canonical_id:
            self.canonical_id = f"{self.provider}/{self.model_id}"
        if not self.display_name:
            self.display_name = self.canonical_id


class ModelRegistry:
    """Registry of known models with alias resolution."""

    def __init__(self):
        self._models: dict[str, ModelDefinition] = {}
        self._aliases: dict[str, str] = {}  # alias → canonical_id
        self._recent: list[str] = []
        self._favorites: set[str] = set()

        # Default aliases for convenience
        self._aliases["pro"] = "deepseek/deepseek-chat"
        self._aliases["fast"] = "deepseek/deepseek-chat"

    def register(self, model: ModelDefinition) -> None:
        self._models[model.canonical_id] = model

    def get(self, canonical_id: str) -> ModelDefinition | None:
        return self._models.get(canonical_id)

    def resolve(self, name: str) -> str | None:
        """Resolve a name that could be alias or canonical id."""
        if name in self._aliases:
            return self._aliases[name]
        if "/" in name and name in self._models:
            return name
        if "/" in name:
            self._models[name] = ModelDefinition(
                provider=name.split("/")[0], model_id=name.split("/")[1],
                canonical_id=name,
            )
            return name
        return None

    def add_alias(self, alias: str, canonical_id: str) -> str | None:
        if alias in self._aliases:
            return None  # collision
        self._aliases[alias] = canonical_id
        return canonical_id

    def remove_alias(self, alias: str) -> bool:
        if alias in self._aliases:
            del self._aliases[alias]
            return True
        return False

    def list_by_provider(self, provider: str) -> list[ModelDefinition]:
        return [m for m in self._models.values() if m.provider == provider]

    def list_all(self) -> list[ModelDefinition]:
        return sorted(self._models.values(), key=lambda m: m.canonical_id)

    def refresh(self) -> None:
        """Refresh cached model metadata.

        This is a placeholder for provider-driven model discovery. When no
        discovery backend is configured, the method is a no-op.
        """
        return None

    def mark_recent(self, canonical_id: str) -> None:
        if canonical_id in self._recent:
            self._recent.remove(canonical_id)
        self._recent.insert(0, canonical_id)
        self._recent = self._recent[:10]

    def get_recent(self) -> list[str]:
        return list(self._recent)

    def add_favorite(self, canonical_id: str) -> None:
        self._favorites.add(canonical_id)

    def remove_favorite(self, canonical_id: str) -> None:
        self._favorites.discard(canonical_id)

    def get_aliases(self) -> dict[str, str]:
        return dict(self._aliases)
