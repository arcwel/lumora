"""Application settings loaded from environment variables / .env file.

Uses pydantic-settings so values can come from the process environment or a
local ``.env`` file (see ``.env.example``). Defaults are tuned for the SQLite
MVP; production deployments override ``DATABASE_URL`` with a Postgres DSN.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---------------------------------------------------------------
    app_name: str = "Lumora"
    environment: str = "development"
    debug: bool = True

    # --- Database ----------------------------------------------------------
    # SQLite for the MVP; swap for a Postgres DSN in production, e.g.
    # postgresql+psycopg://user:pass@db:5432/lumora
    database_url: str = "sqlite:///./lumora.db"

    # --- Scheduler ---------------------------------------------------------
    # Whether APScheduler should start with the app process.
    scheduler_enabled: bool = True
    scheduler_timezone: str = "UTC"

    # --- LLM provider API keys --------------------------------------------
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    perplexity_api_key: str | None = None

    # --- Default models ----------------------------------------------------
    default_provider_model: str = "gpt-4o"
    default_judge_model: str = "claude-sonnet-4-6"


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""

    return Settings()


settings = get_settings()
