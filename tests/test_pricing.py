import pytest
from datetime import UTC, datetime

from novel_memory_agent.models import LLMUsage
from novel_memory_agent.pricing import estimate_chinese_tokens, estimate_cny, pricing_period_at


def test_flash_peak_price_calculation() -> None:
    usage = LLMUsage(
        prompt_tokens=1_000_000,
        cache_hit_tokens=200_000,
        cache_miss_tokens=800_000,
        completion_tokens=100_000,
    )
    cost = estimate_cny("deepseek-v4-flash", usage, exchange_rate=7.2, period="peak")
    expected_usd = 0.2 * 0.014 + 0.8 * 0.44 + 0.1 * 1.32
    assert cost == pytest.approx(expected_usd * 7.2)


def test_chinese_token_estimate() -> None:
    assert estimate_chinese_tokens("你" * 1000) == 600


def test_pricing_period_uses_utc_weekday_windows() -> None:
    assert pricing_period_at(datetime(2026, 9, 2, 2, tzinfo=UTC)) == "peak"
    assert pricing_period_at(datetime(2026, 9, 2, 5, tzinfo=UTC)) == "off_peak"
    assert pricing_period_at(datetime(2026, 9, 5, 2, tzinfo=UTC)) == "off_peak"


def test_auto_period_applies_half_price_off_peak() -> None:
    usage = LLMUsage(prompt_tokens=1_000_000, cache_miss_tokens=1_000_000)
    peak = estimate_cny("deepseek-v4-flash", usage, period="peak")
    off_peak = estimate_cny(
        "deepseek-v4-flash",
        usage,
        period="auto",
        at_utc=datetime(2026, 9, 2, 5, tzinfo=UTC),
    )
    assert off_peak == pytest.approx(peak / 2)
