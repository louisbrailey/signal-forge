# Frozen shadow outcome protocol v1

This protocol adds measurement, not strategy approval. Existing ADR decisions,
risk limits and sealed tests are unchanged. Do not tune this protocol against
its future outcomes. Record any subsequent protocol as a new experiment.

Eligible observations are new `shadow-outcomes-v1` forecasts with a candidate
snapshot captured before inference, completed before the next session opens,
using current real Massive adjusted daily bars. Replay, stale, malformed and
legacy observations are reported separately and never silently included.

The model predicts 5 or 20 sessions. Record three paths and their mean; the path
range is not a confidence interval. Compare mean absolute error with unchanged
price. Model weights remain unverified cached weights; this limits reproducibility.

A positive Kronos diagnostic means the terminal mean exceeds the origin close
plus modeled round-trip costs. A positive strategy diagnostic means at least
one same-UTC-day, pre-inference, long equity candidate passed its existing gates.
Use short-swing candidates for 5-session diagnostics and medium-swing candidates
for 20-session diagnostics; do not blend horizons. Snapshot all candidate IDs, versions, horizons, gates and timestamps, including
rejections. This is a bounded sampled watchlist, not all strategy opportunities.

Report strategy-positive, Kronos-positive, agreement and disagreement cohorts.
An absent candidate means unavailable comparison context, not disagreement.
They overlap. Forecast windows and instruments are correlated. Returns are a
one-share next-session-open to terminal-close diagnostic: default project costs
(zero commission, 3 bps slippage each side, half of 5 bps spread each side).
They do not reproduce strategy exits, stops, sizing, dividends or portfolio
constraints, and must not be described as actual strategy or portfolio P&L.
Do not combine horizons when estimating evidence. No profitability probability
or independent-confirmation claim follows from model/strategy agreement.

Preserve forecasts and failures. Resolve only complete, valid future sessions;
store the actual observations and forecast hash with each immutable outcome.
Missing sessions remain pending, invalid data are excluded. Never rerun a model
because its outcome was poor. Existing unclassified forecasts are not retrofitted
with candidate decisions that became known later.
