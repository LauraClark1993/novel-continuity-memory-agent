from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .models import LLMUsage


@dataclass(frozen=True, slots=True)
class ModelPrice:
    cache_hit_usd_per_million: float
    cache_miss_usd_per_million: float
    output_usd_per_million: float


# DeepSeek official peak pricing as of 2026-08-31. Off-peak is half price.
PEAK_PRICES: dict[str, ModelPrice] = {
    "deepseek-v4-flash": ModelPrice(0.014, 0.44, 1.32),
    "deepseek-v4-pro": ModelPrice(0.044, 1.32, 3.96),
    "deepseek-v4-flash-vision-exp": ModelPrice(0.014, 0.44, 1.32),
}


def estimate_cny(
    model: str,
    usage: LLMUsage,
    *,
    exchange_rate: float = 7.2,
    period: str = "auto",
    at_utc: datetime | None = None,
) -> float:
    price = PEAK_PRICES.get(model, PEAK_PRICES["deepseek-v4-flash"])
    resolved_period = pricing_period_at(at_utc) if period.lower() == "auto" else period.lower()
    multiplier = 0.5 if resolved_period == "off_peak" else 1.0
    cache_miss = usage.cache_miss_tokens
    if cache_miss <= 0:
        cache_miss = max(0, usage.prompt_tokens - usage.cache_hit_tokens)
    usd = (
        usage.cache_hit_tokens * price.cache_hit_usd_per_million
        + cache_miss * price.cache_miss_usd_per_million
        + usage.completion_tokens * price.output_usd_per_million
    ) / 1_000_000
    return usd * exchange_rate * multiplier


def pricing_period_at(at_utc: datetime | None = None) -> str:
    """Resolve DeepSeek peak/off-peak pricing from a UTC timestamp."""
    moment = at_utc or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    else:
        moment = moment.astimezone(UTC)
    is_weekday = moment.weekday() < 5
    is_peak_hour = 1 <= moment.hour < 4 or 6 <= moment.hour < 10
    return "peak" if is_weekday and is_peak_hour else "off_peak"


def estimate_chinese_tokens(text: str) -> int:
    """Use DeepSeek's published approximation: one Chinese character ~= 0.6 token."""
    chinese = sum("\u4e00" <= char <= "\u9fff" for char in text)
    non_chinese = len(text) - chinese
    return max(1, round(chinese * 0.6 + non_chinese * 0.3))
