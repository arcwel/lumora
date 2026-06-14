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

    # --- Provider request tuning ------------------------------------------
    # Max output tokens per provider request. Reasoning models (e.g.
    # gemini-2.5-flash) spend ~1.5k hidden "thinking" tokens before emitting
    # the visible answer, so a low cap (the old 1024) truncates responses
    # before shops are named. 4096 leaves ample room for thinking + answer.
    default_max_tokens: int = 4096

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
    # NOTE: gemini-2.0-flash was retired by Google (returns 404); use 2.5-flash.
    snapshot_models: str = "gpt-4o-mini,claude-haiku-4-5-20251001,gemini-2.5-flash"
    # Variance passes per prompt per provider. AI answers are non-deterministic,
    # so each prompt is asked N times and mention rate is reported as a fraction.
    runs_per_prompt: int = 3

    # --- Alerting ----------------------------------------------------------
    # After each snapshot run, mention rate is compared against the previous
    # run; an alert fires when it moves by at least ``alert_threshold`` (a
    # fraction, so 0.10 = 10 percentage points). All channels are optional —
    # each is skipped silently when its credentials are unset.
    alert_threshold: float = 0.10
    # Public dashboard base URL (e.g. https://lumora.example.com). When set,
    # alert messages include a deep link to the project's analytics view.
    base_url: str | None = None

    # Slack incoming-webhook URL.
    slack_webhook_url: str | None = None

    # SMTP server + addresses for email alerts.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    alert_email_to: str | None = None
    alert_email_from: str | None = None

    # Telegram bot token + target chat id.
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

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
