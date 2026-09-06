"""Exposure / concentration analytics."""

from __future__ import annotations

import pytest

from signalforge.risk.portfolio import Holding, exposure_report


def test_exposure_breakdown() -> None:
    holdings = [
        Holding("AAPL", "Tech", 3_000.0),
        Holding("MSFT", "Tech", 2_000.0),
        Holding("XOM", "Energy", 1_000.0),
        Holding("SH", "Hedge", -1_000.0),  # short
    ]
    rep = exposure_report(holdings, account_equity=10_000.0)
    assert rep.gross_exposure == pytest.approx(7_000.0)
    assert rep.net_exposure == pytest.approx(5_000.0)
    assert rep.long_exposure == pytest.approx(6_000.0)
    assert rep.short_exposure == pytest.approx(1_000.0)
    assert rep.by_sector_pct["Tech"] == pytest.approx(50.0)
    assert rep.largest_position_symbol == "AAPL"
    assert rep.n_positions == 4


def test_empty_portfolio() -> None:
    rep = exposure_report([], account_equity=10_000.0)
    assert rep.gross_exposure == 0.0 and rep.n_positions == 0
