"""Gate 0.g reads the DERIVED ``q`` series over the pre-sealed span.

``_q_by_underlying`` used to compute one trailing yield ``as_of window.end`` —
a sealed-window date — and could say nothing about the sessions the strategy
actually priced on.  It now summarises ``dividend_yield_daily`` on
``[window.start, window.pre_sealed_end]`` per underlying.  The gate's own
semantics are unchanged: a sourced series with every traded session covered
passes; no series, an unsourced record or an uncovered traded session fails.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from signalforge.data.options_corporate_actions import q_series_digest
from signalforge.db.models import DividendYieldDaily, IngestionRun
from signalforge.db.types import utcnow
from signalforge.domain import FeedType
from signalforge.research.options_evidence import _q_by_underlying, _q_series_provenance
from signalforge.research.options_gates import OptionsWindow, gate_0g_dividend_yield
from tests.research import options_gate_support as sup

# The synthetic cycle trades in Feb-Mar 2024; this window puts that on the
# PRE-SEALED span, with a sealed half-year after it.
WINDOW = OptionsWindow(
    start=date(2023, 6, 1),
    pre_sealed_end=date(2024, 6, 30),
    sealed_start=date(2024, 7, 1),
    end=date(2024, 12, 31),
)


def _seed_series(
    session: Session,
    symbol: str,
    sessions: list[date],
    *,
    q: float = 0.013,
    source: str = "vendor_dividends",
) -> None:
    for d in sessions:
        session.add(
            DividendYieldDaily(
                symbol=symbol,
                session_date=d,
                q=q,
                source=source,
                payments=4,
                window_start=d - timedelta(days=365),
                reference_close=505.0,
            )
        )
    session.flush()


def test_sourced_series_covering_every_traded_session_passes(session: Session) -> None:
    trades = list(sup.dual_report().baseline.trades)
    assert trades, "the synthetic cycle must produce a trade for the test to mean anything"
    entry_sessions = sorted({t.entry_date for t in trades})
    assert all(WINDOW.start <= d <= WINDOW.pre_sealed_end for d in entry_sessions)

    _seed_series(session, "SPY", [*entry_sessions, WINDOW.pre_sealed_end])
    # a row INSIDE the sealed window exists and must not be read
    _seed_series(session, "SPY", [WINDOW.end], q=9.9)

    q_map, defaulted = _q_by_underlying(session, ["SPY"], window=WINDOW, trades=trades)
    assert defaulted == 0
    rec = q_map["SPY"]
    assert rec["source"] == "vendor_dividends"
    assert rec["value"] == 0.013  # the sealed-window 9.9 never surfaces
    assert rec["as_of"] == WINDOW.pre_sealed_end.isoformat()
    assert rec["first_session"] == entry_sessions[0].isoformat()
    assert rec["sessions_covered"] == len(entry_sessions) + 1
    assert rec["sessions_traded"] == len(entry_sessions)
    assert rec["sessions_traded_uncovered"] == []

    gate = gate_0g_dividend_yield(sup.availability(q_by_underlying=q_map, q_defaulted_count=0))
    assert gate.passed, gate.detail
    assert gate.evidence["q_by_underlying"]["SPY"]["span_end"] == rec["span_end"]


def test_no_series_on_the_pre_sealed_span_is_defaulted_and_fails(session: Session) -> None:
    trades = list(sup.dual_report().baseline.trades)
    # only a sealed-window row: nothing on the pre-sealed span
    _seed_series(session, "SPY", [WINDOW.end])

    q_map, defaulted = _q_by_underlying(session, ["SPY"], window=WINDOW, trades=trades)
    assert q_map == {} and defaulted == 1
    gate = gate_0g_dividend_yield(
        sup.availability(q_by_underlying=q_map, q_defaulted_count=defaulted)
    )
    assert not gate.passed
    assert "DEFAULTED" in gate.detail and "no q at all for ['SPY']" in gate.detail


def test_a_traded_session_without_a_row_counts_as_defaulted(session: Session) -> None:
    """A series that exists but has a hole on an entry session is exactly the
    case where the pricer would have fallen through to q = 0.0."""
    trades = list(sup.dual_report().baseline.trades)
    entry = min(t.entry_date for t in trades)
    _seed_series(session, "SPY", [entry + timedelta(days=1), WINDOW.pre_sealed_end])

    q_map, defaulted = _q_by_underlying(session, ["SPY"], window=WINDOW, trades=trades)
    assert defaulted == 1
    assert q_map["SPY"]["sessions_traded_uncovered"] == [entry.isoformat()]
    gate = gate_0g_dividend_yield(
        sup.availability(q_by_underlying=q_map, q_defaulted_count=defaulted)
    )
    assert not gate.passed


def test_a_series_under_another_source_is_not_a_source_for_this_gate(session: Session) -> None:
    trades = list(sup.dual_report().baseline.trades)
    _seed_series(
        session, "SPY", sorted({t.entry_date for t in trades}), source="somebody_elses_guess"
    )
    q_map, defaulted = _q_by_underlying(session, ["SPY"], window=WINDOW, trades=trades)
    assert q_map == {} and defaulted == 1


# --- symbol case (review item D) ---------------------------------------------- #
def test_a_lower_case_underlying_cannot_skip_the_traded_session_check(session: Session) -> None:
    """The query upper-cased the symbol but the traded-session lookup did not, so
    ``"spy"`` found its rows, found NO traded sessions and passed with a hole."""
    trades = list(sup.dual_report().baseline.trades)
    entry = min(t.entry_date for t in trades)
    _seed_series(session, "SPY", [entry + timedelta(days=1), WINDOW.pre_sealed_end])

    q_map, defaulted = _q_by_underlying(session, ["spy"], window=WINDOW, trades=trades)
    assert defaulted == 1
    assert set(q_map) == {"SPY"}  # one normalised key, the one gate 0.g compares
    assert q_map["SPY"]["sessions_traded"] == len({t.entry_date for t in trades})
    assert q_map["SPY"]["sessions_traded_uncovered"] == [entry.isoformat()]
    upper = _q_by_underlying(session, ["SPY"], window=WINDOW, trades=trades)
    assert (q_map, defaulted) == upper


# --- provenance (review item B) ----------------------------------------------- #
def _seed_q_run(session: Session) -> IngestionRun:
    run = IngestionRun(
        provider="massive_options",
        feed_type=FeedType.CORP_ACTION,
        kind="options_q_series",
        requested_start=WINDOW.start,
        requested_end=WINDOW.end,
        adjusted=False,
        symbols_requested=["SPY"],
        status="ok",
        started_at=utcnow(),
    )
    session.add(run)
    session.flush()
    return run


def test_digest_distinguishes_empty_from_populated_and_tracks_changes(session: Session) -> None:
    lo, hi = WINDOW.start, WINDOW.pre_sealed_end
    empty = q_series_digest(session, ["SPY"], lo, hi, "vendor_dividends")
    assert len(empty) == 64
    assert empty == q_series_digest(session, ["spy", "SPY"], lo, hi, "vendor_dividends")

    _seed_series(session, "SPY", [date(2024, 2, 1)])
    one = q_series_digest(session, ["SPY"], lo, hi, "vendor_dividends")
    assert one != empty
    assert one == q_series_digest(session, ["SPY"], lo, hi, "vendor_dividends")  # deterministic

    # rows outside the span, under another symbol or another source do not move it
    _seed_series(session, "SPY", [WINDOW.end])
    _seed_series(session, "QQQ", [date(2024, 2, 1)])
    _seed_series(session, "IWM", [date(2024, 2, 1)], source="somebody_elses_guess")
    assert q_series_digest(session, ["SPY"], lo, hi, "vendor_dividends") == one
    assert q_series_digest(session, ["IWM"], lo, hi, "vendor_dividends") == empty

    # a re-derived value on the span does
    row = session.query(DividendYieldDaily).filter_by(symbol="SPY").first()
    assert row is not None
    row.q = 0.0131
    session.flush()
    assert q_series_digest(session, ["SPY"], lo, hi, "vendor_dividends") != one


def test_gate_0g_evidence_records_the_series_digest_and_derivation_run(
    session: Session,
) -> None:
    trades = list(sup.dual_report().baseline.trades)
    entry_sessions = sorted({t.entry_date for t in trades})

    # no series, no derivation: the fields are present and say exactly that
    digest0, run0 = _q_series_provenance(session, ["SPY"], window=WINDOW)
    assert run0 is None and len(digest0) == 64

    first_run = _seed_q_run(session)
    _seed_series(session, "SPY", entry_sessions)
    digest1, run1 = _q_series_provenance(session, ["SPY"], window=WINDOW)
    assert run1 == first_run.id and digest1 != digest0

    q_map, defaulted = _q_by_underlying(session, ["SPY"], window=WINDOW, trades=trades)
    gate = gate_0g_dividend_yield(
        sup.availability(
            q_by_underlying=q_map,
            q_defaulted_count=defaulted,
            q_series_digest=digest1,
            q_series_run_id=run1,
        )
    )
    assert gate.passed, gate.detail
    assert gate.evidence["q_series_digest"] == digest1
    assert gate.evidence["q_series_run_id"] == first_run.id

    # the series is re-derived: same snapshot, different evidence
    second_run = _seed_q_run(session)
    for row in session.query(DividendYieldDaily).filter_by(symbol="SPY"):
        row.q = 0.0125
    session.flush()
    digest2, run2 = _q_series_provenance(session, ["SPY"], window=WINDOW)
    assert run2 == second_run.id != first_run.id
    assert digest2 not in {digest0, digest1}
    regate = gate_0g_dividend_yield(
        sup.availability(
            q_by_underlying=q_map,
            q_defaulted_count=defaulted,
            q_series_digest=digest2,
            q_series_run_id=run2,
        )
    )
    assert regate.evidence["q_series_digest"] != gate.evidence["q_series_digest"]
    assert regate.evidence["q_series_run_id"] != gate.evidence["q_series_run_id"]
