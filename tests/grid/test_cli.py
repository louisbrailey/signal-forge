"""`signalforge grid backtest` / `grid status`: read-only, reports written."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from signalforge.cli import app
from tests.grid.conftest import GRID_SOURCE, BarWriter

_CLOSES = [100.0, 100.0, 94.90, 94.90, 99.70, 99.70]
_OPENS = [100.0, 100.0, 94.90, 90.00, 99.70, 101.00]


def test_backtest_is_read_only_and_writes_a_report(
    db_url: str, write_bars: BarWriter, tmp_path: Path, session: object
) -> None:
    from signalforge.db.models import GridPosition, GridTradeRow, PaperAccount
    from signalforge.db.session import session_scope

    write_bars("AAA", _CLOSES, _OPENS)
    write_bars("SPY", [400.0, 402.0, 404.0, 406.0, 408.0, 410.0])
    session.commit()  # type: ignore[attr-defined]

    out = tmp_path / "reports"
    result = CliRunner().invoke(
        app,
        [
            "grid",
            "backtest",
            "--symbols",
            "AAA",
            "--source",
            GRID_SOURCE,
            "--since",
            "2024-01-01",
            "--until",
            "2024-01-31",
            "--starting-cash",
            "1000",
            "--per-symbol-cap",
            "50",
            "--out",
            str(out),
            "--slug",
            "cli_run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "total return" in result.output
    assert "SPY buy-and-hold" in result.output
    assert "no order was placed" in result.output

    md = out / "cli_run.md"
    js = out / "cli_run.json"
    assert md.is_file() and js.is_file()
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["metrics"]["n_buys"] == 1 and payload["metrics"]["n_sells"] == 1

    # READ-ONLY: the backtest must not have created any live grid state.
    with session_scope() as s:
        assert not list(s.scalars(select(GridTradeRow)))
        assert not list(s.scalars(select(GridPosition)))
        assert s.scalar(select(PaperAccount).where(PaperAccount.name == "grid")) is None


def test_backtest_reports_symbols_with_no_bars(
    db_url: str, write_bars: BarWriter, tmp_path: Path, session: object
) -> None:
    write_bars("AAA", _CLOSES, _OPENS)
    session.commit()  # type: ignore[attr-defined]
    result = CliRunner().invoke(
        app,
        [
            "grid",
            "backtest",
            "--symbols",
            "AAA,NOPE",
            "--source",
            GRID_SOURCE,
            "--out",
            str(tmp_path),
            "--slug",
            "missing",
            "--benchmark",
            "",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "1 skipped" in result.output
    payload = json.loads((tmp_path / "missing.json").read_text(encoding="utf-8"))
    assert payload["skipped_symbols"] == ["NOPE"]


def test_backtest_warns_when_the_budget_is_inconsistent(
    db_url: str, write_bars: BarWriter, tmp_path: Path, session: object
) -> None:
    write_bars("AAA", _CLOSES, _OPENS)
    session.commit()  # type: ignore[attr-defined]
    result = CliRunner().invoke(
        app,
        [
            "grid",
            "backtest",
            "--symbols",
            "AAA",
            "--source",
            GRID_SOURCE,
            "--starting-cash",
            "5",
            "--per-symbol-cap",
            "50",
            "--out",
            str(tmp_path),
            "--slug",
            "budget",
            "--benchmark",
            "",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "cash will bind before the caps do" in result.output


def test_backtest_from_a_data_snapshot_key(
    db_url: str, write_bars: BarWriter, tmp_path: Path, session: object
) -> None:
    from signalforge.db.models import DataSnapshot

    write_bars("AAA", _CLOSES, _OPENS)
    write_bars("BBB", _CLOSES, _OPENS)
    session.add(  # type: ignore[attr-defined]
        DataSnapshot(key="unit_snap", symbols_json=["AAA", "BBB"], description="unit test")
    )
    session.commit()  # type: ignore[attr-defined]

    result = CliRunner().invoke(
        app,
        [
            "grid",
            "backtest",
            "--snapshot-key",
            "unit_snap",
            "--top",
            "1",
            "--source",
            GRID_SOURCE,
            "--out",
            str(tmp_path),
            "--slug",
            "snap",
            "--benchmark",
            "",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads((tmp_path / "snap.json").read_text(encoding="utf-8"))
    assert len(payload["universe"]["symbols"]) == 1


def test_unknown_snapshot_key_exits_nonzero(db_url: str, tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["grid", "backtest", "--snapshot-key", "nope", "--out", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "no DataSnapshot" in result.output


def test_grid_status_prints_the_live_state(db_url: str) -> None:
    result = CliRunner().invoke(app, ["grid", "status"])
    assert result.exit_code == 0, result.output
    body = result.output[: result.output.rindex("}") + 1]
    payload = json.loads(body)
    assert payload["enabled"] is False
    assert payload["account_name"] == "grid"
    assert payload["params"]["universe_size"] == 1000
    assert "no order was placed" in result.output


def test_backtest_rejects_an_inverted_window(db_url: str, tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "grid",
            "backtest",
            "--since",
            str(date(2025, 1, 1)),
            "--until",
            str(date(2024, 1, 1)),
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
