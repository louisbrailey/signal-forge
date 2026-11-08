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


def synthetic_db(path, *, snapshot=None, short=()):
    """Synthetic contract data only: never used for performance evidence."""
    days = list(sessions(START, END))
    with sqlite3.connect(path) as conn:
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
