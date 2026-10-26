# Pre-registration — FX-2 (2026-10-26)

Written **before** any FX-2 result was computed. It follows the rules in
`STRATEGY_COMPLETION_MAP.md` R1–R4. The development gates, costs and sealed
procedure are unchanged from FX-1 (`signalforge.research.fx.harness.FxGates`),
plus **one added stress gate** (below). Gates may be added, never loosened.

## Evidence used (FX-1 development window only; no sealed number)

`fx_donchian_55` (FX-1) over 8 pairs, 2010-01-04 to 2025-10-23:
- 261 OOS trades, −0.20R expectancy.
- Every trade is closed at the latest after **40 bars** (fixed time stop).

## Hypothesis

FX trend-following earns its return from a small number of long trends. A
fixed 40-bar exit cuts those trends short while keeping all the losers, so it
removes the payoff the rule exists for. The textbook form of the rule (channel
breakout entry, opposite-channel trailing exit) lets winners run.

## The single change: `fx_donchian_55_trail20` (version FX-2)

- **Entry, unchanged from FX-1:** close beyond the prior 55-day high (long) or low (short).
- **Initial stop, unchanged:** 2 × ATR(20).
- **Exit, NEW:** close back through the prior **20-day** low (long) or high (short), evaluated on each completed bar after entry and filled at that close with the usual slippage.
- **Safety time stop:** 250 bars (about one year), only to bound a trade. It replaces the 40-bar stop.
- **No profit target.**

No other parameter is chosen. 55 and 20 are the classic published values,
not fitted ones.

## Gates

All FX-1 development gates, unchanged:
- final 365 days sealed and not evaluated;
- 60/40 walk-forward in 4 folds;
- at least 30 pooled OOS trades;
- expectancy ≥ 0;
- bootstrap CI low ≥ +0.02R;
- at least 3 of 4 folds positive;
- expectancy ≥ 0 at 2× spread;
- at least 50% of pairs positive.

**Added gate — holding-cost stress.** Longer holds make the unmodelled
overnight swap material. Each trade is charged **1 bp of price per day held**
(about 2.5% a year, a conservative retail swap on majors), converted to R. The
stressed expectancy must be ≥ 0.

## What happens next

- **FX-2 passes development:** one sealed-year test (`signalforge fx sealed-test`). That needs operator authorisation, then a simulated paper book.
- **FX-2 fails:** no further variant in this round, and forex is reported as having no tradable strategy.
