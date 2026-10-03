# Operating Signal Forge's paper research system

Signal Forge runs deterministic equity scans and accepts only qualified, approved,
in-scope candidates into a **local simulated ledger**. It is not an autonomous
profit guarantee. No brokerage credentials or connection are needed. Kronos has
no authority over entries, exits, ranking, position sizing, approval, or alerts.

## Start and verify

```bash
cd ~/signal-forge
uv sync --frozen --extra llm
uv run alembic upgrade head
uv run uvicorn signalforge.app.main:app --host 127.0.0.1 --port 8787
```

Run the worker in a separate terminal only if the installed launchd worker is
not already running:

```bash
uv run signalforge run-scheduler
```

This Mac already uses `com.signalforge.api` and `com.signalforge.worker`
LaunchAgents. Check `launchctl list` before starting another instance. Do not run
`seed` against an existing real-data account. Local scheduling requires the Mac
to remain awake and logged in; catch-up runs after missed sessions. Safe provider
pacing means a 151-symbol update can take about half an hour.

Open http://127.0.0.1:8787/paper-console and sign in with the existing local
account. The page refreshes every 30 seconds and shows persisted scans, decisions,
account estimates and worker liveness. `/ops` supplies feed and job detail;
`/scanner` and `/candidates/{id}` show evidence; `/journal` shows decisions.
A fresh heartbeat only proves the process is responding, not that data is fresh.
The startup heartbeat now explicitly says catch-up is running during ingestion.

The active account and switches are read from the database. This release does
not reset cash or enable an execution adapter. The October 2 audit found a
$30,000 equity paper account, automatic acceptance enabled, and a two-acceptance
UTC-day cap. A cap, open position, stale data, missing scope, or failed evidence
gate can correctly prevent trading. Rejected and watched decisions are retained;
new sessions produce new candidates rather than rewriting old decisions.

## Acceptance safeguards

New equity paper fills are long-only and cash-funded. At acceptance, the ledger
rechecks the current account under a write lock and uses the stricter of the
configured limit and these ceilings: 0.5% planned risk per trade, 1.5% aggregate
open stop risk, 5% allocation per symbol, 20% per known sector, and no leverage.
Stops and ATR-based candidate sizing remain deterministic. Stops cannot guarantee
maximum loss through a gap. Existing larger positions are not silently liquidated.
The immutable decision record stores the binding limits and size reductions.

Fresh scan timestamps and a current, source-qualified completed market bar are
required for normal acceptance. Automatic acceptance additionally requires the
existing approval, scope, quality and daily-cap checks. Historical replay cannot
masquerade as automatic current acceptance. Scans also reject symbols whose actual
bar date is stale even when the provider's last HTTP request succeeded.

Spread and slippage are included once in the simulated fill price. Daily-bar exits
start on the session after entry and inspect missed sessions chronologically;
entry-day OHLC cannot reveal event order. Suspect exit bars block valuation or
closing with an explicit error; they are never silently skipped. Stop gaps receive adverse open-price
handling. All fills are hypothetical; daily price zones are not executable quotes.

## Research model

Open `/kronos`. The app reuses the installed local runtime at
`~/my-stack/Kronos/.venv/bin/python` and cached `NeoQuasar/Kronos-small` weights.
No model download, paid inference, or provider call occurs. This Python/model
installation is optional and separate from `uv sync`: a new machine must supply
it before inference is available. Missing runtime/weights/data is shown as an
error, never replaced with invented predictions.

Choose a configured watchlist symbol and 5 or 20 held-out sessions. Input is
128 preceding real Massive daily bars. Actual future prices are not sent to the
model. Three seeded paths are compared with the unchanged-price baseline. The
mean absolute price error is **not** investment return, and model pretraining
overlap is unknown. Published adjusted history can contain later vendor revisions.
The sample min/max is not a calibrated confidence interval.

The page charts actual, predicted and baseline prices, tabulates exact values,
records each successful experiment, and exports the input/provenance/result JSON.
Inference is bounded and runs outside the web event loop, without inherited API
keys. The POST releases its SQLite write transaction before model work so it does
not block ingestion for the duration of inference. Import contracts prevent
Kronos from reaching trading and prevent trading from consuming Kronos.

## Known historical defects

The read-only audit in `PAPER_OPERATION_AUDIT.md` found two legacy positions with
exit timestamps before entry and a cost-accounting defect. Original audit rows
are preserved. The paper console flags impossible chronology; accumulated legacy
P&L must not be presented as validated forward performance. New safeguards do not
retroactively repair past outcomes. Any correction needs append-only evidence,
not deletion or rewriting of trades.

A good replay is not a reason to promote a strategy. Evaluate model usefulness
on preregistered unseen windows before considering any separately specified
research component; never repeatedly tune against the same held-out period.

`scripts/kronos_skill_study.py` is that pre-registered evaluation
(`docs/research/kronos/PREREGISTRATION_2026-10-03_kronos_skill.md`). It opens the
database read-only and calls the same `service.replay` the dashboard uses, so it
**shares the one-process inference lock with `/kronos`**: while a study call is
running the dashboard reports "busy", and vice versa (the study sleeps 30 s and
retries). Each call also takes four CPU threads for 50–90 s, so a full run (160
windows, 2–4 h) should be scheduled when the live worker's catch-up and scan are
not due. `plan` and `report` perform no inference and are safe at any time.

Research signal only — no order was placed.
