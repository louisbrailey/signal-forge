"""``universe sectors``: derive ``instrument.sector`` from provider reference data.

Entirely offline — the provider is ``FakeMassiveAPI`` behind
``httpx.MockTransport``; no test here touches the network.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.db.models import Instrument, UniverseTicker
from signalforge.killswitch import get_kill_switch
from signalforge.universe import sectors as sectors_mod
from signalforge.universe.sectors import (
    SECTOR_ETF,
    SIC2_SECTOR,
    etf_sector,
    refresh_sectors,
    sector_from_sic,
    sector_status,
)
from tests.universe.test_universe_pipeline import FakeMassiveAPI, _ticker_row


def _inst(session: Session, symbol: str, kind: str = "stock", sector: str = "") -> Instrument:
    inst = Instrument(symbol=symbol, name=symbol, instrument_type=kind, sector=sector)
    session.add(inst)
    session.flush()
    return inst


def _sector(session: Session, symbol: str) -> str:
    session.expire_all()
    return session.scalar(select(Instrument.sector).where(Instrument.symbol == symbol)) or ""


# --------------------------------------------------------------------------- #
# the mapping tables
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "sic,expected",
    [
        ("7372", "Technology"),  # prepackaged software (MSFT): 737 overrides 73
        ("7389", "Industrials"),  # other business services stay in group 73
        ("3571", "Technology"),  # electronic computers (AAPL): 357 overrides 35
        ("3674", "Technology"),  # semiconductors (NVDA): group 36
        ("3711", "Consumer Discretionary"),  # motor vehicles (TSLA): 371 overrides 37
        ("3721", "Industrials"),  # aircraft: group 37
        ("2834", "Health Care"),  # pharmaceutical preparations: 283 overrides 28
        ("2810", "Materials"),  # industrial chemicals: group 28
        ("6021", "Financials"),
        ("6798", "Real Estate"),  # REITs: 6798 overrides 67
        ("4911", "Utilities"),
        ("1311", "Energy"),
        ("4813", "Communication Services"),
        ("5331", "Consumer Staples"),
        ("8742", "Industrials"),  # management consulting (ACN): group 87
        ("0100", "Consumer Staples"),
        ("100", "Consumer Staples"),  # leading zero lost -> 0100
    ],
)
def test_sector_from_sic(sic: str, expected: str) -> None:
    assert sector_from_sic(sic) == expected


@pytest.mark.parametrize("sic", ["", None, "7", "abcd", "0000", "8888"])
def test_unmappable_sic_is_blank_never_a_guess(sic: str | None) -> None:
    assert sector_from_sic(sic) == ""


def test_the_grouping_key_is_the_screens_two_digit_sic_group() -> None:
    """Same key as ``universe.screen`` (``sic_code[:2]``): every key is 2 digits."""
    assert all(len(k) == 2 and k.isdigit() for k in SIC2_SECTOR)


def test_sector_spdrs_map_to_their_sector_and_other_etfs_to_their_own_bucket() -> None:
    assert etf_sector("XLK") == "Technology" == SECTOR_ETF["XLK"]
    assert etf_sector("xlf") == "Financials"
    assert etf_sector("SPY") == "ETF:SPY"
    assert etf_sector("QQQ") == "ETF:QQQ"
    assert len(SECTOR_ETF) == 11  # the eleven sector SPDRs, in one table


# --------------------------------------------------------------------------- #
# refresh_sectors
# --------------------------------------------------------------------------- #


def test_refresh_uses_stored_sic_without_any_network(session: Session) -> None:
    _inst(session, "MSFT")
    _inst(session, "XLK", "etf")
    _inst(session, "SPY", "etf")
    _ticker_row(session, "MSFT", sic_code="7372")
    session.commit()
    api = FakeMassiveAPI()

    rep = refresh_sectors(session, api.client())

    assert api.calls == []  # stored SIC + ETFs need no request
    assert rep.requests == 0 and rep.updated == 3 and rep.unknown == 0
    assert _sector(session, "MSFT") == "Technology"
    assert _sector(session, "XLK") == "Technology"  # same bucket as MSFT
    assert _sector(session, "SPY") == "ETF:SPY"
    assert rep.by_sector == {"Technology": 2, "ETF:SPY": 1}


def test_refresh_fetches_ticker_details_for_missing_sic_and_stores_them(session: Session) -> None:
    _inst(session, "TSLA")
    _inst(session, "ACN")
    _inst(session, "NOSIC")
    _ticker_row(session, "TSLA")
    session.commit()
    api = FakeMassiveAPI()
    api.ticker_detail["TSLA"] = {
        "status": "OK",
        "results": {
            "ticker": "TSLA",
            "sic_code": "3711",
            "sic_description": "MOTOR VEHICLES & PASSENGER CAR BODIES",
        },
    }
    api.ticker_detail["ACN"] = {
        "status": "OK",
        "results": {"sic_code": "8742", "sic_description": "SERVICES-MANAGEMENT CONSULTING"},
    }

    rep = refresh_sectors(session, api.client())

    assert sorted(c.rsplit("/", 1)[-1] for c in api.calls) == ["ACN", "NOSIC", "TSLA"]
    assert _sector(session, "TSLA") == "Consumer Discretionary"
    assert _sector(session, "ACN") == "Industrials"
    # No SIC from the provider: left BLANK (the ledger caps it as UNKNOWN).
    assert _sector(session, "NOSIC") == ""
    assert rep.unknown == 1 and rep.requests == 3 and rep.failed == 0
    tsla = session.scalar(select(Instrument).where(Instrument.symbol == "TSLA"))
    assert tsla is not None and tsla.industry == "MOTOR VEHICLES & PASSENGER CAR BODIES"
    # The fetched SIC is persisted on universe_ticker, so the next run is offline.
    row = session.scalar(select(UniverseTicker).where(UniverseTicker.ticker == "TSLA"))
    assert row is not None and row.sic_code == "3711"
    api.calls.clear()
    again = refresh_sectors(session, api.client())
    assert [c.rsplit("/", 1)[-1] for c in api.calls] == ["ACN", "NOSIC"]  # TSLA is stored now
    assert again.updated == 0


def test_provider_type_etf_is_bucketed_as_an_etf(session: Session) -> None:
    _inst(session, "ARKK")  # mis-typed as a stock locally
    session.commit()
    api = FakeMassiveAPI()
    api.ticker_detail["ARKK"] = {"status": "OK", "results": {"ticker": "ARKK", "type": "ETF"}}
    refresh_sectors(session, api.client())
    assert _sector(session, "ARKK") == "ETF:ARKK"


def test_request_budget_is_respected_and_the_run_is_resumable(session: Session) -> None:
    for sym in ("AAA", "BBB", "CCC"):
        _inst(session, sym)
    session.commit()
    api = FakeMassiveAPI()
    for sym in ("AAA", "BBB", "CCC"):
        api.ticker_detail[sym] = {"status": "OK", "results": {"sic_code": "6021"}}

    rep = refresh_sectors(session, api.client(), max_requests=2)
    assert rep.requests == 2 and rep.skipped_budget == 1 and rep.unknown == 1
    assert [_sector(session, s) for s in ("AAA", "BBB", "CCC")] == ["Financials", "Financials", ""]

    rep2 = refresh_sectors(session, api.client(), max_requests=2, only_missing=True)
    assert rep2.requests == 1 and rep2.unknown == 0
    assert _sector(session, "CCC") == "Financials"


def test_provider_failure_for_one_ticker_does_not_stop_the_run_or_blank_a_label(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _inst(session, "BAD", sector="Energy")
    _inst(session, "GOOD")
    session.commit()
    api = FakeMassiveAPI()
    api.ticker_detail["GOOD"] = {"status": "OK", "results": {"sic_code": "4911"}}
    client = api.client()
    real = client.get_json

    def flaky(path: str) -> dict:
        if path.endswith("/BAD"):
            raise RuntimeError("boom")
        return real(path)

    monkeypatch.setattr(client, "get_json", flaky)
    rep = refresh_sectors(session, client)
    assert rep.failed == 1
    assert _sector(session, "BAD") == "Energy"  # an existing label is never blanked
    assert _sector(session, "GOOD") == "Utilities"


def test_no_transaction_is_open_during_a_network_call(session: Session) -> None:
    """SQLite rule (db/session.py): no writer holds a transaction across network I/O."""
    _inst(session, "AAA")
    _inst(session, "BBB")
    session.commit()
    api = FakeMassiveAPI()
    api.ticker_detail["AAA"] = {"status": "OK", "results": {"sic_code": "6021"}}
    api.ticker_detail["BBB"] = {"status": "OK", "results": {"sic_code": "1311"}}
    client = api.client()
    real = client.get_json
    seen: list[bool] = []

    def spy(path: str) -> dict:
        seen.append(session.in_transaction())
        return real(path)

    client.get_json = spy  # type: ignore[method-assign]
    refresh_sectors(session, client)
    assert seen == [False, False]


def test_each_instrument_is_its_own_write_unit_retried_on_lock(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _inst(session, "XLE", "etf")
    _inst(session, "XLU", "etf")
    session.commit()
    real_commit = session.commit
    state = {"fail": 1, "commits": 0}

    def commit() -> None:
        # the first WRITE commit hits a transient lock once
        if session.dirty and state["fail"]:
            state["fail"] -= 1
            raise OperationalError("UPDATE", {}, Exception("database is locked"))
        state["commits"] += 1
        real_commit()

    monkeypatch.setattr(session, "commit", commit)
    slept: list[float] = []
    real_retry = sectors_mod.retry_on_lock
    monkeypatch.setattr(
        sectors_mod,
        "retry_on_lock",
        lambda fn, **kw: real_retry(fn, sleep=slept.append, **kw),
    )

    rep = refresh_sectors(session, None)

    assert slept == [0.5]  # exactly one retry, of one unit
    assert rep.updated == 2
    assert _sector(session, "XLE") == "Energy" and _sector(session, "XLU") == "Utilities"


def test_client_none_never_touches_the_network_and_leaves_unknown_blank(session: Session) -> None:
    _inst(session, "ZZZ")
    session.commit()
    rep = refresh_sectors(session, None)
    assert rep.requests == 0 and rep.skipped_budget == 1 and rep.unknown == 1
    assert _sector(session, "ZZZ") == ""


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_without_refresh_is_read_only_status(session: Session, db_url: str) -> None:
    _inst(session, "MSFT", sector="Technology")
    _inst(session, "ZZZ")
    session.commit()
    result = CliRunner().invoke(app, ["universe", "sectors"])
    assert result.exit_code == 0, result.output
    assert '"Technology": 1' in result.output and '"UNKNOWN": 1' in result.output
    assert "read-only status" in result.output
    assert sector_status(session) == {"Technology": 1, "UNKNOWN": 1}


def test_cli_refresh_is_blocked_by_the_kill_switch(
    session: Session, db_url: str, isolated_data_dir: object
) -> None:
    _inst(session, "XLK", "etf")
    session.commit()
    # Kill-switch state lives in the per-test data dir (autouse fixture): no release needed.
    get_kill_switch().engage(reason="halt", actor="pytest")
    result = CliRunner().invoke(app, ["universe", "sectors", "--refresh"])
    assert result.exit_code != 0
    assert _sector(session, "XLK") == ""


def test_cli_refresh_populates_sectors_offline(
    session: Session, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _inst(session, "XLK", "etf")
    _inst(session, "MSFT")
    session.commit()
    api = FakeMassiveAPI()
    api.ticker_detail["MSFT"] = {"status": "OK", "results": {"sic_code": "7372"}}
    import signalforge.universe.bulk as bulk

    monkeypatch.setattr(bulk, "GroupedDailyClient", lambda **_kw: api.client())
    result = CliRunner().invoke(app, ["universe", "sectors", "--refresh"])
    assert result.exit_code == 0, result.output
    assert "no order was placed" in result.output
    session.rollback()
    assert _sector(session, "XLK") == "Technology" and _sector(session, "MSFT") == "Technology"
