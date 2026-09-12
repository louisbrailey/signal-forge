"""`evaluate-promotion --snapshot-key`: keyed datasets are reachable from the CLI.

Without it, an evaluation on a symbol set that some other snapshot already
covers silently re-attaches to that snapshot — for the 24-symbol ex-META
universe that is the DAILY snapshot the live paper approvals sit on. The key is
what keeps an intraday evaluation's gate-9 sealed test on its own dataset.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.db.models import DataSnapshot, StrategyPromotionEvaluation

KEY = "research_24_intraday15m_2016_2025"


def _run(*args: str):
    return CliRunner().invoke(app, ["evaluate-promotion", *args])


def test_snapshot_key_creates_and_reuses_one_keyed_snapshot(db_url: str) -> None:
    result = _run(
        "--strategy",
        "intraday_orb",
        "--symbols",
        "AAPL,MSFT",
        "--snapshot-key",
        KEY,
        "--since",
        "2024-09-22",
        "--until",
        "2026-09-08",
    )
    assert result.exit_code == 0, result.output
    assert KEY in result.output
    assert "sealed test is keyed to THIS dataset" in result.output
    # the disclosure survives (gate 0 fails on absent intraday data, so no look
    # is taken — and that is stated rather than left blank)
    assert "sealed looks:" in result.output
    assert "NO TRADE" in result.output

    from signalforge.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        snaps = list(session.scalars(select(DataSnapshot).where(DataSnapshot.key == KEY)))
        assert len(snaps) == 1
        assert sorted(snaps[0].symbols_json) == ["AAPL", "MSFT"]
        ev = session.scalars(
            select(StrategyPromotionEvaluation).order_by(StrategyPromotionEvaluation.id.desc())
        ).first()
        assert ev is not None and ev.dataset_snapshot_id == snaps[0].id

    # a second run reuses the same row rather than creating a sibling
    again = _run(
        "--strategy",
        "intraday_orb",
        "--symbols",
        "AAPL,MSFT",
        "--snapshot-key",
        KEY,
        "--since",
        "2024-09-22",
        "--until",
        "2026-09-08",
    )
    assert again.exit_code == 0, again.output
    with get_sessionmaker()() as session:
        assert len(list(session.scalars(select(DataSnapshot).where(DataSnapshot.key == KEY)))) == 1


def test_snapshot_key_refuses_to_reinterpret_an_existing_key(db_url: str) -> None:
    """A DataSnapshot is immutable once created. Pointing the same key at a
    different symbol set must fail loudly, not silently re-describe the data
    every earlier evaluation was run on."""
    first = _run("--strategy", "intraday_orb", "--symbols", "AAPL,MSFT", "--snapshot-key", KEY)
    assert first.exit_code == 0, first.output

    clash = _run("--strategy", "intraday_orb", "--symbols", "AAPL,NVDA", "--snapshot-key", KEY)
    assert clash.exit_code == 1
    assert "already exists" in clash.output
    assert "immutable" in clash.output


def test_without_the_key_an_evaluation_attaches_to_the_matching_snapshot(
    db_url: str, session: Session
) -> None:
    """The hazard the flag exists to remove, pinned as a test: an unkeyed run
    joins whatever reusable snapshot already covers the same symbols."""
    existing = DataSnapshot(
        key="universe_2_daily_preexisting",
        symbols_json=["AAPL", "MSFT"],
        description="stands in for the daily snapshot the live approvals sit on",
    )
    session.add(existing)
    session.commit()
    existing_id = existing.id

    result = _run("--strategy", "intraday_orb", "--symbols", "AAPL,MSFT")
    assert result.exit_code == 0, result.output
    assert f"dataset_snapshot_id {existing_id}" in result.output

    keyed = _run("--strategy", "intraday_orb", "--symbols", "AAPL,MSFT", "--snapshot-key", KEY)
    assert keyed.exit_code == 0, keyed.output
    assert f"dataset_snapshot_id {existing_id}" not in keyed.output


def test_snapshot_key_defaults_to_the_configured_universe(db_url: str) -> None:
    result = _run("--strategy", "intraday_orb", "--snapshot-key", "keyed_full_universe")
    assert result.exit_code == 0, result.output

    from signalforge.config import get_settings
    from signalforge.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        snap = session.scalar(select(DataSnapshot).where(DataSnapshot.key == "keyed_full_universe"))
        assert snap is not None
        assert sorted(snap.symbols_json) == sorted(get_settings().research.universe)


def test_the_three_named_datasets_still_work_unchanged(db_url: str) -> None:
    result = _run(
        "--strategy", "intraday_orb", "--dataset", "ex_meta", "--until", str(date.today())
    )
    assert result.exit_code == 0, result.output
    assert "NO TRADE" in result.output
