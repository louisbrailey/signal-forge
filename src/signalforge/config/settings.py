"""Process/environment settings, loaded from ``.env`` / environment only.

All credentials are ``SecretStr`` so they are redacted from logs and ``repr``.
They are never written to the database or to git.
"""

from __future__ import annotations

import secrets
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from signalforge.config import paths
from signalforge.config.research import ResearchConfig


class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


LOCAL_LLM_PROVIDERS = frozenset({"lmstudio", "openai_compat", "openai-compatible"})


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
    # Empty => a SQLite file inside the resolved data dir (keeps checkouts and
    # tests self-contained). Set DATABASE_URL to override (e.g. Postgres).
    database_url: str = ""

    # --- Market data ---
    market_data_provider: str = "fixture"
    market_data_api_key: SecretStr = SecretStr("")
    market_data_provider_secondary: str = ""
    market_data_api_key_secondary: SecretStr = SecretStr("")
    # Minimum seconds between HTTP requests to the market-data provider. Default
    # is the Massive Basic 5-req/min pace; lower it for a higher-tier plan.
    market_data_min_request_spacing_s: float = 12.1

    # --- Options data (education / simulation only; read-only) ---
    # Reuses market_data_api_key unless a distinct key is set here. No provider
    # string toggles execution — there is no options execution path.
    options_provider: str = ""
    options_api_key: SecretStr = SecretStr("")
    # Minimum seconds between HTTP requests to the OPTIONS provider. ``None``
    # (the default) inherits ``market_data_min_request_spacing_s`` — options
    # traffic shares the equities key unless ``options_api_key`` is set, so it
    # shares that account's rate budget too. Set it only when the options
    # entitlement's own rate limit is known (D1 §7.5 / OQ-2); a literal is
    # never hard-coded in the adapter.
    options_min_request_spacing_s: float | None = None

    # --- Forex daily bars (Massive Currencies; research data only) ---
    # OFF by default. Lives here, not on ResearchConfig, for the same reason as
    # the worker policy below: it shapes no signal and must not move
    # ``full_config_hash``. No strategy, scan, alert or paper path reads FX
    # bars. Env: FOREX_INGEST_ENABLED, FOREX_PAIRS, FOREX_LOOKBACK_DAYS.
    forex_ingest_enabled: bool = False
    forex_pairs: str = "EURUSD,USDJPY,GBPUSD,AUDUSD,USDCAD,USDCHF,NZDUSD,XAUUSD"
    forex_lookback_days: int = Field(default=730, gt=0, le=3650)
    # Crypto daily bars from the same Currencies plan. OFF by default.
    # Env: CRYPTO_INGEST_ENABLED, CRYPTO_PAIRS, CRYPTO_LOOKBACK_DAYS.
    crypto_ingest_enabled: bool = False
    crypto_pairs: str = "BTCUSD,ETHUSD,SOLUSD"
    crypto_lookback_days: int = Field(default=730, gt=0, le=3650)

    # --- News ---
    news_provider: str = ""
    news_api_key: SecretStr = SecretStr("")

    # --- Discord (incoming webhook only; never a bot token, never OAuth) ---
    discord_webhook_url: SecretStr = SecretStr("")

    # --- LLM (optional; never on the decision path) ---
    llm_provider: str = ""  # "anthropic" | "lmstudio" | "openai_compat"
    llm_api_key: SecretStr = SecretStr("")  # not needed for a local LM Studio server
    llm_model: str = "claude-sonnet-5"
    llm_base_url: str = "http://127.0.0.1:1234/v1"  # OpenAI-compatible local server (LM Studio)
    llm_reasoning_effort: str = "none"  # local reasoning models: keep hidden reasoning OFF
    llm_timeout_s: float = 120.0

    # --- Notifications (Phase 1: all off until setup complete) ---
    notification_provider: str = ""
    notification_api_key: SecretStr = SecretStr("")
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_to: str = ""

    # --- Worker operating policy (2026-10-04) ---
    # These live HERE, on the process settings, and deliberately NOT on
    # ``ResearchConfig``: they shape no signal, and a field on ResearchConfig
    # moves ``full_config_hash`` (and, if it were ever listed in
    # ``SCOPE_HASH_FIELDS``, ``config_hash`` — un-scoping every live
    # PAPER_APPROVED approval). Env: EOD_INGEST_DEADLINE_MINUTES,
    # CATCH_UP_LOOKBACK_SESSIONS, EOD_GAP_GRACE_MINUTES.
    #
    # Overall wall-clock budget for the daily-bar ingest while the EOD lock is
    # held. Checked BETWEEN symbols only (never mid-transaction); on expiry the
    # run is recorded ``stopped`` with its completed symbols and resumed by the
    # next catch-up. A normal ~175-symbol pass at the 12.1 s Basic pace is
    # ~35 min, so 45 is conservative headroom, not a tight bound.
    eod_ingest_deadline_minutes: float = Field(default=45.0, gt=0)
    # How many completed XNYS sessions before the latest one the catch-up will
    # look back over for sessions that never got an approved-scope scan.
    catch_up_lookback_sessions: int = Field(default=10, ge=0, le=60)
    # /ops and the health check flag the last completed session as a GAP when
    # no successful EOD job run exists this long after its 17:30 ET cutoff.
    eod_gap_grace_minutes: float = Field(default=120.0, ge=0)

    # --- Research config (versioned; hashed onto every run) ---
    research: ResearchConfig = Field(default_factory=ResearchConfig)

    @field_validator("app_allowed_hosts")
    @classmethod
    def _non_empty_hosts(cls, v: str) -> str:
        if not [h.strip() for h in v.split(",") if h.strip()]:
            raise ValueError("app_allowed_hosts must contain at least one host")
        return v

    @model_validator(mode="after")
    def _default_database_url(self) -> Settings:
        if not self.database_url:
            db_path = paths.data_dir() / "signalforge.sqlite"
            self.database_url = f"sqlite+pysqlite:///{db_path}"
        return self

    @property
    def allowed_hosts(self) -> list[str]:
        return [h.strip() for h in self.app_allowed_hosts.split(",") if h.strip()]

    @property
    def is_loopback_only(self) -> bool:
        return self.app_host in {"127.0.0.1", "localhost", "::1"}

    @property
    def llm_enabled(self) -> bool:
        provider = self.llm_provider.strip().lower()
        if provider in LOCAL_LLM_PROVIDERS:
            return True  # a local OpenAI-compatible server needs no key
        return bool(provider) and bool(self.llm_api_key.get_secret_value())

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
