# Automatic collection for frozen comparison books

`com.signalforge.kronos-comparison` is an independent user LaunchAgent. It polls
once per minute and at login, without importing into or changing the operating
scheduler. It reads the operating database through the frozen runner's read-only
snapshot connection. Neither the worker nor the web app needs restarting.

## Trigger and limits

- Only the current completed XNYS session, after market close and before UTC
  midnight. The first enrolled session must have closed.
- The newest approved-scope scan job must have completed successfully. Its
  completion audit must assert enforced readiness and reference completed Massive
  scans covering every frozen strategy version for that experiment's horizon.
- A completed scan with **zero candidates** is valid. Missing/failed/partial,
  future-dated, or wrong-horizon evidence does not trigger collection.
- Each horizon is collected once per session. Later retries/scans that day do
  not add more admissions: this preserves the frozen protocol. An interrupted
  captured batch is resumed by the existing runner, without drawing forecasts
  again. Late resumes cannot backdate an entry.
- The existing runtime lock is checked before starting. A busy runtime defers
  collection. Races remain governed by the frozen runner's unavailable-forecast
  policy; no attempt is repeated to obtain a more favorable prediction.
- The existing source kill switch is respected. Its original missing-file
  convention is initial OFF; the collector does not create that operating file.
  Active, malformed or unreadable states stop collection. The runner also checks
  during inference and before creating private positions.
- Errors expose only exception categories, and back off five minutes. No alert
  adapter, provider request, model promotion or operating database write occurs.

The runner still pins models, code, configuration and approval scopes. Do not
update the frozen checkout, edit manifests, or move its data to follow main.
The collector script is deliberately outside the frozen code hash: it schedules
calls and checks readiness; it does not alter rules or portfolio calculations.

## Installed layout

- Runner checkout: `~/.codex/worktrees/kronos-comparison-collector/signal-forge`
- Frozen checkout: `~/.codex/worktrees/kronos-shadow-research/signal-forge`
- Active books: frozen checkout's `data/kronos-comparison-v1-{short,medium}`
- Private status: frozen checkout's `data/comparison-collector/status.json`
- Job template: `deploy/launchd/com.signalforge.kronos-comparison.plist`

The template names these local paths explicitly. It includes the **path** of the
existing `.env`, never its contents. Status is atomically replaced, mode 0600,
and retains at most 64 state transitions. It contains readiness/capture status,
scan identifiers, timestamps and error categories—not interim P&L. Stdout and
stderr go to `/dev/null` to prevent unbounded daemon logs. A stale status timestamp
or nonzero launchd exit is unhealthy, not a successful collection.

## Install, inspect, stop

From the runner checkout, after tests:

```sh
plutil -lint deploy/launchd/com.signalforge.kronos-comparison.plist
install -m 600 deploy/launchd/com.signalforge.kronos-comparison.plist \
  "$HOME/Library/LaunchAgents/com.signalforge.kronos-comparison.plist"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.signalforge.kronos-comparison.plist"
cat "$HOME/.codex/worktrees/kronos-shadow-research/signal-forge/data/comparison-collector/status.json"
# Stop ONLY the comparison collector:
launchctl bootout "gui/$(id -u)/com.signalforge.kronos-comparison"
```

Do not copy secrets or bootstrap/restart the operating worker as part of this
installation. Do not install a second collector. The collector lock and private
book locks prevent overlapping writes. For a foreground diagnostic, use the
ProgramArguments in the plist with its PYTHONPATH/working directory and add
`--check-only`; that checks triggers without advancing any book.

The Mac must remain awake, logged in and running Signal Forge. Sleep pauses this
poller as well as local scans; it cannot retroactively recover missed entries.
The first real post-close collection has to be observed after a qualifying scan;
offline tests and a waiting-state smoke check do not prove a future collection.

Research signal only — no order was placed.
