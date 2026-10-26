# Reliability audit and operating guide

The web process and CLI scheduler are separate. A working dashboard does not
prove ingestion or paper reconciliation is running. `/ops` displays the worker's
persisted heartbeat, scheduled jobs, ingestion readiness and paper execution
posture. Disabled execution is intentional, not a missing-job fault. With
execution enabled, both a current heartbeat and a registered execution cycle
are necessary; neither proves the last reconciliation succeeded. Check job
outcomes and the paper journal as well.

Future-dated successful-feed timestamps now block the freshness gate. A future
worker heartbeat is not healthy. Correct the host clock rather than editing
stored timestamps. If duplicate-worker verification cannot read the database,
startup refuses with a sanitized error. Resolve database availability and inspect
other workers before retrying; do not bypass the guard.

## Daily operation

1. Open `/ops`: check worker, data source/latency, expected exchange session,
   ingestion outcomes, missed jobs and kill-switch state.
2. Open `/scanner` and a candidate's evidence page. A no-trade decision is a valid
   result; never lower gates merely to generate activity.
3. Open the Paper Console from navigation, `/portfolio` and `/journal` for
   persisted simulated activity. Review rejected actions and reconciliation.
4. Open `/kronos`: watcher heartbeat, input exclusions, mode and timestamps are
   separate from model predictive quality. The panel refreshes every 60 seconds.
5. Keep the Mac awake for local scheduled services. After sleep/restart, confirm
   heartbeat and catch-up completion before treating data as current.

## Prospective Kronos diagnostics

See [frozen protocol](KRONOS-PROSPECTIVE-PROTOCOL.md). New shadow captures include
candidate context and cost assumptions. The watcher resolves outcomes after its
bounded forecast cycle. To run the same evaluator manually from the repository:

```sh
uv run python scripts/kronos_outcomes.py --source-db data/signalforge.sqlite --ledger data/kronos-shadow-daily.sqlite
```

The source database opens read-only. Outcomes append to the separate ledger;
reruns do not overwrite resolved outcomes. Up to 250 unresolved records are
checked per cycle; the ledger retains its 256 MiB cap. Pending or missing sessions
are not losses, and legacy exclusions are not successful predictions. No actual
trades or alerts result from outcome evaluation.

## Release controls

Use an isolated checkout and test databases for kill-switch, restart, duplicate
worker and fill/reconciliation drills. Never exercise those drills against the
operating book. Run lint, typing, import contracts, secret checks, parallel tests
and the separate serial tests before merge. Preserve the live database, sealed
research reports, strategy approvals, risk limits and operator arming. Back up
before deployment; verify API, worker and watcher independently afterward.

Operational reliability is not predictive validation. Kronos remains research
only; a model agreeing with a strategy is not independent proof of profitability.
Research signal only — no order was placed.
