"""``signalforge options-paper status`` — read-only, and it says what it is.

The command opens nothing, closes nothing and reconciles nothing: it is the
operator's view of a SIMULATED book, and it reports the two accounts side by side
rather than merging them (decision 13: they are separate populations).
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.db.models import OptionsCollateralEntry, OptionsPosition, OptionsTrade
from signalforge.db.session import session_scope
from signalforge.paper.options_ledger import (
    OPTIONS_AUTO_SIM_CAP_KEY,
    OPTIONS_AUTO_SIM_ENABLED_KEY,
    accept_options_candidate,
    assert_options_auto_simulate_allowed,
)
from signalforge.settings_store import set_setting
from tests.paper import options_support as fx


def _seed(db_url: str, *, opened: bool = True) -> None:
    with session_scope(write=True) as session:
        acct = fx.options_account(session)
        inst = fx.underlying(session)
        fx.contracts(session)
        fx.option_prints(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION])
        ver = fx.approved_strategy(session)
        cand = fx.options_candidate(session, instrument=inst, version=ver)
        fx.approve_scope(session, cand, ver)
        fx.clean_reconcile_report(session, acct, as_of=fx.FILL_SESSION)
        set_setting(session, OPTIONS_AUTO_SIM_ENABLED_KEY, True)
        set_setting(session, OPTIONS_AUTO_SIM_CAP_KEY, 2)
        if opened:
            plan = assert_options_auto_simulate_allowed(
                session,
                cand,
                account_name=fx.OPTIONS_ACCOUNT,
                pricing=fx.pricing(),
                signal_session=fx.SIGNAL_SESSION,
                fill_session=fx.FILL_SESSION,
            )
            accept_options_candidate(
                session,
                cand.id,
                account_name=fx.OPTIONS_ACCOUNT,
                plan=plan,
                pricing=fx.pricing(),
            )


def test_status_on_a_missing_account_says_how_to_create_it(db_url: str) -> None:
    result = CliRunner().invoke(app, ["options-paper", "status"])
    assert result.exit_code == 0
    assert "does not exist" in result.stdout
    assert "paper init --name options" in result.stdout
    assert "25,000" in result.stdout


def test_status_reports_the_book_its_caps_and_the_reconciliation(db_url: str) -> None:
    _seed(db_url)
    result = CliRunner().invoke(
        app, ["options-paper", "status", "--as-of", fx.FILL_SESSION.isoformat()]
    )
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "options paper account 'options' (SIMULATED)" in out
    assert "collateral 200.00" in out
    assert "spendable" in out
    assert "net delta" in out and "combined" in out and "net vega" in out
    assert "reconciliation 2026-02-18: clean" in out
    assert f"{OPTIONS_AUTO_SIM_ENABLED_KEY}: ON" in out
    assert "SIMULATED options structure — no order was placed." in out
    assert "SPY vertical_credit x1" in out


def test_status_warns_when_no_reconciliation_report_exists_for_the_session(
    db_url: str,
) -> None:
    """Condition AA is positive and dated; the operator should be able to see
    that the guard would refuse, rather than infer it from silence."""
    _seed(db_url)
    result = CliRunner().invoke(app, ["options-paper", "status", "--as-of", "2026-02-19"])
    assert result.exit_code == 0
    # the most recent report is still shown, dated, so staleness is visible
    assert "reconciliation 2026-02-18" in result.stdout


def test_status_is_read_only(db_url: str) -> None:
    _seed(db_url)
    with session_scope() as session:
        before = (
            session.scalar(select(func.count()).select_from(OptionsPosition)),
            session.scalar(select(func.count()).select_from(OptionsTrade)),
            session.scalar(select(func.count()).select_from(OptionsCollateralEntry)),
        )
    assert CliRunner().invoke(app, ["options-paper", "status"]).exit_code == 0
    assert CliRunner().invoke(app, ["options-paper", "status", "--json"]).exit_code == 0
    with session_scope() as session:
        after = (
            session.scalar(select(func.count()).select_from(OptionsPosition)),
            session.scalar(select(func.count()).select_from(OptionsTrade)),
            session.scalar(select(func.count()).select_from(OptionsCollateralEntry)),
        )
    assert before == after


def test_status_json_carries_the_whole_snapshot(db_url: str) -> None:
    _seed(db_url)
    result = CliRunner().invoke(
        app, ["options-paper", "status", "--json", "--as-of", fx.FILL_SESSION.isoformat()]
    )
    assert result.exit_code == 0, result.stdout
    snap = json.loads(result.stdout)
    assert snap["account"] == "options"
    assert snap["n_open"] == 1
    assert set(snap["greeks"]) == {
        "options_net_delta_notional",
        "options_net_vega_per_vol_pt",
        "equity_net_delta_notional",
        "combined_net_delta_notional",
    }
    assert snap["limits"]["per_structure_max_loss_dollars"] == 250.0
    assert any("SEPARATE populations" in d for d in snap["disclosures"])
