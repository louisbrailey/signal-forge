"""Independent Decimal fixtures for the isolated offline portfolio study."""

from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import numpy as np
import pytest
from scripts import conservative_crypto_cost_study as study

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.research.fx.strategies import (
    CRYPTO5_STRATEGIES,
    CRYPTO_STRATEGIES,
    FxStrategy,
    long_only_variant,
)

START = date(2021, 1, 1)
END = START + timedelta(days=3)


def series(pair="BTCUSD", days=5, start=START, prices=None):
    prices = prices or [100] * days
    return PriceSeries.from_bars(
        pair, [(start + timedelta(days=i), p, p + 1, p - 1, p, 0) for i, p in enumerate(prices)]
    )


def trade(
    pair="BTCUSD", entry=START, exit=END, raw_entry="100", raw_exit="100", stop="90", stress=1
):
    return study.Trade(pair, entry, exit, D(raw_entry), D(raw_exit), D(stop), "time_stop", stress)


def unlimited(**overrides):
    return replace(
        study.Limits(),
        allocation=D(1),
        theme=D(1),
        gross=D(1),
        trade_risk=D(1),
        open_risk=D(1),
        **overrides,
    )


def test_decimal_reference_both_sides_all_in_stop_and_stress_boundary():
    # Independent literal reference, not a model/LLM expected answer.
    tr = trade(raw_exit="90")
    assert tr.rate == D("0.0093")  # 90 + 2 + 1 bps
    assert tr.entry_fill == D("100.9300")
    assert tr.exit_fill == D("89.1630")
    assert tr.stop_risk == D("11.7670")  # includes entry and stop-exit costs
    assert tr.entry_fill - tr.exit_fill == tr.stop_risk
    stress = replace(tr, stress=2)
    assert stress.rate == D("0.0185")  # 180 + 4 + 1, NOT 186 bps
    assert stress.stop_risk == D("13.5150")
    assert study.side_rate("ETHUSD", 1) == D("0.0094")
    assert study.side_rate("SOLUSD", 1) == D("0.0101")
    assert study.side_rate("ADAUSD", 1) == D("0.0106")
    with pytest.raises(ValueError):
        study.side_rate("BTCUSD", 3)


@pytest.mark.parametrize(
    "key,cap",
    [
        ("allocation", ".05"),
        ("theme", ".2"),
        ("gross", ".6"),
        ("trade_risk", ".005"),
        ("open_risk", ".015"),
    ],
)
def test_each_quantity_cap_independently_binds_with_post_cost_denominator(key, cap):
    limits = replace(unlimited(), **{key: D(cap)})
    tr = trade()
    qty = study.quantity(
        tr, cash=D(10000), equity=D(10000), gross=D(0), open_risk=D(0), limits=limits
    )
    post_equity = D(10000) - qty * D(".93")
    numerator = qty * (
        tr.stop_risk
        if key in ("trade_risk", "open_risk")
        else tr.raw_entry if key in ("gross", "theme") else tr.entry_fill
    )
    assert numerator <= D(cap) * post_equity
    # Demonstrate that the constrained cap actually binds, not a loose inequality.
    assert D(cap) * post_equity - numerator < D("1e-12")


def test_fractional_cash_bound_no_negative_and_conservation():
    tr = trade(raw_exit="110")
    panel = {"BTCUSD": series(prices=[100, 101, 102, 110, 110])}
    out = study.replay([tr], panel, START, END, unlimited())
    q = D(out["admissions"][0]["qty"])
    assert q != q.to_integral_value()
    assert D(out["admissions"][0]["cash_after"]) >= 0
    assert out["metrics"]["min_cash"] >= 0
    assert out["metrics"]["total_costs"] == pytest.approx(float(q * D(210) * D(".0093")))
    expected_pnl_per_unit = D(110) - D(100) - D(210) * D(".0093")
    assert out["metrics"]["ending_equity"] == pytest.approx(
        float(D(10000) + q * expected_pnl_per_unit)
    )


def test_existing_theme_and_open_risk_room_constrain_next_trade():
    tr = trade()
    # Consume all initial aggregate risk room, independently of cash/gross.
    assert (
        study.quantity(
            tr,
            cash=D(9000),
            equity=D(10000),
            gross=D(1000),
            open_risk=D(150),
            limits=study.Limits(),
        )
        == 0
    )
    assert (
        study.quantity(
            tr, cash=D(9000), equity=D(10000), gross=D(2000), open_risk=D(0), limits=study.Limits()
        )
        == 0
    )


def test_sizing_is_independent_of_future_exit_price_and_all_in_risk_is_reserved():
    tr = trade()
    inputs = {
        "cash": D(10000),
        "equity": D(10000),
        "gross": D(0),
        "open_risk": D(0),
        "limits": study.Limits(),
    }
    q = study.quantity(tr, **inputs)
    assert q == study.quantity(replace(tr, raw_exit=D("1000000")), **inputs)
    assert q == study.quantity(replace(tr, raw_exit=D("1")), **inputs)
    assert q * tr.stop_risk <= D(50)
    h = study.Holding(tr, q)
    assert h.reserve(D(50)) == q * tr.stop_risk
    assert h.reserve(D(150)) > q * tr.stop_risk


def test_simultaneous_portfolio_admissions_enforce_theme_openrisk_and_allocation():
    pairs = ["ADAUSD", "AVAXUSD", "BTCUSD", "DOGEUSD", "ETHUSD", "LINKUSD"]
    out = study.replay(
        [trade(pair=p, stop="99") for p in reversed(pairs)],
        {p: series(p) for p in pairs},
        START,
        END,
    )
    assert [a["pair"] for a in out["admissions"]] == sorted(a["pair"] for a in out["admissions"])
    for key, bound in (
        ("allocation", 0.05),
        ("theme", 0.2),
        ("gross", 0.6),
        ("trade_risk", 0.005),
        ("open_risk", 0.015),
    ):
        assert out["metrics"]["admission_maxima"][key] <= bound + 1e-12
    assert out["metrics"]["admission_maxima"]["theme"] == pytest.approx(0.2)
    assert out["metrics"]["trades"] < len(pairs)


def test_intraday_exit_cash_and_released_risk_cannot_fund_same_open():
    first = trade(exit=START + timedelta(days=1))
    second = trade(pair="ETHUSD", entry=START + timedelta(days=1))
    panel = {p: series(p) for p in ("BTCUSD", "ETHUSD")}
    out = study.replay([second, first], panel, START, END, unlimited())
    # The second entry can spend ONLY cash already left after the first entry.
    a, b = out["admissions"]
    assert b["cash_before"] == a["cash_after"]
    assert D(b["qty"]) * second.entry_fill <= D(a["cash_after"])
    assert D(b["qty"]) * second.entry_fill < 100
    # Even with ample cash, an occupied theme sleeve cannot be recycled at that open.
    limits = replace(unlimited(), theme=D(".05"))
    out = study.replay([first, second], panel, START, END, limits)
    assert out["metrics"]["trades"] == 1


def test_drawdown_halt_is_sticky_while_existing_exit_still_executes():
    first = trade(raw_exit="50", stop="10")
    second = trade(pair="ETHUSD", entry=START + timedelta(days=2))
    panel = {"BTCUSD": series(prices=[100, 50, 100, 50, 50]), "ETHUSD": series("ETHUSD")}
    out = study.replay([first, second], panel, START, END, unlimited())
    assert out["metrics"]["halt_date"] == str(START + timedelta(days=1))
    assert out["metrics"]["skipped"] == {"drawdown_halt": 1}
    assert out["metrics"]["trades"] == 1
    assert out["metrics"]["max_drawdown_pct"] > 10


def test_stale_holding_blocks_entry_without_fabricating_bar():
    btc = series()
    btc = PriceSeries.from_bars(
        "BTCUSD", [(d, 100, 101, 99, 100, 0) for d in btc.dates if d != START + timedelta(days=1)]
    )
    second = trade(pair="ETHUSD", entry=START + timedelta(days=1))
    out = study.replay([trade(), second], {"BTCUSD": btc, "ETHUSD": series("ETHUSD")}, START, END)
    assert out["metrics"]["stale_position_days"] == 1
    assert out["metrics"]["skipped"] == {"stale_holding": 1}
    assert START + timedelta(days=1) not in btc.dates


def signal_once(sub, t):
    return EntrySignal(Direction.LONG, 90, 2) if t == 2 else None


def test_next_open_stop_gap_and_time_fill_parity_with_real_harness():
    strat = FxStrategy("fixture", "fixture", {}, 2, signal_once)
    s = series(days=7, prices=[100, 100, 100, 110, 80, 81, 82])
    trades, rejected = study.harness_candidates(strat, s, START, START + timedelta(days=6), 1)
    assert not rejected
    assert len(trades) == 1
    tr = trades[0]
    assert tr.entry == START + timedelta(days=3)
    assert tr.raw_entry == 110
    assert tr.raw_exit == 80  # subsequent stop gap uses open, not stop=90
    assert tr.reason == "stop"
    # Entry-day stop uses the harness's fixed-stop fill rule.
    s = series(days=7, prices=[100, 100, 100, 100, 100, 100, 100])
    s.low[3] = 89
    ts, _ = study.harness_candidates(strat, s, START, START + timedelta(days=6), 2)
    assert ts[0].entry == ts[0].exit
    assert ts[0].raw_exit == 90


def test_complete_warmup_and_next_calendar_open_required():
    strat = FxStrategy("fixture", "fixture", {}, 2, signal_once)
    s = series(days=7)
    shifted = replace(
        s, dates=tuple(d if i < 3 else d + timedelta(days=1) for i, d in enumerate(s.dates))
    )
    ts, rejected = study.harness_candidates(strat, shifted, START, START + timedelta(days=7), 1)
    assert ts == []
    assert rejected == {"missing_next_calendar_open": 1}
    assert study.eligible_entry(s, 2, START, END) == START + timedelta(days=3)
    assert not study.continuous_history(shifted, 3, 2)


def test_sealed_input_rejected_before_signal_and_flat_start_has_no_carry_in():
    called = []
    strat = FxStrategy("fixture", "fixture", {}, 2, lambda s, t: called.append(t))
    with pytest.raises(ValueError, match="unbounded"):
        study.harness_candidates(strat, series(start=study.SEALED), START, END, 1)
    assert called == []
    with pytest.raises(ValueError):
        study.harness_candidates(strat, series(), START, study.SEALED, 1)
    start = START + timedelta(days=2)
    assert study.eligible_entry(series(), 2, start, END) == START + timedelta(days=3)
    with pytest.raises(ValueError):
        study.replay([trade(entry=START - timedelta(days=1))], {"BTCUSD": series()}, START, END)


def test_parent_long_filter_exactly_reproduces_registered_variant():
    # Oscillating trend provides actual breakouts/stops, rather than an empty parity check.
    prices = [float(100 * np.exp(i * 0.003 + 0.20 * np.sin(i / 35))) for i in range(500)]
    s = series(prices=prices)
    parent = next(s for s in CRYPTO_STRATEGIES if s.key == "crypto_donchian_55")
    filtered = long_only_variant(parent, "filter", "filter")
    a, _ = study.harness_candidates(filtered, s, START, s.dates[-1], 1)
    b, _ = study.harness_candidates(CRYPTO5_STRATEGIES[0], s, START, s.dates[-1], 1)
    assert a and a == b


def fixture_db(path, optional=True):
    conn = sqlite3.connect(path)
    suffix = ", volume REAL, quality_flags TEXT, latency_category TEXT" if optional else ""
    conn.execute(
        "CREATE TABLE crypto_bar_daily (pair TEXT, session_date TEXT, open REAL, "
        "high REAL, low REAL, close REAL, source TEXT" + suffix + ")"
    )
    rows = [
        ("BTCUSD", "2021-01-01", 100, 101, 99, 100, "massive_crypto"),
        ("BTCUSD", "2025-10-26", 999999, 999999, 999999, 999999, "massive_crypto"),
        ("BTCUSD", "2021-01-02", 777, 777, 777, 777, "fixture"),
        ("BTCUSD", "2015-12-31", 666, 666, 666, 666, "massive_crypto"),
    ]
    if optional:
        rows = [(*r, None, "[]", "END_OF_DAY") for r in rows]
        rows += [
            (
                "BTCUSD",
                "2021-01-03",
                100,
                101,
                99,
                100,
                "massive_crypto",
                None,
                json.dumps(["bad"]),
                "END_OF_DAY",
            ),
            ("BTCUSD", "2021-01-04", 100, 101, 99, 100, "massive_crypto", None, "[]", "SIMULATED"),
        ]
    conn.executemany(
        "INSERT INTO crypto_bar_daily VALUES (" + ",".join("?" for _ in rows[0]) + ")", rows
    )
    conn.commit()
    conn.close()


def test_sql_bounds_source_nonfixture_quality_and_no_writes(tmp_path):
    path = tmp_path / "bars.sqlite"
    fixture_db(path)
    before = path.read_bytes()
    panel, meta = study.load_bounded(path, ["BTCUSD"])
    assert panel["BTCUSD"].dates == (START,)
    assert panel["BTCUSD"].close.tolist() == [100]
    assert meta["pairs"]["BTCUSD"]["selected_rows"] == 3
    assert meta["pairs"]["BTCUSD"]["excluded"] == {"quality_flags": 1, "explicit_simulation": 1}
    assert "session_date < ?" in meta["query"] and "source = ?" in meta["query"]
    assert path.read_bytes() == before
    with study.open_readonly(path) as conn:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM crypto_bar_daily")


def test_absent_schema_fields_are_unknown_and_liquidity_unvalidated(tmp_path):
    path = tmp_path / "bars.sqlite"
    fixture_db(path, optional=False)
    panel, meta = study.load_bounded(path, ["BTCUSD"])
    assert meta["quality_status"] == "UNKNOWN"
    assert meta["simulation_status"].startswith("UNKNOWN")
    assert meta["liquidity"].startswith("UNVALIDATED")
    assert np.isnan(panel["BTCUSD"].volume[0])


def test_inception_gaps_and_missing_boundaries_reported():
    s = series(days=4, start=START + timedelta(days=3))
    before_inception = study.coverage(s, START, START + timedelta(days=2))
    assert before_inception["breach"] == "not yet incepted"
    assert before_inception["expected"] == before_inception["missing"] == 0
    c = study.coverage(s, START, START + timedelta(days=6))
    assert c["missing"] == 0 and c["expected"] == 4
    c = study.coverage(s, START, START + timedelta(days=10))
    assert c["missing"] == 4 and c["breach"]
    assert c["gaps"] == [[str(START + timedelta(days=7)), str(START + timedelta(days=10))]]


def test_benchmark_costs_cash_sleeves_and_exposure_matching():
    panel = {
        "BTCUSD": series(days=10),
        "ETHUSD": series("ETHUSD", days=7, start=START + timedelta(days=3)),
    }
    end = START + timedelta(days=9)
    comp = study.hold_components(panel, 2, START, end, 1)
    full = study.hold_scaled(comp, 1)
    assert full["entries"][0]["entry"] == str(START + timedelta(days=3))
    assert full["entries"][1]["entry"] == str(START + timedelta(days=6))
    # Constant prices: the ONLY loss is both-side costs.
    assert full["metrics"]["ending_equity"] == pytest.approx(10000 - full["metrics"]["total_costs"])
    matched = study.matched_hold(comp, 0.1)
    assert matched["metrics"]["mean_exposure_pct"] == pytest.approx(10)
    assert matched["metrics"]["total_costs"] < full["metrics"]["total_costs"]
    assert study.block_interval(full["equity"], full["equity"]) == [0, 0]


def report_fixture():
    portfolio = study.replay([trade()], {"BTCUSD": series()}, START, END)
    full = study.hold_scaled(study.hold_components({"BTCUSD": series()}, 2, START, END, 1), 1)
    row = {
        "window": "followup_SEEN",
        "strategy": "crypto_donchian_55_long",
        "stress": 1,
        "schedule": "variant",
        "portfolio": portfolio,
        "buy_hold": copy.deepcopy(full),
        "exposure_matched": copy.deepcopy(full),
        "excess_annual_mean_90pct_block_interval_pp": [-1, 1],
    }
    parent = copy.deepcopy(row)
    parent["schedule"] = "parent_long_legs"
    return {
        "protocol_commit": "protocol",
        "source_commit": "source",
        "data": {
            "bounded_data_sha256": "data",
            "quality_status": "UNKNOWN",
            "simulation_status": "UNKNOWN",
            "pairs": {},
        },
        "coverage": {},
        "runs": [parent, row],
        "comparisons": [
            {
                "window": row["window"],
                "strategy": row["strategy"],
                "stress": 1,
                "parent_long_candidates": 1,
                "variant_candidates": 1,
                "same_schedule": True,
                "long_signal_filter_parity": True,
            }
        ],
    }


def test_report_derives_contrary_benchmark_and_parent_outcomes_from_values(tmp_path):
    result = report_fixture()
    parent, variant = result["runs"]
    parent["portfolio"]["metrics"]["net_return_pct"] = 3
    variant["portfolio"]["metrics"]["net_return_pct"] = -2
    variant["portfolio"]["metrics"]["max_drawdown_pct"] = 5
    variant["buy_hold"]["metrics"].update(net_return_pct=-10, max_drawdown_pct=1)
    variant["exposure_matched"]["metrics"]["net_return_pct"] = -1
    variant["excess_annual_mean_90pct_block_interval_pp"] = [-4, -1]
    result["comparisons"][0]["long_signal_filter_parity"] = False
    report = study.render(result, tmp_path / "evidence.json", "hash")
    assert "Outcome: 0/1" in report
    assert "net returns; 0/1 exceeded" in report
    assert "0/1 followup excess-return intervals include zero" in report
    assert "Parent/variant full-account equality: 0/1 paired comparisons" in report
    assert "2 runs contain 2 distinct full accounts" in report
    assert "higher absolute returns in 0/1" in report
    assert "larger close drawdowns in 0/1" in report
    assert "filter-before-scheduling parity: 0/1" in report
    assert "Every parent LONG-leg" not in report
    assert "higher absolute returns in every comparison" not in report


def test_report_derives_success_counts_without_counting_duplicate_accounts_twice(tmp_path):
    result = report_fixture()
    report = study.render(result, tmp_path / "evidence.json", "hash")
    assert "Parent/variant full-account equality: 1/1 paired comparisons" in report
    assert "2 runs contain 1 distinct full accounts" in report
    assert "filter-before-scheduling parity: 1/1" in report


@pytest.fixture
def source_repo(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "src").mkdir()
    helper = repo / "src/helper.py"
    helper.write_text("def value():\n    return 1\n")
    (repo / study.PROTOCOL).parent.mkdir(parents=True)
    (repo / study.PROTOCOL).write_text("fixed protocol\n")
    (repo / study.REPORT).parent.mkdir(parents=True)
    (repo / study.REPORT).write_text("existing report must survive refusal\n")
    (repo / ".gitignore").write_text(".toolkit-runs/\n__pycache__/\n")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Source pin fixture")
    git("config", "user.email", "source-pin@example.invalid")
    git("add", ".")
    git("commit", "-qm", "fixture")
    monkeypatch.setattr(study, "ROOT", repo)
    monkeypatch.setattr(study, "ENTRY_SOURCE_PIN", None)
    return repo, helper, git


@pytest.mark.parametrize("kind", ["unstaged", "staged", "untracked", "ignored_python"])
def test_source_pin_refuses_dirty_import_source_before_database_read(
    source_repo, monkeypatch, kind
):
    repo, helper, git = source_repo
    if kind == "untracked":
        (repo / "src/new_helper.py").write_text("value = 2\n")
    elif kind == "ignored_python":
        with (repo / ".gitignore").open("a") as out:
            out.write("src/ignored_helper.py\n")
        git("add", ".gitignore")
        git("commit", "-qm", "ignored source fixture")
        (repo / "src/ignored_helper.py").write_text("value = 2\n")
    else:
        helper.write_text("def value():\n    return 2\n")
        if kind == "staged":
            git("add", "src/helper.py")
    reads = []
    monkeypatch.setattr(study, "load_bounded", lambda *args: reads.append(args))
    with pytest.raises(ValueError, match="source pin"):
        study.evaluate_and_publish(repo / "unused.sqlite")
    assert reads == []


def test_source_pin_allows_ignored_output_and_records_all_tracked_files(source_repo):
    repo, _helper, _ = source_repo
    pin = study.capture_source_pin()
    (repo / ".toolkit-runs").mkdir()
    (repo / ".toolkit-runs/evidence.json").write_text("{}")
    assert study.capture_source_pin() == pin
    assert "src/helper.py" in pin["files"]
    assert study.PROTOCOL in pin["files"]
    assert pin["sha256"] == study.digest({k: pin[k] for k in ("commit", "files")})


@pytest.mark.parametrize("state", ["unstaged", "staged", "committed"])
@pytest.mark.parametrize("phase", ["evaluation", "render"])
def test_imported_helper_mutated_during_evaluation_refuses_all_output(
    source_repo, monkeypatch, state, phase
):
    repo, helper, git = source_repo
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("source_pin_fixture_helper", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    real_runtime_pin = study.capture_runtime_pin
    monkeypatch.setattr(
        study,
        "capture_runtime_pin",
        lambda pin: real_runtime_pin(pin, {"source_pin_fixture_helper": module}),
    )
    monkeypatch.setattr(study, "load_bounded", lambda *args: ({}, {}))

    def mutate():
        assert module.value() == 1
        helper.write_text("def value():\n    return 2\n")
        if state in ("staged", "committed"):
            git("add", "src/helper.py")
        if state == "committed":
            git("commit", "-qm", "source changed during evaluation")

    def mutation(*args):
        if phase == "evaluation":
            mutate()
        return report_fixture()

    monkeypatch.setattr(study, "run_study", mutation)
    if phase == "render":

        def render_mutation(*args):
            mutate()
            return "do not publish"

        monkeypatch.setattr(study, "render", render_mutation)
    before = (repo / study.REPORT).read_bytes()
    with pytest.raises(ValueError, match="source pin"):
        study.evaluate_and_publish(repo / "unused.sqlite")
    assert (repo / study.REPORT).read_bytes() == before
    assert not (repo / ".toolkit-runs/conservative-crypto-cost-study/evidence.json").exists()


def test_runtime_pin_rejects_foreign_project_import(source_repo):
    _, _, _ = source_repo
    from signalforge.research.fx import venues

    with pytest.raises(ValueError, match="outside pinned checkout"):
        study.capture_runtime_pin(
            study.capture_source_pin(), {"signalforge.research.fx.venues": venues}
        )


@pytest.mark.parametrize("change", ["changed_runtime", "new_runtime_module"])
def test_external_runtime_source_change_refuses_publication(source_repo, monkeypatch, change):
    repo, helper, _ = source_repo
    dependency = repo.parent / "external_dependency.py"
    dependency.write_text("value = 1\n")
    spec = importlib.util.spec_from_file_location("source_pin_external_dependency", dependency)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec.loader.exec_module(module)
    inventory = {"source_pin_external_dependency": module}
    real_pin = study.capture_runtime_pin
    monkeypatch.setattr(study, "capture_runtime_pin", lambda pin: real_pin(pin, inventory))
    monkeypatch.setattr(study, "load_bounded", lambda *args: ({}, {}))

    def mutate(*args):
        if change == "changed_runtime":
            dependency.write_text("value = 2\n")
        else:
            inventory["new_runtime_module"] = type(module)("new_runtime_module")
            inventory["new_runtime_module"].__file__ = str(helper)
        return report_fixture()

    monkeypatch.setattr(study, "run_study", mutate)
    before = (repo / study.REPORT).read_bytes()
    with pytest.raises(ValueError, match="runtime source pin changed"):
        study.evaluate_and_publish(repo / "unused.sqlite")
    assert (repo / study.REPORT).read_bytes() == before
    assert not (repo / ".toolkit-runs/conservative-crypto-cost-study/evidence.json").exists()
