"""Process/environment settings, loaded from ``.env`` / environment only.

All credentials are ``SecretStr`` so they are redacted from logs and ``repr``.
They are never written to the database or to git.
"""

from __future__ import annotations

import secrets
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from signalforge.config.research import ResearchConfig


class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: AppEnv = AppEnv.DEV
    app_host: str = "127.0.0.1"
    app_port: int = 8787
    app_allowed_hosts: str = "127.0.0.1,localhost"
    app_encryption_key: SecretStr = SecretStr("")

    # --- Storage ---
    database_url: str = "sqlite+pysqlite:///./data/signalforge.sqlite"

    # --- Market data ---
    market_data_provider: str = "fixture"
    market_data_api_key: SecretStr = SecretStr("")
    market_data_provider_secondary: str = ""
    market_data_api_key_secondary: SecretStr = SecretStr("")

    # --- News ---
    news_provider: str = ""
    news_api_key: SecretStr = SecretStr("")

    # --- LLM (optional; never on the decision path) ---
    llm_provider: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "claude-sonnet-5"

    # --- Notifications (Phase 1: all off until setup complete) ---
    notification_provider: str = ""
    notification_api_key: SecretStr = SecretStr("")
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_to: str = ""

    # --- Research config (versioned; hashed onto every run) ---
    research: ResearchConfig = Field(default_factory=ResearchConfig)

    @field_validator("app_allowed_hosts")
    @classmethod
    def _non_empty_hosts(cls, v: str) -> str:
        if not [h.strip() for h in v.split(",") if h.strip()]:
            raise ValueError("app_allowed_hosts must contain at least one host")
        return v

    @property
    def allowed_hosts(self) -> list[str]:
        return [h.strip() for h in self.app_allowed_hosts.split(",") if h.strip()]

    @property
    def is_loopback_only(self) -> bool:
        return self.app_host in {"127.0.0.1", "localhost", "::1"}

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_provider) and bool(self.llm_api_key.get_secret_value())

    def session_secret(self) -> str:
        """Secret for signing the session cookie.

        Requires ``APP_ENCRYPTION_KEY`` outside dev. In dev, fall back to an
        ephemeral per-process key (sessions do not survive a restart, which is
        fine locally) and let the caller warn.
        """
        key = self.app_encryption_key.get_secret_value()
        if key:
            return key
        if self.app_env is AppEnv.PROD:
            raise RuntimeError("APP_ENCRYPTION_KEY is required when APP_ENV=prod")
        return secrets.token_urlsafe(48)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
