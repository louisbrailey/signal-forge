# Why nine of ten funded strategy books lost under higher costs

Research signal only — no order was placed.

The result is a failed **cost-stress test of ten separately funded daily strategy
books**, not nine software crashes and not a complete evaluation of corporate-stock
trading. Eight books gained under base costs, seven under higher spread/slippage
alone, and one under combined higher friction and commissions. Small gross edges,
frequent turnover, and a $1 minimum commission per order explain much of the loss.
None establishes dependable daily income. No strategy is promoted by this audit.

## Confirmed defects repaired

1. Bar ingestion can create instruments with the default type `stock`. Later
   reference discovery did not correct existing rows. The pinned snapshot has 16
   conflicts with sourced ETF classifications. The offline metadata reader now
   uses exact `ETF`/`CS` reference codes, retains provenance and explicitly labels
   those classifications **current, not point-in-time**. Unknown codes such as
   `ETV` do not receive an inferred ETF exemption. The normalizer reconciles known
   types with an audit record in the same transaction, once per actual change.
   No operating database was rewritten in this audit.
2. The frozen per-instrument backtest engine ignores commissions because it does
   not model funded share quantities. Its report wrapper now rejects nonzero
   commission requests instead of implying they were applied. Such requests must
   use funded replay. The frozen engine itself remains byte-identical.

These fixes restore accounting and eligibility honesty. They do not turn a weak
strategy into a strong one. Regression tests reproduce both defects and verify
read-only metadata extraction, correction audit/idempotence, and fail-closed fees.

## Fixed experiment

Real cached Massive raw daily prices, splits and dividends; 25 symbols;
2016-10-17 through 2026-11-02. Input manifest:
`edb199c01af7811a9ac8dd4237209af97cea476a9088949d7f84daa018dd8eb1`.
The strategy registry and engine were loaded from the archived operating source
at `cbc7acf7c0636ef66d6014b3d49d56dd0daf66ef`, which contains the ten daily
versions below. The repair branch is based on `e4da0e0`; its registry has fewer
strategies. Do not silently substitute that registry when reproducing this table.
Runtime source hashes and full rule specifications accompany the local design.
The specs' dynamically resolved `git_sha` can reflect the caller checkout rather
than the archived module; source-file hashes and the archive commit identify the
actual implementation used.

Every book starts with its own $10,000; shared cash within each book, whole shares,
no leverage or shorts, 5% initial position allocation, 20% sector exposure cap,
0.5% per-trade risk, 1.5% aggregate open risk, 60% exposure cap, 1% volume
participation cap and a 10% drawdown entry halt. Existing next-open fills,
adverse rounding, stop/target/time exits, split-adjusted share quantities, dividend
cash flows, event admission and missing-session checks remain in force. Sector
labels and universe membership are current metadata; historical sector and
survivorship bias remain. Do not add these independent books' returns together.

Four cases were fixed before execution; no parameter or cost was selected to
maximize returns:

| Case | Slippage per fill | Full spread | Commission |
|---|---:|---:|---|
| Base | 3 bp | 5 bp | $0 |
| Commission only | 3 bp | 5 bp | $0.005/share, $1/order minimum |
| Friction only | 10 bp | 10 bp | $0 |
| Combined stress | 10 bp | 10 bp | $0.005/share, $1/order minimum |

Spread charges use the existing half-spread fill convention. The fee amounts are
sensitivity assumptions, not verified tariffs for a future broker/API route.
Webull's [published pricing](https://www.webull.com/pricing) describes app/desktop/web
commission-free stock/ETF transactions with other fees still applicable; it does
not establish the complete cost of a particular API route. No execution route was
contacted, enabled or reconfigured. Cost assumptions were not reduced in production.

## Full-period net returns

Percent of each book's initial cash, **over approximately ten years, not per day
or per year**. Results include marked equity and modeled costs, not cash income.

| Strategy/version | Base | Commission only | Friction only | Combined stress |
|---|---:|---:|---:|---:|
| Trend continuation short 0.1.0 | +9.902% | −3.761% | +4.227% | −7.961% |
| Trend continuation medium 0.1.0 | +9.615% | −2.420% | +4.618% | −7.425% |
| Mean reversion short 0.2.0 | −0.010% | −1.277% | −0.007% | −1.267% |
| Relative strength medium 0.1.0 | +5.179% | −0.266% | +2.913% | −2.104% |
| Volatility breakout short 0.2.0 | −0.581% | −1.361% | −0.600% | −1.374% |
| ETF time-series momentum medium 0.1.0 | +14.518% | +2.564% | +9.539% | −0.050% |
| Turn of month short 0.1.0 | +6.772% | −9.809% | −0.590% | −9.794% |
| ETF time-series momentum position 0.1.0 | +10.564% | +7.478% | +10.239% | +4.723% |
| 52-week-high breakout medium 0.1.0 | +3.207% | +0.020% | +1.208% | −1.587% |
| Trend pullback short 0.1.0 | +4.277% | +1.062% | +2.177% | −0.303% |

For example, short trend continuation paid $1,154 in combined-stress commissions
and lost $796.08. Position momentum paid $416 and gained $472.27. Costs can change
admitted trades, later equity and subsequent fills, so differences between cases
are not an additive causal decomposition. The same dataset was already inspected;
this is descriptive sensitivity evidence, **not an untouched out-of-sample test**.

The prior same-window SPY reference book with a 5% initial allocation and the
remaining cash idle returned +11.931% under stress, including dividends. It does
not have the active strategies' stop/time-exit rules or matched exposure paths;
it is a simple comparator, not proof of equivalent risk. None of these 40 cases
reached the $1,000 weekday or $5,000 workweek targets even once.

## Stock coverage blocker verified

The pinned database has **zero `earnings_event` rows**. Without verified
decision-time earnings coverage, corporate stocks fail closed. Resulting filled
books are ETF-heavy and cannot establish performance for the broader stock system.

A single existing-key verification of `GET /benzinga/v1/earnings` on
**2026-11-04 08:09:00 UTC** returned **HTTP 403 / not_entitled**. Only endpoint,
source, timestamp, status and error category were recorded; no credential or
response body was stored. News entitlement does not imply Earnings entitlement.
Massive documents this as the separate [Benzinga Earnings endpoint](https://massive.com/docs/rest/partners/benzinga/earnings).
Its historical records' `last_updated` field alone would not prove that the
calendar was available before each historical decision. No subscription was bought
or configuration changed. Do not bypass the event filter or infer empty calendars.

## Research disposition and next evidence

Keep the weak strategies experimental and retain every failed result. A separate
monthly slow-trend study already exists at commit `424109f`: positive stress P&L
of $199.36, but the simpler no-trend-filter comparator earned more and the paired
uncertainty interval crossed zero. Repeating that idea or increasing capital does
not establish a new edge. See that commit's `reports/SLOW_TREND_2026-11-03.md`.

The next evidence needed is verified route-specific costs and a point-in-time
earnings coverage source, followed by a separately pre-registered prospective
comparison against simple benchmarks. No new income target, parameter sweep,
sealed-study look, Kronos alteration or automatic paper entry is authorized by
these results. Existing frozen Kronos and forward studies were not opened or changed.

## Reproduce and inspect

Offline command for the registry in the chosen source tree:

```sh
PYTHONPATH=/absolute/archived-source/src uv run python scripts/cost_attribution_report.py \
  /absolute/raw-actions-v1 /absolute/new-output-directory \
  --database /absolute/read-only-market-snapshot.sqlite \
  --listing-evidence /absolute/listing-evidence.json
```

Use an existing verified raw/action snapshot and sourced listing-date evidence;
the command refuses an existing output directory, frozen comparison databases and
unexplained staggered history. It records design/source hashes/effective limits
before results and saves per-case fills, decisions, equity and diagnostic summaries.
Licensed raw data and private databases remain outside Git. The ten-strategy local
artifacts are under `.toolkit-runs/profit-audit-20261104/`; full-history source and
snapshot provenance are under `.toolkit-runs/full-history-20261104/`.

Validation: full parallel suite **2,806 passed**, serial suite **1 passed**;
Ruff, Black, mypy and **21/21 import contracts** passed. A follow-up report-metadata
serialization regression was fixed and covered separately after the full run.
The final focused pass was **12 passed**. A second completed replay using the
expanded provenance record matched all **40 case summaries exactly**. Secret
scanning passed. Summary SHA256:
`05df1424f52ff4e240639c3241e7e653b6338cbaffbbe4f7fdd8ac13bc50d8cc`.
The unsuccessful invocation and corrected replay are retained locally. The
production checkout, running worker, broker settings and frozen studies were not
modified or redeployed. This is a research-accounting repair, not a claim of
dependable profitability.
