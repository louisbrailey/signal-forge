"""Typed configuration: environment settings, research config, config hashing.

``Settings`` holds process/environment configuration (paths, keys, bind address).
``ResearchConfig`` holds the version-controlled knobs that affect *what the
research engine decides* (§9 of ARCHITECTURE.md). Its stable hash
(``ResearchConfig.config_hash``) is recorded on every scan and backtest run so
results are reproducible.
"""

from __future__ import annotations

from signalforge.config.hashing import config_hash
from signalforge.config.research import ResearchConfig
from signalforge.config.settings import Settings, get_settings

__all__ = ["ResearchConfig", "Settings", "config_hash", "get_settings"]
