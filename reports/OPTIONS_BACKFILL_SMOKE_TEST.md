# Options historical-aggregates backfill — production smoke test

Run 2026-09-08. Command:

```
signalforge options backfill --underlyings SPY --max-expirations 6 \
  --max-contracts 10 --strike-band 0.02 --max-total-bars 500
```

SPY only · nearest 6 expirations · ATM-ranked, capped at 10 contracts · ±2% strike
band · daily aggregates only · 500-bar hard ceiling. `signalforge options
backfill` runs `validate_option_aggregates` immediately afterward by default.

## What happened, in order

**Attempt 1** (`ingestion_run #5`, fresh): the default lookback (`--since`
omitted → config default `backfill_lookback_days=365`) made the pre-fetch bar
estimate ~252 sessions/contract, so the 500-bar ceiling only had room for 1
contract → the pre-fetch trim (not a failure) deferred the rest. Per the
"budget-starved underlyings stay retryable" fix, SPY was **not** marked done —
`bars_written=0`, `symbols_ok=[]`.

**Attempt 2** (`--resume 5` with `--since 2026-07-24`, a realistic 45-day
window): re-selected the same capped set, this time with room in the budget.
Result below.

## Contracts selected and excluded

Candidate pool before any cap: **972** SPY contracts expiring `2026-09-08 →
2027-01-29` within ±2% of the reference price (**$770.19**, the last stored SPY
close — no extra API call).

**Expiration cap** (`max-expirations=6`): kept the 6 nearest expirations —
`2026-09-08, 09-09, 09-10, 09-11, 09-14, 09-15` — and excluded the other **16**
(`09-16 … 2027-01-29`). Within those 6 kept expirations + the strike band:
**276** contracts.

**Contract cap** (`max-contracts=10`, ATM-ranked by `|strike − 770.19|`, ties
broken by nearer expiration): kept the 10 nearest — the $770 call and put for
each of the 5 nearest kept expirations (`09-08 … 09-14`) — and excluded the
other **266**, including the $770 call/put for `09-15` (tied on strike, lost
the expiration tie-break) and every further-strike contract.

| Ticker | Type | Strike | Expiry | Selected |
|---|---|---|---|---|
| O:SPY260908C00770000 | call | 770.0 | 2026-09-08 | ✅ |
| O:SPY260908P00770000 | put  | 770.0 | 2026-09-08 | ✅ |
| O:SPY260909C00770000 | call | 770.0 | 2026-09-09 | ✅ |
| O:SPY260909P00770000 | put  | 770.0 | 2026-09-09 | ✅ |
| O:SPY260910C00770000 | call | 770.0 | 2026-09-10 | ✅ |
| O:SPY260910P00770000 | put  | 770.0 | 2026-09-10 | ✅ |
| O:SPY260911C00770000 | call | 770.0 | 2026-09-11 | ✅ |
| O:SPY260911P00770000 | put  | 770.0 | 2026-09-11 | ✅ |
| O:SPY260914C00770000 | call | 770.0 | 2026-09-14 | ✅ |
| O:SPY260914P00770000 | put  | 770.0 | 2026-09-14 | ✅ |
| O:SPY260915C00770000 / P | — | 770.0 | 2026-09-15 | ✗ selection cap (11th/12th nearest) |
| O:SPY260908C00771000 / P + 264 more | — | 771.0+ | various | ✗ selection cap (further from ATM) |

**Never fetched**: every SPY contract outside the ±2% strike band (the
contracts-reference request is itself filtered to the band server-side, so
those were never even returned to Signal Forge), and all 266 excluded-by-cap
contracts inside the band. Historical-aggregates requests were made only for
the 2 newly-selected contracts that weren't already fully covered — never
"every contract."

## Date coverage

| Ticker | Bars this run | Total bars stored | Coverage |
|---|---|---|---|
| `…0908C770000` | 0 (already covered) | 9 | 2026-08-25 → 09-04 |
| `…0908P770000` | 0 (already covered) | 9 | 2026-08-25 → 09-04 |
| `…0909C770000` | 0 (already covered) | 8 | 2026-08-26 → 09-04 |
| `…0909P770000` | 0 (already covered) | 8 | 2026-08-26 → 09-04 |
| `…0910C770000` | 0 (already covered) | 7 | 2026-08-27 → 09-04 |
| `…0910P770000` | 0 (already covered) | 7 | 2026-08-27 → 09-04 |
| `…0911C770000` | 0 (already covered) | 26 | 2026-07-31 → 09-04 |
| `…0911P770000` | 0 (already covered) | 26 | 2026-07-31 → 09-04 |
| **`…0914C770000`** | **5 (new)** | 5 | 2026-08-31 → 09-04 |
| **`…0914P770000`** | **5 (new)** | 5 | 2026-08-31 → 09-04 |

8 of the 10 selected contracts were already fully covered through 2026-09-04
from a prior run (`ingestion_run #2`, 2026-09-07) and were correctly recognized
as complete — not re-fetched. Only the 2 new (Sep-14) contracts hit the API.
`ingestion_run #5` itself reports coverage `2026-08-31 → 2026-09-04` (the range
of *bars this run wrote*; the table's full coverage across all runs is
`2026-07-31 → 2026-09-04`).

## Source and latency, every field

| Field | Source | Latency |
|---|---|---|
| `open/high/low/close/volume/vwap/transactions` | `massive_options` (`/v2/aggs/ticker/O:.../range/1/day/{from}/{to}`) | `HISTORICAL` — settled end-of-day bars, never live/delayed |
| `option_ticker/underlying_symbol/strike/expiration/contract_type` | `massive_options` (`/v3/reference/options/contracts`) | reference data, not time-series |
| `session_date` | derived from the vendor's `t` (epoch ms, UTC midnight) | — |

All 10 rows in the table (`option_aggregate_daily.latency_category`) verified
`HISTORICAL`; `latency_labelled_historical` validation check: **PASS**.

## Bars written / skipped / retried / deferred

| Metric | Count | Detail |
|---|---|---|
| **Written** (this run) | **10** | 5 bars × 2 new Sep-14 contracts |
| **Skipped** (duplicate-key, would-be re-insert) | **0** | no overlap between the new fetch and existing rows |
| **Deferred by selection caps** (never fetched) | **266** | 16 excluded expirations + the ATM-ranked tail beyond 10 contracts, within the kept expirations |
| **Deferred by the total-bar ceiling** (attempt 1 only) | **9 contracts** | attempt 1's 365-day default window made the pre-fetch estimate too conservative for a 500-bar cap; **retried** in attempt 2 with a realistic 45-day window and succeeded |
| **Retried** | **1 underlying (SPY)**, via `--resume 5` | attempt 1 correctly left SPY *not* marked done (a fix from this session's adversarial review) specifically so this retry could recover it |
| **Failed** (adapter/network error) | **0** | |

## Data-quality findings (`validate_option_aggregates`, `massive_options_agg`, run 2026-09-08 03:21:46 UTC)

| Check | Result | Detail |
|---|---|---|
| `chronological_order` | **PASS** | no contract with bars inserted out of date order |
| `no_duplicate_bars` | **PASS** | 110 rows, 110 distinct `(ticker, date)` keys |
| `ohlcv_sanity` | **PASS** | no OHLC-relation or non-positive-price violations |
| `no_post_expiry_bars` | **PASS** | no bar dated after its contract's expiration |
| `sessions_are_trading_days` | **PASS** | every bar falls on an XNYS session |
| `latency_labelled_historical` | **PASS** | no non-`HISTORICAL` label |
| `within_window` | **PASS** | no bar outside the requested window |
| `caps_respected` | **PASS** | 110 total bars ≤ 500-bar ceiling; no per-underlying contract-count breach |

**passed: true**, 0 findings. (Table-wide: 110 bars / 10 contracts total —
includes the 100 bars from the prior run this session started from.)

## Storage used

SQLite `dbstat`, this run's tables only (not the whole 27 MB database, which
also holds 10 years of equities history):

| Table | Rows | Bytes |
|---|---|---|
| `option_aggregate_daily` | 110 | 24,576 (24 KB) |
| `option_contract` | 888 (878 pre-existing chain-snapshot contracts + 10 backfill contracts) | 122,880 (120 KB) |

Well inside the 500-bar / 200,000-bar-default ceilings — this is a deliberately
tiny, bounded run.

## Resumability

Confirmed directly: attempt 1 left `ingestion_run #5` in state `symbols_ok=[]`,
`bars_written=0`, `status="ok"` (no error — a legitimately empty attempt under
tight budget). Attempt 2 passed `--resume 5`, re-entered the *same* run row,
recomputed the contract selection and the per-contract "already covered" check,
skipped the 8 complete contracts without re-fetching, fetched only the 2
incomplete ones, and finished `status="ok"`, `symbols_ok=["SPY"]`. Checkpoints
commit after every contract, so an interrupted run resumes with at most one
contract's progress lost. A third `signalforge options backfill --resume 5`
right now would fetch 0 new bars (SPY is fully covered for this window) — fully
idempotent.

## Safety confirmations

- **No paper option position or trade created**: `paper_trade` and
  `paper_position` tables — **0 rows**. Until today this was true only by code
  inspection (`options_backfill.py` imports only `data.adapters`, `data.calendar`,
  `db.*`, `domain`, `observability` — no `paper`/`alerts`/`llm`/`research.scan`);
  I've now extended import-linter contract **S11** (previously scoped to
  `signalforge.options`, the simulator package only) to also cover
  `signalforge.data.options_backfill`, so this is a build-enforced guarantee
  going forward, not just an observation about the current code.
- **No alert created by this run**: `alert_log` — **0 rows** for this run.
  Options are never an alert source at all — no code path from the backfill to
  an alert, regardless of settings, and S11 (as extended) now fails the build
  if one is ever added.
- **No brokerage interaction**: no brokerage adapter exists anywhere in the
  codebase (import-linter **S1** enforces this architecturally); the only
  network calls this run made were `GET /v3/reference/options/contracts` and
  `GET /v2/aggs/ticker/.../range/1/day/...` against the licensed market-data
  API — read-only reference and historical-price data.
- **No trade recommendation created**: this pipeline never touches
  `Candidate`/`ScanRun` (the recommendation tables) — options are education/
  simulation-only by construction (S11: "options are education/simulation
  only — no alerts, no LLM, no decision path").
- **Kill switch**: inactive (system not halted; this run did not need to be).
- **Discord**: webhook is configured but was not contacted by this run
  (options never route to Discord).

## One caveat found, unrelated to this run

While confirming the above I found the dev database's `alerts_enabled`
app-setting is currently **`True`** (set 2026-09-07 07:48 UTC via a `/settings`
form submission, `changed_by="local-user"` — the app's generic single-user
label, so it doesn't distinguish who submitted it; predates today's work in
this conversation). This is **not** something the options backfill touched or
can touch, but it's a live deviation from your "alerts OFF by default" rule.
`alert_log` still has 0 rows and no stock-research strategy has cleared
validation, so nothing has actually fired — but I'd recommend resetting
`alerts_enabled` to `False`. Say the word and I'll do it; I didn't want to
change system state you didn't ask me to touch in this turn.
