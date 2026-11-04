import importlib
import json
from datetime import date, timedelta

import numpy as np
import pytest

from signalforge.backtest.engine import EntrySignal
from signalforge.backtest.funded import FundedReplay, run_funded_replay
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction


@pytest.fixture
def modules(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "scripts"))
    return importlib.import_module("refinement_rules"), importlib.import_module("refinement_study")


def prices(closes):
    return PriceSeries.from_bars(
        "SPY",
        [
            (date(2024, 1, 1) + timedelta(days=i), c, c + 1, c - 1, c, 1e7)
            for i, c in enumerate(closes)
        ],
    )


def original(_series, _t):
    return EntrySignal(Direction.LONG, 90, 5, target_price=150)


def test_confirmation_reads_previous_prefix_and_consumes_one_session(modules):
    rules, _ = modules
    seen = []

    def base(series, t):
        seen.append((len(series), t))
        return original(series, t)

    fn = rules.refined_signal(base, "mean_reversion.short_swing", {})
    answer = fn(prices([100, 101, 999]), 1)
    assert seen == [(1, 0)]
    assert answer.time_stop_bars == 4
    assert answer.stop_price == 90 and answer.target_price == 150
    assert fn(prices([100, 99]), 1) is None
    assert fn(prices([100, 151]), 1) is None
    assert fn(prices([80, 89]), 1) is None


def test_refinement_does_not_change_when_future_prices_change(modules):
    rules, _ = modules
    for key in [
        "mean_reversion.short_swing",
        "volatility_breakout.short_swing",
        "trend_continuation.medium_swing",
        "relative_strength.medium_swing",
        "high52_breakout.medium_swing",
        "trend_pullback.short_swing",
        "tsmom_etf.position",
        "turn_of_month.short_swing",
    ]:
        history = prices([*np.linspace(95, 105, 220), 106, 1000])
        altered = prices([*np.linspace(95, 105, 220), 106, 1])
        fn = rules.refined_signal(original, key, {history.dates[220]: True})
        assert fn(history, 220) is not None
        assert fn(history, 220) == fn(altered, 220)


def test_missing_market_context_and_unknown_families_fail_closed(modules):
    rules, _ = modules
    assert rules.refined_signal(original, "tsmom_etf.position", {})(prices([100]), 0) is None
    with pytest.raises(ValueError, match="No predeclared"):
        rules.refined_signal(original, "invented", {})


def test_short_and_nonfinite_confirmation_are_refused(modules):
    rules, _ = modules

    def short(*_):
        return EntrySignal(Direction.SHORT, 110, 5, target_price=90)

    assert (
        rules.refined_signal(short, "mean_reversion.short_swing", {})(prices([100, 101]), 1) is None
    )
    assert (
        rules.refined_signal(original, "mean_reversion.short_swing", {})(
            prices([100, float("nan")]), 1
        )
        is None
    )


def test_confirmation_fills_only_after_confirmation_close(modules):
    rules, _ = modules
    days = sessions(date(2024, 1, 2), date(2024, 2, 1))
    series = PriceSeries.from_bars(
        "SPY",
        [
            (d, 102 if i == 3 else 100, 104, 99, 101 if i == 2 else 100, 1e7)
            for i, d in enumerate(days)
        ],
    )

    def base(s, t):
        return original(s, t) if t == 1 else None

    fn = rules.refined_signal(base, "mean_reversion.short_swing", {})
    replay = run_funded_replay(
        {"SPY": series},
        {"SPY": fn},
        {"SPY": "broad"},
        limits=RiskLimits(max_position_concentration_pct=5),
        warmup=0,
    )
    buy = next(f for f in replay.fills if f["side"] == "buy")
    assert buy["signal_day"] == str(days[2])
    assert buy["day"] == str(days[3])
    assert float(buy["price"]) >= 102


def test_bootstrap_rejects_missing_or_future_months_and_is_repeatable(modules):
    rules, _ = modules
    base = {f"{y}-{m:02d}": 0.0 for y in (2021, 2022, 2023) for m in range(1, 13)}
    candidate = dict.fromkeys(base, 0.2)
    result = rules.paired_lower_bound(candidate, base)
    assert result == rules.paired_lower_bound(candidate, base)
    assert result["lower_bound_pp"] == pytest.approx(0.2)
    assert result["comparisons"] == 30
    with pytest.raises(ValueError, match="aligned"):
        rules.paired_lower_bound(candidate | {"2024-01": 99}, base)
    candidate.pop("2022-01")
    with pytest.raises(ValueError, match="aligned"):
        rules.paired_lower_bound(candidate, base)


def test_checkpoint_resumption_detects_corruption_and_wrong_job(modules, tmp_path):
    _, study = modules
    job = ("strategy", "2021", "stress")
    result = dict(zip(("key", "period", "cost_case"), job, strict=True)) | {"value": 1}
    path = tmp_path / "case.json"
    study.save_record(path, job, result)
    assert study.load_record(path, job) == result
    with pytest.raises(ValueError, match="integrity"):
        study.load_record(path, ("other", "2021", "stress"))
    changed = json.loads(path.read_text())
    changed["data"]["value"] = 2
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="integrity"):
        study.load_record(path, job)


def test_no_trade_or_negative_validation_cannot_qualify(modules):
    _, study = modules
    records = {}
    for year in (2021, 2022, 2023):
        for cost in study.CASES:

            def metrics(value, year=year):
                return {
                    "monthly_returns_pct": {f"{year}-{m:02d}": value for m in range(1, 13)},
                    "net_return_pct": value * 12,
                    "closed_trades": 0,
                    "max_drawdown_pct": 0,
                }

            records[("test", str(year), cost)] = {
                "arms": {"baseline": {"metrics": metrics(-1)}, "candidate": {"metrics": metrics(0)}}
            }
    result = study.verdicts(records, ["test"])["test"]
    assert result["status"] == "REJECT_REFINEMENT"
    assert result["promotable"] is False
    assert not result["cost_cases"]["stress"]["gates"]["thirty_trades"]
    records[("test", "2026", "stress")] = {"future": "must not influence selection"}
    assert study.verdicts(records, ["test"])["test"] == result


def test_resume_preserves_disposition_and_refuses_different_result(modules, tmp_path):
    _, study = modules
    path = tmp_path / "disposition.json"
    study.preserve_json(path, {"status": "REJECT_REFINEMENT"})
    before = path.stat().st_mtime_ns
    study.preserve_json(path, {"status": "REJECT_REFINEMENT"})
    assert path.stat().st_mtime_ns == before
    with pytest.raises(ValueError, match="refusing overwrite"):
        study.preserve_json(path, {"status": "PROSPECTIVE_RESEARCH_ONLY"})


def test_extension_veto_and_calendar_trend_condition(modules):
    rules, _ = modules
    extended = prices([100] * 220 + [115])
    assert (
        rules.refined_signal(original, "trend_continuation.short_swing", {})(extended, 220) is None
    )
    declining = prices(np.linspace(115, 100, 221))
    assert rules.refined_signal(original, "turn_of_month.short_swing", {})(declining, 220) is None


def test_annual_diagnostics_exclude_warmup_and_refuse_preperiod_fills(modules):
    _, study = modules
    replay = FundedReplay(
        marks=[{"day": "2020-12-31"}, {"day": "2021-01-04"}],
        decisions=[
            {"day": "2020-12-31", "reason": "warmup"},
            {"day": "2021-01-04", "reason": "eligible"},
        ],
    )
    result = study.period_result(replay, date(2021, 1, 1))
    assert result.decisions == [{"day": "2021-01-04", "reason": "eligible"}]
    assert result.marks == [{"day": "2021-01-04"}]
    assert len(replay.marks) == 2
    replay.fills.append({"day": "2020-12-31"})
    with pytest.raises(ValueError, match="start flat"):
        study.period_result(replay, date(2021, 1, 1))
