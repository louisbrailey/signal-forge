"""Read-only arithmetic and paper evidence; never a forecast or trading input."""

from __future__ import annotations

import argparse
import json
import sqlite3
from decimal import Decimal
from pathlib import Path


def historical_inventory(conn: sqlite3.Connection, tables: set[str]) -> list[dict]:
    """Inventory every stored bar in known market tables; never study outcomes.

    Counts include flagged/simulated rows explicitly. Presence is not a data
    quality pass or evidence that a strategy is applicable to every asset.
    """
    inventory = []
    for table, stamp, series in (
        ("ohlcv_daily", "session_date", "instrument_id"),
        ("ohlcv_intraday", "bar_start", "instrument_id"),
        ("crypto_bar_daily", "session_date", "pair"),
        ("crypto_bar_intraday", "bar_start", "pair"),
        ("fx_bar_daily", "session_date", "pair"),
        ("option_aggregate_daily", "session_date", "option_ticker"),
    ):
        if table not in tables:
            inventory.append({"table": table, "status": "unavailable"})
            continue
        # All identifiers come from the fixed inventory above or schema names.
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        simulated = (
            "SUM(CASE WHEN is_simulated THEN 1 ELSE 0 END)" if "is_simulated" in cols else "NULL"
        )
        flagged = (
            "SUM(CASE WHEN quality_flags IS NULL OR trim(quality_flags) != '[]' THEN 1 ELSE 0 END)"
        )
        if "quality_flags" not in cols:
            flagged = "COUNT(*)"
        groups = "source,latency_category" + (",bar_size" if "bar_size" in cols else "")
        query = (
            f"SELECT {groups},COUNT(*),COUNT(DISTINCT {series}),MIN({stamp}),MAX({stamp}),"  # noqa: S608 -- fixed internal identifiers
            f"{simulated},{flagged} FROM {table} GROUP BY {groups} ORDER BY {groups}"
        )
        names = [
            *groups.split(","),
            "rows",
            "series",
            "first",
            "last",
            "simulated_rows",
            "flagged_or_unknown_quality_rows",
        ]
        inventory.append(
            {
                "table": table,
                "status": "inventoried",
                "quality_metadata_available": "quality_flags" in cols,
                "simulation_metadata_available": "is_simulated" in cols,
                "groups": [dict(zip(names, row, strict=True)) for row in conn.execute(query)],
            }
        )
    return inventory


def assess(path: Path, *, include_history: bool = False) -> dict:
    if not path.is_file():
        raise ValueError("An existing operating SQLite database is required")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if any(name.startswith("comparison_") for name in tables):
            raise ValueError("Frozen comparison databases are excluded from this assessment")
        history = historical_inventory(conn, tables) if include_history else None
        books = []
        for account_id, name, initial in conn.execute(
            "SELECT id,name,initial_cash FROM paper_account ORDER BY id"
        ):
            capital = Decimal(str(initial))
            outcomes = list(
                conn.execute(
                    "SELECT realized_pnl FROM paper_position "
                    "WHERE account_id=? AND closed_at IS NOT NULL",
                    (account_id,),
                )
            )
            books.append(
                {
                    "book": name,
                    "initial_paper_cash": str(capital),
                    "closed_positions": len(outcomes),
                    "recorded_realized_pnl": str(
                        sum((Decimal(str(r[0])) for r in outcomes), Decimal(0))
                    ),
                    "required_weekday_return_pct": (
                        str(Decimal(1000) / capital * 100) if capital > 0 else None
                    ),
                    "required_weekly_return_pct": (
                        str(Decimal(5000) / capital * 100) if capital > 0 else None
                    ),
                    "required_weekend_return_pct": (
                        str(Decimal(400) / capital * 100) if capital > 0 else None
                    ),
                }
            )
    return {
        "status": "INCOME_TARGET_NOT_ESTABLISHED",
        "basis": (
            "Recorded equity paper-position fields; not broker-verified profit. "
            "No combined funded portfolio is assumed."
        ),
        "targets": {"weekday_usd": 1000, "workweek_usd": 5000, "weekend_total_usd": 400},
        "books": books,
        "historical_inventory": history,
        "limitations": [
            "Return requirements are arithmetic, not expected returns or capital recommendations.",
            "Paper cash is not evidence of available real-money capital.",
            "Realized fields omit open-position changes and require legacy-correction review.",
            (
                "Daily target hit rates require complete decision-time equity marks, "
                "cash flows and costs; not calculated here."
            ),
            "No crypto R-multiple illustration is added to equity cash accounts.",
            "No study outcomes, sealed tests, or new parameter searches are accessed.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--history", action="store_true", help="Inventory all stored market bars")
    args = parser.parse_args()
    print(json.dumps(assess(args.database, include_history=args.history), indent=2))
