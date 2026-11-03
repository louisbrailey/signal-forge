# Income target assessment — November 3, 2026

Status: **not established**. No reliable daily, weekly or weekend income is demonstrated.
The targets are $1,000 per weekday or $5,000 per workweek, plus $400 per combined
weekend (interpretation of the requested weekend amount). They are not strategy
parameters, a reason to increase risk, or a criterion for selecting a backtest.

## Verified operating evidence

The operating equity-position table contained 15 closed paper positions with
$8.88 in recorded realized P&L at inspection. These fields exclude open-position
changes, require separate legacy-correction review, and are not broker-confirmed
income. The default and sv2 books each record $30,000 initial paper cash. Each
would need 3.33% of that initial capital per weekday or 16.67% per workweek to meet
the respective target alone. This is arithmetic, not a forecast or a suggestion
to add capital. The books must not be combined as though a funded portfolio were
established. No real brokerage balance was read.

The existing repair audit reports a BNB data gap invalidating expanded-crypto
promotion evidence, withdrawal of unsupported monthly income estimates, failed
daily-strategy gates and a rejected intraday development evaluation. Read
the operating checkout’s `docs/research/REPAIR_AUDIT_2026-11-02.md` (research branch; not yet part of main) for the dated evidence and
limitations. This assessment does not rerun, inspect or alter sealed studies.

## Reproduce the assessment

```sh
python3 scripts/income_target_assessment.py /absolute/path/to/signalforge.sqlite
```

The tool uses SQLite read-only mode and a restricted projection of operating
paper accounts and closed equity positions. It rejects databases containing
comparison tables, makes no provider or brokerage requests and changes no
strategy or risk setting. Missing daily equity/cash-flow history is disclosed;
daily target hit rates and profit probabilities are deliberately unavailable.

## Evidence required before an income claim

1. Reconcile full account equity, cash flows, realized and unrealized changes,
   corrections and all costs on timestamped marks, including zero-trade periods.
2. Keep incomplete datasets ineligible; publish coverage failures alongside results.
3. Freeze each experiment before outcomes, retain failures and count all trials.
   Reusing a final-test period cannot provide new untouched evidence.
4. Use a capital-constrained portfolio replay with concurrent positions, costs,
   allocation limits and shared exposure. Individual-trade R sums do not suffice.
5. Collect fresh prospective observations on an awake host. Report losing periods,
   drawdown, target attainment and uncertainty; do not force trades to meet a quota.
6. Evaluate any new live study separately from the existing frozen Kronos study.
   Neither a model prediction nor agreement with a strategy establishes safety.

No finite test can guarantee future trading income. Performance targets are not
permission to bypass arming, data holds or hard risk limits. Real-money activation
and order submissions were not performed in this assessment.

Reference: [SEC Investor Bulletin: Performance Claims](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47).

## Full stored-history inventory — November 3

Run `python3 scripts/income_target_assessment.py /absolute/path/to/signalforge.sqlite --history`. The tool inventories every row in six known bar tables under one read-only transaction and groups source, latency, and interval separately. Missing simulation metadata is unknown, not evidence that rows are real; absent quality metadata is counted as unknown. Counts are inventory, not a completeness or backtest pass.

| Table | Rows | First observation | Last observation |
|---|---:|---|---|
| Equity daily | 3,355,095 | 2003-10-20 | 2026-11-02 |
| Equity intraday | 1,519,695 | 2016-09-01 13:30 UTC | 2026-10-26 19:45 UTC |
| Crypto daily | 39,144 | 2015-01-01 | 2026-11-02 |
| Crypto intraday | 413,658 | 2017-01-01 00:00 UTC | 2026-11-03 02:00 UTC |
| FX daily | 33,974 | 2010-01-04 | 2026-11-02 |
| Option daily aggregates | 428,070 | 2023-09-11 | 2026-09-04 |

These global bounds do not imply every instrument spans those dates. Preserve per-symbol coverage checks, corporate-action handling and actual market calendars. Existing datasets include known gaps; never interpolate or discard bad intervals to force a strategy pass.

The imported income-target evaluator requires an explicitly sourced daily net-liquidation panel. The operating ledger is not automatically exported as that panel because its current-state snapshots cannot reconstruct historical cash and positions. Historical coverage and valid income evidence remain separate requirements.

A full-history replay of frozen rules may be reported descriptively after recording every window, cost model, eligibility exclusion and failed experiment. Training and evaluation remain chronologically separated. Once a holdout has informed revisions, it is development evidence; further validation requires new prospective observations. Never search repeatedly until every historical day meets a dollar target.
