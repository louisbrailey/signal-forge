import importlib.util
import json
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from signalforge.backtest.funded import FundedReplay
from signalforge.data.calendar import sessions

spec = importlib.util.spec_from_file_location(
    "funded_replay_report_cli", Path(__file__).parents[2] / "scripts/funded_replay_report.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

START, END = date(2024, 1, 2), date(2024, 4, 30)


def synthetic_db(path, *, snapshot=None, short=(), dividends=(), splits=()):
    """Synthetic contract data only: never used for performance evidence."""
    days = list(sessions(START, END))
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE dividend_event(symbol TEXT, ex_dividend_date TEXT,
            cash_amount REAL, pay_date TEXT, currency TEXT, source TEXT)""")
        conn.execute("""CREATE TABLE split_event(symbol TEXT, execution_date TEXT,
            split_from REAL, split_to REAL)""")
        conn.executemany(
            "INSERT INTO dividend_event VALUES (?,?,?,?,'USD','massive_options')", dividends
        )
        conn.executemany("INSERT INTO split_event VALUES (?,?,?,?)", splits)
        conn.execute("CREATE TABLE instrument(id INTEGER, symbol TEXT, sector TEXT)")
        conn.execute("""CREATE TABLE ohlcv_daily(instrument_id INTEGER,session_date TEXT,
            open REAL,high REAL,low REAL,close REAL,volume REAL,is_adjusted INTEGER,
            is_simulated INTEGER,quality_flags TEXT,source TEXT,latency_category TEXT)""")
        conn.execute("""CREATE TABLE data_snapshot(id INTEGER, symbols_json TEXT,
            continuity_mapping_id INTEGER, options_scope_json TEXT)""")
        for i, symbol in enumerate(snapshot or ["SPY"], start=1):
            conn.execute("INSERT INTO instrument VALUES (?,?,?)", (i, symbol, "broad_etf"))
            conn.executemany(
                "INSERT INTO ohlcv_daily VALUES (?,?,100,101,99,100,100000,1,0,'[]',"
                "'massive','END_OF_DAY')",
                [(i, str(d)) for d in (days[5:] if symbol in short else days)],
            )
        if snapshot:
            conn.execute(
                "INSERT INTO data_snapshot VALUES (11, ?, NULL, NULL)", (json.dumps(snapshot),)
            )
    return path


def args(*extra):
    return ["db.sqlite", "--symbols", "SPY", "--since", "2016-10-17", *extra]


def test_defaults_match_the_existing_report_configuration():
    a = module.parse_args(args())
    assert a.until == date(2025, 9, 7)
    assert a.strategy == "trend_continuation.short_swing"
    assert a.initial_cash == Decimal("10000")
    assert (a.max_position_pct, a.max_sector_pct, a.cost_case) == (5.0, 20.0, "base")


@pytest.mark.parametrize(
    "extra",
    [
        ["--until", "2025-09-08"],
        ["--until", "2026-11-02"],  # spans the whole sealed year
        ["--until", "2026-01-15"],
    ],
)
def test_cli_refuses_windows_touching_the_sealed_year(extra, capsys):
    with pytest.raises(SystemExit):
        module.parse_args(args(*extra))
    assert "sealed year" in capsys.readouterr().err


def test_window_after_the_sealed_year_is_allowed():
    a = module.parse_args(
        ["db.sqlite", "--symbols", "SPY", "--since", "2026-09-09", "--until", "2026-11-02"]
    )
    assert a.since == date(2026, 9, 9)


@pytest.mark.parametrize(
    "extra",
    [
        ["--strategy", "intraday_orb.intraday"],
        ["--strategy", "nope.medium_swing"],
        ["--strategy", "high52_breakout.medium_swing,high52_breakout.medium_swing"],
        ["--strategy", "high52_breakout.medium_swing,"],
        ["--max-position-pct", "10.5"],
        ["--max-position-pct", "0"],
        ["--max-sector-pct", "25"],
        ["--initial-cash", "-1"],
        ["--initial-cash", "abc"],
        ["--out", "reports/funded/x.md"],
        ["--snapshot-id", "11"],  # mutually exclusive with --symbols
    ],
)
def test_cli_argument_validation(extra):
    with pytest.raises(SystemExit):
        module.parse_args(args(*extra))


def test_cli_accepts_composite_and_paper_maximum_caps():
    a = module.parse_args(
        [
            "db.sqlite",
            "--snapshot-id",
            "11",
            "--since",
            "2016-10-17",
            "--strategy",
            "high52_breakout.medium_swing,trend_continuation.medium_swing",
            "--max-position-pct",
            "10",
            "--initial-cash",
            "25000",
        ]
    )
    assert a.snapshot_id == 11 and a.symbols is None and a.max_position_pct == 10.0
    assert [s.key for s in module.resolve_strategies(a.strategy)] == [
        "high52_breakout.medium_swing",
        "trend_continuation.medium_swing",
    ]


def test_replay_refuses_sealed_window_before_opening_database(tmp_path):
    with pytest.raises(ValueError, match="sealed year"):
        module.replay(tmp_path / "missing.sqlite", ["SPY"], date(2025, 1, 2), date(2025, 9, 8))


def test_snapshot_skips_incomplete_symbols_and_logs_them(tmp_path):
    path = synthetic_db(tmp_path / "s.sqlite", snapshot=["SPY", "AAA", "XLC"], short={"XLC"})
    before = path.read_bytes()
    logged = []
    r = module.replay(
        path,
        None,
        START,
        END,
        snapshot_id=11,
        strategy="high52_breakout.medium_swing,relative_strength.medium_swing",
        initial_cash=Decimal("25000"),
        max_position_pct=10,
        log=logged.append,
    )
    assert path.read_bytes() == before
    assert list(r["run_config"]["skipped_symbols"]) == ["XLC"]
    assert len(logged) == 1 and logged[0].startswith("skipped XLC")
    assert r["run_config"]["symbols_replayed"] == 2 and set(r["sector_snapshot"]) == {"AAA", "SPY"}
    assert r["initial_cash_usd"] == "25000.00"
    assert r["risk_limits"]["max_position_concentration_pct"] == 10.0
    assert r["strategies"] == ["high52_breakout.medium_swing", "relative_strength.medium_swing"]
    assert r["strategy_spec"] is None and set(r["strategy_specs"]) == set(r["strategies"])
    assert list(r["strategy_attribution"]) == r["strategies"]
    assert r["scenario_diagnostics"]["base"]["strategy_attribution"] == r["strategy_attribution"]
    assert r["run_config"]["passive_comparator_caps_pct"] == {
        "position": 5,
        "sector": 20,
        "gross": 60,
    }
    assert any("Passive comparator keeps fixed 5%" in x for x in r["limitations"])


def test_explicit_symbols_still_halt_on_incomplete_bars(tmp_path):
    path = synthetic_db(tmp_path / "s.sqlite", snapshot=["SPY", "XLC"], short={"XLC"})
    with pytest.raises(ValueError, match="XLC: missing or duplicate sessions"):
        module.replay(path, ["XLC"], START, END)


def test_stress_cost_case_is_primary_and_out_writes_json_and_markdown(tmp_path):
    path = synthetic_db(tmp_path / "s.sqlite")
    out = tmp_path / "reports" / "funded" / "run.json"
    assert (
        module.main(
            [
                str(path),
                "--symbols",
                "SPY",
                "--since",
                str(START),
                "--until",
                str(END),
                "--cost-case",
                "higher_cost_stress",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    r = json.loads(out.read_text())
    assert list(r["scenario_diagnostics"]) == ["higher_cost_stress"]
    assert r["spread_bps"] == 10 and r["cost_model"]["slippage_bps"] == 10
    assert r["strategy"] == "trend_continuation.short_swing" and r["strategy_spec"]
    assert not any("Passive comparator" in x for x in r["limitations"])
    md = out.with_suffix(".md").read_text()
    assert "Strategy attribution (higher_cost_stress)" in md
    assert "| trend_continuation.short_swing | 0 | 0 |" in md


def test_strategy_attribution_reconciles_per_strategy():
    result = FundedReplay(
        fills=[
            {"symbol": "A", "side": "buy", "modeled_cost_usd": "1.00", "strategy": "x"},
            {"symbol": "B", "side": "buy", "modeled_cost_usd": "1.00", "strategy": "y"},
            {
                "symbol": "A",
                "side": "sell",
                "modeled_cost_usd": "1.00",
                "realized_pnl_usd": "12.50",
                "strategy": "x",
            },
            {
                "symbol": "B",
                "side": "sell",
                "modeled_cost_usd": "1.00",
                "realized_pnl_usd": "-5.00",
                "strategy": "y",
            },
        ],
        decisions=[{"status": "rejected", "strategy": "y"}, {"status": "rejected"}],
        costs=Decimal("4.00"),
    )
    a = module.strategy_attribution(result, ["x", "y", "z"], round_trip_pnl=Decimal("7.50"))
    assert a["x"]["net_pnl_usd"] == "12.50" and a["x"]["hit_rate"] == 1.0
    assert a["x"]["profit_factor"] is None and a["x"]["modeled_costs_usd"] == "2.00"
    assert a["y"]["net_pnl_usd"] == "-5.00" and a["y"]["rejected_entries"] == 1
    assert a["z"] == {
        "entries": 0,
        "closed_trades": 0,
        "hit_rate": None,
        "net_pnl_usd": "0.00",
        "profit_factor": None,
        "modeled_costs_usd": "0.00",
        "rejected_entries": 0,
    }
    with pytest.raises(ValueError, match="Unattributed"):
        module.strategy_attribution(
            FundedReplay(fills=[{"side": "buy", "modeled_cost_usd": "0"}]), ["x"]
        )


def test_strategy_attribution_reconciles_against_independent_totals():
    def replay(sell_strategy="x", costs="2.00"):
        return FundedReplay(
            fills=[
                {"symbol": "A", "side": "buy", "modeled_cost_usd": "1.00", "strategy": "x"},
                {
                    "symbol": "A",
                    "side": "sell",
                    "modeled_cost_usd": "1.00",
                    "realized_pnl_usd": "3.00",
                    "strategy": sell_strategy,
                },
            ],
            costs=Decimal(costs),
        )

    assert module.strategy_attribution(replay(), ["x", "y"], round_trip_pnl=Decimal("3.00"))
    with pytest.raises(ValueError, match="does not reconcile to round trips"):
        module.strategy_attribution(replay(), ["x", "y"], round_trip_pnl=Decimal("2.99"))
    with pytest.raises(ValueError, match="costs do not reconcile"):
        module.strategy_attribution(replay(costs="2.01"), ["x", "y"])
    with pytest.raises(ValueError, match="Exit strategy differs"):
        module.strategy_attribution(replay(sell_strategy="y"), ["x", "y"])


@pytest.mark.parametrize(
    "extra",
    [
        ["--max-open-risk-pct", "3.01"],  # above the paper ledger hard maximum
        ["--max-open-risk-pct", "0"],
        ["--max-open-risk-pct", "nan"],
        ["--max-gross-pct", "100.5"],
        ["--max-gross-pct", "-1"],
        ["--max-gross-pct", "inf"],
    ],
)
def test_open_risk_and_gross_caps_never_exceed_paper_ledger_maxima(extra, capsys):
    with pytest.raises(SystemExit):
        module.parse_args(args(*extra))
    assert "paper ledger maximum" in capsys.readouterr().err
    with pytest.raises(ValueError, match="paper ledger maximum"):
        module.check_risk_caps(3.5, 60)
    with pytest.raises(ValueError, match="paper ledger maximum"):
        module.check_risk_caps(1.5, 101)


def test_open_risk_and_gross_defaults_keep_the_existing_limits(tmp_path):
    a = module.parse_args(args())
    assert (a.max_open_risk_pct, a.max_gross_pct) == (1.5, 60.0)
    wide = module.parse_args(args("--max-open-risk-pct", "3.0", "--max-gross-pct", "100"))
    assert (wide.max_open_risk_pct, wide.max_gross_pct) == (3.0, 100.0)
    path = synthetic_db(tmp_path / "s.sqlite")
    default = module.replay(path, ["SPY"], START, END)
    assert default["risk_limits"] == module.RiskLimits(
        max_position_concentration_pct=5.0, max_correlated_exposure_pct=20.0
    ).model_dump(mode="json")
    assert (default["run_config"]["max_open_risk_pct"], default["run_config"]["max_gross_pct"]) == (
        1.5,
        60.0,
    )
    widened = module.replay(path, ["SPY"], START, END, max_open_risk_pct=3.0, max_gross_pct=100)
    assert widened["risk_limits"]["max_daily_portfolio_risk_pct"] == 3.0
    assert widened["risk_limits"]["max_portfolio_exposure_pct"] == 100.0
    assert any("Passive comparator keeps fixed" in x for x in widened["limitations"])
    with pytest.raises(ValueError, match="paper ledger maximum"):
        module.replay(path, ["SPY"], START, END, max_open_risk_pct=3.5)


def test_equity_metrics_on_a_tiny_series():
    m = module.equity_metrics(
        [Decimal("110"), Decimal("99"), Decimal("121")],
        initial_cash=Decimal("100"),
        start=date(2024, 1, 1),
        end=date(2024, 12, 30),  # 365.25 calendar days inclusive would be one year
    )
    assert m["net_return_pct"] == pytest.approx(21.0)
    assert m["max_drawdown_pct"] == pytest.approx(10.0)  # 110 -> 99
    assert m["return_to_max_drawdown"] == pytest.approx(2.1)
    years = 365 / 365.25
    assert m["cagr_pct"] == pytest.approx((1.21 ** (1 / years) - 1) * 100)
    returns = [0.10, -0.10, 121 / 99 - 1]
    mean = sum(returns) / 3
    sd = (sum((r - mean) ** 2 for r in returns) / 2) ** 0.5
    assert m["sharpe_annualised"] == pytest.approx(mean / sd * 252**0.5)
    flat = module.equity_metrics(
        [Decimal("100")] * 3, initial_cash=Decimal("100"), start=START, end=END
    )
    assert flat["max_drawdown_pct"] == 0 and flat["return_to_max_drawdown"] is None
    assert flat["sharpe_annualised"] is None


def test_spy_benchmark_buys_whole_shares_with_the_same_cost_model():
    days = list(sessions(START, END))[:3]
    spy = module.PriceSeries.from_bars(
        "SPY",
        [
            (days[0], 100, 101, 99, 100, 1e6),
            (days[1], 90, 91, 89, 90, 1e6),
            (days[2], 90, 121, 89, 120, 1e6),
        ],
    )
    zero = module.CostModel(slippage_bps=0)
    b = module.spy_benchmark(
        spy, initial_cash=Decimal("1050"), cost_model=zero, spread_bps=0, start=days[0], end=days[2]
    )
    assert b["shares"] == 10 and b["residual_cash_usd"] == "50.00" and not b["price_only"]
    assert b["final_value_usd"] == "1250.00" and b["modeled_costs_usd"] == "0.00"
    assert b["net_return_pct"] == pytest.approx(200 / 1050 * 100)
    assert b["max_drawdown_pct"] == pytest.approx(100 / 1050 * 100)  # 1050 -> 950
    stress = module.CostModel(
        commission_per_share=0.005, commission_min_per_order=1, slippage_bps=10
    )
    s = module.spy_benchmark(
        spy,
        initial_cash=Decimal("1050"),
        cost_model=stress,
        spread_bps=10,
        start=days[0],
        end=days[2],
    )
    # Fill 100 * (1 + 15bps) = 100.15 per share, plus a $1 minimum commission.
    assert s["entry_price_usd"] == "100.15" and s["shares"] == 10
    assert s["residual_cash_usd"] == "47.50"
    # Exit 120 * (1 - 15bps) = 119.82, less the $1 exit commission.
    assert s["final_value_usd"] == "1244.70"
    assert s["modeled_costs_usd"] == "5.30"  # 1.50 + 1 entry, 1.80 + 1 exit


def test_report_carries_benchmark_and_risk_adjusted_per_cost_case(tmp_path):
    path = synthetic_db(tmp_path / "s.sqlite")
    out = tmp_path / "run.json"
    argv = [str(path), "--symbols", "SPY", "--since", str(START), "--until", str(END)]
    assert module.main([*argv, "--cost-scenarios", "--out", str(out)]) == 0
    r = json.loads(out.read_text())
    for label, scenario in r["scenario_diagnostics"].items():
        ra, bench = scenario["risk_adjusted"], scenario["benchmark"]
        assert ra["max_drawdown_pct"] == pytest.approx(scenario["max_drawdown_pct"])
        assert ra["net_return_pct"] == pytest.approx(scenario["diagnostics"]["net_return_pct"])
        assert ra["cagr_pct"] == pytest.approx(scenario["diagnostics"]["annualized_return_pct"])
        assert "risk-free rate 0" in ra["sharpe_policy"]
        assert bench["symbol"] == "SPY" and not bench["price_only"], label
        assert bench["dividends_received_usd"] == "0", label
        assert scenario["exposure_matched_benchmark"]["exposure_pct"] == pytest.approx(
            scenario["diagnostics"]["average_session_exposure_pct"]
        )
        assert "rejection_episodes" in scenario and "active_window" in scenario
    assert any("total return" in x for x in r["limitations"])
    assert not any("no dividend ledger" in x for x in r["limitations"])
    md = out.with_suffix(".md").read_text()
    assert "## Risk-adjusted vs SPY total-return buy-and-hold" in md and "| base | SPY |" in md
    assert "## Rejections (base)" in md


def test_dividends_are_split_adjusted_and_booked_for_replay_and_benchmark(tmp_path):
    days = list(sessions(START, END))
    path = synthetic_db(
        tmp_path / "s.sqlite",
        # Pre-split $2.00 per share; a 2:1 split after the window halves it to $1.00.
        dividends=[("SPY", str(days[10]), 2.0, str(days[12]))],
        splits=[("SPY", "2030-01-02", 1.0, 2.0)],
    )
    r = module.replay(path, ["SPY"], START, END)
    assert r["run_config"]["dividend_events_by_symbol"] == {"SPY": 1}
    bench = r["scenario_diagnostics"]["base"]["benchmark"]
    # 99 shares at the 100.06 base fill earn $1.00 each (the split-adjusted $2.00); the
    # $99 plus $94.06 residual cash buys one more whole share at the pay-date open.
    assert bench["dividends_received_usd"] == "99.00"
    assert bench["dividend_reinvestment_buys"] == 1 and bench["shares"] == 100
    diag = r["scenario_diagnostics"]["base"]["diagnostics"]
    assert Decimal(diag["dividend_income_usd"]) == sum(
        Decimal(e["amount_usd"])
        for e in r["result"]["corporate_events"]
        if e["kind"] == "dividend_entitlement"
    )
    with pytest.raises(ValueError, match="not a replay session"):
        module.replay(
            synthetic_db(
                tmp_path / "bad.sqlite", dividends=[("SPY", "2024-01-06", 1.0, "2024-01-09")]
            ),
            ["SPY"],
            START,
            END,
        )


def test_dividend_conversion_halts_on_bars_not_adjusted_for_an_in_window_split():
    days = list(sessions(START, END))[:4]
    raw = module.PriceSeries.from_bars(
        "X", [(d, p, p + 1, p - 1, p, 1e6) for d, p in zip(days, (100, 100, 50, 50), strict=True)]
    )
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE dividend_event(symbol TEXT, ex_dividend_date TEXT,
        cash_amount REAL, pay_date TEXT, currency TEXT, source TEXT)""")
    conn.execute("""CREATE TABLE split_event(symbol TEXT, execution_date TEXT,
        split_from REAL, split_to REAL)""")
    conn.execute("INSERT INTO split_event VALUES ('X', ?, 1, 2)", (str(days[2]),))
    with pytest.raises(ValueError, match="not adjusted"):
        module._dividends(conn, "X", raw, days[0], days[-1])
    adjusted = module.PriceSeries.from_bars("X", [(d, 50, 51, 49, 50, 1e6) for d in days])
    conn.execute(
        "INSERT INTO dividend_event VALUES ('X', ?, 1.0, ?, 'USD', 'massive_options')",
        (str(days[1]), str(days[3])),
    )
    (div,) = module._dividends(conn, "X", adjusted, days[0], days[-1])
    assert div.amount == Decimal("0.5") and div.pay_date == days[3]


def test_spy_benchmark_reinvests_dividends_in_whole_shares():
    days = list(sessions(START, END))[:4]
    spy = module.PriceSeries.from_bars("SPY", [(d, 100, 101, 99, 100, 1e6) for d in days])
    zero = module.CostModel(slippage_bps=0)
    div = module.Dividend("SPY", days[1], days[2], Decimal("5"), "test")
    b = module.spy_benchmark(
        spy,
        dividends=[div],
        initial_cash=Decimal("1050"),
        cost_model=zero,
        spread_bps=0,
        start=days[0],
        end=days[3],
    )
    # 10 shares, $50 residual; $50 dividend paid on day 2 plus $50 buys one share.
    assert b["dividends_received_usd"] == "50.00" and b["dividend_reinvestment_buys"] == 1
    assert b["shares"] == 11 and b["residual_cash_usd"] == "0.00"
    assert b["final_value_usd"] == "1100.00"
    late = module.spy_benchmark(
        spy,
        dividends=[div],
        initial_cash=Decimal("1050"),
        cost_model=zero,
        spread_bps=0,
        start=days[2],
        end=days[3],
        from_index=2,
    )
    # Bought after the ex-date: no entitlement.
    assert late["start"] == str(days[2]) and late["dividends_received_usd"] == "0"


def test_exposure_matched_spy_scales_daily_total_returns():
    days = list(sessions(START, END))[:3]
    spy = module.PriceSeries.from_bars(
        "SPY",
        [
            (days[0], 100, 101, 99, 100, 1e6),
            (days[1], 100, 111, 99, 110, 1e6),
            (days[2], 100, 101, 98, 99, 1e6),
        ],
    )
    div = module.Dividend("SPY", days[2], days[2], Decimal("1"), "test")
    m = module.exposure_matched_spy(
        spy,
        dividends=[div],
        exposure_pct=50,
        initial_cash=Decimal("100"),
        start=days[0],
        end=days[2],
    )
    # Day 2: +10% x 0.5; day 3: (99 + 1) / 110 - 1 x 0.5.
    expected = 1.05 * (1 + 0.5 * (100 / 110 - 1)) * 100
    assert m["net_return_pct"] == pytest.approx(expected - 100)
    with pytest.raises(ValueError):
        module.exposure_matched_spy(
            spy, exposure_pct=101, initial_cash=Decimal("100"), start=days[0], end=days[2]
        )


def test_rejection_episodes_count_runs_of_consecutive_sessions():
    days = [str(d) for d in list(sessions(START, END))[:6]]
    result = FundedReplay(
        marks=[{"day": d} for d in days],
        decisions=[
            {"day": days[i], "symbol": sym, "status": "rejected", "reason": "cap"}
            for sym, idx in (("A", (0, 1, 2, 4, 5)), ("B", (3,)))
            for i in idx
        ]
        + [{"day": days[1], "symbol": "C", "status": "accepted", "reason": None}],
    )
    assert module.rejection_episodes(result) == {
        "cap": {"candidate_days": 6, "symbols": 2, "episodes": 3}
    }


def test_input_receipt_covers_benchmark_dividend_payment_date(tmp_path):
    path = synthetic_db(
        tmp_path / "s.sqlite",
        snapshot=["SPY", "AAA"],
        dividends=[("SPY", "2024-01-03", 1, "2024-01-08")],
    )
    first = module.replay(path, ["AAA"], START, END)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE dividend_event SET pay_date = '2024-01-09' WHERE symbol = 'SPY'")
    second = module.replay(path, ["AAA"], START, END)

    assert first["dataset_sha256_by_symbol"] == second["dataset_sha256_by_symbol"]
    assert first["result"] == second["result"]
    assert (
        first["replay_assumptions"]["source_reference_sha256"]
        != second["replay_assumptions"]["source_reference_sha256"]
    )
