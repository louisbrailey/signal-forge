"""Separate equity paper books per PAPER_APPROVED strategy version.

Operator decision 2026-10-03 (paper only). One book per approved version: the
same symbol may be held by two versions at once, every cap and the daily
auto-simulation cap is per book, and auto-simulation decides books in
strategy-version-id order, candidates by rank then id — never by the horizon
string. Entirely offline: bars are fixtures, no provider is contacted.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    AuditLog,
    Candidate,
    DataSnapshot,
    Instrument,
    PaperAccount,
    PaperPosition,
    PaperTrade,
    ScanRun,
    Strategy,
    StrategyPromotionEvaluation,
    StrategyVersion,
)
from signalforge.domain import Direction, Horizon, PaperDecision, QualityGate, StrategyStatus
from signalforge.paper.auto_simulate import AUTO_SIM_CAP_KEY, auto_simulate_scan_runs
from signalforge.paper.books import (
    LEGACY_ACCOUNT,
    MANUAL_ACCOUNT,
    book_for_candidate,
    book_for_version,
    book_name,
    equity_books,
)
from signalforge.paper.ledger import accept_candidate, mark_to_market, record_decision
from signalforge.paper.portfolio import portfolio_snapshot
from signalforge.research import approval_scope as scope_mod
from signalforge.settings_store import set_setting
from tests.paper.test_auto_simulate import SPEC_HASH, _bars

SYMBOLS = ("AAPL", "MSFT", "NVDA")


@pytest.fixture
def scope_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scope_mod, "current_spec_json_hash", lambda _s, _v: SPEC_HASH)


def _version(
    session: Session, name: str, horizon: Horizon, snap: DataSnapshot, status: StrategyStatus
) -> StrategyVersion:
    strat = Strategy(name=name, horizon=horizon, status=status)
    session.add(strat)
    session.flush()
    ver = StrategyVersion(
        strategy_id=strat.id, version="0.1.0", status=status, spec_json={}, git_sha="test"
    )
    session.add(ver)
    session.flush()
    if status is StrategyStatus.PAPER_APPROVED:
        session.add(
            StrategyPromotionEvaluation(
                strategy_version_id=ver.id,
                dataset_snapshot_id=snap.id,
                evaluated_at=datetime.now(UTC),
                config_hash="cfg",
                spec_json_hash=SPEC_HASH,
                universe_json=list(SYMBOLS),
                window_start=date(2025, 1, 1),
                window_end=date(2026, 8, 1),
                data_provenance_json={"sources": ["massive"]},
                passed=True,
                verdict="PAPER_APPROVED",
            )
        )
    return ver


def _candidate(
    session: Session, run: ScanRun, inst: Instrument, ver: StrategyVersion, rank: int
) -> Candidate:
    cand = Candidate(
        scan_run_id=run.id,
        instrument_id=inst.id,
        strategy_version_id=ver.id,
        horizon=run.horizon,
        direction=Direction.LONG,
        entry_zone_low=99.0,
        entry_zone_high=101.0,
        invalidation_level=95.0,
        target_level=112.0,
        target_logic="x",
        time_stop_days=10,
        reward_risk_estimate=2.4,
        risk_dollars=150.0,
        risk_pct_of_account=0.5,
        liquidity_json={"last_price": 100.0},
        slippage_assumption_json={"bps": 3},
        event_risk_json={"upcoming_earnings": []},
        portfolio_context_json={},
        data_freshness_json={"fresh": True},
        ranking_json={"score": 0.4},
        reasons_qualify=["test"],
        reasons_fail=["could gap down"],
        quality_gate_status=QualityGate.PASSED,
        failed_gates=[],
        rank_in_horizon=rank,
    )
    session.add(cand)
    session.flush()
    return cand


def _world(
    session: Session, *, medium_first: bool = True
) -> tuple[dict[str, StrategyVersion], dict[str, ScanRun], dict[str, list[Candidate]]]:
    """Two PAPER_APPROVED versions (short and medium swing) that fire on the SAME
    three symbols, each in its own approved-scope scan run. ``medium_first``
    creates the MEDIUM candidates first, so both candidate id order and the old
    horizon-string order ("MEDIUM_SWING" < "SHORT_SWING") favour medium."""
    session.add(PaperAccount(name=LEGACY_ACCOUNT, initial_cash=30_000, cash=30_000))
    snap = DataSnapshot(key="universe_test", symbols_json=list(SYMBOLS))
    session.add(snap)
    session.flush()
    # The SHORT version is created first: it has the LOWER strategy_version id.
    short = _version(session, "short", Horizon.SHORT_SWING, snap, StrategyStatus.PAPER_APPROVED)
    medium = _version(session, "medium", Horizon.MEDIUM_SWING, snap, StrategyStatus.PAPER_APPROVED)
    insts = []
    for sym in SYMBOLS:
        inst = Instrument(symbol=sym, name=sym, instrument_type="stock", sector="tech")
        session.add(inst)
        session.flush()
        _bars(session, inst)
        insts.append(inst)
    versions = {"short": short, "medium": medium}
    runs: dict[str, ScanRun] = {}
    cands: dict[str, list[Candidate]] = {}
    for key in ("medium", "short") if medium_first else ("short", "medium"):
        ver = versions[key]
        run = ScanRun(
            horizon=Horizon.MEDIUM_SWING if key == "medium" else Horizon.SHORT_SWING,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            config_hash="cfg",
            source="massive",
            dataset_snapshot_id=snap.id,
            universe_json=list(SYMBOLS),
            universe_size=len(SYMBOLS),
        )
        session.add(run)
        session.flush()
        runs[key] = run
        cands[key] = [
            _candidate(session, run, inst, ver, rank) for rank, inst in enumerate(insts, start=1)
        ]
    session.flush()
    return versions, runs, cands


def _open_symbols(session: Session, account_id: int) -> list[str]:
    rows = session.execute(
        select(Instrument.symbol)
        .join(PaperPosition, PaperPosition.instrument_id == Instrument.id)
        .where(PaperPosition.account_id == account_id, PaperPosition.closed_at.is_(None))
        .order_by(PaperPosition.id)
    ).all()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- #
# The defect: one version starved the other. The fix: one book per version.
# --------------------------------------------------------------------------- #


def test_two_versions_hold_the_same_symbol_in_separate_books(
    session: Session, scope_matches: None
) -> None:
    versions, runs, cands = _world(session)
    set_setting(session, "auto_simulate_qualified_signals", True)
    set_setting(session, AUTO_SIM_CAP_KEY, 2)

    rep = auto_simulate_scan_runs(session, [runs["medium"].id, runs["short"].id])

    # Each book takes its own two best-ranked candidates; nothing is refused for
    # "an open paper position already exists".
    assert rep.rejected == [] and rep.skipped == []
    assert len(rep.accepted) == 4
    short_book = book_for_version(session, versions["short"].id, create=False)
    medium_book = book_for_version(session, versions["medium"].id, create=False)
    assert short_book is not None and medium_book is not None
    assert short_book.id != medium_book.id
    assert _open_symbols(session, short_book.id) == ["AAPL", "MSFT"]
    assert _open_symbols(session, medium_book.id) == ["AAPL", "MSFT"]
    # The daily cap (2) is per book: the third candidate of EACH book is WATCH.
    assert sorted(c for c, _ in rep.watched) == sorted(
        [cands["short"][2].id, cands["medium"][2].id]
    )
    for _, reason in rep.watched:
        assert reason == "auto-simulation daily cap (2) reached — not taken"

    # Books start from the legacy account's reference equity; the legacy account
    # itself is untouched (no money is moved between accounts).
    legacy = session.scalar(select(PaperAccount).where(PaperAccount.name == LEGACY_ACCOUNT))
    assert legacy is not None and legacy.strategy_version_id is None
    assert Decimal(legacy.cash) == Decimal("30000")
    for book, ver in ((short_book, versions["short"]), (medium_book, versions["medium"])):
        assert book.name == book_name(ver.id)
        assert Decimal(book.initial_cash) == Decimal("30000")
        assert Decimal(book.cash) < Decimal("30000")
    # Every position is attributed to its own version, in its own book.
    for pos in session.scalars(select(PaperPosition)):
        owner = session.get(PaperAccount, pos.account_id)
        assert owner is not None and owner.strategy_version_id == pos.strategy_version_id


def test_order_is_book_by_version_id_then_rank_not_horizon_string(
    session: Session, scope_matches: None
) -> None:
    """MEDIUM candidates were created first (lower ids) and "MEDIUM_SWING" sorts
    before "SHORT_SWING", yet the SHORT version has the lower strategy_version
    id, so its book decides first — and inside each book rank order holds."""
    versions, runs, cands = _world(session, medium_first=True)
    assert versions["short"].id < versions["medium"].id
    assert cands["medium"][0].id < cands["short"][0].id
    set_setting(session, "auto_simulate_qualified_signals", True)
    set_setting(session, AUTO_SIM_CAP_KEY, 10)

    rep = auto_simulate_scan_runs(session, [runs["medium"].id, runs["short"].id])

    decided = [session.get(PaperTrade, tid).candidate_id for tid in rep.accepted]  # type: ignore[union-attr]
    assert decided == [c.id for c in cands["short"]] + [c.id for c in cands["medium"]]
    # paper_trade ids are assigned in decision order: deterministic and repeatable.
    assert rep.accepted == sorted(rep.accepted)


def test_open_position_rule_is_per_book(session: Session, scope_matches: None) -> None:
    versions, runs, cands = _world(session)
    set_setting(session, "auto_simulate_qualified_signals", True)
    set_setting(session, AUTO_SIM_CAP_KEY, 10)
    auto_simulate_scan_runs(session, [runs["short"].id])  # short book now holds all three

    # A NEW short-swing candidate on AAPL is refused (its own book holds AAPL)...
    run2 = ScanRun(
        horizon=Horizon.SHORT_SWING,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        config_hash="cfg",
        source="massive",
        dataset_snapshot_id=runs["short"].dataset_snapshot_id,
        universe_json=list(SYMBOLS),
        universe_size=len(SYMBOLS),
    )
    session.add(run2)
    session.flush()
    aapl = session.get(Instrument, cands["short"][0].instrument_id)
    assert aapl is not None
    dup = _candidate(session, run2, aapl, versions["short"], 1)
    rep = auto_simulate_scan_runs(session, [run2.id])
    assert rep.rejected == [
        (dup.id, "auto-simulation refused: an open paper position already exists")
    ]
    # ...while the medium version, whose book is empty, takes AAPL.
    rep_medium = auto_simulate_scan_runs(session, [runs["medium"].id])
    assert len(rep_medium.accepted) == 3 and rep_medium.rejected == []


def test_risk_caps_are_per_book(session: Session, scope_matches: None) -> None:
    """Each book sizes against ITS OWN equity and exposure. Both books take AAPL
    at the full symbol ceiling: 10% * 30,000 = 3,000 -> floor(3,000 / 100.06) = 29
    shares each. (Fill = 100 * 1.00055 = 100.055 -> 100.06.) A single shared book
    would have had no symbol budget left for the second acceptance."""
    versions, runs, cands = _world(session)
    set_setting(session, "auto_simulate_qualified_signals", True)
    set_setting(session, AUTO_SIM_CAP_KEY, 1)
    for c in (*cands["short"], *cands["medium"]):
        c.risk_dollars = 10_000.0  # never the binding cap
    session.flush()

    rep = auto_simulate_scan_runs(session, [runs["medium"].id, runs["short"].id])
    assert len(rep.accepted) == 2
    for tid in rep.accepted:
        trade = session.get(PaperTrade, tid)
        assert trade is not None
        risk = trade.plan_json["risk_decision"]
        assert risk["equity"] == "30000.000000" and risk["symbol_before"] == "0"
        assert risk["share_caps"]["symbol"] == 29
        assert risk["book_strategy_version_id"] in {v.id for v in versions.values()}
    books = {risk_owner.strategy_version_id for risk_owner in equity_books(session)}
    assert {versions["short"].id, versions["medium"].id} <= books


# --------------------------------------------------------------------------- #
# Book resolution
# --------------------------------------------------------------------------- #


def test_book_creation_is_lazy_idempotent_and_audited(session: Session) -> None:
    versions, _, _ = _world(session)
    vid = versions["short"].id
    assert book_for_version(session, vid, create=False) is None  # lazy
    first = book_for_version(session, vid)
    again = book_for_version(session, vid)
    assert first is not None and again is not None and first.id == again.id
    assert (
        len(
            list(
                session.scalars(select(PaperAccount).where(PaperAccount.strategy_version_id == vid))
            )
        )
        == 1
    )
    audits = list(session.scalars(select(AuditLog).where(AuditLog.action == "paper.book_created")))
    assert len(audits) == 1 and audits[0].after_json["strategy_version_id"] == vid


def test_a_non_approved_candidate_never_lands_in_an_approved_book(session: Session) -> None:
    versions, runs, cands = _world(session)
    snap = session.get(DataSnapshot, runs["short"].dataset_snapshot_id)
    assert snap is not None
    experimental = _version(session, "exp", Horizon.SHORT_SWING, snap, StrategyStatus.EXPERIMENTAL)
    aapl = session.get(Instrument, cands["short"][0].instrument_id)
    assert aapl is not None
    cand = _candidate(session, runs["short"], aapl, experimental, 9)

    legacy = session.scalar(select(PaperAccount).where(PaperAccount.name == LEGACY_ACCOUNT))
    assert legacy is not None
    # Legacy account unkeyed -> it is the unattributed book.
    assert book_for_candidate(session, cand).id == legacy.id
    # Once the legacy account is a version's book (the live migration outcome),
    # unattributed decisions go to the separate ``manual`` account instead.
    legacy.strategy_version_id = versions["medium"].id
    session.flush()
    manual = book_for_candidate(session, cand)
    assert manual.name == MANUAL_ACCOUNT and manual.strategy_version_id is None
    assert Decimal(manual.initial_cash) == Decimal(legacy.initial_cash)
    tid = record_decision(session, cand.id, PaperDecision.WATCH, note="manual")
    trade = session.get(PaperTrade, tid)
    assert trade is not None and trade.account_id == manual.id
    # ...and the medium version's own candidates go to the legacy account, its book.
    assert book_for_candidate(session, cands["medium"][0]).id == legacy.id


def test_explicit_account_cannot_cross_books(session: Session) -> None:
    versions, _, cands = _world(session)
    book_for_version(session, versions["medium"].id)
    with pytest.raises(ValueError, match="is the book of strategy version"):
        accept_candidate(
            session,
            cands["short"][0].id,
            account_name=book_name(versions["medium"].id),
            as_of=date(2024, 2, 1),
        )
    assert session.scalar(select(PaperTrade)) is None


# --------------------------------------------------------------------------- #
# Marking and reporting across books
# --------------------------------------------------------------------------- #


def test_mark_to_market_covers_every_book_and_snapshot_shows_each(
    session: Session, scope_matches: None
) -> None:
    versions, runs, _ = _world(session)
    set_setting(session, "auto_simulate_qualified_signals", True)
    set_setting(session, AUTO_SIM_CAP_KEY, 1)
    auto_simulate_scan_runs(session, [runs["medium"].id, runs["short"].id])

    res = mark_to_market(session)
    assert res.checked == 2  # one open position in each of the two books

    snap = portfolio_snapshot(session)
    assert snap["exists"] and snap["account"] == "all equity books"
    by_account = {b["account"]: b for b in snap["books"]}
    assert set(by_account) == {
        book_name(versions["short"].id),
        book_name(versions["medium"].id),
        LEGACY_ACCOUNT,
    }
    assert by_account[book_name(versions["short"].id)]["n_open"] == 1
    assert by_account[LEGACY_ACCOUNT]["n_open"] == 0
    assert snap["n_open"] == 2
    assert snap["initial_cash"] == 90_000.0
    # Combined exposure per symbol ACROSS books: AAPL is held by both.
    (aapl,) = snap["symbol_exposure"]
    assert aapl["symbol"] == "AAPL" and len(aapl["books"]) == 2
    per_book_qty = [p["qty"] for p in snap["open_positions"]]
    assert aapl["qty"] == sum(per_book_qty)
    assert aapl["market_value"] == pytest.approx(100.0 * sum(per_book_qty))
    assert aapl["pct_of_combined_equity"] == pytest.approx(
        aapl["market_value"] / snap["equity_estimate"] * 100.0, abs=0.01
    )
    # A named account is still available on its own.
    one = portfolio_snapshot(session, account_name=book_name(versions["short"].id))
    assert one["n_open"] == 1 and len(one["books"]) == 1
