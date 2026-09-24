# Pre-registration — regime-diverse OOS evidence for the live scan gate (2026-09-24)

Problem: effectively every live candidate from the three PAPER_APPROVED versions
(`trend_continuation.short_swing` v2, `trend_continuation.medium_swing` v3,
`relative_strength.medium_swing` v5) is rejected by `research/scan.py`'s
`_oos_regime_coverage` gate: "1 regime(s) … < 2 required — single-regime edge"
(`QualityThresholds.min_oos_regimes=2`, `min_trades_per_regime=10`). This record
is written BEFORE any write to the live database. Nothing below has been run with
`--confirm`. All numbers were produced read-only (SQLite `mode=ro`).

## 1. Correction to the task premise (verified against source and the DB)

The brief attributed the scan gate's `oos_by_regime` rows to the sealed window of
`research.promotion.evaluate_promotion`. **That is not what the code does.**

- `scan._build_draft` reads `persistence.latest_oos_metric` — the newest
  `backtest_run` for the strategy name+version, `phase='out_of_sample'` — and its
  sibling `oos_by_regime` rows.
- The only writer of `backtest_run`/`backtest_metric` is
  `persistence.persist_backtest_result`, called only by the `signalforge
  backtest-report` CLI (`cli.py:1727-1748`). `evaluate_promotion` never persists a
  `backtest_run`; its sealed result lives only in `strategy_sealed_test`.
- The rows the scan reads today are `backtest_run` 38 (v2), 39 (v3), 41 (v5),
  written 2026-09-07 07:35 — **before the first sealed test existed** (2026-09-08
  06:32). Window 2024-08-28 → 2026-09-07 (a `backtest-report --years 2` run) on the
  25-symbol configured universe (incl. META), `source=None`.
- `backtest_runner` splits each symbol's bars 60/40 (`_TRAIN_FRAC=0.6`), so "OOS"
  is roughly 2025-11 → 2026-09: 100% `bull` by the classifier (§2).

Consequence: a new sealed look — on a new `DataSnapshot`, or with a widened
`sealed_window_days` — **would not change the scan gate at all**. It would spend
a sealed look per family and leave every live candidate rejected. That design is
rejected here. No new `DataSnapshot` is needed or registered.

Confirmed facts that do hold: the sealed window is pinned per
`(strategy_version_id, dataset_snapshot_id)` (`promotion.py:1003-1015`); every
existing sealed window for v2/v3/v5 is 2025-09-07/08 → 2026-09-07/08.
`sealed_window_days` lives in `PromotionThresholds` (`ResearchConfig.promotion`),
not `QualityThresholds`; `promotion` is **not** in `SCOPE_HASH_FIELDS`
(`quality_gates` is), so changing it would move only `full_config_hash`.
`MIN_PRESEALED_DAYS = ceil(200·365.25/252)+60 = 350`.

## 2. What the regime classifier actually says

Proxy SPY, source `massive`, 2,498 real sessions 2016-10-17 → 2026-09-24 (the
10-year history starts 2016-10-17, not 2016-09-12; AAPL identical). Classifier
`research.regime.regime_from_proxy` (the one the scan gate buckets by), run over
the full history so SMA-200 is warm; the first 199 sessions (to 2017-08-01) are
excluded as warmup, where the function returns NEUTRAL only because SMA-200 is
NaN. Tool: `scripts/regime_span_census.py`.

Non-bull spans (≥ 5 sessions):

| Label | Span | Sessions |
|---|---|---|
| neutral | 2018-10-29 → 2018-11-28 | 22 |
| bear | 2018-12-11 → 2019-01-24 | 30 |
| neutral | 2019-01-25 → 2019-03-29 | 45 |
| neutral | 2019-05-30 → 2019-06-14 | 12 |
| neutral | 2020-03-16 → 2020-03-27 | 10 |
| bear | 2020-03-30 → 2020-05-27 | 41 |
| neutral | 2020-05-28 → 2020-07-08 | 29 |
| neutral | 2022-03-14 → 2022-04-27 | 32 |
| bear | 2022-04-28 → 2023-02-01 | 192 |
| neutral | 2023-02-02 → 2023-03-31 | 37 (two runs) |
| bear | 2025-04-14 → 2025-05-07 | 17 |
| neutral | 2025-05-08 → 2025-06-30 | 36 |

Totals: bull 1,787, bear 280, neutral 232. Since 2023-06-08 the ONLY non-bull
stretch is 2025-04-14 → 2025-06-30 (53 sessions). Trailing 365 days: 251/251 bull;
trailing 548 days: 321 bull / 39 neutral / 17 bear. (Gate 6's separate
`backtest.regime` classifier agrees in shape: bear 2022-04 → 2023-02, 2025-04.)

The two evaluation universes (snapshot 3 `universe_24_ex_meta`, snapshot 11
`research_150_massive_10y_presealed_sel`) share this proxy, so their regime
calendars are identical; they differ only in trade counts (§3).

## 3. Structural finding: which trends each strategy can trade at all

Shorts are disabled (`allow_short_candidates=False`), so:

- `trend_continuation.*` LONG requires `not regime.risk_off` → never enters in
  `bear` (or high vol). Max attainable coverage: bull + neutral.
- `relative_strength.medium_swing` requires `regime.trend is BULL` → enters only
  in bull. Neutral trades appear only where the entry-date label differs from the
  signal-date label at a transition. **The 2-regime scan gate is structurally
  unsatisfiable for this version on any window.**

OOS trade COUNTS per trend (no performance numbers were computed or viewed),
`scripts/regime_trade_census.py`, source `massive`, end 2026-09-24:

| Universe | Years | tc.short bull/neutral | tc.medium bull/neutral | rs.medium bull/neutral |
|---|---|---|---|---|
| 25-sym configured (current evidence) | 2 | 113 / 0 | 100 / 0 | 76 / 0 |
| same | 4 | 204 / 24 | 186 / 20 | 125 / 1 |
| same | 5 | 238 / 24 | 220 / 20 | 156 / 1 |
| snapshot 3 (24) | 2 | 108 / 0 | 95 / 0 | 72 / 0 |
| snapshot 3 | 4 | 197 / 23 | 179 / 19 | 117 / 1 |
| snapshot 11 (150) | 2 | 607 / 0 | 565 / 0 | 581 / 0 |
| snapshot 11 | 4 | 1,098 / 148 | 1,016 / 140 | 986 / 5 |

Bear count is 0 in every cell. The years=2 row at end 2026-09-07 reproduces the
stored runs to within one trade (106/94/73 vs 105/93/72).

## 4. What is run (Phase 2, after operator sign-off)

`scripts/refresh_scan_oos_evidence.py --end <run date> --years 4 --confirm`, with
the worker stopped. It calls the same `run_strategy_over_universe` +
`persist_backtest_result` path as `backtest-report`, for exactly the three
versions above, on the same 25-symbol configured universe the current evidence
uses, with `source='massive'` pinned (a bare `backtest-report` today would read
duplicate `massive` + `massive_grouped` bars for 2025-01 → 2026-09), the effective
research config and its cost model, shorts per config (off). It refuses if a
stored version's spec hash differs from the code's. It never calls
`evaluate_promotion` and never writes `strategy_sealed_test`, a status, a setting
or a threshold.

**Window rule (fixed now):** `years` is the smallest integer Y such that the
40% OOS segment starts on or before 2025-04-14, the first session of the only
non-bull span since 2023-06: `end − 0.4·(365·Y + 10) days ≤ 2025-04-14`. For any
end up to ~2026-11-20 that is Y = 4 (Y = 3 starts OOS around 2025-06 and cuts the
span in half). SMA-200 warmup inside the run (to ~2023-07) falls in-sample only.
If the run slips past 2026-11-20, recompute Y by this rule; do not pick Y by count.

## 5. Sealed-look cost

**Zero.** No sealed test is taken. Current family counts from
`strategy_sealed_test` (the `count_sealed_looks` k), recorded for the ledger:

| Family | Sealed rows (snapshots) | k | Next look, if one were ever taken |
|---|---|---|---|
| trend_continuation.short_swing | 1, 2, 3, 4 | 4 | 5 |
| trend_continuation.medium_swing | 1, 2, 3, 4, 11 | 5 | 6 |
| relative_strength.medium_swing | 1, 2, 3, 4 | 4 | 5 |

(The sealed-look alternative is costed here only for comparison: it would take
looks 5 / 6 / 5 and still not change the scan gate.)

This refresh does look at data that overlaps the locked 2025-09 → 2026-09 sealed
windows. So do the current evidence rows 38/39/41. It is the scan's quality
evidence, not a sealed test, and it can neither grant nor revoke approval.

## 6. Pre-registered expectations

The trade counts in §3 are already known, so the coverage outcome is **not** a
prediction. It is a disclosed, structural fact. The other scan-gate checks on the
same run (OOS n ≥ 20, OOS expectancy > 0, bootstrap CI low ≥ −0.15R) have not been
computed on the new window.

- v2 `trend_continuation.short_swing`: coverage expected to reach 2 trends (bull
  + neutral, 24 neutral). Expectancy/CI on the longer OOS window: **uncertain**.
- v3 `trend_continuation.medium_swing`: coverage expected to reach 2 trends (20
  neutral). Its CURRENT stored OOS expectancy (run 39) is already −0.049R, which
  fails `min_oos_expectancy_r` whatever the regime count. Outcome: **uncertain,
  leaning fail**.
- v5 `relative_strength.medium_swing`: coverage expected **FAIL** (1 neutral
  trade). This is by construction and is reported as such. No window fixes it.
  Whether a bull-only strategy should be eligible under a 2-trend gate is an
  operator policy question. It is out of scope here: the gate is not relaxed and
  the strategy is not changed.

## 7. Why this window is not selection-on-outcome

The `min_oos_regimes=2` requirement existed before this task and is unchanged.
The window length is set by the classifier's own labels: it is the shortest
window whose OOS segment contains the only genuine non-bull period in the past
three years. It is not set to make any strategy pass. Counts were computed before
this record was written, and that is disclosed above. No expectancy, P&L, CI or
Sharpe was computed on any candidate window. The rule in §4 is mechanical, and a
reader can reproduce it from `scripts/regime_span_census.py`.

## 8. Rules

- Symmetric: every outcome is reported verbatim, including fails of expectancy or
  CI on the new window and v5's structural coverage fail. A fail is not re-run
  with a different `years`, universe or end date.
- No threshold, parameter, cost, universe, `sealed_window_days` or config change.
- Worker stopped. `backtest_run` count rises by exactly 3.
  `strategy_sealed_test` stays at its current count (22).
- The candidate-level effect is observed at the next scheduled scan. It is not
  forced.
