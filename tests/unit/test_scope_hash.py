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
        # `intraday` is an OPERATING policy: whether intraday candidates are
        # scanned on an approved dataset, scheduled and alerted on. It changes
        # no rule, threshold, universe or cost, so the same strategy on the
        # same dataset produces the same signals either way. The signal-shaping
        # intraday settings — `intraday_bar_size`, `enabled_horizons` — are
        # hashed and stay hashed. Hashing this section would also have moved
        # config_hash the moment it appeared and put both live PAPER_APPROVED
        # approvals out of scope for nothing.
        "intraday",
        # The mechanical grid is not a registered, promotion-gated strategy: it
        # produces no candidate and can never be approved, so its parameters
        # must not appear in — or be able to change — an approval scope hash.
        "grid",
        # `execution` decides only whether an already-gated decision may be
        # SUBMITTED to a broker's paper endpoint — never which signals exist.
        # The same strategy on the same dataset produces identical candidates
        # with execution enabled or disabled, and hashing it would have moved
        # config_hash the moment the section appeared, putting both live
        # PAPER_APPROVED approvals out of scope for nothing (D6 ADR §2).
        "execution",
    }


def test_the_intraday_operating_flag_does_not_move_the_scope_hash() -> None:
    base = ResearchConfig()
    on = base.model_copy(
        update={"intraday": base.intraday.model_copy(update={"operating_enabled": True})}
    )
    assert on.config_hash == base.config_hash  # not a signal-shaping change
    assert on.full_config_hash != base.full_config_hash  # but still audited


def test_grid_settings_can_never_change_the_approval_scope_hash() -> None:
    from signalforge.config.research import GridConfig

    base = ResearchConfig()
    grid_on = ResearchConfig(
        grid=GridConfig(enabled=True, per_symbol_cap=5.0, universe_size=1_000, buy_usd=1.0)
    )
    assert base.config_hash == grid_on.config_hash
    assert base.full_config_hash != grid_on.full_config_hash
