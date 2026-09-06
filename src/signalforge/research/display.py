"""Render-time guards for candidate presentation (invariant S10).

A probability/confidence figure is shown **only** when it is a calibrated
out-of-sample number for that exact strategy version — i.e. only when a
``calibration_ref`` is present. Otherwise the UI shows nothing rather than an
unearned number.
"""

from __future__ import annotations


def probability_display(
    probability_calibrated: float | None,
    calibration_ref: str | None,
) -> str | None:
    if probability_calibrated is None or not calibration_ref:
        return None
    p = max(0.0, min(1.0, probability_calibrated))
    return f"{p:.0%}"


def confidence_note(calibration_ref: str | None) -> str:
    if calibration_ref:
        return f"Calibrated out-of-sample (ref: {calibration_ref})."
    return (
        "No calibrated probability — this system has no out-of-sample evidence of "
        "predictive value for this setup. Treat the setup as unproven."
    )
