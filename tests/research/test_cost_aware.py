from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import EntryProposal, EntryVerdict
from signalforge.research.cost_aware import (
    EdgeModel,
    TrainingTrade,
    admit,
    fit_edge,
    training_trades,
)
from tests.backtest.test_funded import bars, run


def samples():
    return tuple(
        TrainingTrade(
            f"ETF{i}",
            date(y, m, 1),
            date(y, m, 20),
            0.03 + i * 0.001,
            "bull" if m % 2 else "neutral",
        )
        for y in (2018, 2019)
        for m in range(1, 13)
        for i in range(5)
    )


def proposal(shares=4):
    return EntryProposal(
        "ETF",
        date(2021, 1, 5),
        date(2021, 1, 4),
        shares,
        Decimal(100) * shares,
        Decimal(2),
        Decimal(100),
    )


def test_deterministic_month_block_estimate_and_future_poison_excluded():
    cutoff = date(2020, 12, 31)
    model = fit_edge(samples(), cutoff)
    assert model.status == "ESTIMATED"
    assert model.count == 120 and model.months == 24
    poison = TrainingTrade("FUTURE", date(2022, 1, 1), date(2022, 1, 3), float("nan"), "bear")
    assert fit_edge((*samples(), poison), cutoff) == model
    assert fit_edge(tuple(reversed(samples())), cutoff) == model
    assert admit(model, proposal()).accepted


def test_missing_history_or_regime_diversity_fails_closed():
    cutoff = date(2020, 12, 31)
    for observations in ((), samples()[:99], tuple(replace(s, regime="bull") for s in samples())):
        model = fit_edge(observations, cutoff)
        assert model.status == "INSUFFICIENT_EVIDENCE"
        assert not admit(model, proposal()).accepted


def test_commission_floor_uses_actual_lot_and_stress_floor():
    model = EdgeModel(
        date(2020, 12, 31), 120, 24, {"bull": 60, "neutral": 60}, 0.02, "ESTIMATED", "test"
    )
    small = admit(model, proposal(1))
    larger = admit(model, proposal(4))
    assert not small.accepted and larger.accepted
    assert Decimal(small.evidence["estimated_round_trip_cost_usd"]) >= Decimal("2.30")
    assert Decimal(larger.evidence["estimated_round_trip_cost_usd"]) >= Decimal("3.20")


def test_future_fit_cannot_be_used_for_old_signal():
    model = fit_edge(samples(), date(2021, 1, 4))
    with pytest.raises(ValueError, match="precede"):
        admit(model, proposal())


def test_negative_estimate_rejects_even_large_lot():
    model = fit_edge(tuple(replace(s, gross_return=-0.01) for s in samples()), date(2020, 12, 31))
    assert model.status == "NONPOSITIVE_EDGE"
    assert not admit(model, proposal(100)).accepted


def test_veto_has_no_fills_or_costs_and_cannot_resize():
    seen = []

    def reject(p):
        seen.append(p)
        return EntryVerdict(False, "estimated_edge_does_not_cover_costs", {"shares": p.shares})

    result = run({"A": bars()}, entry_admission=reject)
    assert not result.fills and result.costs == 0
    assert result.marks[-1]["cash_usd"] == "10000.00"
    assert seen and seen[0].signal_day < seen[0].day
    assert not hasattr(seen[0], "close") and not hasattr(seen[0], "high")
    assert result.decisions[0]["reason"] == "estimated_edge_does_not_cover_costs"


def test_accepting_hook_preserves_default_fills_and_cash():
    normal = run({"A": bars()})
    hooked = run({"A": bars()}, entry_admission=lambda p: EntryVerdict(True, "ok", {}))
    assert normal == hooked
    assert sum(Decimal(f["modeled_cost_usd"]) for f in normal.fills) == normal.costs


def test_prior_risk_rejection_cannot_be_overridden():
    from signalforge.config.research import RiskLimits

    def forbidden(p):
        raise AssertionError("Should not reach entry policy after risk rejection")

    result = run(
        {"A": bars()}, limits=RiskLimits(per_trade_risk_pct=0.001), entry_admission=forbidden
    )
    assert not result.fills


def test_training_omits_terminal_exit_and_uses_only_closed_outcomes():
    b = bars()
    r = run({"A": b}, cost_model=CostModel(commission_min_per_order=1))
    regimes = dict.fromkeys(b.dates, "bull")
    assert training_trades(r, regimes, b.dates[-1]) == ()
    r.fills[-1]["reason"] = "time_stop"
    assert training_trades(r, regimes, b.dates[1]) == ()
    (label,) = training_trades(r, regimes, b.dates[-1])
    assert label.gross_return == pytest.approx(0, abs=1e-9)


def test_known_nonfinite_label_rejected():
    bad = replace(samples()[0], gross_return=float("inf"))
    with pytest.raises(ValueError):
        fit_edge((bad,), date(2020, 12, 31))
