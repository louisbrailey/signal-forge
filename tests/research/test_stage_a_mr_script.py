"""``scripts/stage_a_mr.py`` — the read-only tripwire and the variant wrapper.

No database, no provider, no sealed window: the live-path refusal is a pure
path check, and the wrapper identity is checked on a tiny synthetic series
through the public engine.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import run_backtest
from signalforge.data.series import PriceSeries
from signalforge.research.regime import RegimeState, Trend, Vol
from signalforge.research.strategies.base import signal_fn_for
from signalforge.research.strategies.mean_reversion import MeanReversion

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "stage_a_mr.py"


def _load_script() -> object:
    spec = importlib.util.spec_from_file_location("stage_a_mr", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stage_a_mr"] = mod
    spec.loader.exec_module(mod)
    return mod


def _series(n: int = 260, seed: int = 7) -> PriceSeries:
    """A choppy series with periodic sharp down days and overnight gaps, so the
    mean-reversion rule fires and the fill differs from the signal close."""
    rng = np.random.default_rng(seed)
    rows = []
    d = date(2021, 1, 4)
    c = 100.0
    for i in range(n):
        shock = -4.0 if i % 23 == 0 and i > 40 else 0.0
        c = max(10.0, c + float(rng.normal(0.0, 0.8)) + shock)
        o = c + float(rng.normal(0.0, 0.6))
        h = max(o, c) + abs(float(rng.normal(0, 0.5))) + 0.05
        lo = min(o, c) - abs(float(rng.normal(0, 0.5))) - 0.05
        rows.append((d, o, h, lo, c, 1_000_000.0))
        d += timedelta(days=1)
    return PriceSeries.from_bars("SYN", rows)


def test_refuses_the_live_database_path(tmp_path: Path) -> None:
    mod = _load_script()
    with pytest.raises(mod.StageAViolation, match="LIVE database"):  # type: ignore[attr-defined]
        mod.refuse_live_db(mod.LIVE_DB_PATH)  # type: ignore[attr-defined]
    with pytest.raises(mod.StageAViolation, match="LIVE database"):  # type: ignore[attr-defined]
        mod.main(["--db", str(mod.LIVE_DB_PATH), "--emit", str(tmp_path / "x.json")])  # type: ignore[attr-defined]
    with pytest.raises(mod.StageAViolation, match="does not exist"):  # type: ignore[attr-defined]
        mod.refuse_live_db(tmp_path / "missing.sqlite")  # type: ignore[attr-defined]
    copy = tmp_path / "copy.sqlite"
    copy.write_bytes(b"")
    assert mod.refuse_live_db(copy) == copy.resolve()  # type: ignore[attr-defined]
    assert "mode=ro" in mod.read_only_url(copy)  # type: ignore[attr-defined]


def test_wrapper_at_blend_zero_reproduces_v010_trades() -> None:
    mod = _load_script()
    series = _series()
    strat = MeanReversion()
    bull = RegimeState(Trend.BULL, Vol.LOW, date(2021, 1, 1))
    fn = signal_fn_for(strat, regime_by_date=dict.fromkeys(series.dates, bull))
    cm = CostModel()

    baseline = run_backtest(series, fn, cost_model=cm, warmup=30)
    assert len(baseline.trades) >= 3, "fixture must produce trades to be a test"

    records: dict[tuple[str, date], object] = {}
    degenerate = mod.run_variant(  # type: ignore[attr-defined]
        series,
        fn,
        stop_atr=strat.params.stop_atr,
        cost_model=cm,
        warmup=30,
        stop_anchor_blend=0.0,
        records=records,
    )
    assert mod._same_trades(baseline.trades, degenerate.trades)  # type: ignore[attr-defined]
    assert {(t.symbol, t.entry_date) for t in baseline.trades} <= set(records)

    # The non-degenerate V1 moves the stop to exactly stop_atr x ATR below the fill.
    v1_records: dict[tuple[str, date], object] = {}
    v1 = mod.run_variant(  # type: ignore[attr-defined]
        series,
        fn,
        stop_atr=strat.params.stop_atr,
        cost_model=cm,
        warmup=30,
        stop_anchor_blend=1.0,
        records=v1_records,
    )
    for tr in v1.trades:
        rec = v1_records[(tr.symbol, tr.entry_date)]
        assert abs((rec.raw_fill - rec.stop_level) - rec.stop_distance) < 1e-9  # type: ignore[attr-defined]
        assert not (tr.exit_reason == "stop" and tr.pnl_r > 0)
