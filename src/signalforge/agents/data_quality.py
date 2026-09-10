"""Market-data quality agent (read-only).

Reports deterministic freshness/coverage/entitlement facts already recorded
by the data layer: feed status, ingestion runs, data-validation reports,
entitlement checks, and universe-screen quality. Never re-runs a check,
never re-fetches from a provider, never writes anything but its own
``AgentReport`` + audit event (see ``signalforge.agents.base.ResearchAgent``).

Import-boundary note (S14, ``pyproject.toml``): this module deliberately does
NOT import ``signalforge.scheduler`` (for ``last_completed_session``) or
``signalforge.universe.screen`` (for ``latest_screen`` / ``data_quality_summary``)
even though the task this agent performs conceptually wants both. Both
modules transitively import forbidden modules — ``signalforge.scheduler``
imports ``signalforge.killswitch`` directly, and ``signalforge.universe.screen``
imports ``signalforge.research.promotion`` (which imports
``signalforge.research.persistence``) — so importing either here would break
import-linter contract S14 even though the specific function this agent wants
has no side effects itself; ``lint-imports`` checks the whole transitive
import graph of a module, not just the functions actually called from it.
The small amount of logic this agent needs from them (the "last completed
U.S. session" rule; the universe screen's market-cap-coverage counts) is
reproduced locally against the ORM models instead, which have no such
entanglement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.agents.base import ResearchAgent
from signalforge.config import get_settings
from signalforge.data.feeds import feed_status_report
from signalforge.data.validate import latest_validation
from signalforge.db.models import (
    EntitlementCheck,
    IngestionRun,
    Instrument,
    OHLCVDaily,
    UniverseMember,
    UniverseScreenRun,
)
from signalforge.settings_store import effective_research_config

# Mirrors signalforge.scheduler.EOD_CRON — duplicated rather than imported;
# see the module docstring for why.
_EOD_CRON = (17, 30)  # America/New_York


def _last_completed_session(now: datetime) -> date:
    """Reproduces ``signalforge.scheduler.last_completed_session`` without
    importing ``signalforge.scheduler``. Exchange holidays are NOT modelled —
    on a holiday this expects a session that never happened, which shows as
    "1 session behind" until the next real close."""
    n = now.astimezone(ZoneInfo("America/New_York"))
    d = n.date()
    if n.weekday() >= 5 or (n.hour, n.minute) < _EOD_CRON:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


class DataQualityAgent(ResearchAgent):
    """Reads already-recorded data-health signals and reports them as-is.

    Never ingests, never probes a provider, never re-runs validation or the
    universe screen — it only reads what those deterministic jobs already
    wrote.
    """

    name = "data_quality"
    role = "Market-data quality agent"
    allowed_inputs = (
        "signalforge.data.feeds.feed_status_report",
        "signalforge.data.validate.latest_validation",
        "signalforge.db.models.IngestionRun",
        "signalforge.db.models.EntitlementCheck",
        "signalforge.db.models.UniverseScreenRun",
        "signalforge.db.models.UniverseMember",
        "signalforge.db.models.OHLCVDaily",
        "signalforge.settings_store.effective_research_config",
        "signalforge.config.get_settings",
    )
    outputs = (
        "feed_coverage",
        "stale_feed_list",
        "entitlement_limitations",
        "session_freshness",
        "reconciliation_status",
    )
    prohibited = (
        "ingest_data",
        "backfill_data",
        "probe_provider",
        "run_validation",
        "run_universe_screen",
        "write_setting",
    )
    llm_narrative = False

    def collect(self, session: Session) -> dict[str, Any]:
        now = datetime.now(UTC)
        settings = get_settings()
        provider = settings.market_data_provider or "fixture"
        secondary = settings.market_data_provider_secondary or ""
        universe = list(effective_research_config(session).universe)

        missing: list[str] = []

        # --- feed status -----------------------------------------------
        feeds = feed_status_report(session)
        if not feeds["feeds"]:
            missing.append("no data feeds registered yet — feed_status_report returned zero feeds")
        stale_feeds = [
            {
                "provider": f["provider"],
                "feed_type": f["feed_type"],
                "age_seconds": f["age_seconds"],
                "last_success_at": f["last_success_at"],
            }
            for f in feeds["feeds"]
            if f["is_stale"]
        ]

        # --- latest ingestion run per feed_type -------------------------
        feed_types = list(session.scalars(select(IngestionRun.feed_type).distinct()))
        ingestion_runs: list[dict[str, Any]] = []
        for ft in feed_types:
            row = session.scalar(
                select(IngestionRun)
                .where(IngestionRun.feed_type == ft)
                .order_by(IngestionRun.started_at.desc())
                .limit(1)
            )
            if row is None:
                continue
            ingestion_runs.append(
                {
                    "feed_type": row.feed_type.value,
                    "provider": row.provider,
                    "status": row.status,
                    "started_at": row.started_at.isoformat(),
                    "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                    "bars_written": row.bars_written,
                    "symbols_ok": len(row.symbols_ok or []),
                    "symbols_failed": len(row.symbols_failed or {}),
                    "gap_symbols": len(row.gaps_json or {}),
                    "source": "signalforge.db.models.IngestionRun",
                    "as_of": row.started_at.isoformat(),
                }
            )
        if not ingestion_runs:
            missing.append("no ingestion runs recorded yet")

        # --- data-validation report for the research provider -----------
        validation_row = latest_validation(session, provider)
        validation: dict[str, Any] | None = None
        if validation_row is None:
            missing.append(f"no data-validation report yet for provider={provider!r}")
        else:
            checks = validation_row.checks_json or {}
            failed_checks = [name for name, c in checks.items() if not c.get("passed", False)]
            validation = {
                "provider": validation_row.provider,
                "ran_at": validation_row.ran_at.isoformat(),
                "passed": validation_row.passed,
                "failed_checks": failed_checks,
                "findings": list(validation_row.findings_json or []),
                "source": "signalforge.db.models.DataValidationReport",
                "as_of": validation_row.ran_at.isoformat(),
            }

        # --- entitlement checks, latest per feed -------------------------
        entitlement_feeds = sorted(set(session.scalars(select(EntitlementCheck.feed).distinct())))
        entitlements: list[dict[str, Any]] = []
        for feed_name in entitlement_feeds:
            ent_row = session.scalar(
                select(EntitlementCheck)
                .where(EntitlementCheck.feed == feed_name)
                .order_by(EntitlementCheck.checked_at.desc())
                .limit(1)
            )
            if ent_row is None:
                continue
            entitlements.append(
                {
                    "feed": ent_row.feed,
                    "subscription": ent_row.subscription,
                    "available": ent_row.available,
                    "http_status": ent_row.http_status,
                    "latency_category": ent_row.latency_category,
                    "error_category": ent_row.error_category,
                    "detail": ent_row.detail,
                    "source": ent_row.source,
                    "as_of": ent_row.checked_at.isoformat(),
                }
            )
        if not entitlements:
            missing.append(
                "no entitlement checks recorded yet — run `signalforge providers verify`"
            )
        entitlement_blocked = [
            e for e in entitlements if not e["available"] or e["http_status"] == 403
        ]

        # --- universe screen data quality --------------------------------
        screen_run = session.scalar(
            select(UniverseScreenRun)
            .where(UniverseScreenRun.status == "ok")
            .order_by(UniverseScreenRun.started_at.desc())
            .limit(1)
        )
        universe_quality: dict[str, Any] | None = None
        if screen_run is None:
            missing.append("no universe screen run yet")
        else:
            cs_in_scope = int(
                session.scalar(
                    select(func.count())
                    .select_from(UniverseMember)
                    .where(
                        UniverseMember.run_id == screen_run.id,
                        UniverseMember.security_type == "CS",
                    )
                )
                or 0
            )
            cs_missing_cap = int(
                session.scalar(
                    select(func.count())
                    .select_from(UniverseMember)
                    .where(
                        UniverseMember.run_id == screen_run.id,
                        UniverseMember.security_type == "CS",
                        UniverseMember.market_cap.is_(None),
                    )
                )
                or 0
            )
            universe_quality = {
                "screen_date": screen_run.screen_date.isoformat(),
                "started_at": screen_run.started_at.isoformat(),
                "eligible": screen_run.eligible,
                "discovered": screen_run.discovered,
                "in_scope_types": screen_run.in_scope_types,
                "excluded_by_reason": dict(screen_run.excluded_by_reason or {}),
                "cs_in_scope": cs_in_scope,
                "market_cap_unavailable": cs_missing_cap,
                "source": "signalforge.db.models.UniverseScreenRun/UniverseMember",
                "as_of": screen_run.started_at.isoformat(),
            }

        # --- expected-session freshness ----------------------------------
        expected_session = _last_completed_session(now)
        newest_bar = session.scalar(
            select(func.max(OHLCVDaily.session_date))
            .join(Instrument, Instrument.id == OHLCVDaily.instrument_id)
            .where(OHLCVDaily.source == provider, Instrument.symbol.in_(universe))
        )
        sessions_behind: int | None = None
        if newest_bar is None:
            missing.append(
                f"no OHLCV daily bars for source={provider!r} across the configured research "
                f"universe ({len(universe)} symbols)"
            )
        else:
            d = newest_bar
            sessions_behind = 0
            while d < expected_session:
                d += timedelta(days=1)
                if d.weekday() < 5:
                    sessions_behind += 1
        freshness = {
            "provider": provider,
            "universe_size": len(universe),
            "expected_session": expected_session.isoformat(),
            "newest_bar": newest_bar.isoformat() if newest_bar else None,
            "sessions_behind": sessions_behind,
            "note": "exchange holidays are not modelled: a holiday can show as 1 session behind",
            "source": "signalforge.db.models.OHLCVDaily",
            "as_of": now.isoformat(),
        }

        # --- cross-source reconciliation ----------------------------------
        if secondary:
            reconciliation = {
                "secondary_provider": secondary,
                "possible": True,
                "note": (
                    "a secondary source is configured — cross-source reconciliation is "
                    "possible; this read-only agent does not run it"
                ),
                "as_of": now.isoformat(),
            }
        else:
            reconciliation = {
                "secondary_provider": None,
                "possible": False,
                "as_of": now.isoformat(),
            }
            missing.append("no secondary source configured — cross-source reconciliation not run")

        return {
            "as_of": now.isoformat(),
            "provider": provider,
            "feeds": feeds["feeds"],
            "stale_feeds": stale_feeds,
            "ingestion_runs": ingestion_runs,
            "validation": validation,
            "entitlements": entitlements,
            "entitlement_blocked": entitlement_blocked,
            "universe_quality": universe_quality,
            "freshness": freshness,
            "reconciliation": reconciliation,
            "missing_data": missing,
        }

    def summarize(self, evidence: dict[str, Any]) -> str:
        lines: list[str] = [
            f"Data-quality report as of {evidence['as_of']} "
            f"(research provider: {evidence['provider']})."
        ]

        stale = evidence["stale_feeds"]
        if stale:
            names = ", ".join(f"{s['provider']}/{s['feed_type']}" for s in stale)
            lines.append(f"STALE FEEDS ({len(stale)}): {names}.")
        elif evidence["feeds"]:
            lines.append("No feeds are currently flagged stale.")
        else:
            lines.append("No feeds are registered yet.")

        fr = evidence["freshness"]
        if fr["sessions_behind"] is None:
            lines.append(
                f"Daily-bar freshness for {fr['provider']} could not be determined "
                "(no bars for the configured universe)."
            )
        elif fr["sessions_behind"] == 0:
            lines.append(
                f"Daily bars for {fr['provider']} are current through the expected "
                f"session {fr['expected_session']}."
            )
        else:
            lines.append(
                f"Daily bars for {fr['provider']} are {fr['sessions_behind']} session(s) behind "
                f"the expected session {fr['expected_session']} (newest bar: {fr['newest_bar']})."
            )

        val = evidence["validation"]
        if val is None:
            lines.append(
                f"No data-validation report exists yet for provider={evidence['provider']!r}."
            )
        elif val["passed"]:
            lines.append(f"Latest data-validation report ({val['ran_at']}) passed all checks.")
        else:
            lines.append(
                f"Latest data-validation report ({val['ran_at']}) FAILED checks: "
                + ", ".join(val["failed_checks"])
                + "."
            )

        blocked = evidence["entitlement_blocked"]
        if blocked:
            names = ", ".join(
                f"{e['feed']} (http={e['http_status']}, {e['error_category']})" for e in blocked
            )
            lines.append(f"Entitlement limitations ({len(blocked)}): {names}.")
        elif evidence["entitlements"]:
            lines.append("No entitlement limitations found on the latest checks.")
        else:
            lines.append("No entitlement checks have been recorded yet.")

        uq = evidence["universe_quality"]
        if uq is None:
            lines.append("No universe screen run has been recorded yet.")
        else:
            lines.append(
                f"Latest universe screen ({uq['started_at']}): {uq['eligible']} eligible of "
                f"{uq['discovered']} discovered; {uq['market_cap_unavailable']} of "
                f"{uq['cs_in_scope']} common-stock members have no market cap "
                "(market_cap_unavailable)."
            )

        rec = evidence["reconciliation"]
        if rec["possible"]:
            lines.append(
                f"A secondary source ({rec['secondary_provider']}) is configured; cross-source "
                "reconciliation is possible but was not run by this read-only agent."
            )
        else:
            lines.append(
                "No secondary source is configured — cross-source reconciliation is not run."
            )

        if evidence["missing_data"]:
            lines.append(
                f"Missing data ({len(evidence['missing_data'])}): "
                + "; ".join(evidence["missing_data"])
                + "."
            )

        return "\n".join(lines)
