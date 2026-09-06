"""Alert dispatch: policy engine + channel adapters.

Default policy (Phase 1): all channels OFF until setup completed; local on-page +
log file always available; <= 2 high-priority candidate alerts/day; 1 daily
briefing; nothing when data is stale or a strategy is disabled; nothing overnight
except system-health failures; no options alerts. Every alert body includes
``Research signal only — no order was placed.`` and a link to the local evidence
page.
"""

from __future__ import annotations
