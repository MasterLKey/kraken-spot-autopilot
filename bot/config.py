from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_mode: Literal["paper", "live"] = "paper"
    strategy: Literal["dca", "grid", "both"] = "dca"

    kraken_api_key: str = ""
    kraken_api_secret: str = ""

    symbol: str = "BTC/USD"

    dca_quote_amount: float = 15.0
    dca_interval_seconds: int = 86_400
    dca_dip_pct: float = 0.0
    dca_enabled: bool = True

    grid_enabled: bool = False
    grid_lower_price: float = 0.0
    grid_upper_price: float = 0.0
    grid_levels: int = 8
    grid_quote_per_level: float = 20.0
    grid_base_reserve: float = 0.0

    max_daily_loss_quote: float = 50.0
    max_position_quote: float = 500.0
    max_order_quote: float = 50.0
    kill_switch_file: Path = Path("data/KILL")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    poll_interval_seconds: int = 30
    data_dir: Path = Path("data")
    log_level: str = "INFO"
    fee_rate: float = Field(default=0.0026, description="Assumed taker fee for paper/backtest")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper().replace("-", "/")

    @property
    def is_paper(self) -> bool:
        return self.bot_mode == "paper"

    @property
    def is_live(self) -> bool:
        return self.bot_mode == "live"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "exports").mkdir(parents=True, exist_ok=True)
        self.kill_switch_file.parent.mkdir(parents=True, exist_ok=True)

    def db_path(self) -> Path:
        return self.data_dir / "journal.sqlite3"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
