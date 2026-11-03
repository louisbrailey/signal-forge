# Higher-cost failure audit — 2026-11-03

The failures are economic losses under the specified stress assumptions, not failed
software assertions. Accounting checks found no double debit of spread, slippage
or commissions. No cost assumptions were lowered, positions enlarged, signals
tuned, or historical losing trades filtered out to manufacture a pass.

Input: the action-aware historical report from implementation `a611b53`, whose
coverage and limitations are in `ACTION_AWARE_COMPARISON_2026-11-03.md`.
Each strategy has its own $10,000 account, shared across instruments within that
book. These are previously observed histories, not new out-of-sample results.

| Strategy | Stress net P&L | Commissions | Spread, slippage and rounding | Pre-cost attribution on those same fills |
|---|---:|---:|---:|---:|
| Short trend | −$796.08 | $1,154.00 | $750.63 | $1,108.55 |
| Medium trend | −$742.52 | $1,052.00 | $686.63 | $996.11 |
| Mean reversion | −$126.73 | $126.00 | $82.51 | $81.78 |
| Relative strength | −$210.38 | $490.00 | $334.90 | $614.52 |
| Breakout | −$137.36 | $82.00 | $53.23 | −$2.13 |

Pre-cost attribution adds the recorded cost ledger back to final net P&L,
including earned dividends once. It is **not a zero-cost replay**: changing costs
can alter whole-share sizing, cash, admissions and subsequent trades. Base and
stress results are not paired identical trade paths. Per-fill cent rounding is
included in modeled costs.

## What this fixes and what remains unproven

`scripts/funded_cost_audit.py` now produces a reproducible decomposition from the
saved historical report, with the input hash, trade counts, per-round-trip cost
burden, realized historical breakeven shortfall, and explicit no-promotion status.
It rejects forward records, unfinished positions and inconsistent accounting.
It never opens an operating or comparison database, changes a study, or fetches
provider data.

The first four strategies have positive fixed-fill pre-cost attribution but
insufficient realized edge to pay stress costs. Breakout has negative attribution
even before costs; cheaper execution alone cannot repair this sample. Mean
reversion also loses under base costs. None supports reliable income claims.

The proper remedy is a separately versioned cost-aware research candidate, not a
patch to these historical outcomes. Its entry admission would require a positive
lower confidence bound for expected net edge from training-only evidence after
round-trip costs. No such calibrated estimate exists here, so importing hindsight
per-trade profits into an entry filter would introduce leakage. Candidates should
be compared against the unchanged baseline on training/validation periods and
then new prospective observations; abandon candidates that fail. Verified lower
fees can be an additional disclosed scenario, never a replacement for stress.

The existing ten-book forward study remains an unchanged baseline. It starts
observing November 4, 2026, with fills no earlier than November 5. Its source
fingerprint still matches; no future performance is available yet. The older
frozen Kronos study and all interim results remain untouched. No new strategy,
cost reduction, risk expansion, promotion or brokerage action was activated.

## Reproduce

```sh
uv run python scripts/funded_cost_audit.py /absolute/path/to/action-aware-report.json
uv run pytest tests/test_funded_cost_audit.py tests/backtest/test_funded.py --no-cov -q
```

The CLI reads only the named historical JSON (maximum 256 MiB), writes its audit
to stdout, and reports historical breakeven arithmetic as descriptive evidence,
not an executable forecast. Synthetic tests cover reconciliation, dividend
payment non-duplication, gross losses, malformed costs and exclusion of forward
evidence. Synthetic test values are not performance evidence.

Research signal only — no order was placed.
