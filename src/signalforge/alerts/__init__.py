"""Alert dispatch: policy engine + channel adapters.

Default policy: all channels OFF until the user completes setup; the local
on-disk log is always written; <= 2 high-priority candidate alerts/day (only for
paper_approved strategies on a fresh feed); one daily briefing; nothing when data
is stale or a strategy is disabled; nothing overnight except system-health
failures; no options alerts. Every alert body includes
``Research signal only — no order was placed.`` and a link to the local
evidence page.
"""

from __future__ import annotations

from signalforge.alerts.dispatch import AlertCycleResult, plan_alerts, run_alert_cycle

__all__ = ["AlertCycleResult", "plan_alerts", "run_alert_cycle"]
