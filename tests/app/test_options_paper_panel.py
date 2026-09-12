"""The Paper Probation page's minimal options panel (W3c).

Minimal by design, not by omission. Contract S16 forbids ``signalforge.app`` from
importing ``paper.options_ledger`` / ``options_marks`` / ``options_auto_simulate``
by any number of hops, so the richer reader behind ``options-paper status``
(``options_portfolio_snapshot``) is not reachable from a view. The panel is fed
by ``research.paper_probation.options_paper_status``, which touches ORM models
and nothing else — asserted here and by ``lint-imports``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient


def test_the_panel_says_so_when_no_options_account_exists(
    registered_client: TestClient,
) -> None:
    r = registered_client.get("/paper-probation")
    assert r.status_code == 200
    assert "Options paper book (SIMULATED, separate account)" in r.text
    assert "does not exist" in r.text
    assert "condition AA refuses to open without a dated, clean one" in r.text
    assert "research.options.paper_eod_enabled" in r.text
    assert "auto_simulate_options_enabled" in r.text
    assert "never run" in r.text


def test_the_panel_reports_the_account_structures_and_reconciliation(
    registered_client: TestClient,
) -> None:
    from signalforge.db.models import (
        Instrument,
        JobRun,
        OptionsPosition,
        OptionsReconcileReport,
        PaperAccount,
    )
    from signalforge.db.session import session_scope

    with session_scope(write=True) as s:
        acct = PaperAccount(
            name="options",
            initial_cash=Decimal("25000"),
            cash=Decimal("25050"),
            collateral_reserved=Decimal("200"),
        )
        inst = Instrument(symbol="SPY", instrument_type="etf")
        s.add_all([acct, inst])
        s.flush()
        s.add(
            OptionsPosition(
                account_id=acct.id,
                underlying_instrument_id=inst.id,
                underlying_symbol="SPY",
                structure_type="vertical_credit",
                contracts=1,
                entry_net_premium=Decimal("50"),
                r_dollars=Decimal("200"),
                collateral_reserved=Decimal("200"),
                expiration_date=date(2026, 3, 20),
                opened_at=datetime(2026, 2, 18, 21, 0, tzinfo=UTC),
            )
        )
        s.add(
            OptionsReconcileReport(
                account_id=acct.id,
                as_of=date(2026, 2, 18),
                clean=True,
                findings_json=[],
                open_structures=1,
            )
        )
        s.add(
            JobRun(
                name="options_paper_eod",
                started_at=datetime(2026, 2, 18, 23, 30, tzinfo=UTC),
                finished_at=datetime(2026, 2, 18, 23, 31, tzinfo=UTC),
                status="ok",
                detail="",
            )
        )

    r = registered_client.get("/paper-probation")
    assert r.status_code == 200
    assert "Collateral reconciliation 2026-02-18" in r.text
    assert "SPY vertical_credit" in r.text
    assert "last ok," in r.text
    assert "SIMULATED options paper account — no order was ever placed." in r.text
