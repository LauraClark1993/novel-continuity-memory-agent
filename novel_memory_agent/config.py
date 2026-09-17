from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    database_path: Path = Path("data/novel_memory.db")
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    default_model: str = "deepseek-v4-flash"
    budget_stop_cny: float = 150.0
    exchange_rate_cny_per_usd: float = 7.2
    pricing_period: str = "auto"
    request_timeout_seconds: int = 240
    max_context_tokens: int = 18_000

    @classmethod
    def from_env(cls, database_path: str | Path | None = None) -> "Settings":
        return cls(
            database_path=Path(
                database_path or os.getenv("NOVEL_MEMORY_DB", "data/novel_memory.db")
            ),
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            default_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            budget_stop_cny=float(os.getenv("NOVEL_MEMORY_BUDGET_STOP_CNY", "150")),
            exchange_rate_cny_per_usd=float(os.getenv("USD_CNY_RATE", "7.2")),
            pricing_period=os.getenv("DEEPSEEK_PRICING_PERIOD", "auto").lower(),
            request_timeout_seconds=int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "240")),
            max_context_tokens=int(os.getenv("NOVEL_MEMORY_MAX_CONTEXT_TOKENS", "18000")),
        )
