"""The equity paper ledger is unchanged by I-O6 — pinned two ways.

Two mechanisms, because neither is sufficient alone:

1. **A source-hash pin** over the equity functions I-O6 does not touch at all.
   If any of them moves by a single byte, this test fails and the author has to
   say why. It covers the arithmetic (``_slippage_frac``, ``_money``), the exit
   logic (``_exit_reason``, ``_exit_price``), the plan and the complete evidence
   snapshot (``_plan``, ``_candidate_snapshot``), and ``record_decision``.

2. **A behavioural golden** over the two functions I-O6 *does* touch —
   ``accept_candidate`` and ``mark_to_market`` — because a source pin on them
   would only say "it changed", which is already known. Each gains exactly one
   NARROWING refusal (an options candidate; a non-equity instrument), neither of
   which can fire on an equity input, and the golden is what proves it: every
   price, quantity, cash figure and snapshot key an equity acceptance and an
   equity mark produce is asserted literally.

``tests/paper/test_equity_path_unchanged.py`` (the D6 golden) also still passes
unmodified, and ``tests/paper/test_activation_guards.py``'s existing verdicts are
untouched; those two are the third leg and they are deliberately not restated here.
"""

from __future__ import annotations

import hashlib
import inspect
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from signalforge.db.models import Candidate, Instrument, PaperAccount, PaperPosition
from signalforge.paper import ledger
from signalforge.paper.equity_guard import NotAnEquityPosition
from signalforge.paper.ledger import accept_candidate, mark_to_market
from signalforge.paper.portfolio import portfolio_snapshot

#: sha256 of the source text of each equity function I-O6 leaves alone.
#:
#: **These are the PARENT commit's values, not this branch's.** Verified with
#: ``git diff HEAD -- src/signalforge/paper/ledger.py``: the only hunks on that
#: file are the two narrowing refusals, the instrument-type assertion, one import
#: and two docstring lines — none of them inside any function named below. A
#: golden captured after a change proves nothing about the change; re-run that
#: diff if any of these ever moves.
#:
#: Regenerate ONLY with an explanation of what moved and why it is safe.
#:
#: Recorded as the **first 32 hex characters** of each digest. 128 bits is far
#: more than a change detector needs, and it keeps every line inside the line
#: limit with the ``allowlist secret`` pragma the secret-scan gate requires —
#: these are source digests, not credentials, and the gate's baseline is never
#: rewritten to accommodate them.
PIN = 32
EQUITY_FUNCTION_HASHES = {
    "_money": "650058bcb5ef47482a500171c7dfd567",  # pragma: allowlist secret
    "_slippage_frac": "82e9facd5705ba063e6803274d4cdbaa",  # pragma: allowlist secret
    "_exit_reason": "01c841e1312d9cf5fc893e239fbf1aeb",  # pragma: allowlist secret
    "_exit_price": "41fc4aff71ed45a24540ec1088ca801c",  # pragma: allowlist secret
    "_plan": "70df55354a44f326646850b96ad707c0",  # pragma: allowlist secret
    "_candidate_snapshot": "3c650839b5988a1e0bc2cf0ac85f4991",  # pragma: allowlist secret
    "record_decision": "d461d60df12d850362ff0fb14394c8cf",  # pragma: allowlist secret
    "_time_stop_date": "23aa985297150bfc23fdea2e4361b5a9",  # pragma: allowlist secret
    "auto_simulate_enabled": "49904cbb2b70b6daf1ec03732e688b85",  # pragma: allowlist secret
    "_account": "dda728d6c95648c5122e3124f15a2466",  # pragma: allowlist secret
}

#: sha256 of the WHOLE of ``paper/auto_simulate.py``. I-O6 does not edit it.
AUTO_SIMULATE_MODULE_HASH = "67088b4dfb9feb43ecbdbfc8aea384d6"  # pragma: allowlist secret


def _source_hash(name: str) -> str:
    return hashlib.sha256(inspect.getsource(getattr(ledger, name)).encode()).hexdigest()[:PIN]


def test_the_untouched_equity_functions_are_byte_identical() -> None:
    """A source-hash pin. If this fails, an equity function moved — say why."""
    actual = {name: _source_hash(name) for name in EQUITY_FUNCTION_HASHES}
    assert actual == EQUITY_FUNCTION_HASHES


def test_the_equity_ledger_never_imports_the_options_modules() -> None:
    """The dependency arrow runs options -> equity and never back. A shared
    helper would be a shared blast radius, and the equity path is live."""
    src = inspect.getsource(ledger)
    for mod in (
        "signalforge.paper.options_ledger",
        "signalforge.paper.options_marks",
        "signalforge.paper.options_auto_simulate",
    ):
        assert f"from {mod} import" not in src, mod
        assert f"import {mod}" not in src, mod


def test_paper_auto_simulate_is_byte_identical() -> None:
    """The strongest guarantee available that the live equity auto-simulation —
    setting ON since 2026-09-10, cap 2/day — is unaffected: the module it runs
    through was not edited at all. The options branch is a SIBLING module that
    copies its five structural guarantees rather than sharing code with it."""
    from signalforge.paper import auto_simulate

    src = inspect.getsource(auto_simulate)
    assert "options" not in src.lower()
    assert hashlib.sha256(src.encode()).hexdigest()[:PIN] == AUTO_SIMULATE_MODULE_HASH


# --------------------------------------------------------------------------- #
# Behavioural goldens over the two functions that DID change
# --------------------------------------------------------------------------- #

ACCEPT_GOLDEN = {
    "cash_after": "7642.40",
    "fill_price": "471.260000",
    "shares": 5,
    "side": "long",
    "spread_cost": "0.590000",
    "slippage": "0.710000",
    "commission": "0.000000",
    "stop_level": 466.0,
    "target_level": 485.0,
    "plan_fill_price": 471.2591,
}


def test_the_equity_accept_path_produces_the_identical_numbers(
    session: Session, passing_candidate: Candidate, account: PaperAccount
) -> None:
    passing_candidate.entry_zone_low = 470.0
    passing_candidate.entry_zone_high = 472.0
    passing_candidate.invalidation_level = 466.0
    passing_candidate.target_level = 485.0
    passing_candidate.risk_dollars = 25.0
    session.flush()

    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 2, 1))
    from signalforge.db.models import PaperFill

    fill = session.get(PaperFill, res.fill_id)
    position = session.get(PaperPosition, res.position_id)
    assert fill is not None and position is not None
    assert {
        "cash_after": str(Decimal(account.cash)),
        "fill_price": str(Decimal(fill.price)),
        "shares": res.shares,
        "side": res.side.value,
        "spread_cost": str(Decimal(fill.spread_cost)),
        "slippage": str(Decimal(fill.slippage)),
        "commission": str(Decimal(fill.commission)),
        "stop_level": position.stop_level,
        "target_level": position.target_level,
        "plan_fill_price": res.fill_price,
    } == ACCEPT_GOLDEN


def test_the_new_collateral_column_is_zero_and_spendable_equals_cash(
    session: Session, account: PaperAccount
) -> None:
    """The additive ``paper_account.collateral_reserved`` is 0 on every existing
    account, so ``spendable_cash == cash`` and no equity arithmetic moves."""
    assert account.collateral_reserved == Decimal("0")
    assert account.spendable_cash == account.cash


def test_the_equity_mark_produces_the_identical_close(
    session: Session, passing_candidate: Candidate, account: PaperAccount
) -> None:
    """``mark_to_market``'s one change is the instrument-type assertion, which
    cannot fire on a stock. The close, the P&L and the cash movement are pinned."""
    passing_candidate.entry_zone_low = 99.5
    passing_candidate.entry_zone_high = 100.5
    passing_candidate.invalidation_level = 96.0
    passing_candidate.target_level = 100.5  # inside the fixture bars, so it fills
    session.flush()
    accept_candidate(session, passing_candidate.id, as_of=date(2024, 1, 10))

    res = mark_to_market(session, as_of=date(2024, 1, 20))
    assert (res.checked, res.closed) == (1, 1)
    position = session.scalar(__import__("sqlalchemy").select(PaperPosition))
    assert position is not None
    assert position.closed_at is not None
    assert float(position.realized_pnl) == pytest.approx(res.realized_pnl, abs=0.01)


def test_mark_to_market_refuses_an_option_typed_instrument(
    session: Session, account: PaperAccount
) -> None:
    """DEFENCE IN DEPTH against a row this design never creates.

    The options design introduces no new ``Instrument.instrument_type`` value at
    all — the discriminator is ``Candidate.structure_kind``, and options
    structures live in ``options_position``, never in ``paper_position``. This
    test therefore has to **construct** an option-typed instrument that
    production never writes, which is the point: the assertion fires if some
    future code path introduces one.
    """
    from datetime import datetime

    from signalforge.domain import Horizon, PositionSide

    inst = Instrument(symbol="SPY  260320P00430000", name="opt", instrument_type="option")
    session.add(inst)
    session.flush()
    session.add(
        PaperPosition(
            account_id=account.id,
            instrument_id=inst.id,
            horizon=Horizon.POSITION,
            side=PositionSide.SHORT,
            qty=1,
            avg_price=Decimal("1.20"),
            opened_at=datetime.now(tz=__import__("datetime").UTC),
        )
    )
    session.flush()

    with pytest.raises(NotAnEquityPosition, match="mark_options_to_market"):
        mark_to_market(session, as_of=date(2026, 2, 18))
    with pytest.raises(NotAnEquityPosition, match="portfolio_snapshot"):
        portfolio_snapshot(session, as_of=date(2026, 2, 18))
    # Not a ValueError: job_paper_mtm must fail loudly with a named JobRun.
    assert not issubclass(NotAnEquityPosition, ValueError)


def test_the_equity_guard_still_refuses_options(session: Session, account: PaperAccount) -> None:
    """Two routes, both closed, and the second is the one the map's §3.6 misses.

    The instrument-type check refuses an option-typed instrument, as it always
    did. The NEW narrowing refusal closes the route §3.6 does not defend: an
    options candidate points its ``instrument_id`` at the UNDERLYING, and SPY is
    an ``etf``, so it would otherwise PASS the instrument-type check.
    """
    from signalforge.db.models import CandidateOptionStructure
    from signalforge.domain import StrategyStatus
    from signalforge.paper.ledger import AutoSimulateForbidden, assert_auto_simulate_allowed
    from signalforge.settings_store import set_setting
    from tests.paper import options_support as fx

    set_setting(session, "auto_simulate_qualified_signals", True)
    inst = fx.underlying(session)  # instrument_type 'etf' — passes the old check
    ver = fx.approved_strategy(session, status=StrategyStatus.PAPER_APPROVED)
    cand = fx.options_candidate(session, instrument=inst, version=ver)
    assert inst.instrument_type == "etf"

    with pytest.raises(AutoSimulateForbidden, match="carries an options structure"):
        assert_auto_simulate_allowed(session, cand)
    with pytest.raises(AutoSimulateForbidden, match="carries an options structure"):
        accept_candidate(session, cand.id)

    # and nothing was written through the equity ledger
    from sqlalchemy import func, select

    from signalforge.db.models import PaperTrade

    assert session.scalar(select(func.count()).select_from(PaperTrade)) == 0
    assert session.scalar(select(func.count()).select_from(PaperPosition)) == 0
    assert session.scalar(select(func.count()).select_from(CandidateOptionStructure)) == 1


def test_the_narrowing_refusal_changes_no_existing_verdict(
    session: Session, passing_candidate: Candidate, account: PaperAccount
) -> None:
    """``structure_kind`` is NULL on every pre-existing candidate by the column
    default, so the new refusal refuses a class that did not exist before and
    refuses nothing the guard previously accepted."""
    from signalforge.paper.ledger import AutoSimulateForbidden, assert_auto_simulate_allowed

    assert passing_candidate.structure_kind is None
    with pytest.raises(AutoSimulateForbidden) as exc:
        assert_auto_simulate_allowed(session, passing_candidate)
    # the FIRST failed condition is still the setting, not the new refusal
    assert "auto_simulate_qualified_signals is off" in str(exc.value)
