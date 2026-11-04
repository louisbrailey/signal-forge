# Cost-aware trend v0.1.0 — separate research protocol

Frozen design before candidate results, 2026-11-03. Not part of the operating
registry, Kronos study or funded-validation-v1. Status EXPERIMENTAL; paper-only.

Hypothesis: the existing short-swing trend trigger overtrades relative to its
estimated gross edge and small-account commission floor. A conservative estimate
from earlier completed baseline trades can reject entries unable to cover costs.
The short-swing baseline is chosen after seeing the earlier five-strategy reports;
that selection is disclosed and does not create an untouched historical test.

Keep trend_continuation.short_swing@0.1.0 triggers, stops, targets and ten-session
time stops unchanged. At a proposed next-open fill, after original cash, sizing,
liquidity and risk checks, allow a trade only when:

    bootstrap_lower_gross_return * actual_proposed_notional
        > 1.5 * estimated_round_trip_cost

Round-trip cost uses the actual whole-share proposal, current open, modeled spread,
slippage, conservative cent rounding and commissions on both sides. The estimate
uses a flat-price exit reference; actual exits and gaps can differ. The extra 50%
reserve is fixed before results, not optimized. The admission hook can only reject;
it cannot enlarge a position, change risk settings or inspect later session prices.

Training labels are completed unchanged-baseline trades under stress costs:
(realized net price P&L + recorded entry/exit modeled costs) / entry notional.
Dividends are excluded from labels (conservative price-only estimate), but paid and
accrued dividends remain in portfolio accounting. Actual split share quantities and
cost basis come from the existing action-aware engine. End-of-window forced exits
are excluded from training. No unclosed or future trade outcome is used.

Fit one pooled estimate from at least 100 trades in 24 exit-month clusters. Resample
whole exit-month clusters 2,000 times with fixed seed 20261103 and take the 5th
percentile of the trade-weighted mean. Require at least two entry-trend regimes
with ten trades each. This approximate uncertainty estimate is not a probability
of profit; temporal dependence, survivor selection and regime shifts remain risks.

Annual expanding folds: training begins with available history 2016-10-17 and ends
December 31 before each evaluation year; first evaluation year 2021. 2021–2023 are
validation; 2024–latest are previously observed descriptive follow-up, NOT sealed
or untouched tests. Refit the fixed estimator once per year only. Baseline and
candidate each start each fold with $10,000 and identical shared cash/risk/costs.
Report fold resets and no pooled cross-fold compounded-return claim. Annual final
liquidation is charged; do not train on that artificial exit in later fits.

Base and stress costs use existing fixed scenarios. The candidate always demands
stress-budget admission even when replaying base costs. No post-result parameter
selection, symbol selection, threshold search, promotion, alerts or scheduling.
Record input hash, source hash, protocol hash, every model and admission decision.
Replay is offline from raw licensed snapshots; operating DB metadata is read-only.
No frozen-study configuration, source checkout, ledger or interim result is read
for fitting or rewritten. Future prospective validation needs a separate versioned
study after reviewing these results. Cash-only behavior is not a profitable edge.

Research signal only — no order was placed.
