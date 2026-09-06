"""DB-backed overlay on the env-provided configuration (ARCHITECTURE.md §9).

Env / ``.env`` provides the base ``ResearchConfig``. The Settings page can store a
partial override dict in the ``research_overrides`` AppSetting; this module
deep-merges it and returns a fresh frozen ``ResearchConfig``. Every override
still flows through the same validation and the same ``config_hash``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.config import ResearchConfig, get_settings
from signalforge.db.models import AppSetting, AppSettingHistory

RESEARCH_OVERRIDES_KEY = "research_overrides"
APP_OVERRIDES_KEY = "app_overrides"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def get_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.scalar(select(AppSetting).where(AppSetting.key == key))
    return row.value_json if row is not None else default


def set_setting(session: Session, key: str, value: Any, *, actor: str = "local-user") -> None:
    row = session.scalar(select(AppSetting).where(AppSetting.key == key))
    old = row.value_json if row is not None else None
    if row is None:
        session.add(AppSetting(key=key, value_json=value, updated_by=actor))
    else:
        row.value_json = value
        row.updated_by = actor
    session.add(
        AppSettingHistory(key=key, old_value_json=old, new_value_json=value, changed_by=actor)
    )
    session.flush()


def effective_research_config(session: Session | None) -> ResearchConfig:
    base = get_settings().research
    if session is None:
        return base
    overrides = get_setting(session, RESEARCH_OVERRIDES_KEY, {}) or {}
    if not overrides:
        return base
    merged = _deep_merge(base.model_dump(mode="json"), overrides)
    return ResearchConfig.model_validate(merged)
