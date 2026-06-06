"""CostTracker — track token usage and compute cost per model."""

from dataclasses import dataclass, field

# Default pricing per 1k tokens (USD). Update as vendor pricing changes.
# ``cache_hit`` is the (cheaper) price for prompt tokens served from the
# provider's context cache; when absent it falls back to the ``input`` price.
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat":     {"input": 0.00027, "output": 0.0011, "cache_hit": 0.00007},
    "deepseek-reasoner": {"input": 0.00055, "output": 0.00219, "cache_hit": 0.00014},
    # deepseek v4 family (approximate; update with official vendor pricing).
    "deepseek-v4-flash": {"input": 0.00027, "output": 0.0011, "cache_hit": 0.00007},
    "deepseek-v4":       {"input": 0.00027, "output": 0.0011, "cache_hit": 0.00007},
    "gpt-4o":            {"input": 0.005,   "output": 0.015},
    "gpt-4o-mini":       {"input": 0.00015, "output": 0.0006},
}


@dataclass
class CostSnapshot:
    """Accumulated token usage and cost for a single run."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    cache_savings_usd: float = 0.0
    cost_usd: float = 0.0
    calls: int = 0
    by_model: dict[str, dict] = field(default_factory=dict)

    def add_call(self, model: str, prompt_tokens: int = 0, completion_tokens: int = 0,
                 input_price: float = 0.0, output_price: float = 0.0,
                 cached_tokens: int = 0, cache_hit_price: float = 0.0) -> None:
        """Record one LLM call and compute its cost.

        If prices are 0, falls back to DEFAULT_PRICING for known models.
        ``cached_tokens`` are prompt tokens served from the provider's prompt
        cache (a subset of ``prompt_tokens``); they are billed at the cheaper
        ``cache_hit_price`` and the savings versus the full input price are
        tracked separately.
        """
        if input_price == 0.0 and output_price == 0.0:
            defaults = DEFAULT_PRICING.get(model, {})
            input_price = defaults.get("input", 0.0)
            output_price = defaults.get("output", 0.0)
            if cache_hit_price == 0.0:
                cache_hit_price = defaults.get("cache_hit", input_price)

        cached = max(0, min(cached_tokens, prompt_tokens))
        uncached = prompt_tokens - cached
        call_cost = (
            (uncached / 1000) * input_price
            + (cached / 1000) * cache_hit_price
            + (completion_tokens / 1000) * output_price
        )
        # Savings = what the cached tokens would have cost at the full price.
        call_savings = (cached / 1000) * (input_price - cache_hit_price)

        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += prompt_tokens + completion_tokens
        self.cached_tokens += cached
        self.cache_savings_usd += call_savings
        self.cost_usd += call_cost
        self.calls += 1

        if model not in self.by_model:
            self.by_model[model] = {"prompt_tokens": 0, "completion_tokens": 0,
                                    "cached_tokens": 0, "cost_usd": 0.0, "calls": 0}
        self.by_model[model]["prompt_tokens"] += prompt_tokens
        self.by_model[model]["completion_tokens"] += completion_tokens
        self.by_model[model]["cached_tokens"] += cached
        self.by_model[model]["cost_usd"] += call_cost
        self.by_model[model]["calls"] += 1

    def summary(self) -> dict:
        """Return a summary dict for inclusion in AgentResult.metadata."""
        return {
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_savings_usd": round(self.cache_savings_usd, 6),
            "cost_usd": round(self.cost_usd, 6),
            "calls": self.calls,
            "by_model": {
                m: {"prompt": d["prompt_tokens"], "completion": d["completion_tokens"],
                    "cached": d.get("cached_tokens", 0),
                    "cost_usd": round(d["cost_usd"], 6), "calls": d["calls"]}
                for m, d in self.by_model.items()
            },
        }
