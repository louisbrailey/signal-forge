# Strategy promotion — live evaluation results

Run 2026-09-08, `signalforge evaluate-promotion` (default: all 6 strategies,
full universe, full ingested history). Window `2016-09-10..2026-09-08`,
universe 25 symbols, `config_hash 11b54aee64db`, `git_sha 7708be7` — **this is
the post-adversarial-review-fix run** (see "What changed since the first run"
below). An earlier run against `git_sha 9eb53fa` produced the same overall
verdict and per-strategy blocking pattern; this run supersedes it as the
current evidence.

## Operational result

```
NO TRADE — insufficient evidence or poor risk/reward
```

**No strategy cleared every gate.** This is the pipeline working correctly,
not a defect — three strategies were one real, documented finding away from
passing; the rest have genuine, material evidence gaps. Nothing was created,
weakened, or tuned to force a pass.

## What changed since the first run

Between the first live run and this one, an adversarial code review found 11
confirmed defects in the pipeline itself (not in any strategy) and all 11
were fixed, regression-tested, and committed (`7708be7`). The two that could
plausibly change a strategy's evidence are:

- **Gate 1** now requires a real per-fold edge (≥15 trades *and* positive
  expectancy) in at least half the folds — not just "any trade in the fold."
  Re-running confirms this is a strictly stronger check that **every
  strategy still clears**: e.g. `trend_continuation.medium_swing` now shows
  "4 with any trades, 4 clearing both a per-fold trade floor and positive
  expectancy" — the old logic would have reported the same PASS, but on
  weaker grounds.
- **Gate 7** (benchmark comparison) now computes strategy and benchmark
  Sharpe over the identical actual-data span. The resulting Sharpe ratios
  moved slightly from the first run (e.g. `trend_continuation.short_swing`
  +0.86→+0.87) but no strategy's gate 7 verdict flipped.

The other 9 fixes (sealed-window pinning, the `upsert_strategy_version`
status-bypass close, alert-dedupe collision resistance, the sealed-test race
guard, the alert-lookback watermark, `job_ingest` writing an `IngestionRun`
row, and the calendar-disjointness/`MIN_PRESEALED_DAYS` gate-0 fixes) affect
correctness and safety under conditions this run doesn't exercise (concurrent
evaluation, re-evaluation after new data arrives, a scheduler outage, a
malicious `spec.status`) rather than today's single evaluation's numbers.

**Net effect: the honest result is unchanged.** All 6 sealed tests were
reused verbatim (same `sealed_test_id`, identical locked metrics as the first
run) — none was or could be recomputed. The per-strategy blocking gates are
identical to the first run.

## Per-strategy result

| Strategy | Gates passed | Blocking gate(s) |
|---|---|---|
| `intraday_orb.intraday` | 0/1 (short-circuit) | **0. data_availability** — no intraday bar history ingested; not evaluated |
| `trend_continuation.short_swing` | **9/10** | **8. data_quality_and_leakage** only |
| `trend_continuation.medium_swing` | **9/10** | **8. data_quality_and_leakage** only |
| `mean_reversion.short_swing` | 5/10 | 3, 4, 5, 7, 8 |
| `relative_strength.medium_swing` | **9/10** | **8. data_quality_and_leakage** only |
| `volatility_breakout.short_swing` | 5/10 | 4, 6, 7, 8, 9 |

**3 of 6 strategies are blocked by exactly one gate — gate 8 — and it is the
*same* finding for all three**, so this is the single highest-leverage item:

> `validate_daily` FAIL: **META 90 missing sessions (6.9%)**, e.g.
> 2022-01-31, 2022-02-01, 2022-02-02 — exceeds the 2% missing-session
> tolerance. Root cause: the FB→META ticker rename left a real gap in the
> ingested history. Leakage self-check: clean (not the issue).

This is a genuine, disclosed data-quality issue, not a bug in the gate. I did
not relax the gate, exclude META, or backfill the gap to manufacture a pass —
that decision (fix the data, narrow the universe, or accept the finding as
disqualifying) is yours. If resolved, the 3 strategies above would clear gate
8 and their promotion would then turn on gate 9 alone (the sealed result,
already computed and locked — see below).

## Full gate-by-gate detail

### `trend_continuation.short_swing` v0.1.0 — 9/10

| # | Gate | Result | Detail |
|---|---|---|---|
| 1 | rolling_walkforward | PASS | 4 rolling folds over the pre-sealed span, 4 with any trades, 3 clearing both a per-fold trade floor (≥15) and positive expectancy (need ≥2 of 4) |
| 2 | min_oos_trades | PASS | 348 OOS trades (need ≥30) |
| 3 | net_expectancy | PASS | +0.2609R net of costs (need >0) |
| 4 | bootstrap_ci | PASS | 95% CI lower bound +0.1131R (need >+0.02R) |
| 5 | parameter_sensitivity | PASS | 9/9 grid points evaluable, 100% positive, 100% of neighbours positive |
| 6 | regime_coverage | PASS | bull 957 / bear 23 / range 77 trades (need ≥10 each, 3/3 regimes met) |
| 7 | benchmark_comparison | PASS | Sharpe +0.87 vs SPY +0.72 (CAGR +7.0% vs +13.4%, vol 8.2% vs 18.6%, maxDD 27.8% vs 34.1%) — same actual-data span for both (gate-7 fix) |
| **8** | **data_quality_and_leakage** | **FAIL** | validate_daily FAIL (META gap, above); leakage self-check clean |
| 9 | sealed_final_test | PASS (locked) | window 2025-09-07..2026-09-07, 112 trades, net expectancy **+0.3246R** — reused verbatim from the first run |
| 10 | live_paper_probation | PASS | health-monitor active (downgrade z≤-2.0, disable z≤-3.5) |

### `trend_continuation.medium_swing` v0.1.0 — 9/10

326 OOS trades, expectancy +0.2936R, CI low +0.1026R, sensitivity 100%/100%,
regimes bull 874/bear 23/range 71, Sharpe +1.22 vs benchmark +0.72
(CAGR +10.8% vs +13.4%, vol 8.8% vs 18.6%, maxDD 28.5% vs 34.1%). Gate 1: 4 of
4 folds clear both the trade-floor and expectancy bar. Sealed test (locked,
reused verbatim): 98 trades, net expectancy **+0.0109R** — positive, but
thin; a material change in even 1-2 sealed trades would flip it. Blocked by
gate 8 only.

### `relative_strength.medium_swing` v0.1.0 — 9/10

209 OOS trades, expectancy +0.2875R, CI low +0.0913R, sensitivity 100%/100%,
regimes bull 487/bear 11/range 94 (bear is the thinnest at 11, just above the
10-trade floor), Sharpe **+1.30** vs benchmark +0.72 — the best risk-adjusted
figure of the six (CAGR +7.7% vs +13.4%, but vol only 5.8% vs 18.6%, maxDD
17.8% vs 34.1%). Gate 1: all 4 folds clear both bars. Sealed test (locked,
reused verbatim): 16 trades, net expectancy **+0.2935R**. Blocked by gate 8
only. This matches the "only strategy with all 4 walk-forward folds positive"
finding from the earlier extended-history backtest report.

### `mean_reversion.short_swing` v0.1.0 — 5/10 (genuine negative edge)

| # | Gate | Result | Detail |
|---|---|---|---|
| 1 | rolling_walkforward | PASS | 4 folds with trades; only 2 of 4 clear both the trade-floor and expectancy bar (need ≥2 of 4 — passes, but by the minimum) |
| 2 | min_oos_trades | PASS | 320 trades |
| 3 | net_expectancy | **FAIL** | **-0.0782R** net of costs |
| 4 | bootstrap_ci | **FAIL** | 95% CI lower bound **-0.1643R** |
| 5 | parameter_sensitivity | **FAIL** | 0% of 9 grid points positive, 0% of neighbours positive — the edge is negative everywhere on the grid, not just fragile |
| 6 | regime_coverage | PASS | bull 630 / bear 47 / range 262 |
| 7 | benchmark_comparison | **FAIL** | Sharpe **-0.76** vs SPY +0.72 (CAGR -3.5% vs +13.4%) |
| 8 | data_quality_and_leakage | FAIL | same META finding |
| 9 | sealed_final_test | PASS (locked) | 91 trades, net expectancy +0.1230R (positive on the sealed slice, but everything upstream already disqualifies it) |
| 10 | live_paper_probation | PASS | |

Matches the earlier extended-history finding: mean reversion loses money
over the full 10-year OOS window. This is not a data problem — it's a real,
negative edge net of costs. **Notable under the new gate-1 logic**: only 2 of
4 folds actually clear the per-fold edge bar (the minimum to still pass gate
1) — under the old "any trade" logic this would have looked identical to the
profitable strategies above at a glance; the stricter check now surfaces that
distinction directly in the evidence even though the pass/fail outcome here
was already correctly negative via gates 3/4/5/7.

### `volatility_breakout.short_swing` v0.1.0 — 5/10

52 OOS trades (passes gate 2), net expectancy technically positive (+0.0541R,
gate 3 PASS) but the **bootstrap CI lower bound is -0.3447R** (gate 4 FAIL —
the point estimate is unreliable at this sample size). **Zero bear-regime
trades** (gate 6 FAIL — only 2 of 3 regimes covered). Sharpe +0.64 trails the
benchmark's +0.72 (gate 7 FAIL). Data quality FAIL (gate 8, same finding).
**The sealed test itself failed** (gate 9): only 10 trades, net expectancy
**-0.0979R** — the one strategy here whose sealed-window result is actually
negative. Locked, reused verbatim from the first run; will never be
re-run for this version.

### `intraday_orb.intraday` v0.1.0 — not evaluated

No intraday bar history is ingested for this horizon (`backtest-extended` and
this pipeline both skip it). Reported as `data_availability` FAIL — not
fabricated as a pass or a numeric result on absent data.

## What would change the outcome

1. **Fix or accept the META gap** (gate 8) → `trend_continuation.short_swing`,
   `trend_continuation.medium_swing`, and `relative_strength.medium_swing`
   would each pass all 10 gates and become `PAPER_APPROVED` automatically on
   the next `evaluate-promotion` run — their sealed tests are already computed
   and locked, so nothing about their outcome could change even if you fixed
   the data today; only gate 8's verdict would flip.
2. `mean_reversion.short_swing` and `volatility_breakout.short_swing` have
   independent, genuine evidence failures (negative expectancy/CI/benchmark,
   thin or negative sealed result, missing regime coverage) that a data fix
   would not resolve.
3. `intraday_orb.intraday` needs intraday history ingested before it can be
   evaluated at all.

## Every evaluation is preserved

All 12 evaluations to date (6 from the first run, 6 from this post-fix run)
are `StrategyPromotionEvaluation` rows (append-only) and visible in full,
gate-by-gate, with raw evidence, on **Strategy Promotion**
(`/strategies/promotion`) in the dashboard — the dashboard shows each
strategy's *latest* evaluation, i.e. this run's results. The 4 sealed tests
that exist (`trend_continuation.short_swing`, `trend_continuation.medium_swing`,
`relative_strength.medium_swing`, `volatility_breakout.short_swing`) are each
locked to their exact strategy version and were reused byte-for-byte by this
run — a future re-run reuses them verbatim and does not recompute.

## Critical finding, found and corrected while verifying the first run

Before the first pipeline run, **all 6 strategies were already marked
`paper_approved`** in the live database — with **zero supporting evidence**:
no `strategy_promotion_evaluation` row existed yet for any of them, no
`audit_log` row existed for the change at all (the table was completely
empty), and each `Strategy.status` disagreed with its own
`StrategyVersion.status` (which was correctly `experimental`). This predates
the pipeline built this turn — most likely a leftover from earlier manual
dashboard testing (before I locked `act_strategy_status` to downgrade-only)
that never went through any audited path. Net effect: candidate-trade alerts
were **not actually blocked** — the "requires `paper_approved`" gate in
`plan_alerts` was silently satisfied for every strategy with zero real
evidence behind it, the exact failure mode this whole feature exists to
prevent.

**I corrected it**: reset all 6 back to `experimental` (matching their
version status and the fact that not one has ever passed a gate), with a
proper `audit_log` row this time (`action="strategy.status_correction"`,
actor `operator_correction`, reason recorded). The subsequent adversarial
review then found and closed the root cause in code
(`upsert_strategy_version` no longer trusts `spec.status` on creation either
— see "What changed since the first run" above), so this class of desync
cannot recur silently. After both runs, live status matches the evidence
exactly: every strategy is `experimental`; none is alert-eligible.

## Alerts

`alerts_enabled` is `True`; candidate-trade alerts are **structurally
blocked** (require `Strategy.status == paper_approved`, and none is).
Daily briefing, system-health, and data-staleness/ingestion-failure alerts
are live — the latter two now also see failures on the *actual* scheduled
paths (`job_ingest` writes an `IngestionRun` row; the alert lookback windows
widen to a persisted watermark instead of permanently missing anything older
than the rolling window), per the review-fix round.
