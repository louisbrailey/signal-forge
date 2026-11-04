# Fixed strategy refinements, research protocol R1

Research signal only — no order was placed.

This protocol is recorded before evaluating these variants. All historical data
has already been inspected in other experiments. No period is an untouched final
test. There is no optimization loop, parameter search or operating promotion.
Existing strategies, risk limits, Kronos and forward studies remain unchanged.

## Hypotheses and exact changes

One candidate per existing daily strategy; all original entry rules remain the
starting point. Only long signals are eligible. Stops/targets remain unchanged
except that a delayed confirmation consumes one session of the original time stop.

| Family | Fixed candidate | Failure hypothesis |
|---|---|---|
| Mean reversion | Original signal on previous session; today's close must exceed previous close, remain above original stop and below original target. Enter next open. | Some unusual down moves continue falling; wait for a completed recovery bar. |
| Volatility breakout | Same one-session follow-through confirmation and original stop/target constraints. | Initial breakouts can reverse immediately. |
| Trend continuation, relative strength, 52-week-high breakout, trend pullback | Original signal plus `close - SMA20 <= ATR14`. | Chasing extended moves can produce weak entry prices and reversals. |
| ETF time-series momentum, both horizons | Original month-end signal plus SPY close strictly above its SMA200. | Broad equity drawdowns may overwhelm individual ETF momentum. |
| Turn of month | Original calendar signal plus the instrument's close strictly above SMA200. | A calendar effect may not compensate for a persistent downtrend. |

These are assumptions, not established improvements. The one-ATR threshold,
20/200-session averages and one-session delay are fixed conventional scales, not
values chosen by backtest returns. A lost opportunity is part of each variant's
cost. Confirmation reads only the previous prefix and today's completed bar;
same-day close is never used for a same-day fill. Short signals are rejected.

## Data and controls

Use the verified Massive raw/action snapshot, 25 symbols, 2016-10-17 through
2026-11-02, manifest
`edb199c01af7811a9ac8dd4237209af97cea476a9088949d7f84daa018dd8eb1`.
Use archived strategy source `cbc7acf7c0636ef66d6014b3d49d56dd0daf66ef` for the
ten daily baselines; record each specification and source hash. Current main's
smaller registry must not be silently substituted for the ten-strategy study.
Read-only, sourced classification corrections from PR62 are retained and labelled
current, not historical point-in-time. Stocks without decision-time earnings
coverage remain excluded. No live API calls or fixture performance data.

Every book starts with $10,000, no leverage, 5% initial position allocation,
20% sector cap, existing 0.5% per-trade/1.5% aggregate risk/60% exposure limits,
10% drawdown entry halt, 1% volume participation, actual whole shares and corporate
actions. Current sector labels, surviving universe, modeled spreads, missing
historical quote/regulatory-fee coverage and bar-path ambiguity remain limitations.

Compare unchanged baseline and candidate at three fixed costs: base (3 bp
slippage, 5 bp full spread, zero commission), friction (10 bp/10 bp, zero
commission), combined stress (10 bp/10 bp plus $0.005/share, $1 minimum/order).
The commission floor is synthetic stress, not a claim about Webull's published
commission. Keep all three, including failures; do not choose the cheaper case.

Additional simpler comparator: SPY only, last exchange session of month, close
above SMA200, long, stop 3 ATR14 below close, no target, 63-session time stop,
identical capital/risk/fill rules. Cash earns zero. These contextual benchmarks
have different exposures and do not replace paired baseline-versus-candidate tests.

## Chronology and decision rule

- Development: 2017-01-01 through 2020-12-31; descriptive, no fitting.
- Validation: independent annual books for 2021, 2022 and 2023. Warm-up uses only
  preceding history; each book starts flat and liquidates at its last session.
- Previously observed follow-up: 2024, 2025 and 2026 through snapshot end, evaluated
  after recording the validation disposition. It cannot change the chosen rules
  or rescue a failed validation result. No sealed look is spent.

For each strategy, require ALL cost cases to have positive mean validation-year
return, at least two positive years, at least two years beating baseline, at least
30 closed trades, and worst annual drawdown no more than one percentage point
above baseline's worst annual drawdown. These are conservative screening
assumptions, not existing production promotion gates.

Additionally require a positive lower bound for paired candidate-minus-baseline
monthly returns. Use 3-month nonoverlapping blocks, 10,000 bootstrap draws, fixed
seed 20261104, and a one-sided lower quantile of `0.05 / (10 * 3)` to account for
ten families/horizons and three cost comparisons. This is descriptive uncertainty
on reused history; it does not undo prior searches or prove an investable edge.
Missing months, empty evidence, nonfinite values or fewer than 24 months fail.

Report all candidates, costs, annual folds, drawdowns, exposures, costs, trade
counts, paired intervals and regime attribution. Do not sum separately funded
books or call annually reset books one continuous equity curve. No parameter
revisions after these outcomes. Passing earns only consideration for a NEW
prospective protocol, never automatic paper/live activation or a profit promise.
