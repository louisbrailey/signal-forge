"""Manual, OFFLINE broker-CSV import for portfolio analytics only (invariant S2).

This package must never perform network I/O and must never import
``signalforge.data``. Imported positions/transactions are used for
exposure/concentration visualisation and are NEVER fed to the scanner as
tradable candidates.
"""

from __future__ import annotations

from signalforge.portfolio.import_csv import (
    ImportPreview,
    ImportSummary,
    import_csv,
    portfolio_analytics,
    sniff,
)

__all__ = [
    "ImportPreview",
    "ImportSummary",
    "import_csv",
    "portfolio_analytics",
    "sniff",
]
