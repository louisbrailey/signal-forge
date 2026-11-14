# Pre-registration — R3-C: admission order, trim-to-budget and the luck band in a funded account

Status: written 2026-11-10 before any replay of this study. Operator request
(2026-11-10): "continue pushing for more profit within each strategy and the kronos ai
part of the workflow". No sealed look, no operating-database write, no change to any
frozen study, risk limit or approved version. Results file, named in advance:
`docs/research/RESULTS_r3_capacity_admission_2026-11-10.md`.

## Why

In the operating paper book, 154 approved trend_continuation.medium signals became 17
positions: about half got no decision because the open-risk budget could not fit one more
share, and 22% hit the two-per-day cap. Nothing ranks same-day candidates (every passed
candidate scores 0.5); the funded replay admits alphabetically (`backtest/funded.py:408`)
and rejects outright when a budget is short. `RESULTS_funded_approved_set_2026-11-08.md`
showed a $30–60 dividend changing one configuration from +12.6% to −0.2% through
admission alone, and listed a jittered admission test and trim-to-budget sizing as
untested. When capacity binds, *which* signals are taken is the lever.

## Scope (fixed)

- Books: each PAPER_APPROVED version alone on its approved snapshot —
  trend_continuation.short_swing (3), relative_strength.medium_swing (3),
  trend_continuation.medium_swing (11), high52_breakout.medium_swing (11).
- Engine: the funded shared-account replay (`backtest/funded.py`), next-open fills,
  whole shares, dividends booked, $30,000 starting cash, per-trade risk 0.5%, symbol cap
  10%, sector cap 20%. Two cap sets: **operating** (open risk and gross exposure as in the
  operating research configuration read from the scratch copy, plus the two-accepts-per-day
  cap) and **maxima** (open risk 3.0%, gross 100%, no daily cap).
- Periods, replayed independently from fresh cash: **IS** 2016-10-17..2022-02-10 and
  **OOS** 2022-02-11..2025-09-05. Nothing on or after 2025-09-07 is loaded.
- Costs: base case for all tests; the stress case is reported for the final table only.

## Identity check (must pass before anything is reported)

The study uses a script-local admission ordering. With the alphabetical key and outright
rejection it must reproduce the library `run_funded_replay` result exactly (same fills,
same final equity to the cent) for all four books on both cap sets. If it cannot, the
study stops and reports that.

## Arms

1. **Random order (luck band):** 40 seeded random same-day orders (seed 20261110 + i),
   outright rejection as now.
2. **Trim-to-budget:** the same 40 orders, but an entry that breaches the open-risk, gross
   or sector budget is trimmed to the largest whole-share size that fits (minimum one
   share) instead of being rejected. Per-trade risk and the symbol cap are unchanged.
3. **Ranked order,** each with and without trim, keys computed from bars up to and
   including the signal day only:
   - K1 relative strength: 63-session return minus SPY's, highest first.
   - K2 volume surge: signal-day volume ÷ 20-session mean volume, highest first.
   - K3 stop distance: `(close_t − stop_t) / close_t`, widest first (full planned risk
     fits under the 10% symbol cap; cost per R is lowest).

No other key or arm is run.

## Metrics and decision rules (fixed)

Per book, cap set and period: net return %, CAGR, max drawdown, daily Sharpe (zero cash
rate), mean exposure, entries taken ÷ signals, and SPY total return for reference.

- **Luck band (fact):** 5th, 50th and 95th percentile of net return and Sharpe across the
  40 random orders.
- **Trim-to-budget** is an admission candidate for a book only if, in **both** periods,
  trim beats reject on net return in at least 26 of the 40 paired orders (one-sided sign
  test p < 0.05) *and* its median max drawdown is not more than 2 points higher.
- **A ranking key** is an admission candidate for a book only if its net return *and* its
  Sharpe are above the 90th percentile of that book's random-order distribution in
  **both** periods, on the same cap set and trim mode.
- Twelve key-by-book comparisons are run per cap set; with a 10% × 10% joint tail under
  the null, about one false "candidate" in a hundred is expected per comparison. Every
  cell is reported whether or not it qualifies. No re-run after a fail.

## Expectations (stated in advance)

Capacity binds for trend_continuation.medium on 150 symbols and much less on the
24-symbol books, so differences should concentrate there. The luck band is expected to be
wide (several points of net return). Trim-to-budget is expected to help modestly. No
ranking key is expected to clear the bar: fifteen conditioners already failed
out-of-sample as filters on trend_continuation.medium.

## What a pass does and does not license

Admission order and trimming are ledger behaviour, not strategy rules; adopting either in
the operating paper book is an operator decision and, while the v2 studies are frozen,
belongs to a future study generation. Nothing here changes the operating scan, ledger,
risk limits or any frozen study.

Research signal only — no order was placed.
