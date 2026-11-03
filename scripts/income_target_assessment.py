"""Read-only arithmetic and paper evidence; never a forecast or trading input."""

from __future__ import annotations

import argparse
import json
import sqlite3
from decimal import Decimal
from pathlib import Path


def assess(path: Path) -> dict:
    if not path.is_file():
        raise ValueError("An existing operating SQLite database is required")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if any(name.startswith("comparison_") for name in tables):
            raise ValueError("Frozen comparison databases are excluded from this assessment")
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
    print(json.dumps(assess(parser.parse_args().database), indent=2))
