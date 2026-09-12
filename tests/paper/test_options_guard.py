"""The SECOND guard: ``assert_options_auto_simulate_allowed`` (D3 §10.2).

One test per condition, each asserting the refusal **names the condition**. The
guard refuses on the first failed condition in A-AB order, matching
``assert_auto_simulate_allowed``'s existing behaviour.

Nothing here touches real data: every print, bar, contract and account row is a
fixture built in ``tests/paper/options_support.py``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from signalforge.db.models import Candidate, CandidateOptionStructure, OptionContract, PaperAccount
from signalforge.domain import Direction, QualityGate, StrategyStatus
from signalforge.paper.options_ledger import (
    OPTIONS_AUTO_SIM_CAP_KEY,
    OPTIONS_AUTO_SIM_ENABLED_KEY,
    OptionsAutoSimulateForbidden,
    assert_options_auto_simulate_allowed,
)
from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, set_setting
from tests.paper import options_support as fx


def _arm(session: Session, *, cap: int = 2) -> None:
    set_setting(session, OPTIONS_AUTO_SIM_ENABLED_KEY, True)
    set_setting(session, OPTIONS_AUTO_SIM_CAP_KEY, cap)


def _world(
    session: Session,
    *,
    arm: bool = True,
    account: bool = True,
    reconcile: bool = True,
    prints: bool = True,
    **cand_kw: object,
) -> tuple[Candidate, PaperAccount | None]:
    acct = fx.options_account(session) if account else None
    inst = fx.underlying(session)
    fx.contracts(
        session,
        shares_per_contract=int(cand_kw.pop("contract_spc", 100)),
        style=str(cand_kw.pop("contract_style", "american")),
    )
    if prints:
        fx.option_prints(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION])
    ver = fx.approved_strategy(
        session, status=cand_kw.pop("status", StrategyStatus.PAPER_APPROVED)  # type: ignore[arg-type]
    )
    cand = fx.options_candidate(session, instrument=inst, version=ver, **cand_kw)  # type: ignore[arg-type]
    fx.approve_scope(session, cand, ver)
    if acct is not None and reconcile:
        fx.clean_reconcile_report(session, acct, as_of=fx.FILL_SESSION)
    if arm:
        _arm(session)
    return cand, acct


def _call(session: Session, cand: Candidate, *, account_name: str = fx.OPTIONS_ACCOUNT) -> object:
    return assert_options_auto_simulate_allowed(
        session,
        cand,
        account_name=account_name,
        pricing=fx.pricing(),
        signal_session=fx.SIGNAL_SESSION,
        fill_session=fx.FILL_SESSION,
    )


def _refusal(session: Session, cand: Candidate, **kw: str) -> OptionsAutoSimulateForbidden:
    with pytest.raises(OptionsAutoSimulateForbidden) as exc:
        _call(session, cand, **kw)  # type: ignore[arg-type]
    return exc.value


# --------------------------------------------------------------------------- #


def test_the_happy_path_returns_a_plan_the_acceptance_can_use(session: Session) -> None:
    cand, _ = _world(session)
    plan = _call(session, cand)
    assert plan.structure.structure_type == "vertical_credit"  # type: ignore[attr-defined]
    assert plan.r_dollars > 0  # type: ignore[attr-defined]
    assert plan.collateral_required == pytest.approx(200.0)  # type: ignore[attr-defined]
    assert plan.signal_session == fx.SIGNAL_SESSION  # type: ignore[attr-defined]
    assert plan.fill_session == fx.FILL_SESSION  # type: ignore[attr-defined]
    # Every limit is recorded with its POST-entry value, bound or not — that is
    # the only way "the greek caps do not bind at decision 4's numbers" stays
    # knowable rather than inferred from an absence of refusals.
    entries = plan.limits.to_dict()  # type: ignore[attr-defined]
    assert "options_net_delta" in entries and "combined_net_delta" in entries
    assert "options_net_vega" in entries and "min_credit_to_width" in entries
    assert entries["max_open_structures"]["value"] == 1.0  # POST-entry, not 0
    assert all(e["state"] in {"ok", "binding"} for e in entries.values())


def test_condition_A_the_second_setting_is_off_by_default(session: Session) -> None:
    """Nothing is armed by default: a fresh database has the options setting
    absent, which reads as FALSE, and the equity setting is a different key."""
    cand, _ = _world(session, arm=False)
    exc = _refusal(session, cand)
    assert exc.condition == "A"
    assert OPTIONS_AUTO_SIM_ENABLED_KEY in str(exc)
    # Turning the EQUITY setting on does not arm the options path.
    set_setting(session, "auto_simulate_qualified_signals", True)
    assert _refusal(session, cand).condition == "A"


def test_condition_B_the_kill_switch_is_shared(session: Session) -> None:
    from signalforge.killswitch import get_kill_switch

    cand, _ = _world(session)
    get_kill_switch().engage(reason="test", actor="test")
    try:
        with pytest.raises(Exception, match=r"kill switch|engaged"):
            _call(session, cand)
    finally:
        get_kill_switch().release(reason="test", actor="test")


def test_condition_C_requires_the_positive_structure_discriminator(session: Session) -> None:
    cand, _ = _world(session, structure_kind=None)
    assert _refusal(session, cand).condition == "C"


def test_condition_C_refuses_a_marked_candidate_with_no_structure_row(session: Session) -> None:
    cand, _ = _world(session, with_structure_row=False)
    exc = _refusal(session, cand)
    assert exc.condition == "C"
    assert "carries no structure row" in str(exc)


def test_condition_D_requires_every_quality_gate(session: Session) -> None:
    cand, _ = _world(session, gate=QualityGate.NO_TRADE)
    assert _refusal(session, cand).condition == "D"


def test_condition_E_refuses_avoid(session: Session) -> None:
    cand, _ = _world(session, direction=Direction.AVOID)
    assert _refusal(session, cand).condition == "E"


def test_condition_F_requires_paper_approved(session: Session) -> None:
    cand, _ = _world(session, status=StrategyStatus.EXPERIMENTAL)
    assert _refusal(session, cand).condition == "F"


def test_condition_G_requires_the_versions_single_approved_structure_type(
    session: Session,
) -> None:
    """Gate 0.5: exactly one structure type per version."""
    cand, _ = _world(session, structure_type="vertical_debit")
    exc = _refusal(session, cand)
    assert exc.condition == "G"
    assert "vertical_credit" in str(exc)


def test_condition_H_requires_the_five_part_equity_scope_match(session: Session) -> None:
    from signalforge.db.models import ScanRun

    cand, _ = _world(session)
    run = session.get(ScanRun, cand.scan_run_id)
    assert run is not None
    run.config_hash = "a-different-config"  # the scan drifts out of the approval
    session.flush()
    assert _refusal(session, cand).condition == "H"


def test_condition_I_compares_the_sixth_options_scope_part(session: Session) -> None:
    from signalforge.db.models import StrategyVersion

    cand, _ = _world(session)
    ver = session.get(StrategyVersion, cand.strategy_version_id)
    assert ver is not None
    ver.spec_json = dict(ver.spec_json or {}) | {"options_scope_hash": "an-old-options-scope"}
    session.flush()
    assert _refusal(session, cand).condition == "I"


def test_condition_I_moves_when_a_refusal_only_limit_moves(session: Session) -> None:
    """Changing an options capital limit un-scopes the OPTIONS strategy and
    nothing else. The equity ``config_hash`` does not move at all."""
    from signalforge.config.research import ResearchConfig
    from signalforge.db.models import StrategyVersion
    from signalforge.paper.options_ledger import options_scope_hash
    from signalforge.settings_store import effective_research_config

    cand, _ = _world(session)
    before_scope = options_scope_hash(effective_research_config(session))
    before_config_hash = effective_research_config(session).config_hash
    ver = session.get(StrategyVersion, cand.strategy_version_id)
    assert ver is not None
    ver.spec_json = dict(ver.spec_json or {}) | {"options_scope_hash": before_scope}
    session.flush()
    _call(session, cand)  # in scope

    set_setting(
        session,
        RESEARCH_OVERRIDES_KEY,
        {"options_risk": {"per_structure_max_loss_dollars": 700.0}},
    )
    cfg = effective_research_config(session)
    assert options_scope_hash(cfg) != before_scope
    assert cfg.config_hash == before_config_hash == ResearchConfig().config_hash
    assert _refusal(session, cand).condition == "I"


def test_condition_K_requires_a_100_share_multiplier_read_from_the_contract(
    session: Session,
) -> None:
    cand, _ = _world(session, contract_spc=10, shares_per_contract=10)
    exc = _refusal(session, cand)
    assert exc.condition == "K"
    assert "shares_per_contract" in str(exc)


def test_condition_K_catches_a_leg_that_disagrees_with_its_contract_row(
    session: Session,
) -> None:
    """A leg carrying 100 while the contract row says 10 is refused too: the
    multiplier is READ, and a disagreement is not resolved in the leg's favour."""
    cand, _ = _world(session, contract_spc=10)
    assert _refusal(session, cand).condition == "K"


def test_condition_L_admits_american_only_as_a_scope_restriction(session: Session) -> None:
    cand, _ = _world(session, contract_style="european", style="european")
    exc = _refusal(session, cand)
    assert exc.condition == "L"
    assert "SCOPE restriction" in str(exc)


def test_condition_M_a_missing_print_on_the_FILL_session_is_a_non_entry(
    session: Session,
) -> None:
    """And it is evaluated at t+1, not t: the guard consults nothing in the
    future, because the fill session is the session it is running on."""
    cand, _ = _world(session, prints=False)
    fx.option_prints(session, sessions=[fx.SIGNAL_SESSION])  # signal only, no fill
    exc = _refusal(session, cand)
    assert exc.condition == "M"
    assert fx.FILL_SESSION.isoformat() in str(exc)


def test_condition_M_one_missing_leg_is_enough(session: Session) -> None:
    cand, _ = _world(session, prints=False)
    fx.option_prints(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION], skip=(fx.LONG_TICKER,))
    exc = _refusal(session, cand)
    assert exc.condition == "M"
    assert fx.LONG_TICKER in str(exc)


def test_condition_N_refuses_a_missing_account(session: Session) -> None:
    cand, _ = _world(session, account=False)
    exc = _refusal(session, cand)
    assert exc.condition == "N"
    assert "does not exist" in str(exc)


def test_condition_N_refuses_a_wrong_account_name_not_just_a_missing_one(
    session: Session,
) -> None:
    """The account is named in CONFIGURATION, not by the caller. ``"default"`` is
    a perfectly valid string and it resolves to the live EQUITY book."""
    cand, _ = _world(session)
    fx.equity_account(session)
    exc = _refusal(session, cand, account_name="default")
    assert exc.condition == "N"
    assert "not the configured options account" in str(exc)


def test_condition_N_refuses_even_when_the_configured_name_points_at_the_equity_book(
    session: Session,
) -> None:
    """The second clause is an id comparison, so editing the configured name to
    'default' still cannot target the equity account."""
    cand, _ = _world(session)
    fx.equity_account(session)
    set_setting(
        session, RESEARCH_OVERRIDES_KEY, {"options_risk": {"paper_account_name": "default"}}
    )
    exc = _refusal(session, cand, account_name="default")
    assert exc.condition == "N"
    assert "EQUITY account" in str(exc)


def test_condition_O_refuses_when_spendable_cash_is_short(session: Session) -> None:
    cand, acct = _world(session)
    assert acct is not None
    acct.cash = Decimal("100")
    session.flush()
    exc = _refusal(session, cand)
    assert exc.condition == "O"
    assert "spendable cash" in str(exc)


def test_condition_P_refuses_above_the_collateral_cap(session: Session) -> None:
    cand, _ = _world(session)
    set_setting(session, RESEARCH_OVERRIDES_KEY, {"options_risk": {"collateral_cap_dollars": 50.0}})
    assert _refusal(session, cand).condition == "P"


def test_condition_Q_refuses_above_the_per_structure_max_loss(session: Session) -> None:
    cand, _ = _world(session)
    set_setting(
        session,
        RESEARCH_OVERRIDES_KEY,
        {
            "options_risk": {
                "collateral_cap_dollars": 5000.0,
                "per_structure_max_loss_dollars": 10.0,
            }
        },
    )
    assert _refusal(session, cand).condition == "Q"


def test_condition_R_refuses_above_the_aggregate_open_max_loss(session: Session) -> None:
    cand, _ = _world(session)
    set_setting(
        session, RESEARCH_OVERRIDES_KEY, {"options_risk": {"total_open_max_loss_dollars": 10.0}}
    )
    assert _refusal(session, cand).condition == "R"


def test_condition_S_refuses_a_short_delta_above_the_ceiling(session: Session) -> None:
    """``max_short_delta`` is the risk axis and it is KEPT as a pre-registered
    gate; D3 §9(B)'s canonical REFUSAL record is refused naming exactly this."""
    cand, _ = _world(session)
    set_setting(session, RESEARCH_OVERRIDES_KEY, {"options_shaping": {"max_short_delta": 0.001}})
    exc = _refusal(session, cand)
    assert exc.condition == "S"
    assert "max_short_delta" in str(exc)


def test_condition_S_keeps_min_credit_to_width_as_its_own_gate(session: Session) -> None:
    """The PAIR is kept, per map §3.2's Rule: rev 1's proposal to retire the
    credit hurdle was withdrawn."""
    cand, _ = _world(session)
    set_setting(
        session,
        RESEARCH_OVERRIDES_KEY,
        {"options_shaping": {"max_short_delta": 1.0, "min_credit_to_width": 0.95}},
    )
    exc = _refusal(session, cand)
    assert exc.condition == "S"
    assert "min_credit_to_width" in str(exc)


def test_condition_T_evaluates_theta_at_BOTH_spread_settings(session: Session) -> None:
    """Gate 4b is permanent by decision 5: the 2x run is not optional, and it is
    the binding cell."""
    cand, _ = _world(session)
    plan = _call(session, cand)
    entries = plan.limits.to_dict()  # type: ignore[attr-defined]
    assert entries["theta_at_1x"]["value"] > entries["theta_at_2x"]["value"]
    set_setting(
        session,
        RESEARCH_OVERRIDES_KEY,
        {"options_shaping": {"min_net_credit_after_costs_to_max_loss": 0.99}},
    )
    exc = _refusal(session, cand)
    assert exc.condition == "T"


def test_condition_U_and_W_the_greek_caps(session: Session) -> None:
    cand, _ = _world(session)
    set_setting(
        session, RESEARCH_OVERRIDES_KEY, {"options_risk": {"max_net_delta_notional_dollars": 1.0}}
    )
    assert _refusal(session, cand).condition == "U"
    set_setting(
        session,
        RESEARCH_OVERRIDES_KEY,
        {"options_risk": {"max_net_vega_dollars_per_vol_pt": 0.001}},
    )
    assert _refusal(session, cand).condition == "W"


def test_condition_V_the_combined_cap_can_only_refuse_an_OPTIONS_open(
    session: Session,
) -> None:
    """D3 §5.2 Finding 2: the combined cap is evaluated ONLY inside this guard.
    It is never consulted by ``size_position``, ``accept_candidate`` or
    ``assert_auto_simulate_allowed`` — asserted here by source inspection, so the
    claim is mechanical rather than a promise."""
    import inspect

    from signalforge.paper import auto_simulate, ledger
    from signalforge.risk import engine

    for module in (ledger, auto_simulate, engine):
        src = inspect.getsource(module)
        assert "combined_max_net_delta_notional_dollars" not in src, module.__name__

    cand, _ = _world(session)
    set_setting(
        session,
        RESEARCH_OVERRIDES_KEY,
        {"options_risk": {"combined_max_net_delta_notional_dollars": 1.0}},
    )
    assert _refusal(session, cand).condition == "V"


def _open_structure_on_another_underlying(session: Session, account: PaperAccount) -> None:
    """An open structure on a DIFFERENT name, so the per-underlying check (X)
    does not fire before the count check (Y)."""
    from signalforge.db.models import OptionsPosition
    from signalforge.db.types import utcnow

    other = fx.underlying(session, symbol="QQQ", close=380.0)
    session.add(
        OptionsPosition(
            account_id=account.id,
            underlying_instrument_id=other.id,
            underlying_symbol="QQQ",
            structure_type="vertical_credit",
            contracts=1,
            entry_net_premium=Decimal("50"),
            r_dollars=Decimal("150"),
            collateral_reserved=Decimal("0"),
            strike_width=2.0,
            expiration_date=fx.EXPIRY,
            opened_at=utcnow(),
        )
    )
    session.flush()


def test_condition_Y_the_open_structure_count(session: Session) -> None:
    cand, acct = _world(session)
    assert acct is not None
    _open_structure_on_another_underlying(session, acct)
    set_setting(session, RESEARCH_OVERRIDES_KEY, {"options_risk": {"max_open_structures": 1}})
    assert _refusal(session, cand).condition == "Y"


def test_condition_X_is_keyed_on_the_UNDERLYING_not_on_a_contract(session: Session) -> None:
    """A multi-leg structure spans several contract rows, so an instrument-keyed
    check would not stop a second structure on the same name."""
    from signalforge.db.models import Instrument, OptionsPosition
    from signalforge.db.types import utcnow

    cand, acct = _world(session)
    assert acct is not None
    inst = session.scalar(
        __import__("sqlalchemy").select(Instrument).where(Instrument.symbol == fx.UNDERLYING)
    )
    assert inst is not None
    session.add(
        OptionsPosition(
            account_id=acct.id,
            underlying_instrument_id=inst.id,
            underlying_symbol=fx.UNDERLYING,
            structure_type="vertical_credit",
            contracts=1,
            entry_net_premium=Decimal("50"),
            r_dollars=Decimal("150"),
            collateral_reserved=Decimal("0"),
            strike_width=2.0,
            expiration_date=fx.EXPIRY,
            opened_at=utcnow(),
        )
    )
    session.flush()
    assert _refusal(session, cand).condition == "X"


def test_condition_Z_the_options_daily_cap_is_separate_from_the_equity_one(
    session: Session,
) -> None:
    """The options cap defaults to 0; the live equity cap is 2. They are
    different keys and neither reads the other."""
    from signalforge.paper.auto_simulate import AUTO_SIM_CAP_KEY, DEFAULT_MAX_PER_DAY

    cand, _ = _world(session)
    assert AUTO_SIM_CAP_KEY != OPTIONS_AUTO_SIM_CAP_KEY
    set_setting(session, AUTO_SIM_CAP_KEY, DEFAULT_MAX_PER_DAY)  # the equity cap: 2
    _arm(session, cap=0)  # the options cap: 0
    assert _refusal(session, cand).condition == "Z"


def test_condition_AA_is_satisfied_only_POSITIVELY(session: Session) -> None:
    """A MISSING reconciliation report refuses exactly as a divergent one does.
    This is the satisfied-by-absence case rev 1's flag failed on."""
    cand, _ = _world(session, reconcile=False)
    exc = _refusal(session, cand)
    assert exc.condition == "AA"
    assert "no collateral reconciliation report" in str(exc)


def test_condition_AA_refuses_a_divergent_report(session: Session) -> None:
    from signalforge.db.models import OptionsReconcileReport

    cand, acct = _world(session, reconcile=False)
    assert acct is not None
    session.add(
        OptionsReconcileReport(
            account_id=acct.id,
            as_of=fx.FILL_SESSION,
            clean=False,
            findings_json=[{"check": "2_balance_matches_open_structures", "detail": "x"}],
            collateral_reserved_observed=Decimal("0"),
            collateral_reserved_expected=Decimal("1"),
            open_structures=0,
        )
    )
    session.flush()
    exc = _refusal(session, cand)
    assert exc.condition == "AA"
    assert "not clean" in str(exc)


def test_condition_AA_refuses_a_report_dated_to_a_different_session(session: Session) -> None:
    cand, acct = _world(session, reconcile=False)
    assert acct is not None
    fx.clean_reconcile_report(session, acct, as_of=fx.FILL_SESSION - timedelta(days=7))
    assert _refusal(session, cand).condition == "AA"


def test_condition_AB_requires_a_completed_session_and_the_t_plus_1_offset(
    session: Session,
) -> None:
    """A same-session fill is refused: the equity convention is signal at t, fill
    at t+1, and an options path that filled at t would fill a full session
    earlier, on a close its own signal was computed from."""
    cand, acct = _world(session)
    assert acct is not None
    with pytest.raises(OptionsAutoSimulateForbidden) as exc:
        assert_options_auto_simulate_allowed(
            session,
            cand,
            account_name=fx.OPTIONS_ACCOUNT,
            pricing=fx.pricing(),
            signal_session=fx.FILL_SESSION,
            fill_session=fx.FILL_SESSION,
        )
    assert exc.value.condition == "AB"
    assert "fill at t+1" in str(exc.value)


def test_condition_AB_refuses_a_non_session_fill_date(session: Session) -> None:
    saturday = date(2026, 2, 21)
    cand, acct = _world(session)
    assert acct is not None
    fx.option_prints(session, sessions=[saturday])
    fx.clean_reconcile_report(session, acct, as_of=saturday)
    with pytest.raises(OptionsAutoSimulateForbidden) as exc:
        assert_options_auto_simulate_allowed(
            session,
            cand,
            account_name=fx.OPTIONS_ACCOUNT,
            pricing=fx.pricing(),
            signal_session=fx.SIGNAL_SESSION,
            fill_session=saturday,
        )
    assert exc.value.condition == "AB"


def test_the_shaping_parameters_come_from_spec_json_when_the_strategy_carries_them(
    session: Session,
) -> None:
    """D3 §4: the shaping group lives in the strategy's own ``spec_json``, so it
    is inside ``spec_json_hash`` and the five-part scope match. The configured
    values are DEFAULTS for a strategy that carries no options block."""
    from signalforge.db.models import StrategyVersion

    cand, _ = _world(session)
    ver = session.get(StrategyVersion, cand.strategy_version_id)
    assert ver is not None
    ver.spec_json = {"options": {"max_short_delta": 0.0005, "structure_type": "vertical_credit"}}
    session.flush()
    exc = _refusal(session, cand)
    assert exc.condition == "S"
    assert "0.0005" in str(exc)


def test_a_refusal_carries_a_named_condition_and_a_distinct_exception_type(
    session: Session,
) -> None:
    """A DISTINCT type, so no existing ``except AutoSimulateForbidden`` handler
    anywhere in the tree can swallow an options refusal."""
    from signalforge.paper.ledger import AutoSimulateForbidden

    cand, _ = _world(session, arm=False)
    assert not issubclass(OptionsAutoSimulateForbidden, AutoSimulateForbidden)
    exc = _refusal(session, cand)
    assert exc.condition and exc.detail
    assert not isinstance(exc, AutoSimulateForbidden)


def test_nothing_is_written_by_a_refusal(session: Session) -> None:
    from sqlalchemy import func, select

    from signalforge.db.models import OptionsCollateralEntry, OptionsPosition, OptionsTrade

    cand, acct = _world(session, arm=False)
    assert acct is not None
    _refusal(session, cand)
    for model in (OptionsPosition, OptionsTrade, OptionsCollateralEntry):
        assert session.scalar(select(func.count()).select_from(model)) == 0
    assert acct.collateral_reserved == Decimal("0")
    assert acct.cash == fx.OPTIONS_ACCOUNT_CASH


def test_the_structure_row_and_the_contract_row_are_never_mutated(session: Session) -> None:
    cand, _ = _world(session)
    before = session.scalar(
        __import__("sqlalchemy")
        .select(CandidateOptionStructure)
        .where(CandidateOptionStructure.candidate_id == cand.id)
    )
    assert before is not None
    legs_before = list(before.legs_json)
    _call(session, cand)
    assert before.legs_json == legs_before
    contract = session.scalar(
        __import__("sqlalchemy")
        .select(OptionContract)
        .where(OptionContract.option_ticker == fx.SHORT_TICKER)
    )
    assert contract is not None and contract.shares_per_contract == 100
