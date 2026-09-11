"""The approval-scope config hash covers only the signal-shaping sections, so an
unrelated config addition can never silently un-scope a live approval."""

from __future__ import annotations

from signalforge.config.research import ResearchConfig


def test_unrelated_sections_do_not_move_the_scope_hash() -> None:
    base = ResearchConfig()
    h = base.config_hash
    variants = [
        base.model_copy(update={"agents": base.agents.model_copy(update={"enabled": True})}),
        base.model_copy(update={"news": base.news.model_copy(update={"poll_enabled": True})}),
        base.model_copy(update={"max_high_priority_alerts_per_day": 5}),
        base.model_copy(
            update={"health_monitor": base.health_monitor.model_copy(update={"downgrade_z": -1.0})}
        ),
    ]
    for v in variants:
        assert v.config_hash == h
        assert v.full_config_hash != base.full_config_hash


def test_signal_shaping_sections_move_the_scope_hash() -> None:
    base = ResearchConfig()
    h = base.config_hash
    assert base.model_copy(update={"slippage_bps": 9.0}).config_hash != h
    assert base.model_copy(update={"allow_short_candidates": True}).config_hash != h
    assert (
        base.model_copy(
            update={"risk": base.risk.model_copy(update={"per_trade_risk_pct": 0.1})}
        ).config_hash
        != h
    )
    assert base.model_copy(update={"watchlist": ("AAPL",)}).config_hash != h


def test_every_scope_field_exists_on_the_model() -> None:
    fields = set(ResearchConfig.model_fields)
    assert set(ResearchConfig.SCOPE_HASH_FIELDS) <= fields
    excluded = fields - set(ResearchConfig.SCOPE_HASH_FIELDS)
    # Documented exclusions and nothing else: adding a new section is a decision.
    assert excluded == {
        "agents",
        "news",
        "options",
        "universe_pipeline",
        "health_monitor",
        "max_high_priority_alerts_per_day",
        "promotion",
    }
