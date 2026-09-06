"""Tracker for safety invariants still landing later in Phase 1.

S8 (stale feed disables live alerts) is now covered by
``tests/data/test_freshness.py`` and the alert-policy tests.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.safety


@pytest.mark.skip(
    reason="Phase 1 §1.6: probability shown only with a calibrated OOS calibration_ref"
)
def test_s10_probability_requires_calibration_ref() -> None: ...
