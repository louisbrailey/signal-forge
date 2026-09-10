# Strategy Completion Program — plan and starting inventory (2026-09-10)

Goal set by the operator: bring every remaining strategy to full operation.
Honest framing: profitability cannot be guaranteed and promotion gates will NOT
be weakened. Each strategy therefore ends in one of two states — an honest
PAPER_APPROVED verdict on the deterministic gates, or a documented,
evidence-backed "does not pass" with the research that was tried.

## Starting inventory (approved dataset: snapshot 3 `universe_24_ex_meta`, source `massive`)

| Version | Strategy | Status | Blocking gates (latest evaluation) | Sealed-year result (2025-09-08..2026-09-08) |
|---|---|---|---|---|
| 2 | trend_continuation.short_swing v0.1.0 | PAPER_APPROVED | — | +0.2982R on 109 trades |
| 5 | relative_strength.medium_swing v0.1.0 | PAPER_APPROVED | — | +0.2935R on 16 trades |
| 3 | trend_continuation.medium_swing v0.1.0 | experimental | `sealed_final_test` only | −0.0294R on 95 trades |
| 4 | mean_reversion.short_swing v0.1.0 | experimental | `net_expectancy`, `bootstrap_ci`, `parameter_sensitivity`, `benchmark_comparison` (pre-sealed OOS) | +0.1278R on 84 trades (passes) |
| 6 | volatility_breakout.short_swing v0.1.0 | experimental | `bootstrap_ci`, `regime_coverage`, `benchmark_comparison`, `sealed_final_test` | −0.0979R on 10 trades |
| 1 | intraday_orb.intraday v0.1.0 | experimental | `data_availability` (no intraday bars; EOD-only operation) | n/a |

Data: 24 symbols with ~2,067–2,487 daily bars each (2016-10 → 2026-09-09) under
source `massive`; the bulk universe (`massive_grouped`, 2,655 symbols) covers only
2025-01 → 2026-09 and is not readable by the research path.

Key thresholds (config/research.py): min OOS trades 30, net expectancy > 0R,
bootstrap CI low ≥ +0.02R, sensitivity positive fraction ≥ 0.6 / neighbour
fraction ≥ 0.75 (grid cells need ≥ 15 trades), ≥ 3 regimes with ≥ 10 trades each,
must beat benchmark Sharpe, data validation + leakage checks, sealed test ≥ 0R.

## Rules of engagement (binding on every agent and every phase)

1. No tuning against the sealed window; every change must be motivated on
   pre-sealed data (walk-forward folds, sensitivity grids).
2. Any sealed re-run of a modified strategy is a "second look" and is counted and
   disclosed in the evaluation record; live paper evidence is the confirming test.
3. No gate or threshold is weakened; the cost model is unchanged.
4. New behaviour ships as a NEW version (v0.2.0); v0.1.0 stays intact and scoped.
5. Source isolation stays (research reads `massive` only); a larger universe means
   a new reusable DataSnapshot with real 10-year per-symbol history.
6. Multiple-testing discipline: the number of variants tried per strategy is
   recorded; a pass after many tries is reported as such.
7. Paper-only. No brokerage, no LLM decisions; LLMs only summarise audited evidence.

## Phased multi-agent plan (Fable orchestrates; Sonnet/Opus teams do bounded work)

1. **Understand** (read-only, ~10 Sonnet readers + Opus synthesizer + critic):
   gates and sealed semantics, backtest engine and costs, each failing strategy's
   rule set, data-layer capacity for a larger 10-year universe, prior docs, live
   feedback loop, exact gate-by-gate numbers. Output:
   `docs/research/STRATEGY_COMPLETION_MAP.md`.
2. **Design** (Opus judge panels per strategy): three independent proposals per
   strategy from distinct angles — signal quality/regime filtering, exits and risk
   engineering, universe breadth and statistical power — scored by two judges for
   legitimacy (no lookahead, no sealed contamination), expected gate impact,
   robustness, and cost; synthesized into one design per strategy.
3. **Implement and validate** (Opus/Sonnet in worktrees): v0.2.0 per strategy,
   pre-sealed walk-forward + sensitivity on the approved dataset (and on the
   expanded dataset if built), then three adversarial reviewers per candidate
   (lookahead/leakage, overfitting/multiple testing, code correctness/tests).
4. **Integrate** (Fable): gates, promotion pipeline run with sealed looks
   disclosed, commit, worker restart, report; live paper probation confirms.

Special cases: `intraday_orb` needs an intraday data pipeline and is excluded from
EOD-only operation by policy — it gets a data-requirements design, not a
promotion attempt, until the operator decides on intraday operation.
`volatility_breakout` cannot reach statistical power on 24 symbols; universe
expansion is a prerequisite for it.

## Status

Planning saved 2026-09-10. Phase 1 was prepared but not launched (operator paused
before the workflow started). Nothing in the strategy code or database has changed.
