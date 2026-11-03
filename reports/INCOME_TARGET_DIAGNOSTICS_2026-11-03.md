# Income-target diagnostics — 2026-11-03

**Verdict: targets not met; no promotion or live-trading basis.** This is descriptive analysis of already-observed Massive daily history. It does not use frozen Kronos data or change a strategy, production configuration, paper book or risk limit.

## Dataset and fixed assumptions

Window: 2016-10-17–2026-11-02; $10,000 starting cash; 23 symbols × 2,525 sessions = 58,075 observations. The default 25-symbol universe excludes META (1,273 absent sessions) and XLC (420 pre-inception sessions), based on coverage before the broader run. No missing session is filled. This is not 100% of stored market history.

This runs signal rules and funded sizing, **not the full production scanner**: minimum price/average dollar-volume/event and promotion gates are not reproduced. The 1% previous-volume cap is not a replacement for those gates. These outputs cannot be presented as expected operating-paper returns. Whole-share sizing and cent rounding on split-adjusted historical prices also do not reconstruct contemporaneous raw lots and split events. This is another reason to complete corporate-action accounting before economic validation.

Unchanged `trend_continuation.short_swing` rules; causal next-open fills, one cash account, 5% initial position/20% sector/60% total exposure caps and existing 0.5% per-trade/1.5% aggregate open-risk limits. Daily marks include modeled liquidation costs. Exchange closures carry the last modeled mark; they do not imply weekend trading.

Fixed scenarios were stated in `docs/INCOME_TARGET_RESEARCH_NEXT.md` before the broader run. Costs change admissions and share counts as well as fill P&L, so differences between runs are not just fee subtraction. Adverse cent rounding remains in every scenario.

## All scenario outcomes

| Scenario | Net P&L | Annualized return | Close-mark max drawdown | Round trips | Costs | Mean exposure |
|---|---:|---:|---:|---:|---:|---:|
| base | $1424.53 | 1.335% | 4.70% | 1085 | $644.50 | 10.34% |
| zero_fees_spread_slippage | $2116.28 | 1.929% | 3.78% | 1117 | $71.14 | 10.71% |
| higher_cost_stress | $-1635.41 | -1.762% | 16.93% | 950 | $3088.85 | 8.85% |

Every scenario missed all **2,621 weekday $1,000 targets**, all **524 complete $5,000 workweeks**, and all **524 $400 weekends**. One final partial workweek is excluded. Weekday counts include holidays. Weekend P&L is zero under the explicit equity-closure valuation policy; there is no eligible weekend strategy in this run.

Base-case best/worst weekday: $125.12 / −$135.43. Mean complete workweek: $2.75. The largest single closed-trade gain was $88.91; excluding it leaves $1,335.62. NVDA contributed $454.13 and AAPL $277.42, together about 51% of net P&L. This concentration is descriptive, not a reason to select those stocks after seeing outcomes.

## Base-case annual mark-to-market contributions

Calendar-year contributions are not independent folds or untouched tests; boundary years are partial.

| Year | Net mark P&L |
|---|---:|
| 2016 | $5.70 |
| 2017 | $-53.97 |
| 2018 | $-25.47 |
| 2019 | $68.53 |
| 2020 | $357.65 |
| 2021 | $116.88 |
| 2022 | $68.10 |
| 2023 | $118.43 |
| 2024 | $437.82 |
| 2025 | $69.39 |
| 2026 | $261.47 |

## Passive reference and interpretation

- base: passive net price P&L $83140.58; initial residual cash $4014.55.
- zero_fees_spread_slippage: passive net price P&L $83599.76; initial residual cash $4017.54.
- higher_cost_stress: passive net price P&L $82549.59; initial residual cash $4005.46.

This reference uses the same capital, window and cost scenarios with 5% name/20% sector/60% aggregate **initial** budgets and alphabetical admission. It then holds without stop/open-risk caps or rebalancing, so exposures can drift far beyond initial caps. It is **not risk-equivalent**. Its large historical return is heavily affected by survivor selection and holding NVDA through its historical appreciation; it is not a deployable income recommendation. No dividend cash flows are modeled in either path. The initial comparator implementation lacked the 60% total budget; only corrected results are listed above.

## What needs to change

1. Complete corporate-action cash accounting, listing/ticker lifecycle, point-in-time eligibility/events/sector data and ETF look-through correlation before full-history claims. META needs identity reconciliation; XLC needs inception-aware admission, not invented bars.
2. Add a tested portfolio drawdown entry suspension and observed-cost/impact calibration. The higher-cost run lost 16.35%; do not loosen risk constraints to compensate.
3. Compare unchanged baseline strategies in a common funded development framework with genuinely comparable risk budgets. Low exposure alone is not proof that more exposure would help; the cost-stress failure shows why forced trading is unjustified.
4. Any new entry/exit hypothesis must be versioned and chosen using development evidence only, then tested prospectively. This entire window is already observed; it cannot be relabeled untouched or used to tune for a dollar target.
5. Weekend income requires independent continuous-market research and validated data. No FX/crypto/options trade is authorized by this equity report.

No demonstrated change currently makes $1,000/day reliable. More models, removing stops, higher leverage or pruning historical losers would not establish that claim. The evidence supports further research, not income promises.

## Reproduce

```sh
PYTHONPATH=src uv run python scripts/funded_replay_report.py /absolute/path/signalforge.sqlite \
  --symbols AAPL AMZN DIA GOOGL HD IWM JPM MSFT NVDA QQQ SPY UNH XLB XLE XLF XLI XLK XLP XLRE XLU XLV XLY XOM \
  --since 2016-10-17 --until 2026-11-02 --cost-scenarios > replay.json
```

Full local JSON stays under ignored `.toolkit-runs/funded-default-universe-diagnostics.json`; it includes bar hashes, sector snapshot, costs, strategy spec, rejections, fills, marks, calendar evidence and all scenarios. Reproducing requires the same inputs. Aggregate bar-hash identity: `e01b4a57f5c29d23c1f74635c133d8ebbc6f2f2db2cf8219689483de0573bd49`.

Research signal only — no order was placed.
