# ADR 0005 — prospective Kronos shadow watch

Status: research implementation only, 2026-10-24. No decision-path integration approved.

The operator requests broad 24/7 discovery and two-way checking with deterministic strategies. The existing Kronos study and eval-mode diagnostic remain negative; ADR0004 stays closed. Agreement is not independent evidence or a probability of profit. No existing safety/import contract is weakened.

## Conservative implementation assumptions

- 25 logical stable-hash discovery partitions, sharing one offline local model subprocess slot. These are not 25 independently trained models. A separate strategy-check *lane* prioritizes symbols with already-persisted same-UTC-day candidates; it uses the same model and is explicitly not independent confirmation.
- Only explicitly named real Massive equity/ETF daily histories currently supported. Bond ETFs are possible when their stored instrument type/data pass the same checks. Direct bonds, options/calls/puts, crypto, FX and futures forecasts are unsupported, not silently fed to an equity calendar/volume model. Those require separate adapters, session models and asset-specific validation.
- Completed XNYS bars, 128-session continuous windows, no simulated/unadjusted/flagged data. Future calendar dates only cross the inference boundary, no future OHLCV.
- Max250 requested symbols, max25 attempted forecasts per UTCday including failures; one horizon (5 or20), one locked writer; stop at256MiB ledger size (plus one bounded record/journal). Every attempt reserved before inference. Dedupe symbol/origin/horizon. Crashed entries remain recorded and are not retried automatically.
- Separate research SQLite ledger; source database opened mode=ro. No paper/candidate/risk writes, alerts, auto-promotion or automatic backtests. No forecast probabilities or calibrated uncertainty claims. The 3 sampled paths are not independent analysts.
- Watch polls every5minutes and only computes unseen completed daily inputs. The Mac must remain awake. It does not create tick-level monitoring, and repeated polling does not generate fresh information.
- Kill switch stops new attempts and cancels inference via bounded subprocess cleanup. Missing file follows existing initial-state convention; malformed file stops shadow work.
- Current cached model weights are labelled unverified_cached_weights; worker code SHA and exact input history/hash are stored. These records are operational/prospective research, not admissible promotion evidence until weights are pinned and the study protocol is separately frozen.

## Evaluation discipline

Do not backtest only attractive forecasts and treat that as validation. Retain every attempted prediction and all exclusions; evaluate fixed baseline/strategy-only/Kronos-only/agreement/disagreement cohorts on future data with fixed costs and risk rules. Any trading filter is a new strategy version requiring untouched out-of-sample and forward-paper evaluation, calibrated uncertainty and multiple-testing controls. No reuse of closed/sealed studies, optimization target or promised profit. Running 25 copies does not reopen a failed study.

No model agreement can bypass liquidity, freshness, concentration, position sizing, drawdown or operator arming. Options stay subject to their independent education/research restrictions.

## Commands

From the repository with its environment installed:

```sh
uv run python scripts/kronos_shadow.py \
  --source-db "$PWD/data/signalforge.sqlite" \
  --output-db "$PWD/data/kronos-shadow.sqlite" \
  --kill-switch "$PWD/data/kill_switch.json" \
  --symbols SPY QQQ IWM --max-calls 25
```

Add `--watch` to keep observing new completed bars. Omitting `--symbols` reads the configured
watchlist from the read-only source database each cycle. Each ticker argument is validated;
a space-separated string passed as one argument is rejected before recording an attempt.
The deploy template `deploy/launchd/com.signalforge.kronos.plist` uses one persistent ledger,
`data/kronos-shadow-daily.sqlite`. Do not create another ledger to bypass its daily budget.
The authenticated `/kronos` page reads its heartbeat, attempt counts and latest statuses,
refreshing every minute without running inference. The daemon checks every five minutes;
the Mac must remain awake. A kill switch stops inference and work, while the daemon sleeps
until it is released. A missing heartbeat or one older than ten minutes is visibly stale.

Prospective mode requires the latest completed exchange session. For explicit diagnostic
replay only, `--replay-latest` permits older inputs and records `historical_replay`,
`data_stale`, latest available and expected session. Replay cannot be combined with watch.
Earlier unlabelled outputs are `legacy_unclassified`, never prospective evidence. Keep
these separate from new evaluation cohorts. Local diagnostics included an invalid combined
ticker argument and alphabetically selected stale instruments; those failures do not show
a broken model. A successful forecast does not establish model skill.

Missing, stale or invalid inputs are recorded as per-symbol input exclusions before a model
attempt is reserved. They are checked again next cycle when data may have arrived, without
spending inference budget or permanently deduplicating that session. Actual inference
failures and interrupted attempts still consume the daily limit and are never silently retried.

Query `forecasts` in the separate ledger for status/payload; `trade_approved` is always false.
A failed runtime check is not a forecast failure score. This implementation has no calibration,
outcome evaluator, automatic strategy backtest, cross-asset support or claim of independent
model verification. The negative ADR0004 outcome still applies.
