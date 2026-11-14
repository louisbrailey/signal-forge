# Pre-registration — R4-O: do the approved rules add anything on top of holding the index?

Status: written 2026-11-10 after the R3 results and before any run of this study. Operator
request (2026-11-10): "continue pushing for more profit within each strategy and the kronos ai
part of the workflow". No sealed look, no operating-database write, no change to any frozen
study, risk limit or approved version. Results file, named in advance:
`docs/research/RESULTS_r4_core_overlay_2026-11-10.md`.

## Why

`RESULTS_r3_capacity_admission_2026-11-10.md`: none of 1,376 funded replays reached SPY's
total return in its period (+130.1% IS, +50.6% OOS, against a best single run of +53.3% and
+29.2%), at 11% to 45% mean exposure. Idle capital is the largest gap, and a core-index
holding is listed as untested in `RESULTS_funded_approved_set_2026-11-08.md`. Parking idle
cash in the index is trivially "more profit"; the question that matters is whether running
the rules on top of that core adds to it or subtracts from it. That is the rules' active
return against the index on the capital they use, after costs.

## Scope (fixed)

- Books: each PAPER_APPROVED version alone on its approved snapshot, exactly as in R3-C
  (trend_continuation.short_swing and relative_strength.medium_swing on 3;
  trend_continuation.medium_swing and high52_breakout.medium_swing on 11).
- Replays: the R3-C script-local funded replay (identity-checked against the library), the
  same 40 random same-day orders (seed 20261110 + i), outright rejection, both cap sets
  (operating, maxima), $30,000, base costs. IS 2016-10-17..2022-02-10 and OOS
  2022-02-11..2025-09-05, each from fresh cash. Nothing on or after 2025-09-07 is loaded (the
  R3-C disclosure about split rows read by the library dividend loader applies unchanged).
- The overlay never changes a book's trades: entries, exits, sizes and costs are those of the
  standalone replay, sized on the book's own equity.

## Overlay accounting (fixed)

The account is the book plus an index sleeve that holds the book's idle cash in SPY.

- `E_t` book equity and `C_t` book cash at the close of session t (from the replay's daily
  marks; `C_t` floored at 0). Flow on session t: `F_t = C_t − C_{t−1}` (entries withdraw,
  exits and dividends deposit), taken at the open of session t.
- Sleeve value `K_t`, with `K_0 = C_0 = 30,000`:
  `K_t = (K_{t−1}·(1 + r_on,t) + F_t − cost_t)·(1 + r_id,t)`, where `r_on` is SPY's
  close-to-open and `r_id` its open-to-close return on adjusted prices (so their product is
  SPY's total return), and `cost_t = c·|F_t|` with `c` = 5.5 bps (base) or 11 bps (stress).
- Account value `V_t = (E_t − C_t) + K_t`.
- If `K_t < 0` on any session the book asked for more than the sleeve held. Such sessions are
  counted and the largest shortfall reported; a cell with a shortfall above 1% of account
  value on any session is marked "not implementable as stated" and cannot qualify.
- Reference: SPY bought with the whole $30,000 at the first open and held (one 5.5 bps cost).

## Metrics and decision rule (fixed)

Per book, cap set and period, across the 40 orders: account net return, CAGR, max drawdown,
daily Sharpe (zero cash rate); and the **increment** = account minus the SPY reference on each
(net return in points, CAGR, Sharpe, max drawdown). Also the standalone book for context.

A book/cap-set is an **account-level candidate** only if, in **both** periods: the median
net-return increment is positive, the median Sharpe increment is positive, at least 36 of the
40 orders have a positive net-return increment, and the median max drawdown is not more than
2 points above SPY's. Qualifying cells are then repeated at stress costs (rule costs and
sleeve cost) and reported; a cell that loses its standing there is reported as "base costs
only". Eight book-by-cap-set cells; every cell is shown whether or not it qualifies. No other
sleeve, gate, fraction or leverage is run.

## Expectations (stated in advance)

Every overlay account will be far above its standalone book. No cell is expected to qualify:
the IS period is a strong index stretch, earlier work found no approved rule ahead of
exposure-matched SPY, and R3-P found no trigger ahead of random dates in the symbol-years it
traded. Increments are expected to be negative in IS and near zero in OOS, with the short
trend book closest.

## What a result does and does not license

A qualifying cell would be the first evidence that a rule earns more than the index on the
capital it uses; it would justify a prospective account-level comparison, nothing else. A
fail means the rule subtracts from an index core on this sample: standing alone it is
profitable only because it is long equities part of the time. Either way, nothing here
changes the operating scan, ledger, risk limits or any frozen study, and a sleeve in the
operating paper books is an operator decision for a future study generation.

Research signal only — no order was placed.
