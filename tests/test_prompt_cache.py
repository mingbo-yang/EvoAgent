"""Tests for P2 prompt-cache accounting."""

import pytest

from evoagent.core.cost import CostSnapshot
from evoagent.models.openai_compatible import OpenAICompatibleProvider
from evoagent.models.schema import ModelConfig


def test_add_call_prices_cached_tokens_cheaper():
    cost = CostSnapshot()
    cost.add_call("deepseek-chat", prompt_tokens=1000, completion_tokens=500,
                  cached_tokens=800)
    # uncached 200 @0.00027/1k + cached 800 @0.00007/1k + 500 out @0.0011/1k
    expected = (0.2 * 0.00027) + (0.8 * 0.00007) + (0.5 * 0.0011)
    assert cost.cost_usd == pytest.approx(expected)
    assert cost.cached_tokens == 800
    # savings = cached * (input - cache_hit)
    assert cost.cache_savings_usd == pytest.approx(0.8 * (0.00027 - 0.00007))


def test_add_call_without_cache_matches_full_price():
    cost = CostSnapshot()
    cost.add_call("deepseek-chat", prompt_tokens=1000, completion_tokens=0)
    assert cost.cost_usd == pytest.approx(0.00027)
    assert cost.cached_tokens == 0
    assert cost.cache_savings_usd == 0.0


def test_cached_tokens_capped_at_prompt_tokens():
    cost = CostSnapshot()
    cost.add_call("deepseek-chat", prompt_tokens=100, completion_tokens=0,
                  cached_tokens=999)
    assert cost.cached_tokens == 100  # capped


def test_summary_exposes_cache_fields():
    cost = CostSnapshot()
    cost.add_call("deepseek-chat", prompt_tokens=500, completion_tokens=100,
                  cached_tokens=400)
    s = cost.summary()
    assert s["cached_tokens"] == 400
    assert "cache_savings_usd" in s
    assert s["by_model"]["deepseek-chat"]["cached"] == 400


def test_parse_response_surfaces_cache_tokens(monkeypatch):
    monkeypatch.setenv("DUMMY_KEY", "x")
    cfg = ModelConfig(provider="deepseek", base_url="https://api.example/v1",
                      api_key_env="DUMMY_KEY")
    provider = OpenAICompatibleProvider(cfg)
    raw = {
        "model": "deepseek-chat",
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
            "prompt_cache_hit_tokens": 64, "prompt_cache_miss_tokens": 36,
        },
    }
    resp = provider._parse_response(raw)
    assert resp.usage["prompt_cache_hit_tokens"] == 64
    assert resp.usage["prompt_cache_miss_tokens"] == 36


@pytest.mark.asyncio
async def test_engine_track_cost_uses_cache(monkeypatch, tmp_path):
    from evoagent.core.react import ReActEngine

    engine = ReActEngine(model_router=object(), tool_registry=object())

    class _Resp:
        model = "deepseek-chat"
        usage = {"prompt_tokens": 1000, "completion_tokens": 0,
                 "prompt_cache_hit_tokens": 1000}

    engine._track_cost(_Resp())
    assert engine.cost.cached_tokens == 1000
    # All prompt tokens cached → cost is the cheap cache_hit price only.
    assert engine.cost.cost_usd == pytest.approx(1.0 * 0.00007)
