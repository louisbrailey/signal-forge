"""Deterministic risk engine: position sizing and portfolio-limit enforcement.

Never imports :mod:`signalforge.llm` (invariant S3). A candidate that cannot be
sized within every configured limit becomes ``NO TRADE``.
"""

from __future__ import annotations

from signalforge.risk.engine import (
    OpenExposure,
    SizingRequest,
    SizingResult,
    size_position,
)
from signalforge.risk.portfolio import ExposureReport, Holding, exposure_report

__all__ = [
    "OpenExposure",
    "SizingRequest",
    "SizingResult",
    "size_position",
    "ExposureReport",
    "Holding",
    "exposure_report",
]
