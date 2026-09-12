"""The one place that answers "does this deployment operate on INTRADAY?".

Before this module the answer was stated in four places that did not agree
(design §A.2, §11 item 1):

1. ``ResearchConfig.enabled_horizons`` **includes** ``Horizon.INTRADAY``, so
   the routine research scan has always scanned it;
2. ``approved_scope_scan.approved_horizons`` **excluded** it unconditionally;
3. ``alerts.dispatch`` **skipped** it unconditionally;
4. ``MassiveAdapter`` declared no intraday feed at all.

Each surface hard-coded its own answer, so "EOD-only" was a property of four
separate lines of code rather than a decision anyone could make, read or
reverse. Every surface now asks this module, and the answer comes from one
config flag: ``research.intraday.operating_enabled`` (default False).

**What OFF means.** Byte-identical to the behaviour before the flag existed:
the approved-scope scan refuses INTRADAY, the alert dispatcher skips it, and no
intraday job is scheduled. The routine research scan keeps scanning the
horizon, exactly as it always has — that is research, not operation, and with
no intraday bars it produces nothing.

**What ON does not buy.** Operating intraday does not make intraday execution
realistic on this entitlement, and nothing here pretends otherwise: the feed is
DELAYED >= 15 min against a 15m research bar, so the modelled next-bar-open
fill is permanently one bar earlier than any live action could be. That
disclosure travels with the policy (:data:`LATENCY_DISCLOSURE`) so a surface
that starts operating intraday cannot do so silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time
from typing import Any

from signalforge.config.research import ResearchConfig
from signalforge.data.calendar import bar_minutes
from signalforge.domain import Horizon

LATENCY_DISCLOSURE = (
    "intraday operation runs on a DELAYED (>= 15 min) feed: at a 15m bar the backtest's "
    "next-bar-open fill is one bar earlier than this entitlement can attain, so an intraday "
    "candidate is research evidence, never an executable price"
)


def operating_enabled(cfg: ResearchConfig) -> bool:
    """The single switch. Everything else in this module derives from it."""
    return bool(cfg.intraday.operating_enabled)


def operating_horizons(cfg: ResearchConfig, horizons: Sequence[Horizon]) -> list[Horizon]:
    """``horizons`` filtered by the intraday operating policy.

    Used by every surface that ACTS on a horizon (scans an approved dataset,
    dispatches an alert). Order is preserved so a caller's own ordering, and
    therefore its output, is unchanged when the policy removes nothing."""
    if operating_enabled(cfg):
        return list(horizons)
    return [h for h in horizons if h is not Horizon.INTRADAY]


def scan_interval_minutes(cfg: ResearchConfig) -> int:
    """Cadence of the in-session scan: the bar size unless overridden.

    A finer cadence cannot see anything new — there is no new bar — and a
    coarser one would skip signals the strategy's own entry window admits."""
    override = cfg.intraday.scan_interval_minutes
    return int(override) if override else bar_minutes(cfg.intraday_bar_size)


def _parse_et(value: str) -> time:
    hh, _, mm = value.partition(":")
    return time(int(hh), int(mm or 0))


def in_session_window(cfg: ResearchConfig, now: datetime | None = None) -> bool:
    """True only inside the configured RTH window of a real exchange session.

    Checked against the NYSE calendar, so holidays and early closes are not a
    list anyone has to maintain."""
    from datetime import UTC
    from zoneinfo import ZoneInfo

    from signalforge.data.calendar import is_session, rth_bounds

    et = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/New_York"))
    day = et.date()
    if not is_session(day):
        return False
    bounds = rth_bounds(day)
    if bounds is None:
        return False
    lo = max(_parse_et(cfg.intraday.session_start_et), bounds[0].time())
    hi = min(_parse_et(cfg.intraday.session_end_et), bounds[1].time())
    return lo <= et.time().replace(tzinfo=None) < hi


def policy_surfaces(cfg: ResearchConfig) -> dict[str, Any]:
    """What every surface will do with INTRADAY under this config.

    Exists so the consistency of the four surfaces is a thing that can be
    asserted in one test and printed in one operator report, instead of being
    re-derived by reading four modules."""
    enabled = operating_enabled(cfg)
    return {
        "operating_enabled": enabled,
        "research_scan_horizons_include_intraday": Horizon.INTRADAY in cfg.enabled_horizons,
        "approved_scope_scan_includes_intraday": enabled,
        "alerts_dispatch_includes_intraday": enabled,
        "scheduled_intraday_scan_job": enabled,
        "scan_interval_minutes": scan_interval_minutes(cfg),
        "bar_size": cfg.intraday_bar_size,
        "latency_disclosure": LATENCY_DISCLOSURE,
    }
