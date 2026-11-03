"""Dollar targets must never manufacture profit or reliable-income evidence."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from signalforge.research.income_targets import IncomeEvidence, assess_income_targets


def _evidence(changes, *, opening=date(2026, 10, 25), flows=None, **overrides):
    flows = flows or [0] * len(changes)
    equity = Decimal(30000)
    rows = []
    for offset, (change, flow) in enumerate(zip(changes, flows, strict=True), 1):
        equity += Decimal(change) + Decimal(flow)
        rows.append(
            {
                "day": (opening + timedelta(days=offset)).isoformat(),
                "net_liquidation_usd": str(equity),
                "external_flow_usd": str(flow),
                "valuation_quality": "complete",
            }
        )
    payload = {
        "data_kind": "fixture",
        "source_reference": "test-only synthetic observations",
        "strategy_version": "test-v1",
        "cost_model_reference": "test costs already deducted",
        "costs_included": True,
        "timezone": "America/New_York",
        "weekend_market_access": False,
        "opening_date": opening.isoformat(),
        "opening_valuation_quality": "complete",
        "opening_equity_usd": "30000.00",
        "through_date": (opening + timedelta(days=max(len(changes), 1))).isoformat(),
        "observations": rows,
        **overrides,
    }
    return IncomeEvidence.model_validate(payload)


def test_complete_week_and_weekend_are_separate_targets():
    result = assess_income_targets(_evidence([1000] * 5 + [200, 200]))
    assert result["weekday_days"]["target_hits"] == 5
    assert result["workweeks"]["target_hits"] == 1
    assert result["weekends"]["target_hits"] == 1
    assert result["full_period_net_pnl_usd"] == "5400.00"
    assert result["cashflow_adjusted_drawdown_usd"] == "0.00"
    assert result["reliability_status"] == "not_established"
    assert result["automatic_trading_authorized"] is False
    assert any("Weekend market access" in text for text in result["limitations"])


def test_weekly_hit_does_not_imply_daily_income():
    result = assess_income_targets(_evidence([0, -1000, 0, 0, 6000, 0, 0]))
    assert result["workweeks"]["target_hits"] == 1
    assert result["weekday_days"]["target_hits"] == 1
    assert result["weekday_days"]["target_misses"] == 4
    assert result["weekends"]["target_hits"] == 0
    assert result["cashflow_adjusted_drawdown_usd"] == "1000.00"
    assert result["cashflow_adjusted_drawdown_pct"] == "3.33"


def test_deposits_are_not_profit_and_withdrawals_are_not_losses():
    result = assess_income_targets(_evidence([0, 0, -100, 200, 0], flows=[10000, -5000, 0, 0, 0]))
    assert result["full_period_net_pnl_usd"] == "100.00"
    assert result["weekday_days"]["target_hits"] == 0
    assert result["cashflow_adjusted_drawdown_usd"] == "100.00"
    assert result["daily_net_pnl_usd"]["2026-10-26"] == "0.00"
    assert result["daily_net_pnl_usd"]["2026-10-27"] == "0.00"


def test_missing_day_does_not_bridge_multiday_profit_or_fill_zero():
    evidence = _evidence([1000] * 7)
    evidence.observations.pop(1)
    result = assess_income_targets(evidence)
    assert result["missing_dates"] == ["2026-10-27"]
    assert result["unassessable_daily_changes"] == ["2026-10-27", "2026-10-28"]
    assert result["full_period_net_pnl_usd"] is None
    assert result["cashflow_adjusted_drawdown_pct"] is None
    assert result["workweeks"]["complete_periods"] == 0
    assert result["workweeks"]["incomplete_period_starts"] == ["2026-10-26"]
    assert result["weekends"]["complete_periods"] == 1


@pytest.mark.parametrize("quality", ["stale", "missing"])
def test_invalid_valuation_invalidates_itself_and_next_day(quality):
    evidence = _evidence([1000] * 5)
    evidence.observations[1].valuation_quality = quality
    result = assess_income_targets(evidence)
    assert result["stale_or_missing_valuation_dates"] == ["2026-10-27"]
    assert result["usable_daily_changes"] == 3
    assert result["workweeks"]["complete_periods"] == 0


def test_stale_opening_valuation_cannot_authorize_first_day_profit():
    result = assess_income_targets(_evidence([1000] * 5, opening_valuation_quality="stale"))
    assert result["unassessable_daily_changes"] == ["2026-10-26"]
    assert result["full_period_net_pnl_usd"] is None


def test_missing_costs_withhold_all_net_target_statistics():
    result = assess_income_targets(_evidence([1000] * 7, costs_included=False))
    assert result["usable_daily_changes"] == 0
    assert result["weekday_days"]["observed_hit_fraction"] is None
    assert result["workweeks"]["complete_periods"] == 0
    assert result["full_period_net_pnl_usd"] is None


def test_partial_boundaries_are_never_full_weeks():
    result = assess_income_targets(_evidence([2000] * 5, opening=date(2026, 10, 27)))
    assert result["workweeks"]["complete_periods"] == 0
    assert result["workweeks"]["boundary_partial_period_starts"] == ["2026-10-26"]
    assert result["weekends"]["complete_periods"] == 1


def test_closed_weekend_zero_marks_are_misses_not_removed_from_denominator():
    result = assess_income_targets(_evidence([1000] * 5 + [0, 0]))
    assert result["weekends"]["target_misses"] == 1
    assert result["weekends"]["zero_pnl_periods"] == 1


def test_empty_panel_cannot_pass():
    result = assess_income_targets(_evidence([]))
    assert result["missing_dates"] == ["2026-10-26"]
    assert result["weekday_days"]["observed_hit_fraction"] is None
    assert result["reliability_status"] == "not_established"


def test_input_order_does_not_change_results():
    evidence = _evidence([1000] * 14)
    expected = assess_income_targets(evidence)
    evidence.observations.reverse()
    assert assess_income_targets(evidence) == expected


@pytest.mark.parametrize("kind", ["fixture", "backtest", "forward_paper"])
def test_even_perfect_observed_results_never_claim_reliability(kind):
    report = assess_income_targets(
        _evidence([1000] * 100, data_kind=kind, weekend_market_access=True)
    )
    assert report["reliability_status"] == "not_established"
    assert report["automatic_trading_authorized"] is False


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "-1", "1.001"])
def test_invalid_money_rejected(value):
    with pytest.raises(ValidationError):
        _evidence([0], opening_equity_usd=value)


def test_duplicate_days_rejected():
    payload = _evidence([0]).model_dump()
    payload["observations"] *= 2
    with pytest.raises(ValidationError, match="duplicate"):
        IncomeEvidence.model_validate(payload)


@pytest.mark.parametrize("day", ["2026-10-25", "2026-10-30"])
def test_outside_window_rejected(day):
    payload = _evidence([0]).model_dump()
    payload["observations"][0]["day"] = day
    with pytest.raises(ValidationError, match="observations must lie"):
        IncomeEvidence.model_validate(payload)


def test_timezone_must_be_explicit_and_valid():
    with pytest.raises(ValidationError, match="IANA timezone"):
        _evidence([0], timezone="local-ish")


def test_year_boundary_and_daylight_savings_do_not_split_calendar_periods():
    year = assess_income_targets(_evidence([1000] * 7, opening=date(2025, 12, 28)))
    assert year["workweeks"]["complete_periods"] == 1
    assert year["weekends"]["complete_periods"] == 1
    dst = assess_income_targets(_evidence([1000] * 7))  # DST ends Nov 1
    assert dst["weekends"]["complete_periods"] == 1


def test_literal_every_calendar_day_target_includes_weekend_misses():
    result = assess_income_targets(_evidence([1000] * 5 + [200, 200]))
    assert result["calendar_days"]["complete_periods"] == 7
    assert result["calendar_days"]["target_hits"] == 5
    assert result["calendar_days"]["target_misses"] == 2
    assert result["weekends"]["target_hits"] == 1


def test_unverified_costs_do_not_mislabel_complete_valuations_as_stale():
    result = assess_income_targets(_evidence([1000] * 7, costs_included=False))
    assert any("Costs are not included" in item for item in result["limitations"])
    assert not any("Incomplete/stale" in item for item in result["limitations"])


def test_cli_is_reproducible_read_only_and_hashes_exact_input(tmp_path):
    import hashlib
    import json
    import subprocess
    import sys
    from pathlib import Path

    evidence = _evidence([1000] * 7)
    source = evidence.model_dump_json().encode()
    path = tmp_path / "evidence.json"
    path.write_bytes(source)
    before = list(tmp_path.iterdir())
    command = [sys.executable, "scripts/income_target_report.py", str(path)]
    first = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    second = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(first.stdout)
    assert result["input_sha256"] == hashlib.sha256(source).hexdigest()
    assert first.stdout == second.stdout
    assert result["reliability_status"] == "not_established"
    assert path.read_bytes() == source
    assert list(tmp_path.iterdir()) == before


def test_missing_flow_cannot_be_silently_assumed_zero():
    payload = _evidence([0]).model_dump()
    del payload["observations"][0]["external_flow_usd"]
    with pytest.raises(ValidationError, match="external_flow_usd"):
        IncomeEvidence.model_validate(payload)
