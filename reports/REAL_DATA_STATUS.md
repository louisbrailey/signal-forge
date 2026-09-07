# Real-data status — Massive end-of-day daily bars

> **Hypothetical research output. Past results do not predict future results.**
> Every strategy below is **EXPERIMENTAL** (paper only, no alerts). Promotion to
> `paper_approved` is a manual, audited action — nothing here promotes anything.
> No fixture/simulated data is used in any number on this page.

Generated 2026-09-07 · git `dd1aff6` · config hash `010b9087…6ad47`

## Scope and limits (these bound every conclusion)

- **~2 years, 500 daily bars per symbol**, 2024-09-09 → 2026-09-04 (Massive Basic caps history at ~2y).
- **25 instruments**: 10 large-cap US equities + 15 sector/index ETFs. No small/mid-cap, no non-US.
- **One strategy version (0.1.0)**, one backtest run each, `seed=0`.
- **Single chronological 60/40 hold-out**, not walk-forward: `walkforward_window` is empty, one fold per strategy, OOS ≈ the last ~10 months.
- **Commission modeled as zero** (`commission_per_share=0`); 3.0 bps slippage + half-spread are applied.
- Massive daily feed is **split-adjusted only** — no dividend adjustment, no earnings feed. The spec's earnings-window exclusion did nothing on this data; dividend gaps count as losses on MEDIUM_SWING holds.
- **Every OOS trade for every strategy is in a `bull/high` or `bull/low` regime.** Zero bear, zero range-bound. The OOS window is one continuous equity bull market.
- No forward/live-paper validation exists yet (`paper_trade`, `scan_run`, `strategy_health` all 0 rows).

## Data integrity (independently verified against `./data/signalforge.sqlite`)

| Check | Value |
|---|---|
| `ohlcv_daily` rows | 12,500 |
| instruments × bars | 25 × exactly 500 |
| date span | 2024-09-09 … 2026-09-04 |
| `latency_category = END_OF_DAY` | 12,500 / 12,500 |
| `is_simulated = false` | 12,500 / 12,500 |
| `source = 'massive'` | 12,500 / 12,500 |
| bars with quality flags | 0 |
| `ohlcv_intraday` rows | 0 |
| `data_feed_status` | `massive / BAR_DAILY / END_OF_DAY`, 0 consecutive failures |
| `alert_log` | 0 |
| `paper_account / order / fill / position / trade` | 0 / 0 / 0 / 0 / 0 |
| `candidate / scan_run / strategy_health` | 0 / 0 / 0 |

Ingest: 25 HTTP GETs to `api.massive.com` (1 per symbol), throttled to the 5 req/min Basic limit (~12 s spacing); API key never written to logs, DB, or the raw-payload cache.

## Per-symbol coverage

All 25 symbols: **500 bars each, 2024-09-09 → 2026-09-04.** Uniform; no gaps, no partial current session (adapter caps at yesterday ET).

`AAPL AMZN DIA GOOGL HD IWM JPM META MSFT NVDA QQQ SPY UNH XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY XOM`

## Quality gates

`min_oos_trades ≥ 20` (G2) · `oos_expectancy_r > 0` (G3) · `oos_expectancy CI low ≥ -0.15R` (G4) · a committed OOS backtest must exist (G1) · **OOS evidence spans ≥ 2 trend regimes (bull/bear/neutral), ≥ 10 trades each (G5)**. Clearing all five makes a strategy **eligible to emit PASSED candidates in a scan (paper only)** — it is **not** evidence of a live edge, and status stays `experimental`.

| Strategy (horizon) | OOS trades | OOS expectancy | OOS 95% CI (expectancy) | IS expectancy | Gates | Status |
|---|---|---|---|---|---|---|
| trend_continuation.short_swing | 105 | +0.269 R | [-0.086, +0.651] | +0.163 R | **fails G5** (bull-only OOS) | experimental |
| mean_reversion.short_swing | 82 | +0.192 R | [+0.021, +0.352] | **-0.198 R** | **fails G5** (bull-only OOS) | experimental |
| relative_strength.medium_swing | 72 | +0.114 R | **[-0.193, +0.430]** | +0.859 R | **fails G4 & G5** | experimental |
| trend_continuation.medium_swing | 93 | **-0.049 R** | [-0.363, +0.274] | +0.160 R | **fails G3, G4 & G5** | experimental |
| volatility_breakout.short_swing | **10** | -0.141 R | [-0.858, +0.701] | -0.311 R | **fails G2, G3, G4 & G5** | experimental |
| intraday_orb.intraday | — | — | — | — | **not evaluable** | experimental |

**0 of 6 clear the gates; 0 of 6 are promotable.** Every strategy's OOS trades are confined to bull/high + bull/low (one trend regime), so all six now fail the regime-coverage gate G5 regardless of expectancy.

## Why each strategy is still experimental

### intraday_orb.intraday — could not be evaluated
No intraday bars exist (`ohlcv_intraday` = 0 rows; Massive here is a daily-only feed). The run produced 0 trades over an empty dataset. Its "G1 backtest exists / G4 CI-low 0.0 ≥ -0.15" are artifacts of an empty run, not passed gates. It stays experimental by **non-evaluation**. The INTRADAY horizon also has no live feed, so its live alerts are disabled regardless.

### trend_continuation.short_swing — clears the gates, not a validated edge
Passes G1–G4 (n=105, OOS +0.269 R, CI low -0.086, IS +0.163 R). Reasons it is not promotable:
- **The OOS expectancy CI lower bound is below zero (-0.086 R)** — +0.269 R is not statistically distinguishable from break-even at 95%.
- OOS beats IS only via **larger winners** (avg win 1.84 R vs 1.26 R) on a **lower win rate** (42.9% vs 49.3%) and **~2× the max drawdown** (13.9 R vs 6.8 R) — a few-big-winners profile, not a broad edge.
- **Bull-only OOS**: `bull/low` n=101 (+0.263 R), `bull/high` n=4. No bear, no range-bound.
- Parameter sensitivity on this data: 17/27 grid points positive, verdict "robust" — but scored on the **same ~10-month bull window**, so it does not address regime or CI risk.
- Promotion is manual.

### mean_reversion.short_swing — clears the gates, shows a regime-luck signature
Passes G1–G4 (n=82, OOS +0.192 R, CI low **+0.021 R** — barely above both zero and the -0.15 floor). Reasons it is not promotable:
- **It lost money in-sample**: IS expectancy **-0.198 R**, profit factor 0.52, -31.8 R total over 161 trades, 33 R max drawdown. The strategy that lost badly on 161 IS trades then "worked" on 82 OOS trades — the IS-negative / OOS-positive inversion is a **non-stationarity / regime-luck** pattern, not evidence of edge.
- **Bull-only OOS** (`bull/low` +0.160 R n=66, `bull/high` +0.322 R n=16).
- Sensitivity 27/27 positive — again measured on the same bull OOS window; several grid points' CIs still straddle zero.
- Promotion is manual.

### relative_strength.medium_swing — fails G4
OOS expectancy CI low is **-0.193 R < -0.15** floor, so +0.114 R point expectancy is **not separable from a loss**. Also: IS +0.859 R at 66.7% win (33 trades) **collapses** to +0.114 R at 44.4% win OOS, with a **9-trade losing streak** and a `bull/high` sub-regime already negative (-0.004 R). Not promotable.

### trend_continuation.medium_swing — fails G3 and G4
**OOS expectancy is negative** (-0.049 R, profit factor 0.93); CI low -0.363 R. IS +0.160 R → OOS negative is an overfit / regime divergence. Only conclusion: not promotable.

### volatility_breakout.short_swing — fails G2, G3, G4 (data-starved)
**10 OOS trades** (needs 20), 40 total. Both IS (-0.311 R) and OOS (-0.141 R) are net-losing. Single `bull/low` OOS segment. Insufficient data to evaluate; nothing to promote.

## What real data changed vs the earlier fixture run

On fixture (random-walk) data every strategy had negative OOS expectancy and sensitivity flagged all as FRAGILE. On real Massive EOD data, `trend_continuation.short_swing` (+0.269 R) and `mean_reversion.short_swing` (+0.192 R) show positive OOS expectancy and their sensitivity grids read "robust" — **but** every positive result is a single bull-market, single-fold, ~10-month hold-out over ~2 years of one 25-name universe with zero commission. It is not out-of-bull, not walk-forward, not live-paper validated. The regime-coverage gate (G5) encodes this: with OOS trades confined to one trend regime, **no strategy is eligible**, and none can be promoted.
