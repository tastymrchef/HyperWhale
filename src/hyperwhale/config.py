"""Configuration management using pydantic-settings."""

from pydantic_settings import BaseSettings
from pydantic import Field

from hyperwhale.constants import (
    DEFAULT_ANOMALY_SIGMA,
    DEFAULT_CORRELATION_THRESHOLD,
    DEFAULT_MIN_POSITION_CHANGE_PCT,
    DEFAULT_POLL_INTERVAL_OTHER,
    DEFAULT_POLL_INTERVAL_TOP,
)


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- Database ---
    database_url: str = "sqlite:///data/hyperwhale.db"

    # --- Polling ---
    poll_interval_top_whales: int = DEFAULT_POLL_INTERVAL_TOP
    poll_interval_other_whales: int = DEFAULT_POLL_INTERVAL_OTHER

    # --- Thresholds ---
    min_position_change_pct: float = DEFAULT_MIN_POSITION_CHANGE_PCT
    anomaly_sigma_threshold: float = DEFAULT_ANOMALY_SIGMA
    correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD

    # --- Logging ---
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton — import this everywhere
settings = Settings()
