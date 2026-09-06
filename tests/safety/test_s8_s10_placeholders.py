"""S8 & S10 placeholders — implemented in Phase 1, tracked here so the suite is honest."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.safety


@pytest.mark.skip(reason="Phase 1 §1.3/§1.12: FreshnessGate disables live alerts on stale feeds")
def test_s8_stale_feed_disables_live_alerts() -> None: ...


@pytest.mark.skip(
    reason="Phase 1 §1.6: probability shown only with a calibrated OOS calibration_ref"
)
def test_s10_probability_requires_calibration_ref() -> None: ...
