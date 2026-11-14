from datetime import date

from signalforge.agents.portfolio_risk import _max_abs_correlation
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries


def _series(symbol, rows):
    return PriceSeries.from_bars(
        symbol, [(day, close, close, close, close, 1000) for day, close in rows]
    )


def test_correlation_uses_only_common_consecutive_session_intervals(monkeypatch, session):
    days = sessions(date(2024, 1, 2), date(2024, 4, 30))
    rows = [(day, 100 + (i % 7) + i / 10) for i, day in enumerate(days)]
    # Omit a session within the overlap, plus one at each end of one series.
    # Each deletion inside the overlap removes both incident return intervals.
    a = _series("A", rows)
    b = _series(
        "B", [(d, 2 * p) for i, (d, p) in enumerate(rows) if i not in (0, 50, len(rows) - 1)]
    )
    data = {"A": a, "B": b}
    monkeypatch.setattr(PriceSeries, "load", lambda db, symbol, *args, **kw: data[symbol])

    result = _max_abs_correlation(session, ["B", "A", "A"], "massive", end=days[-1])
    assert result == {
        "symbols": ["A", "B"],
        "corr": 1.0,
        "sample_count": 60,
        "common_return_count": len(days) - 5,
        "first_close_session": days[-64].isoformat(),
        "last_close_session": days[-2].isoformat(),
    }


def test_correlation_omits_staggered_series_with_insufficient_overlap(monkeypatch, session):
    days = sessions(date(2024, 1, 2), date(2024, 5, 17))
    rows = [(day, 100 + i % 7) for i, day in enumerate(days)]
    data = {"A": _series("A", rows[:65]), "B": _series("B", rows[-65:])}
    monkeypatch.setattr(PriceSeries, "load", lambda db, symbol, *args, **kw: data[symbol])

    assert _max_abs_correlation(session, ["A", "B"], "massive", end=days[-1]) is None
