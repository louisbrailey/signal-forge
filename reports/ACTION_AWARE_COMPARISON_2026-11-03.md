# Action-aware comparison and forward setup — 2026-11-03

**Verdict: accounting and research infrastructure implemented; no strategy promoted.** Every strategy loses under the prespecified higher-cost scenario. Prospective validation has only been initialized, not completed.

Implementation commit: `a611b53`. The prior frozen Kronos study, its interim results, operating paper accounts and trading settings were not modified.

## Verified data and corrections

- Real Massive raw (`adjusted=false`) daily bars, 2016-10-17 through 2026-11-02: 25 canonical instruments and 62,705 usable raw observations.
- 10 split events and 977 cash-dividend records, from separately cached corporate-action endpoints. All 78 endpoint snapshots completed; raw content hashes and retrieval timestamps are retained locally.
- FB/META uses the existing verified 1:1 identity mapping, selecting FB before 2022-06-09 and META afterward. Both raw ticker histories remain intact.
- XLC is permitted to start later without invented pre-listing bars. Massive reference data lists 2018-06-18; its first returned bar is 2018-06-19. The unobserved listing session is explicitly reported; eligibility requires 220 real observations afterward.
- The operating DB had `instrument_type=stock` even for SPY and QQQ. All 15 configured ETFs were independently verified through Massive ticker-reference responses; corrections apply only to isolated research metadata. The initial all-blocked diagnostic exposed this metadata defect and is not a strategy result.
- `/benzinga/v1/earnings` returned **HTTP 403** at 2026-11-03 19:24 UTC. There are no earnings-event rows in the operating DB. All ten stock instruments therefore remain entry-ineligible; 15 ETFs can qualify. News access does not imply earnings access.
- Split quantities, stop/target levels, cost basis, dividend receivables and payment cash now use the correct historical share basis. Raw prices are used for fills; features use only splits effective by the decision date.

## All unchanged daily baselines

Each row is an independent $10,000 account with one cash balance shared across eligible instruments. Do not add the profits as if they came from a single $10,000 account. No strategy, threshold or model was tuned. Versions are those in the current registry; they must not be confused with older mean-reversion or breakout versions.

| Strategy/version | Base net P&L | Stress net P&L | Base closed trades | Base dividend income | Base close-mark max DD |
|---|---:|---:|---:|---:|---:|
| trend_continuation.short_swing@0.1.0 | $990.23 | $-796.08 | 635 | $134.61 | 2.69% |
| trend_continuation.medium_swing@0.1.0 | $961.49 | $-742.52 | 572 | $180.02 | 3.10% |
| mean_reversion.short_swing@0.2.0 | $-1.03 | $-126.73 | 73 | $13.67 | 2.58% |
| relative_strength.medium_swing@0.1.0 | $517.92 | $-210.38 | 249 | $161.10 | 4.04% |
| volatility_breakout.short_swing@0.2.0 | $-58.08 | $-137.36 | 47 | $8.01 | 1.44% |

Every daily/weekly/weekend income target is still missed. Base costs are 3bps slippage plus 5bps full spread with no commission; stress uses 10bps slippage, 10bps full spread and $0.005/share with a $1 minimum per side. Actual shares, cents, cash, commissions and receivables reconcile. Costs remain modeled, not measured execution.

Risk limits: 0.5% per trade, 1.5% aggregate open stop risk, 5% initial position allocation, 20% sector bucket and 60% portfolio notional exposure, no leverage, whole-share entries and 1% previous-session volume participation. The new 10% drawdown latch blocks additional entries while keeping exits active. It did not trigger in these real-data runs; gap and latch behavior is separately tested. ETF look-through concentration is not available.

The old report used back-adjusted prices as executable ticks, omitted dividends and admitted stocks without earnings evidence. The new results use raw share accounting and different eligible data coverage. Their difference must not be called an improvement in predictive skill. This is previously observed history with a survivor universe and current sector metadata; no new sealed look was used.

## Independent forward collection

- New study: `/Users/louisbrailey/Projects/signal-forge/data/funded-validation-v1`.
- Five strategies × two cost scenarios = ten isolated books. First observation: **2026-11-04**. First possible fills: **2026-11-05**, following a recorded forward decision.
- Source/configuration/lockfile fingerprints and explicit strategy specs are pinned. Open positions carry across observations; there is no forced daily liquidation. Previously observed raw data, marks and decisions cannot be silently revised.
- Collector: `com.signalforge.funded-validation`, every 1,800 seconds. New EOD fetches are gated by the existing **17:30 America/New_York** completion cutoff. Requests use 12.1-second spacing, existing backoff and kill-switch checks, exclusive collector locking and bounded resumable files.
- Launchd bootstrapped successfully, first run exit code **0**, status **WAITING_FOR_FIRST_FUTURE_SESSION**. Zero forward sessions, trades or performance conclusions exist yet. This independent collector resumes after login/reboot; the Mac must be awake.
- Review floors: 126 observed sessions, 30 closed trades per book and at least two trend regimes with ten trades each. A floor being met does not imply validation or automatic promotion. Maximum collection is 252 sessions, with a 2 GiB storage cap.
- Code drift, revised inputs, missing prospective sessions or missing credentials stop collection visibly. No automatic retrospective backfill is labelled forward evidence.

## Checks and remaining limits

Full local pytest passed twice (latest full log `.toolkit-runs/20261103T193240.499420Z.log`, exit 0, 317.9 seconds). Final focused accounting and readiness checks passed. Ruff, Black, mypy (282 source files), all 21 import contracts and secret scanning passed. Known Starlette/AnyIO deprecation warnings remain.

Stock earnings coverage is externally unavailable (403); enabling stock event-aware research needs licensed, timestamped coverage and a separately versioned plan. No subscription was purchased or configuration weakened. Fractional reverse-split cash-in-lieu, mergers/spin-offs/delisting settlements, historical sector membership, ETF look-through and observed market impact remain unsupported or unverified and must not be inferred. A first-day XLC bar remains unavailable.

Primary references: [raw-price adjustment semantics](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends), [cash dividends](https://massive.com/docs/rest/stocks/corporate-actions/dividends), [Benzinga earnings entitlement](https://massive.com/docs/rest/partners/benzinga/earnings).

## Operate and reproduce

```sh
PYTHONPATH=src uv run python scripts/funded_forward.py status \
  /Users/louisbrailey/Projects/signal-forge/data/funded-validation-v1

PYTHONPATH=src uv run python scripts/action_replay_report.py \
  .toolkit-runs/raw-actions-v1 \
  --database /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite \
  --listing-evidence .toolkit-runs/verified-security-metadata.json > action-report.json
```

Raw licensed data, detailed fills and local study files are excluded from git. See `docs/ACTION_AWARE_REPLAY.md` for clean-environment acquisition, data contracts, installation and failure behavior.

Research signal only — no order was placed.
