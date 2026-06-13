"""Application settings loaded from environment variables / .env file.

Uses pydantic-settings so values can come from the process environment or a
local ``.env`` file (see ``.env.example``). Postgres is the primary database
(``.env.example`` ships a Postgres DSN); if ``DATABASE_URL`` is left unset the
app falls back to a local SQLite file so the CLI and quick local dev work with
zero infrastructure.
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
    # Postgres is the primary backend (set DATABASE_URL via .env, e.g.
    # postgresql+psycopg://user:pass@db:5432/lumora). When DATABASE_URL is
    # unset we fall back to a local SQLite file for CLI / quick local dev.
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
    # Cost-efficient defaults: gpt-4o-mini for answer capture, Haiku-class
    # (cheapest current Claude) for the LLM-as-judge scoring pass.
    default_provider_model: str = "gpt-4o-mini"
    default_judge_model: str = "claude-haiku-4-5-20251001"

    # --- Snapshot capture --------------------------------------------------
    # Models queried on every snapshot, one per provider, as a comma-separated
    # list. Providers without a configured API key are skipped at run time.
    snapshot_models: str = "gpt-4o-mini,claude-haiku-4-5-20251001,gemini-2.0-flash"
    # Variance passes per prompt per provider. AI answers are non-deterministic,
    # so each prompt is asked N times and mention rate is reported as a fraction.
    runs_per_prompt: int = 3

    @property
    def snapshot_model_list(self) -> list[str]:
        """Parsed, de-duplicated list of snapshot capture models."""

        seen: list[str] = []
        for raw in self.snapshot_models.split(","):
            model = raw.strip()
            if model and model not in seen:
                seen.append(model)
        return seen


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""

    return Settings()


settings = get_settings()
