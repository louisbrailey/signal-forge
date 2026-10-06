"""Every price read on the options paper path names its source (PR #14 review).

The defect: ``_option_print`` selected ``option_aggregate_daily`` by ticker + date
with NO source filter (highest id won) and ``_underlying_close`` read bars with no
source filter. Under two vendors' rows that is a coin toss for the mark.

Every test here seeds TWO sources with DIFFERENT prices for the same tickers,
sessions and symbol, then asserts that the recorded source is the one read and
the rival is never read — and that a read which cannot name ONE source is a
REFUSAL (condition AC at entry, a ``paper.options_mark_refused`` audit row at
mark) rather than a guess. Everything is a fixture; nothing reads real data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    AuditLog,
    Instrument,
    OptionsMark,
    OptionsPosition,
    PaperPosition,
    PaperTrade,
)
from signalforge.domain import Horizon, PaperDecision, PositionSide
from signalforge.paper import options_eod as eod
from signalforge.paper.options_ledger import (
    OptionsAutoSimulateForbidden,
    PriceSourceUnresolved,
    _option_print,
    _underlying_close,
    assert_options_auto_simulate_allowed,
    leg_quote,
    structure_from_position,
)
from signalforge.paper.options_marks import (
    MARK_REFUSED_ACTION,
    mark_options_to_market,
    process_option_expiries,
    reconcile_options_collateral,
    resolve_underlying_sources,
)
from signalforge.paper.portfolio import portfolio_snapshot
from tests.paper import options_support as fx
from tests.paper.test_options_ledger import _open, _sessions_after, _world

#: The rival vendor. Its prints and bars are deliberately far from the fixture's
#: (1.20 / 0.70 at a 450 spot) so a wrong read cannot pass by coincidence.
RIVAL = "rival_vendor"
RIVAL_SHORT = 9.99
RIVAL_LONG = 9.00
RIVAL_SPOT = 460.0


def _seed_rival(session: Session, *, sessions: list, inst: Instrument | None = None) -> None:  # type: ignore[type-arg]
    """The SAME tickers, sessions and symbol under a second source label."""
    inst = inst or session.scalar(select(Instrument).where(Instrument.symbol == fx.UNDERLYING))
    assert inst is not None
    fx.underlying(session, instrument=inst, close=RIVAL_SPOT, source=RIVAL)
    fx.option_prints(
        session, sessions=sessions, short_close=RIVAL_SHORT, long_close=RIVAL_LONG, source=RIVAL
    )


def _refusals(session: Session) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).where(AuditLog.action == MARK_REFUSED_ACTION)))


# --------------------------------------------------------------------------- #
# The two primitive reads
# --------------------------------------------------------------------------- #


def test_the_print_read_takes_ONLY_the_named_source_and_refuses_to_guess(
    session: Session,
) -> None:
    fx.underlying(session)
    fx.contracts(session)
    fx.option_prints(session, sessions=[fx.FILL_SESSION])
    _seed_rival(session, sessions=[fx.FILL_SESSION])

    assert _option_print(session, fx.SHORT_TICKER, fx.FILL_SESSION, source="fixture") == 1.20
    assert _option_print(session, fx.SHORT_TICKER, fx.FILL_SESSION, source=RIVAL) == RIVAL_SHORT
    # a source that holds no row is an ABSENCE, never a fall-through to another
    assert _option_print(session, fx.SHORT_TICKER, fx.FILL_SESSION, source="nowhere") is None
    with pytest.raises(PriceSourceUnresolved, match="no option-data source"):
        _option_print(session, fx.SHORT_TICKER, fx.FILL_SESSION, source="")


def test_the_close_read_takes_ONLY_the_named_source_and_refuses_to_guess(
    session: Session,
) -> None:
    fx.underlying(session)
    _seed_rival(session, sessions=[])

    assert _underlying_close(session, fx.UNDERLYING, fx.FILL_SESSION, source="fixture") == fx.SPOT
    assert _underlying_close(session, fx.UNDERLYING, fx.FILL_SESSION, source=RIVAL) == RIVAL_SPOT
    assert _underlying_close(session, fx.UNDERLYING, fx.FILL_SESSION, source="nowhere") is None
    with pytest.raises(PriceSourceUnresolved, match="no underlying-bar source"):
        _underlying_close(session, fx.UNDERLYING, fx.FILL_SESSION, source="   ")


def test_a_leg_quote_never_mixes_the_structures_spot_source_with_the_contexts(
    session: Session,
) -> None:
    from signalforge.paper.options_ledger import LegSpec

    fx.underlying(session)
    fx.contracts(session)
    fx.option_prints(session, sessions=[fx.FILL_SESSION])
    _seed_rival(session, sessions=[fx.FILL_SESSION])
    leg = LegSpec(fx.SHORT_TICKER, "put", fx.SHORT_STRIKE, fx.EXPIRY, -1, 100, "american")

    q = leg_quote(
        session,
        leg,
        underlying_symbol=fx.UNDERLYING,
        as_of=fx.FILL_SESSION,
        pricing=fx.pricing(),
        option_source="fixture",
        underlying_source="fixture",
    )
    assert (q.print_close, q.underlying_close) == (1.20, fx.SPOT)

    # the structure says 'fixture', the context's spot came from the rival
    with pytest.raises(PriceSourceUnresolved, match="never computed off one vendor's spot"):
        leg_quote(
            session,
            leg,
            underlying_symbol=fx.UNDERLYING,
            as_of=fx.FILL_SESSION,
            pricing=fx.pricing(underlying_source=RIVAL),
            option_source="fixture",
            underlying_source="fixture",
        )
    for kw in ({"option_source": ""}, {"underlying_source": ""}):
        with pytest.raises(PriceSourceUnresolved):
            leg_quote(
                session,
                leg,
                underlying_symbol=fx.UNDERLYING,
                as_of=fx.FILL_SESSION,
                pricing=fx.pricing(),
                **{"option_source": "fixture", "underlying_source": "fixture", **kw},
            )


# --------------------------------------------------------------------------- #
# Entry: condition AC and the recorded provenance
# --------------------------------------------------------------------------- #


def test_an_entry_fills_from_the_recorded_source_and_records_both_labels(
    session: Session,
) -> None:
    cand, _ = _world(session)
    _seed_rival(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION])

    res = _open(session, cand)
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    assert position.option_source == "fixture"
    assert position.underlying_source == "fixture"
    prints = {leg.option_ticker: float(leg.entry_print) for leg in position.legs}
    assert prints == {
        fx.SHORT_TICKER: 1.20,
        fx.LONG_TICKER: 0.70,
    }, "the rival's 9.99 was never read"

    structure = structure_from_position(position)
    assert (structure.option_source, structure.underlying_source) == ("fixture", "fixture")
    trade_snapshot = session.scalar(
        select(PaperTrade.id).where(PaperTrade.id == -1)
    )  # (options trades live in options_trade; the equity table is untouched)
    assert trade_snapshot is None


def test_condition_AC_refuses_an_entry_whose_snapshot_names_no_option_source(
    session: Session,
) -> None:
    """The option-data label is read from the scan's DataSnapshot by the SAME
    resolver PR #14 gave the evidence path; a snapshot that records none is a
    refusal, never a fall-through to the bar label or to 'whatever is stored'."""
    acct = fx.options_account(session)
    inst = fx.underlying(session)
    fx.contracts(session)
    fx.option_prints(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION])
    ver = fx.approved_strategy(session)
    cand = fx.options_candidate(session, instrument=inst, version=ver)
    fx.approve_scope(session, cand, ver, snapshot_key="no-option-source", option_source=None)
    fx.clean_reconcile_report(session, acct, as_of=fx.FILL_SESSION)
    from signalforge.paper.options_ledger import (
        OPTIONS_AUTO_SIM_CAP_KEY,
        OPTIONS_AUTO_SIM_ENABLED_KEY,
    )
    from signalforge.settings_store import set_setting

    set_setting(session, OPTIONS_AUTO_SIM_ENABLED_KEY, True)
    set_setting(session, OPTIONS_AUTO_SIM_CAP_KEY, 2)

    with pytest.raises(OptionsAutoSimulateForbidden) as exc:
        _open(session, cand)
    assert exc.value.condition == "AC"
    assert "names no option-data source" in str(exc.value)
    assert session.scalar(select(OptionsPosition.id)) is None


def test_condition_AC_refuses_a_pricing_context_whose_spot_came_from_another_source(
    session: Session,
) -> None:
    cand, _ = _world(session)
    _seed_rival(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION])
    with pytest.raises(OptionsAutoSimulateForbidden) as exc:
        assert_options_auto_simulate_allowed(
            session,
            cand,
            account_name=fx.OPTIONS_ACCOUNT,
            pricing=fx.pricing(underlying_source=RIVAL),
            signal_session=fx.SIGNAL_SESSION,
            fill_session=fx.FILL_SESSION,
        )
    assert exc.value.condition == "AC"
    assert RIVAL in str(exc.value) and "fixture" in str(exc.value)


# --------------------------------------------------------------------------- #
# Marks, expiry and reconciliation: the recorded source, or a refusal ROW
# --------------------------------------------------------------------------- #


def test_a_mark_reads_the_recorded_source_and_never_the_rival(session: Session) -> None:
    cand, _ = _world(session)
    _open(session, cand)
    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    fx.option_prints(session, sessions=[nxt])  # unchanged prints -> net premium stays 50
    _seed_rival(session, sessions=[nxt])

    res = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt, pricing=fx.resolver()
    )
    assert res.checked == 1 and res.mark_refused == 0 and res.closed == 0
    mark = session.scalar(select(OptionsMark).where(OptionsMark.as_of == nxt))
    assert mark is not None
    # -(-1 x 1.20 + 1 x 0.70) x 100 = 50.00 from the fixture; the rival would give 99
    assert float(mark.net_premium) == pytest.approx(50.0)
    assert mark.legs_priced == 2 and not mark.synthetic
    assert _refusals(session) == []


def test_a_position_with_no_recorded_option_source_is_REFUSED_a_mark_as_a_row(
    session: Session,
) -> None:
    cand, _ = _world(session)
    res = _open(session, cand)
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    position.option_source = ""  # the state a pre-provenance row would be in
    session.flush()
    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    fx.option_prints(session, sessions=[nxt])

    before = session.scalar(select(OptionsMark.id))
    res2 = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt, pricing=fx.resolver()
    )
    assert res2.checked == 1
    assert res2.mark_refused == 1 and res2.refused_position_ids == [position.id]
    assert res2.closed == 0 and res2.unpriceable == 0
    assert session.scalar(select(OptionsMark.id)) == before, "no mark was written"
    assert position.closed_at is None, "not closed either"

    rows = _refusals(session)
    assert len(rows) == 1
    row = rows[0]
    assert row.entity == f"options_position:{position.id}"
    assert row.after_json["stage"] == "mark"
    assert row.after_json["as_of"] == nxt.isoformat()
    assert "records no option-data source" in row.after_json["reason"]
    assert (
        row.after_json["option_source"] == "" and row.after_json["underlying_source"] == "fixture"
    )
    assert row.after_json["simulated"] is True

    # ...and the session's reconciliation says so twice: unmarked (11) and unrecorded (12)
    recon = reconcile_options_collateral(session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt)
    checks = {f["check"] for f in recon.findings}
    assert recon.clean is False
    assert "12_price_sources_recorded" in checks
    assert "11_open_structure_marked_this_session" in checks


def test_a_mark_is_refused_when_the_contexts_spot_source_is_not_the_positions(
    session: Session,
) -> None:
    cand, _ = _world(session)
    _open(session, cand)
    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    fx.option_prints(session, sessions=[nxt])
    _seed_rival(session, sessions=[nxt])

    res = mark_options_to_market(
        session,
        account_name=fx.OPTIONS_ACCOUNT,
        as_of=nxt,
        pricing=fx.resolver(contexts={fx.UNDERLYING: fx.pricing(underlying_source=RIVAL)}),
    )
    assert res.mark_refused == 1 and res.checked == 1
    assert session.scalar(select(OptionsMark).where(OptionsMark.as_of == nxt)) is None
    (row,) = _refusals(session)
    assert RIVAL in row.after_json["reason"] and "fixture" in row.after_json["reason"]


def test_expiry_processing_refuses_the_same_way_and_settles_nothing(session: Session) -> None:
    cand, _ = _world(session)
    res = _open(session, cand)
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    position.underlying_source = ""
    session.flush()
    on_expiry = fx.EXPIRY  # at/past the last trade session: the settlement branch
    _seed_rival(session, sessions=[on_expiry])

    report = process_option_expiries(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=on_expiry, pricing=fx.resolver()
    )
    assert report.checked == 1
    assert report.mark_refused == 1 and report.refused_position_ids == [position.id]
    assert report.expired_worthless == 0 and report.assigned == 0 and report.force_closed == 0
    assert position.closed_at is None
    (row,) = _refusals(session)
    assert row.after_json["stage"] == "expiry"
    assert "records no underlying-bar source" in row.after_json["reason"]


# --------------------------------------------------------------------------- #
# The EOD chain's per-name spot source
# --------------------------------------------------------------------------- #


def test_the_spot_source_is_the_RECORDED_one_even_when_two_sources_hold_bars(
    session: Session,
) -> None:
    cand, _ = _world(session)
    _open(session, cand)
    _seed_rival(session, sessions=[fx.FILL_SESSION])
    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]

    sources = resolve_underlying_sources(
        session,
        frozenset({fx.UNDERLYING}),
        as_of=nxt,
        account_name=fx.OPTIONS_ACCOUNT,
        signal_session=fx.FILL_SESSION,
    )
    assert sources.resolved == {fx.UNDERLYING: "fixture"}
    assert sources.refused == {}


def test_with_nothing_recorded_two_stored_sources_refuse_the_name_by_name(
    session: Session,
) -> None:
    """Nothing open and nothing proposed: the only witnesses are the bars, and two
    labels is an ambiguity, not a choice. This is the live database's SPY."""
    fx.underlying(session)
    _seed_rival(session, sessions=[])

    sources = resolve_underlying_sources(
        session,
        frozenset({fx.UNDERLYING}),
        as_of=fx.FILL_SESSION,
        account_name=fx.OPTIONS_ACCOUNT,
        signal_session=fx.SIGNAL_SESSION,
    )
    assert sources.resolved == {}
    assert "never guessed" in sources.refused[fx.UNDERLYING]
    assert "fixture" in sources.refused[fx.UNDERLYING] and RIVAL in sources.refused[fx.UNDERLYING]

    resolved = eod._options_eod_pricing(
        session, underlyings=frozenset({fx.UNDERLYING}), as_of=fx.FILL_SESSION
    )
    assert resolved.unpriceable_underlyings == (fx.UNDERLYING,)
    with pytest.raises(eod.OptionsEodUnpriceable, match="never guessed"):
        resolved(fx.UNDERLYING, fx.FILL_SESSION)


def test_a_blank_recorded_source_on_an_open_structure_refuses_the_name(session: Session) -> None:
    cand, _ = _world(session)
    res = _open(session, cand)
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    position.underlying_source = ""
    session.flush()
    sources = resolve_underlying_sources(
        session,
        frozenset({fx.UNDERLYING}),
        as_of=fx.FILL_SESSION,
        account_name=fx.OPTIONS_ACCOUNT,
        signal_session=fx.SIGNAL_SESSION,
    )
    assert fx.UNDERLYING in sources.refused
    assert "records NO bar source" in sources.refused[fx.UNDERLYING]


def test_the_eod_pricing_context_carries_the_source_its_spot_was_read_from(
    session: Session,
) -> None:
    from signalforge.db.models import DividendEvent

    fx.underlying(session)
    session.add(
        DividendEvent(
            symbol=fx.UNDERLYING,
            ex_dividend_date=fx.SIGNAL_SESSION - timedelta(days=60),
            cash_amount=1.50,
            source="massive_options",
            ingested_at=datetime.now(UTC),
        )
    )
    session.flush()
    resolved = eod._options_eod_pricing(
        session, underlyings=frozenset({fx.UNDERLYING}), as_of=fx.FILL_SESSION
    )
    assert resolved(fx.UNDERLYING, fx.FILL_SESSION).underlying_source == "fixture"


# --------------------------------------------------------------------------- #
# The EQUITY paper path has the same defect at ``portfolio_snapshot``
# --------------------------------------------------------------------------- #


def _equity_position(session: Session, inst: Instrument, *, source: str | None) -> PaperPosition:
    acct = fx.equity_account(session)
    opened = datetime.combine(fx.SIGNAL_SESSION, datetime.min.time(), tzinfo=UTC)
    pos = PaperPosition(
        account_id=acct.id,
        instrument_id=inst.id,
        horizon=Horizon.MEDIUM_SWING,
        side=PositionSide.LONG,
        qty=10,
        avg_price=Decimal("440"),
        stop_level=420.0,
        target_level=480.0,
        time_stop_date=opened + timedelta(days=40),
        opened_at=opened,
    )
    session.add(pos)
    session.flush()
    if source is not None:
        session.add(
            PaperTrade(
                account_id=acct.id,
                position_id=pos.id,
                decision=PaperDecision.ACCEPTED,
                signal_snapshot_json={"scan": {"source": source}, "symbol": inst.symbol},
                plan_json={"shares": 10},
                actor="test",
                created_at=opened,
            )
        )
        session.flush()
    return pos


def test_the_equity_portfolio_prices_from_the_positions_recorded_source(
    session: Session,
) -> None:
    inst = fx.underlying(session)
    _seed_rival(session, sessions=[], inst=inst)
    _equity_position(session, inst, source=RIVAL)

    snap = portfolio_snapshot(session, account_name="default", as_of=fx.FILL_SESSION)
    (row,) = snap["open_positions"]
    assert row["last_price"] == RIVAL_SPOT, "the recorded source, not the highest id"


def test_the_equity_portfolio_fails_closed_on_two_sources_without_provenance(
    session: Session,
) -> None:
    """A legacy acceptance with no recorded source may still be priced when ONE
    source holds the bars; two sources for the same session is ambiguous and a
    number would be a guess — the same rule the equity mark already applies."""
    inst = fx.underlying(session)
    _equity_position(session, inst, source=None)
    snap = portfolio_snapshot(session, account_name="default", as_of=fx.FILL_SESSION)
    assert snap["open_positions"][0]["last_price"] == fx.SPOT

    _seed_rival(session, sessions=[], inst=inst)
    with pytest.raises(ValueError, match="ambiguous paper mark sources"):
        portfolio_snapshot(session, account_name="default", as_of=fx.FILL_SESSION)
