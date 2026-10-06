"""``scripts/options_rejection_breakdown.py`` — the read-only funnel on a seeded chain.

Hermetic: no provider, no network, no live database.  A synthetic put chain is
written to the migrated test database through the ORM, priced from Black-Scholes
at one known volatility so the frozen strategy's own inversion recovers it, and
the script then reads that file back through ``mode=ro``.

Two chains, one difference:

* ``$1`` strike spacing — the exact ``$8`` wing exists, so the funnel passes
  stage (d) and the session is decided by the credit floor / OP-1 fit;
* ``$12`` strike spacing — no strike sits at ``K_short - 8``, so the funnel stops
  at stage (d) and records the wing as NOT STORED (uncollected, not illiquid).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy.orm import Session

from signalforge.data import calendar
from signalforge.db.models import (
    DataSnapshot,
    DividendYieldDaily,
    Instrument,
    OHLCVDaily,
    OptionAggregateDaily,
    OptionContract,
)
from signalforge.db.types import utcnow
from signalforge.domain import LatencyCategory
from signalforge.options import blackscholes
from signalforge.research.options_strategies.short_vertical import OptionsShortVertical

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "options_rejection_breakdown.py"

SYMBOL = "SPY"
BAR_SOURCE = "massive"
OPTION_SOURCE = "massive_options"
Q_SOURCE = "vendor_dividends"
LEVEL = 500.0
SIGMA = 0.45
RATE = 0.04
Q = 0.013
EXPIRY = date(2024, 4, 19)  # third Friday
WINDOW_START = date(2023, 12, 1)
WINDOW_END = date(2024, 5, 31)
SNAPSHOT_KEY = "options_test_snapshot"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("options_rejection_breakdown", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["options_rejection_breakdown"] = mod
    spec.loader.exec_module(mod)
    return mod


def _ticker(expiry: date, right: str, strike: float) -> str:
    cp = "C" if right == "call" else "P"
    return f"O:{SYMBOL}{expiry:%y%m%d}{cp}{round(strike * 1000):08d}"


def _seed(session: Session, *, strikes: list[float]) -> None:
    inst = Instrument(symbol=SYMBOL, name=SYMBOL, instrument_type="etf", exchange="ARCX")
    session.add(inst)
    session.flush()
    sessions = calendar.sessions(WINDOW_START, WINDOW_END)
    for d in sessions:
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=d,
                open=LEVEL,
                high=LEVEL,
                low=LEVEL,
                close=LEVEL,
                adj_close=LEVEL,
                volume=1_000_000,
                source=BAR_SOURCE,
                latency_category=LatencyCategory.HISTORICAL,
                ingested_at=datetime.now(UTC),
                is_simulated=False,
            )
        )
        session.add(
            DividendYieldDaily(
                symbol=SYMBOL,
                session_date=d,
                q=Q,
                source=Q_SOURCE,
                payments=4,
                window_start=d - timedelta(days=365),
                reference_close=LEVEL,
            )
        )
    for k in strikes:
        ticker = _ticker(EXPIRY, "put", k)
        session.add(
            OptionContract(
                option_ticker=ticker,
                underlying_symbol=SYMBOL,
                contract_type="put",
                strike_price=k,
                expiration_date=EXPIRY,
                exercise_style="american",
                shares_per_contract=100,
                source=OPTION_SOURCE,
                ingested_at=utcnow(),
            )
        )
        for d in sessions:
            if d > EXPIRY:
                continue
            t_years = max((EXPIRY - d).days, 1) / 365.0
            px = max(
                0.01, round(blackscholes.price(LEVEL, k, t_years, RATE, SIGMA, call=False, q=Q), 2)
            )
            session.add(
                OptionAggregateDaily(
                    option_ticker=ticker,
                    underlying_symbol=SYMBOL,
                    session_date=d,
                    open=px,
                    high=px,
                    low=px,
                    close=px,
                    volume=1500.0,
                    transactions=40,
                    source=OPTION_SOURCE,
                    latency_category=LatencyCategory.HISTORICAL,
                    ingested_at=utcnow(),
                    quality_flags=[],
                )
            )
    session.add(
        DataSnapshot(
            key=SNAPSHOT_KEY,
            symbols_json=[SYMBOL],
            description="test",
            source_note="test",
            options_scope_json={
                "schema_version": 1,
                "underlyings": [SYMBOL],
                "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
                "option_data": {"source": OPTION_SOURCE},
                "ingestion_run_ids": [],
            },
        )
    )
    session.commit()


def _db_file(isolated_data_dir: Path) -> Path:
    return isolated_data_dir / "test.sqlite"


def _run(mod: ModuleType, db: Path):  # type: ignore[no-untyped-def]
    return mod.run(db, snapshot_key=SNAPSHOT_KEY, sealed_days=30)


def test_dense_dollar_strikes_clear_the_wing_stage(
    db_url: str, session: Session, isolated_data_dir: Path
) -> None:
    _seed(session, strikes=[float(k) for k in range(440, 521)])
    mod = _load_script()
    scope, pre_sealed_end, funnels, grids = _run(mod, _db_file(isolated_data_dir))

    assert scope.symbols == (SYMBOL,)
    assert scope.option_source == OPTION_SOURCE
    assert pre_sealed_end == WINDOW_END - timedelta(days=31)
    (f,) = funnels
    # two monthly cycles fall in the window; only April has stored contracts, so
    # May is counted at stage (b) with its sub-reason, exactly as the live run does
    assert f.signal_sessions == 2
    rec, may = f.records
    assert may.stage == "b_no_expiry_in_dte_window"
    assert may.note == "no contracts stored for expiry 2024-05-17"
    assert rec.expiry == EXPIRY.isoformat()
    assert rec.side == "put"
    assert rec.dte == 35
    # the $1 grid holds the exact wing: the funnel passed (c) and (d)
    assert rec.short_strike is not None
    assert rec.nearest_width == pytest.approx(8.0)
    assert rec.exact_wing_stored is True and rec.exact_wing_print_eligible is True
    assert rec.stage in {"f_credit_floor", "g_op1_risk_fit", "selectable"}
    assert f.counts["d_no_wing_at_exact_width"] == 0
    # the per-side delta decomposition saw a usable surface
    assert rec.otm_print_eligible is not None and rec.otm_print_eligible > 10
    assert rec.otm_with_invertible_iv == rec.otm_print_eligible

    # the stored grid is reported as identities: $1 spacing, exact-$8 pairs present
    (grid,) = grids
    assert grid.right == "put"
    assert grid.n_strikes == 81
    assert grid.median_spacing == pytest.approx(1.0)
    assert grid.pairs_exactly_8 == 81 - 8
    assert grid.widths_nearest_8[0] == pytest.approx(8.0)


def test_dense_funnel_agrees_with_the_frozen_strategy(
    db_url: str, session: Session, isolated_data_dir: Path
) -> None:
    """On the dense chain the funnel's verdict must be the strategy's own verdict:
    ``selectable`` iff ``OptionsShortVertical.__call__`` returns a signal."""
    _seed(session, strikes=[float(k) for k in range(440, 521)])
    mod = _load_script()
    db = _db_file(isolated_data_dir)
    _, _, funnels, _ = _run(mod, db)
    rec = funnels[0].records[0]

    con = mod.open_readonly(db)
    try:
        series = mod.load_underlying(con, SYMBOL, WINDOW_START, WINDOW_END, source=BAR_SOURCE)
        chain = mod.load_chain(
            con, SYMBOL, WINDOW_START, WINDOW_END, option_source=OPTION_SOURCE, series=series
        )
        q_lookup = mod.load_q_lookup(con, [SYMBOL], source=Q_SOURCE)
    finally:
        con.close()
    assert chain is not None
    strat = OptionsShortVertical(q_lookup=q_lookup, q_source=Q_SOURCE)
    t = chain.index_of(date.fromisoformat(rec.session_date))
    assert t is not None
    signal = strat(chain.head(t), series.head(t), t)
    assert (signal is not None) == (rec.stage == "selectable")


def test_coarse_twelve_dollar_grid_stops_at_the_wing(
    db_url: str, session: Session, isolated_data_dir: Path
) -> None:
    _seed(session, strikes=[float(k) for k in range(440, 521, 12)])
    mod = _load_script()
    _, _, funnels, grids = _run(mod, _db_file(isolated_data_dir))
    (f,) = funnels
    assert f.signal_sessions == 2
    rec = f.records[0]
    assert rec.stage == "d_no_wing_at_exact_width"
    assert rec.exact_wing_stored is False
    assert rec.exact_wing_print_eligible is False
    assert rec.nearest_width == pytest.approx(12.0)
    assert rec.note == "exact wing strike not stored"
    assert f.d_exact_wing_not_stored == 1
    assert f.d_exact_wing_stored_not_eligible == 0
    assert f.nearest_width_histogram == {"12": 1}
    (grid,) = grids
    assert grid.median_spacing == pytest.approx(12.0)
    assert grid.pairs_exactly_8 == 0
    assert grid.widths_nearest_8[0] == pytest.approx(12.0)


def test_markdown_and_json_carry_counts_and_identities_only(
    db_url: str, session: Session, isolated_data_dir: Path
) -> None:
    _seed(session, strikes=[float(k) for k in range(440, 521, 12)])
    mod = _load_script()
    scope, pre_sealed_end, funnels, grids = _run(mod, _db_file(isolated_data_dir))
    md = mod.render_markdown(
        scope,
        pre_sealed_end=pre_sealed_end,
        funnels=funnels,
        grids=grids,
        params=mod.ShortVerticalParams(),
        db_path=_db_file(isolated_data_dir),
    )
    assert "| d_no_wing_at_exact_width | 1 | 1 |" in md
    assert "| b_no_expiry_in_dte_window | 1 | 1 |" in md
    assert "| selectable | 0 | 0 |" in md
    for forbidden in ("P&L", "return", "credit:", "close=", "vwap"):
        assert forbidden not in md
    payload = mod.to_json(scope, pre_sealed_end=pre_sealed_end, funnels=funnels, grids=grids)
    text = json.dumps(payload, default=str)
    record = json.loads(text)["funnels"][0]["records"][0]
    assert set(record) == {
        "underlying",
        "session_date",
        "expiry",
        "side",
        "stage",
        "dte",
        "short_strike",
        "wing_target",
        "nearest_width",
        "exact_wing_stored",
        "exact_wing_print_eligible",
        "otm_print_eligible",
        "otm_with_invertible_iv",
        "note",
    }


def test_open_readonly_refuses_writes_and_missing_files(tmp_path: Path) -> None:
    mod = _load_script()
    with pytest.raises(FileNotFoundError):
        mod.open_readonly(tmp_path / "absent.sqlite")
    path = tmp_path / "present.sqlite"
    sqlite3.connect(path).execute("CREATE TABLE t (x)").connection.close()
    con = mod.open_readonly(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO t VALUES (1)")
    finally:
        con.close()
