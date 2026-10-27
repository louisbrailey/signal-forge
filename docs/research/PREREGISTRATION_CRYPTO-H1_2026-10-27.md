# Pre-registration — CRYPTO-H1, hourly round-the-clock crypto (2026-10-27)

Written **before** any hourly crypto data was ingested or any result was computed.
Rules R1–R4 of `STRATEGY_COMPLETION_MAP.md` apply.

## Data

- **Bars:** `crypto_bar_intraday`, 1-hour bars, every UTC hour, 7 days a week.
- **Pairs:** BTCUSD, ETHUSD and SOLUSD, from 2017-01-01 or each pair's first available hour.
- **Sealed window:** the final 365 calendar days are sealed and not evaluated.

## Costs (unchanged from CRYPTO-1)

- **Per-side cost:** 2 × (half-spread + retail taker fee). That is 24 bps for BTC, 26 for ETH and 40 for SOL, plus 1 bp slippage.
- **Stress:** 2× those costs.

Hourly trading pays these costs far more often than daily trading. That is the
central risk, and it is stated before any result.

## Rules (bars are hours; parameters are classic or derived from the daily rules, not fitted)

1. **`crypto_h_donchian168_trail72`** (breakout)
   - **Entry:** a close beyond the prior 168-hour (7-day) high (long) or low (short).
   - **Stop:** 2 × ATR(24).
   - **Exit:** a close back through the prior 72-hour opposite channel.
   - **Safety stop:** 720 hours.
2. **`crypto_h_tsmom72_sma168`** (momentum)
   - **Entry:** the close crosses SMA(168) in the direction of the 72-hour return.
   - **Stop:** 3 × ATR(24).
   - **Time stop:** 48 hours.
3. **`crypto_h_zfade48`** (mean reversion)
   - **Entry:** fade a close 2.5 standard deviations from its 48-hour mean.
   - **Target:** the mean.
   - **Stop:** 1.5 × ATR(24).
   - **Time stop:** 12 hours.

## Gates (identical to FX-1 / CRYPTO-1 development gates)

- 60/40 walk-forward in 4 folds;
- at least 30 pooled OOS trades;
- expectancy ≥ 0;
- bootstrap CI low ≥ +0.02R;
- at least 3 of 4 folds positive;
- expectancy ≥ 0 at 2× cost;
- at least 50% of pairs positive.

## What happens next

- **A rule passes:** it gets one sealed-year test (operator authorisation), and only then a simulated paper book.
- **A rule fails:** it is reported, with no variants in this round.
