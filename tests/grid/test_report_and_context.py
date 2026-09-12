"""The /grid page and the markdown/JSON report writer."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from signalforge.grid.config import GridParams
from signalforge.grid.engine import GridSeries, run_grid_backtest
from signalforge.grid.report import render_report_md, write_report
from signalforge.grid.universe import GridUniverse
from tests.grid.conftest import GRID_SOURCE, BarWriter


def _result() -> object:
    d = tuple(date(2024, 1, 2) + timedelta(days=i) for i in range(6))
    series = GridSeries(
        "AAA", d, (100.0, 100.0, 94.9, 90.0, 99.7, 101.0), (100.0, 100.0, 94.9, 94.9, 99.7, 99.7)
    )
    bench = GridSeries("SPY", d, (400.0,) * 6, (400.0, 402.0, 404.0, 406.0, 408.0, 410.0))
    return run_grid_backtest(
        {"AAA": series},
        GridParams(starting_cash=1_000.0, universe_name="test", universe_size=1),
        requested=["AAA", "ZZZ"],
        benchmark=bench,
    )


def test_markdown_report_states_the_rules_parameters_and_limitations() -> None:
    md = render_report_md(
        _result(),  # type: ignore[arg-type]
        title="Grid test run",
        universe=GridUniverse("test", ("AAA",), "unit test", "rank note"),
        source=GRID_SOURCE,
    )
    assert "# Grid test run" in md
    assert "not financial advice" in md.lower()
    assert "not a registered strategy" in md
    # Rules, parameters, cost model.
    assert "next session's open" in md
    assert "per_symbol_cap" in md and "buy_usd" in md and "drop_pct" in md
    assert "slippage 3 bps + half-spread" in md
    # Benchmark + data limitations.
    assert "SPY buy-and-hold" in md
    assert "survivorship-biased" in md
    assert "U.S.-listed symbols only" in md
    assert "adjusted AS OF THE FETCH DATE" in md
    assert "Daily closes only" in md


def test_write_report_emits_markdown_and_json(tmp_path: Path) -> None:
    md, js = write_report(
        _result(),  # type: ignore[arg-type]
        slug="unit_run",
        title="Grid unit run",
        out_dir=tmp_path,
        source=GRID_SOURCE,
        git_sha="deadbeef",
    )
    assert md.name == "unit_run.md" and js.name == "unit_run.json"
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["title"] == "Grid unit run"
    assert payload["git_sha"] == "deadbeef"
    assert payload["skipped_symbols"] == ["ZZZ"]
    assert payload["metrics"]["n_trades"] == len(payload["trades"])
    assert payload["benchmark"]["symbol"] == "SPY"
    assert "adjustment_note" in payload


def test_report_can_omit_the_bulky_arrays(tmp_path: Path) -> None:
    _md, js = write_report(
        _result(),  # type: ignore[arg-type]
        slug="small",
        title="small",
        out_dir=tmp_path,
        include_trades=False,
    )
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert "trades" not in payload and "equity_curve" not in payload
    assert payload["metrics"]["n_trades"] >= 0


def test_grid_context_with_no_account(session: Session) -> None:
    from signalforge.app.views import grid_context

    ctx = grid_context(session)
    assert ctx["exists"] is False
    assert ctx["enabled"] is False  # research.grid.enabled defaults to False
    assert ctx["params"]["per_symbol_cap"] == 50.0
    assert ctx["budget_is_consistent"] is False  # 1000 x $50 against $5,000


def test_grid_context_reports_positions_and_trades(session: Session, write_bars: BarWriter) -> None:
    from signalforge.app.views import grid_context
    from signalforge.config.research import GridConfig
    from signalforge.grid.live import run_grid_daily

    start = date(2024, 1, 2)
    write_bars("AAA", [100.0, 100.0, 94.9, 94.9], [100.0, 100.0, 94.9, 90.0], start)
    cfg = GridConfig.model_validate(
        {"enabled": True, "universe_size": 1, "starting_cash": 1_000.0, "source": GRID_SOURCE}
    )
    for i in (1, 2, 3):
        run_grid_daily(session, cfg=cfg, as_of=start + timedelta(days=i), symbols=["AAA"])

    ctx = grid_context(session)
    assert ctx["exists"] is True
    assert ctx["n_trades"] == 1
    assert ctx["n_positions"] == 1
    assert ctx["positions"][0]["symbol"] == "AAA"
    assert ctx["trades"][0]["side"] == "buy"
    assert ctx["cash"] < 1_000.0
    assert ctx["equity"] == pytest.approx(ctx["cash"] + ctx["market_value"])
