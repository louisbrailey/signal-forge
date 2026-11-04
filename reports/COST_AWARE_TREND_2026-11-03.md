# Cost-aware trend evaluation — 2026-11-03

**Verdict: implemented, but no actionable edge found.** The fixed candidate made zero trades in every fold. Remaining in cash avoided some losses and missed gains; it does not establish a profitable strategy. No thresholds were retuned after these results.

Protocol: [COST_AWARE_TREND_V1](../docs/research/COST_AWARE_TREND_V1.md). The original five-strategy comparison informed choosing short trend, so no part of this historical experiment is an untouched test.

Raw Massive data: 25 canonical instruments, 62,705 observations, 2016-10-17–2026-11-02. Fifteen verified ETFs may qualify; ten stocks remain blocked by unavailable historical earnings coverage. Raw splits, share quantities and cash dividends are included in portfolio accounting. XLC lacks its first listed session; fixed survivor selection/current sector metadata and modeled execution remain limitations.

Each annual evaluation resets baseline and candidate to separate $10,000 accounts. Both retain shared cash, no leverage, 5% position/20% sector/60% total exposure ceilings, 0.5% trade/1.5% open-stop risk, 10% drawdown entry halt, volume constraints and next-open fills. Do not sum fold returns as a compounded account.

| Evaluation | Training through | Training trades | Lower gross-return estimate | Baseline base P&L | Baseline stress P&L | Candidate base/stress P&L | Candidate trades |
|---|---|---:|---:|---:|---:|---:|---:|
| 2021-01-04–2021-12-31 | 2020-12-31 | 239 | -0.0222% | $103.11 | $-209.71 | $0 / $0 | 0 |
| 2022-01-03–2022-12-30 | 2021-12-31 | 345 | 0.0708% | $34.02 | $31.11 | $0 / $0 | 0 |
| 2023-01-03–2023-12-29 | 2022-12-31 | 346 | 0.0909% | $229.04 | $1.66 | $0 / $0 | 0 |
| 2024-01-02–2024-12-31 | 2023-12-31 | 409 | 0.1418% | $95.07 | $-66.78 | $0 / $0 | 0 |
| 2025-01-02–2025-12-31 | 2024-12-31 | 471 | 0.1831% | $46.22 | $-50.34 | $0 / $0 | 0 |
| 2026-01-02–2026-11-02 | 2025-12-31 | 525 | 0.2150% | $57.69 | $-108.03 | $0 / $0 | 0 |

Training begins 2016-10-17 and expands annually through the previous December 31. Only normally closed trades with outcomes available by that cutoff become labels; artificial terminal liquidation is excluded. Validation: 2021–2023. Previously observed descriptive follow-up: 2024–2026-11-02. No sealed test was opened and no prospective result is claimed.

The bootstrap uses 2,000 resamples of exit-month clusters, fixed seed, at least 100 trades/24 months/two entry-trend regimes. Training labels add recorded modeled costs back to net price P&L; dividends are excluded from labels conservatively. A model can reject only; it cannot resize or override existing risk rejection. Costs are charged once in accounting. The 1.5 multiplier is an additional admission reserve, not another ledger debit.

The strongest lower estimate was approximately 0.215% per trade. An illustrative $500 lot needs roughly 1.05% gross return to cover the fixed stress costs plus the 50% reserve; whole-share rounding and smaller lots can require more. This gap explains the rejection outcome. These are conditional historical estimates, not calibrated probabilities or guaranteed returns.

Base: 3bps slippage + 5bps full spread, zero commission. Stress: 10bps slippage + 10bps full spread, $0.005/share with $1 minimum each side. The candidate uses at least the stress cost budget in both scenarios, computed at the actual proposed next-open quantity.

Artifacts record design/source/protocol/input hashes, every annual model, paired baseline/candidate funded books, fills, risk/cost vetoes and metrics. The offline runner creates a new output directory and refuses overwrite. No provider calls, trading, operating registry changes or scheduling are performed.

Implementation lives in a separate checkout; the original frozen Kronos and forward collector source/configuration/results remain unchanged. The candidate is experimental and not promoted. A new prospective study has not been started for a candidate that produced no trades.

```sh
uv sync --frozen --extra llm
PYTHONPATH=src uv run python scripts/cost_aware_report.py /absolute/raw-snapshot /absolute/new-output \
  --database /absolute/signalforge.sqlite --listing-evidence /absolute/verified-security-metadata.json
```

Research signal only — no order was placed.
