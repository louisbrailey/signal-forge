# W1 — Research-universe expansion: PRE-REGISTRATION

**Status: PRE-REGISTRATION ONLY.** Nothing was ingested, no provider API was
called, and nothing was written to `data/signalforge.sqlite`. Every number below
comes from read-only `SELECT`s against the live database, read-only computation
over those rows, or source files cited by `file:line`. This document exists to be
**written down before** any data is fetched or any backtest is run on the result,
so that the universe cannot be chosen after seeing which symbols help
(STRATEGY_COMPLETION_MAP.md §3(a), last bullet of "Constraints to respect").

Governing documents: `docs/research/STRATEGY_COMPLETION_MAP.md` §0, §1 (R1–R7b),
§2.3, §3(a), §4.0, §4.2, §4.3; `docs/research/STRATEGY_COMPLETION_PLAN.md`
"Rules of engagement".

Machine-readable companion: **`w1_universe_preregistration.json`** (same
directory) — the full 150-symbol list, per-symbol liquidity/rank/list-date, the
reserve list, and every table below as raw numbers.

Claim labelling: **FACT** = verified against a file:line or a query/computation
run for this document. **DERIVED** = arithmetic on FACTs, derivation shown.
**HYPOTHESIS** = an inference a later phase must test. Standard errors accompany
every estimate; **a difference under 2 SE is not evidence.**

---

## 1. What this pre-registers

1. The symbol-selection rule and its frozen cutoff date (§2).
2. The ETF / single-name composition rule (§3).
3. Target **N = 150**, with the statistical-power arithmetic and the cost
   arithmetic that justify it against N = 100 and N = 300 (§4).
4. The `DataSnapshot` key, checked read-only against both auto-generators and
   every existing reusable snapshot (§5).
5. The exact ingestion plan: API-call count, wall clock at the *runtime* pacing
   value, retry/resume behaviour, and the completeness verification that reuses
   gate 8's own `validate_daily` logic (§6).
6. The spread-sensitivity plan at 2× and 5× the modelled spread (§7).
7. The pre-registered expectation that a powered v6 re-run **leaves gates 4 and 7
   failing** (§8) — so that "gate 4 still fails" is not later reported as news.
8. Source-isolation and snapshot-key-shadowing safeguards, plus three additional
   hazards found while writing this (§9).
9. The exact operator approval lines (§10).

This document authorises nothing. §10 is what the operator would have to say.

---

## 2. Symbol-selection rule (pre-registered, frozen)

### 2.1 The rule

> **Rule W1-SEL.** As of the frozen cutoff date **2026-09-08**:
>
> 1. **Base pool** — the `universe_member` rows of `universe_screen_run` **id 3**
>    (`screen_date` 2026-09-08, 420 archived `massive_grouped` sessions,
>    `status = ok`) whose `eligible = 1`, i.e. whose `exclusion_reasons` list is
>    empty.
> 2. **Liquidity statistic** — for each pool member, the **median** of
>    `close × volume` over the **60 most recent `massive_grouped` sessions on or
>    before 2026-09-08** (2026-06-12 → 2026-09-08 inclusive). A symbol must be
>    present in **≥ 57 of those 60 sessions** to be rankable.
> 3. **Composition** — see §3: the 15 snapshot-3 ETFs verbatim, plus the top 135
>    common stocks by the statistic in (2).
> 4. **Listing filter (common stocks only)** — `universe_ticker.list_date ≤
>    2016-10-17`.
> 5. **Ties** — higher median dollar volume wins; exact ties break by ticker
>    ascending. (FACT: no tie occurred.)
> 6. **Frozen** — the resulting 150 tickers are enumerated in
>    `w1_universe_preregistration.json` and in §11 of this document. Changes are
>    permitted **only** through the completeness/replacement rule in §6.4, which
>    is itself pre-registered here and is a data-quality rule, never a
>    performance rule.

### 2.2 Why this base pool

FACT (queried): `universe_screen_run` id 3 (2026-09-09 18:52:52) discovered
13,157 tickers, held 10,746 in scope, and marked **2,181** eligible — **1,599
common stocks (CS) and 582 ETFs**. That is the same run the map cites (§3(a)).

FACT (`universe/screen.py:110-268`): `eligible = 1` already encodes every screen
the project has agreed to apply — `security_type ∈ {CS, ETF}` and `locale = us`
(`config/research.py:154`), active listing, `last_close ≥ $5`
(`research.py:155`), 20-session mean dollar volume `≥ $20M` (`research.py:156-157`),
CS market cap `≥ $2B` **and verified** (`research.py:158-159`; unknown cap never
passes), presence in `≥ 95%` of the 420 archived sessions (`research.py:160-161`),
listing age `≥ 30 days` (`research.py:165`), the spike / zero-volume data-quality
checks (`research.py:163-164`), exclusion of any ticker named in a
`symbol_continuity_mapping` (`screen.py:205-206`), and a 25% cap on any one
2-digit SIC group (`screen.py:231-252`).

Re-using this pool rather than inventing new filters means the expansion adds
**no new selection criterion of my own** beyond the liquidity statistic, the
composition rule and the listing filter, all three of which are stated above and
frozen before any backtest.

FACT (worth stating explicitly): **META is excluded by the base pool** —
`universe_member` for run 3 records `META` with
`exclusion_reasons = ["market_cap_unverified", "corporate_action_continuity"]`.
The expanded universe therefore cannot re-introduce the exact defect that fails
gate 8 on snapshots 1, 2 and 4 (MAP §0.1).

### 2.3 Why a 60-session *median*, not the screen's 20-session mean

FACT (`config/research.py:157`, `screen.py:175-181`): `UniverseMember.avg_dollar_volume`
is the **arithmetic mean** of the last **20** sessions' dollar volume.

Two reasons to compute a different statistic for *ranking*:

- A mean over 20 sessions is dominated by single-day events (index rebalances,
  earnings, an option-expiry Friday). A **median** over 60 sessions is the
  liquidity a strategy can expect on an ordinary day, which is what a spread
  assumption should be anchored to.
- DERIVED (computed read-only): the two statistics disagree materially at the
  top. By 20-session mean, `SPY` ranks above `NVDA`; by 60-session median,
  `MU` (35,744.1 $M) edges `SPY` (33,680.4 $M) and `NVDA` (26,569.2 $M). The
  ranking is not a relabelling of the screen's own number, so it must be stated
  as a distinct, pre-registered rule rather than left implicit.

FACT: the computation reads `ohlcv_daily` rows with `source = 'massive_grouped'`
only. Per R6 this number is used **solely to decide which symbols to backfill**;
it is never cited as evidence of `massive` history, and it never enters a gate.
(MAP §3(a) makes exactly this point; `research/universe.py:45-76`'s
source-blending screen is **not** used here at all.)

### 2.4 Why the listing filter, and what it buys

FACT (computed): without a listing filter, the top-135 CS by the statistic
contains **26 names listed after 2016-10-17**, the earliest `massive` session
already ingested — the most extreme being `SNDK` (`list_date` 2025-02-13, ~19
months of possible history).

Three consequences, all of which the listing filter removes:

1. **Per-symbol IS/OOS misalignment (MAP §4.3).** FACT
   (`backtest_runner.py:29, 158-160`): `_TRAIN_FRAC = 0.6` splits at 60% of *each
   symbol's own* bar count, not a shared calendar date. With a 2025-listed name
   in the universe, that symbol's entire out-of-sample period sits in 2026 while
   `SPY`'s sits in 2022-2026. **With the filter, every member starts on
   2016-10-17 (§6.2), so the 60% boundary lands on the same calendar date for
   every symbol** — the misalignment the map flags as *worsening* under expansion
   is instead *reduced below today's level*. This is the single strongest
   argument for the filter.
2. **Regime breadth.** A symbol with 19 months of history contributes to one
   walk-forward fold (gate 1) and one or two regime buckets (gate 6). It inflates
   nominal `n` without adding independent regime information — precisely the
   effective-sample-size problem MAP §3(a) raises against the iid bootstrap.
3. **IPO-cohort bias.** HYPOTHESIS: the 2020–2021 listing cohort (`PLTR`,
   `SNOW`, `COIN`, `HOOD`, `RKLB`, `IONQ`, `ASTS`, `SOFI`, …) shares a highly
   distinctive return history. Admitting 20+ of them into a 150-name universe is
   a large, unintended factor bet that has nothing to do with any strategy's
   mechanism.

A listing filter is a **stricter** selection, never a weakening (R4). It is
pre-registered here, before results are seen.

DERIVED: the filter drops 26 names from the unfiltered top-135
(`SNDK, PLTR, BE, DELL, GEV, APP, HOOD, IREN, CRWD, CRDO, ALAB, RKLB, VRT, SNOW,
SOFI, UBER, COIN, DDOG, NU, PATH, NET, SPOT, ASTS, DASH, IONQ, CEG`) and pulls in
the next 26 by rank (`PWR, UNP, MELI, CDNS, SNPS, MPC, MDT, CMCSA, CLS, SBUX,
WELL, DE, F, PYPL, CME, SHW, VRTX, LOW, VST, BMY, WDAY, STM, TGT, RCL, MO, TRV`).

**A caveat the filter does not fix.** FACT: `universe_ticker.list_date` is the
*listing* date of the current entity, and it can predate the current ticker.
`NBIS` (Nebius Group) carries `list_date = 2011-05-24` — the former Yandex
listing — and its shares were halted for roughly two and a half years. It passes
the listing filter and is in the pre-registered 150. Its `massive` history will
almost certainly contain a multi-year hole and therefore **fail** gate 8's
`session_completeness` check. That is exactly what the §6.4 completeness rule is
for, and `NBIS` is named here in advance as the most likely drop.

---

## 3. ETF / single-name composition rule (pre-registered)

> **Rule W1-COMP.** The universe is **15 fixed ETFs + 135 common stocks**:
>
> - **ETF anchor (verbatim, not re-ranked):** the fifteen ETFs of dataset
>   snapshot 3 `universe_24_ex_meta` — `DIA, IWM, QQQ, SPY, XLB, XLC, XLE, XLF,
>   XLI, XLK, XLP, XLRE, XLU, XLV, XLY`.
> - **Common stocks:** the top 135 of the base pool by Rule W1-SEL(2), subject to
>   W1-SEL(4).
> - No other instrument type enters. No ETF is added or removed.

### 3.1 Why an anchor set rather than "top 150 by ADV"

MAP §3(a) requires this choice to be made and written down first, because
"top 150 by ADV" on a 1,599-name CS screen is an **all-single-name** universe and
a different distribution shift from "keep the ETFs and add single names".

DERIVED (computed read-only) — a pure top-150-by-median-dollar-volume rule would
**drop six** of the fifteen current ETFs, because their overall ranks are:

| ETF | rank (all eligible) | 60-session median $ volume |
|---|---|---|
| SPY | 2 | 33,680.4 $M |
| QQQ | 4 | 25,483.2 $M |
| IWM | 15 | 5,880.4 $M |
| DIA | 61 | 1,830.6 $M |
| XLF | 63 | 1,764.2 $M |
| XLE | 69 | 1,693.1 $M |
| XLK | 74 | 1,497.6 $M |
| XLV | 76 | 1,471.7 $M |
| XLI | 101 | 1,211.1 $M |
| XLP | 138 | 882.8 $M |
| XLU | 142 | 856.8 $M |
| XLY | 162 | 777.9 $M |
| XLC | 206 | 611.1 $M |
| XLB | 215 | 590.6 $M |
| XLRE | 595 | 213.8 $M |

Dropping `XLY, XLC, XLB, XLRE` (and, at N = 150, `XLP`/`XLU` are marginal) would
silently remove four sector exposures from the research universe as a side effect
of a liquidity rule. That is a design decision masquerading as arithmetic. Fixing
the anchor makes it explicit.

### 3.2 Four reasons the anchor is the right choice

1. **The new snapshot is a strict superset of snapshot 3.** DERIVED (computed):
   all 24 snapshot-3 symbols are in the pre-registered 150 — the nine common
   stocks sit at CS ranks 2 (`NVDA`), 4 (`AAPL`), 6 (`MSFT`), 9 (`AMZN`),
   10 (`GOOGL`), 29 (`JPM`), 36 (`XOM`), 42 (`UNH`), 66 (`HD`), all inside the
   top 135, so the anchor is not doing the work for the single names. A superset
   means the *increment* attributable to the 126 new names is measurable by
   difference. Results are still **not comparable** to snapshot 3 (MAP §3(a):
   "a distribution shift, not a more-powered version of the same experiment") —
   but the decomposition is at least available.
2. **The ETF share falls 62.5% → 10%.** FACT (MAP §3(a)): 15 of snapshot 3's 24
   symbols are ETFs, several of which contain the others, which is why "every CI
   in this document is too narrow". Holding the ETF count fixed while tripling
   the single-name count is the composition that most reduces that dependence per
   API call spent. It does not eliminate it: `SPY`, `QQQ` and `XLK` still contain
   many of the 135, and `GOOG`/`GOOGL` are two share classes of one company in
   the list.
3. **Zero API cost.** The fifteen ETFs already have `massive` history (FACT:
   queried — 2,487 bars each from 2016-10-17, except `XLC` at 2,067 bars from
   2018-06-19).
4. **They are the cheapest names to trade.** Broad ETFs quote the tightest
   spreads of anything in the pool, which partially offsets §7's cost penalty.

### 3.3 Sector composition of the 135 (disclosed, not steered)

DERIVED (2-digit SIC group counts among the 135 CS; the screen's own 25% cap
already applied at pool level): `36` electronics 19, `73` business services 18,
`35` industrial/computer equipment 14, `28` chemicals/pharma 12, `38`
instruments 9, then a long tail. **Maximum single-group share 14.1%**, well
inside the screen's 25% ceiling. No sector rebalancing is applied on top; the
concentration is reported so it cannot later be discovered and presented as a
finding.

---

## 4. Target N — the arithmetic, and the recommendation

### 4.1 Inputs (all from MAP §0.3, §0.4, §3(a))

FACT (MAP §0.3): `volatility_breakout.short_swing` v0.1.0 (version 6) has
**OOS n = 51**, **OOS expectancy +0.0613R**, implied **per-trade sd = 1.554**,
**SE(OOS) = 0.2176R**. Gate 4 requires `exp > 0.02 + 1.96·sd/√n`.

FACT (MAP §0.3 / §2.3): today's gate-5 grid has cells as thin as **n ≈ 19**
against a floor of 15 (`sensitivity_min_grid_trades = 15`,
`config/research.py:106`), and gate 1 reuses the same constant
(`promotion.py:632`). v6's sealed test has **n = 10** and **SE = 0.491R**.

Breadth assumption: for a fixed per-symbol signal rate, trade count scales with
symbol count.

### 4.2 The three candidates, side by side

DERIVED (all figures computed for this document; `n` projected as
`51 × N / 24`, half-width as `1.96 × 1.554 / √n`):

| | **N = 100** | **N = 150** | **N = 300** |
|---|---|---|---|
| new symbols to ingest | 76 | **126** | 276 |
| paced API minutes (12.1 s) | 15.3 | **25.4** | 55.7 |
| deepest common stock, median $ vol | 887.3 $M (`GILD`, CS rank 85) | **598.2 $M (`TRV`, CS rank 135)** | 319.5 $M (`TRGP`, CS rank 285) |
| v6 projected OOS `n` | 212 | **319** | 638 |
| gate-4 CI half-width | ±0.2092 | **±0.1705** | ±0.1206 |
| gate-4 required expectancy | +0.2292R | **+0.1905R** | +0.1406R |
| … as a multiple of the observed +0.0613R | **3.74×** | **3.11×** | **2.29×** |
| **gate 4 verdict at the observed point estimate** | **FAIL** | **FAIL** | **FAIL** |
| gate-5 thinnest cell (from n ≈ 19) | 79 | 119 | 238 |
| gate-2 floor (30) | cleared | cleared | cleared |
| v6 projected sealed `n` / SE | 42 / 0.240R | **62 / 0.197R** | 125 / 0.139R |

DERIVED: the `n` at which gate 4 would clear **at the observed point estimate**
is `(1.96 × 1.554 / (0.0613 − 0.02))² = 5,439` OOS trades — the map's 5,428, to
rounding. At v6's per-symbol rate that is **≈ 2,560 symbols**, i.e. the entire
2,181-name eligible pool and then some, ≈ 4.5 hours of paced API calls, and it
would still be wrong because the bootstrap assumes iid trades (MAP §3(a)).

**Gate 4 therefore does not discriminate between 100, 150 and 300.** It fails at
all three. Saying so *before* the run is the point of §8.

### 4.3 The breadth multiplier is itself uncertain — and it argues for more, not less

HYPOTHESIS (new, stated for falsification): v6's signals may be
ETF-concentrated. FACT (MAP §2.3, quoting
`reports/volatility_breakout.short_swing-0.1.0.md`): in the committed 2-year
report `SPY` alone produced **8 of 40** trades while `AAPL, HD, XLF, XLP, XLU`
produced zero. If ETFs fire at rate `k ×` the common-stock rate, the breadth
multiplier is `(15k + 135)/(15k + 9)`, not `150/24`:

DERIVED:

| ETF:CS signal-rate ratio `k` | breadth multiplier | v6 OOS `n` | gate-4 half-width | required expectancy |
|---|---|---|---|---|
| 1 (uniform — the map's assumption) | 6.25× | 319 | ±0.1705 | +0.1905R |
| 2 | 4.23× | 216 | ±0.2072 | +0.2272R |
| 3 | 3.33× | 170 | ±0.2336 | +0.2536R |
| 4 | 2.83× | 144 | ±0.2538 | +0.2738R |

Two conclusions. (i) The map's 6.25× is an **upper bound on the upper bound** —
MAP §3(a) already calls √6.25 an upper bound on account of trade correlation;
this adds a second, independent reason it is optimistic. (ii) Because the
multiplier may be as low as ~3×, N = 100 is genuinely at risk of leaving gate 5's
per-cell floor uncomfortable (79 → as low as ~40 under `k = 3`), whereas N = 150
keeps it comfortable across the whole range.

### 4.4 The cost penalty, and why it is milder here than MAP §0.4 feared

MAP §0.4 warns that "names ranked 25–150 by ADV plausibly quote wider than the
5 bps flat assumption" and that the resulting cost increment "for v6 is larger
than its whole point estimate".

DERIVED (computed read-only) — the liquidity floor of the pre-registered
universe:

- **Least liquid member overall: `XLRE`, 213.8 $M/day median — and it is already
  in snapshot 3 today.**
- Least liquid *new* name: `TRV`, **598.2 $M/day** median — **2.8× more liquid
  than the least liquid symbol the approved dataset already contains.**
- At N = 300 the deepest common stock is still 319.5 $M/day (`TRGP`), also above
  `XLRE`.

So on this evidence the expansion **adds no name less liquid than something
already in the approved dataset**, and the flat-5-bps assumption is no more wrong
for the 126 new names than it already is for `XLRE`, `XLB` and `XLC`.

That weakens the cost objection but does **not** remove it, for three reasons:
(a) dollar volume is not spread — a $600M/day single name can quote wider than a
$214M/day ETF, because ETF spreads are held tight by creation/redemption
arbitrage; the project holds **no spread data at all** (FACT:
`universe/screen.py:47` flags every screened symbol
`spread_filter_not_licensed`); (b) 126 single names bring earnings gaps and
idiosyncratic overnight risk that 15 sector ETFs do not; (c) the cost model does
not adapt (§7). Hence §7's sensitivity is **mandatory**, not optional, exactly as
MAP §4.2 item 8 requires.

### 4.5 Recommendation: **N = 150**

The reasoning, in order of weight:

1. **Nothing decides this on gate 4** (§4.2), so the choice must be made on the
   gates that breadth *can* move (5, 6, and gate 9's sealed power) and on cost,
   time and honesty about the distribution shift.
2. **N = 100 is not clearly enough** once the breadth multiplier is treated as
   uncertain (§4.3). N = 150 keeps every counting floor comfortable across
   `k ∈ [1, 4]`.
3. **N = 300 buys a √2 = 1.41× CI shrink and flips no gate.** It changes the
   gate-4 required expectancy from +0.191R to +0.141R, still 2.3× the observed
   +0.0613R. It costs 2.2× the API calls (276 vs 126), 2.2× the wall clock
   (55.7 vs 25.4 paced minutes) and doubles the depth of the distribution shift.
   Under R5's "prefer few, mechanism-motivated" discipline, spending that for no
   gate flip is not justified.
4. **150 is the ceiling the project has already adopted.** FACT:
   `UniverseFilters.max_universe_size = 150` (`config/research.py:139`). Choosing
   150 introduces no new number into the program. (It gates only
   `research/universe.py:screen_universe`'s display — MAP §3(a) — so this is a
   consistency argument, not a constraint.)
5. **The listing filter's alignment benefit (§2.4.1) is worth more than 150
   extra correlated large-caps.**

**Honest statement of what N = 150 buys:** it fixes gate 2's margin, comfortably
fixes gate 5's per-cell floor, gives gate 6's bear bucket ~6× more chances to be
non-zero, and cuts v6's sealed-test SE from 0.491R to ~0.197R. It does **not**
fix gate 4 and does **not** address gate 7. See §8.

---

## 5. DataSnapshot key

> **Pre-registered key:** `research_150_massive_10y_2026-09-08`

FACT (`db/models/research.py:237`): `DataSnapshot.key` is `String(64)`; this key
is 35 characters.

**Collision check against both auto-generators** (MAP §3(a) requires this as a
standing rule, not a one-off):

| Generator | Pattern | Can it produce this key? |
|---|---|---|
| `get_or_create_dataset_snapshot` unkeyed mint (`promotion.py:339`) | `universe_auto_{n}sym_{10-hex fingerprint}` | **No** — fixed `universe_auto_` prefix |
| `run_screen` (`universe/screen.py:259`) | `liquid_us_{ISO date}_{8-hex digest}` | **No** — fixed `liquid_us_` prefix |

**Collision check against existing rows** (FACT, queried read-only):
`select count(*) from data_snapshot where key like 'research!_%' escape '!'` → **0**.
No row with this key exists. The ten existing keys are ids 1–10 as tabulated in
MAP §3(a) and re-verified for this document.

**Shadowing check** (MAP §3(a) step 1; FACT, queried): the reusable snapshots are
ids 2 (25 symbols), 3 (24), 4 (25), 6 (2,551), 8 (2,312), 10 (2,181). **None has
150 symbols**, so no existing reusable row can absorb an unkeyed call on the new
set. FACT: the live scan universe is 25 symbols
(`get_settings().research.universe`), so `research/scan.py:165`'s unkeyed mint
cannot collide with the new set either — today. That is a snapshot of today's
state, not a guarantee: §9.2 makes the check a standing rule.

Description and `source_note` to store with the row (pre-registered wording):

- `description`: *"150-symbol research universe pre-registered in
  docs/research/diagnostics/w1_universe_preregistration.md (cutoff 2026-09-08):
  the 15 ETFs of universe_24_ex_meta verbatim plus the top 135 U.S. common stocks
  by 60-session median dollar volume over 2026-06-12..2026-09-08 among the
  eligible members of universe_screen_run 3, restricted to list_date <=
  2016-10-17. Selection frozen before any backtest. Split-adjusted AS OF the
  fetch date, NOT point-in-time; discovery was active-only, so the set is
  survivorship-biased."*
- `source_note`: `massive daily; END_OF_DAY; per-symbol history 2016-10-17..`

The row must be created with **`key=` passed explicitly** and must be the value
of the `dataset_snapshot=` argument to every `evaluate_promotion` call that uses
it (§9.2 explains why this is not optional and why the CLI cannot do it today).

---

## 6. Ingestion plan

### 6.1 Scope

DERIVED: 150 symbols − 24 already ingested under `massive` = **126 symbols to
backfill**. (FACT, queried: the `massive` source currently holds 26 instruments —
the 24 of snapshot 3 plus `META` and `FB` — with 2,487 bars each from 2016-10-17,
except `XLC` 2,067 from 2018-06-19, `META` 1,214 and `FB` 1,446.)

### 6.2 The command

```
signalforge data ingest-history \
  --since 2016-10-17 \
  --symbols "<the 126 new tickers, comma-separated>"
```

FACT (`cli.py:92-141`): this resolves the primary adapter from
`market_data_provider` (FACT: runtime value **`massive`**), calls
`ingest_daily_history` (`data/ingest.py:355`) inside `session_scope(write=True)`,
and records one `IngestionRun` row. Every bar is written with
`source = adapter.provider_name = "massive"` (`ingest.py:240`), which is what R6
and gate 8 require.

`--since 2016-10-17` is pre-registered rather than letting
`discover_history_depth` probe, for the reason in §2.4.1: a common start date
makes `_TRAIN_FRAC`'s 60% boundary land on the same calendar date for every
symbol.

**Why `ingest_daily_history` and not `ingest_universe`.** Both exist and both
reach the same `ingest_symbol` inner loop, so the API cost, pacing and
per-symbol-commit behaviour of §6.3–§6.4 are identical either way. FACT
(`ingest.py:296-317`): `ingest_universe` is the plain loop — it returns an
in-memory `IngestReport` and writes **no** `IngestionRun` row, so a 126-symbol
backfill would leave no durable record of what was requested, what succeeded and
what failed. FACT (`ingest.py:355-372, 404-430`): `ingest_daily_history` wraps
the same loop and additionally persists an `IngestionRun` carrying the requested
window, discovered earliest date, actual coverage, per-symbol gaps and failures,
and it supports `resume_run_id`. **The resume and audit-trail behaviour
pre-registered in §6.4 is only available through `ingest_daily_history`**, which
is why it is the pre-registered entry point; `ingest_universe` is named here only
to record that it was considered and rejected.

### 6.3 API-call count, pacing and wall clock

FACT (`data/adapters/massive.py:164-210`): `fetch_daily_bars` issues **exactly one**
`GET /v2/aggs/ticker/{SYM}/range/1/day/{start}/{stop}?adjusted=true&sort=asc&limit=50000`
per symbol for the whole range. ~2,490 daily bars is ~5% of the 50,000 cap, so no
pagination is expected (a `next_url` in the response is treated as an error).

FACT (`massive.py:225-231`): `fetch_corporate_actions` and `fetch_earnings` both
`return ()` without a request. So `ingest_symbol` makes **1 API call per symbol,
not 3**.

FACT (resolving MAP §3(a)'s open item — "confirm the *runtime* value of
`settings.market_data_min_request_spacing_s` before scheduling"): the runtime
value is **12.1 s**. Verified two ways: no `MARKET_DATA_MIN_REQUEST_SPACING_S`
key exists in `.env` (checked by listing key names only, no values read) or in
the process environment, and `get_settings().market_data_min_request_spacing_s`
evaluates to `12.1` — the class default at `config/settings.py:53`.

DERIVED: **126 successful calls.** The first is unpaced (the adapter's
`_last_request` starts at 0), so **125 × 12.1 s = 1,512.5 s ≈ 25.2 minutes** of
enforced spacing. HTTP latency is absorbed inside the spacing window
(`massive.py:125` stamps `_last_request` *before* the request), and the
per-symbol `session.commit()` is milliseconds. **Budget 35 minutes** to cover
retries.

Worst case, stated for completeness: FACT (`massive.py:44`) `_MAX_ATTEMPTS = 5`,
so the hard ceiling is 630 requests if every symbol needed all five attempts.
That will not happen; the number to approve is **126, budget ≤ 140**.

### 6.4 Retry, resume and the completeness rule

**Retry (FACT, `massive.py:109-158`).** Up to 5 attempts per request. Retried on
`{429, 500, 502, 503, 504}` and on any `httpx.HTTPError`. Backoff is
`min(30.0, 1.5 × 2^(attempt−1))` seconds, or the server's `Retry-After` when it
sends a numeric one. Exhausting attempts raises `AdapterError`, which
`ingest_symbol` catches (`ingest.py:185-198`): it records the failure in
`data_feed_status`, returns a `SymbolIngestResult` with `error` set, and the run
**continues to the next symbol**. One bad ticker does not abort the backfill.

**Resume (FACT, `ingest.py:404-430`).** `ingest_daily_history` commits after
every symbol and keeps `symbols_ok` / `symbols_failed` on the `IngestionRun` row.
`signalforge data ingest-history --resume <run_id>` skips symbols already in
`symbols_ok`. Re-running the same command without `--resume` is idempotent for
bars: `ingest_symbol` pre-reads the existing `(instrument, date, source)` set and
counts repeats as `bars_skipped` (`ingest.py:211-224`). The run's final `status`
is `ok` / `partial` / `failed`.

**Concurrency (FACT, `ingest.py:171-186, 296-307`).** The network fetch happens
*before* the write transaction and the loop commits once per symbol, so the
SQLite write lock is never held across a 12.1 s paced wait. This is what makes it
safe to run while the paper worker holds its own connection — the design is
documented in `docs/SQLITE_CONCURRENCY.md` and is the same path that built the
existing 26 symbols. It is still a write to the live database and needs the
operator's explicit go-ahead (§10).

> **Rule W1-COMPLETE (pre-registered).** After the backfill, run
> `validate_daily(session, <the 150 symbols>, source="massive", persist=False)`
> in-process — read-only, `persist=False`, the *same function* gate 8 calls
> (`promotion.py:808`). A candidate is **dropped** from the snapshot if and only
> if:
> (a) it has **no** `massive` rows at all — i.e. it appears in
> `symbol_coverage`'s `missing:` list (`validate.py:86-99`); or
> (b) it appears in the `session_completeness` detail — more than **2.0%** of the
> XNYS sessions between its own first and last `massive` bar are absent
> (`validate.py:63, 147-161`); or
> (c) its first `massive` bar is later than **2018-09-08**, i.e. the provider
> delivered under ~8 years despite a pre-2016 `list_date` — the ticker-change /
> relisting signature described in §2.4 (`NBIS` is the named candidate).
> Each drop is replaced by the next symbol in the **pre-registered reserve list**
> (§11.3, CS ranks 136–160 of the filtered pool, in strict rank order), which is
> itself ingested and must pass the same test. Drops, reasons and replacements
> are recorded **before any backtest is run**. No symbol is ever dropped or
> retained on the basis of a backtest result.

**Why the whole `validate_daily` result matters, not just completeness.** FACT
(`validate.py:66-224`) gate 8 fails if *any* check fails, and three of them are
**source-wide, not per-symbol**: `db_unique_bars` scans every
`(instrument, date, source='massive')` group, and `chronological_order` /
`no_duplicate_sessions` run over all listed symbols. A single duplicated bar
anywhere in the `massive` source fails gate 8 for the entire snapshot.

**One check is a no-op for this source, and that must be disclosed.** FACT
(`massive.py:212`): `DailyBar(..., adj_close=c)` — the adapter sets `adj_close`
equal to `close`, so `validate.py:180-205`'s `adjustment_behaviour` check sees a
constant ratio of exactly 1.0, zero jumps, and always passes. It is not evidence
that the data is correctly back-adjusted. The bars are **split-adjusted as of the
fetch date, not point-in-time** — the same known bias the existing 24 carry, now
carried by 150.

### 6.5 Registering the snapshot

Only after W1-COMPLETE passes:

```python
get_or_create_dataset_snapshot(
    session,
    key="research_150_massive_10y_2026-09-08",
    symbols=<final list>,
    description=<§5 wording>,
    source_note="massive daily; END_OF_DAY; per-symbol history 2016-10-17..",
)
```

FACT (`promotion.py:310-329`): passing the key makes the row immutable-by-contract
— a later keyed call with a different symbol set raises `ValueError` instead of
silently reusing it. If W1-COMPLETE forces a drop **after** the row is created,
the correct action is a **new key** (`…_2026-09-08_r2`), never an edit.

---

## 7. Spread-sensitivity plan (2× and 5×)

### 7.1 The mechanism, and that it needs no code change

FACT (`backtest/engine.py:84-94`):

```
run_backtest(series, signal_fn, *, cost_model=None, spread_bps=5.0, warmup=50)
slip = (cm.slippage_bps + (spread_bps / 2 if cm.half_spread_fill_penalty else 0.0)) / 10_000
```

FACT: `slip` is the **only** channel through which cost enters a trade —
`CostModel.spread_cost` / `total_entry_cost` are never called by `run_backtest`.
FACT (`engine.py:143`): the recorded `costs_bps = slip × 2 × 10_000`, i.e. the
round trip.

FACT (MAP §0.4, re-verified): `backtest_runner.py:205-206` calls `run_backtest`
**without** `spread_bps`, so every symbol is charged the flat 5.0 bps default and
the spread term is universe-independent.

Because `slippage_bps` and `spread_bps/2` are summed into one number, a spread
sensitivity is obtainable **with no change to any file under `src/`** by passing a
`CostModel` with a raised `slippage_bps` to
`run_strategy_over_universe(..., cost_model=…)` — which FACT (MAP §4.0) contains
no `session.add`/`flush`/`commit` and is therefore read-only:

| Scenario | equivalent quoted spread | `CostModel.slippage_bps` to pass | slip / side | **round trip** |
|---|---|---|---|---|
| baseline (frozen, what the gates use) | 5 bps | 3.0 | 5.5 bps | **11.0 bps** |
| **2× the modelled spread** | 10 bps | **5.5** | 8.0 bps | **16.0 bps** |
| **5× the modelled spread** | 25 bps | **13.0** | 15.5 bps | **31.0 bps** |
| MAP §0.4 named case | 20 bps | 10.5 | 13.0 bps | 26.0 bps |
| MAP §0.4 named case | 60 bps | 30.5 | 33.0 bps | 66.0 bps |

**A documentation inconsistency in the map, flagged not resolved.** MAP §3(a)
asks for "a sensitivity at **2× and 5× the modelled spread** (26 bps and 66 bps
round trip)". But §0.4 states 26 bps corresponds to a **20 bps** quoted spread and
66 bps to a **60 bps** quoted spread — which against the modelled 5 bps are **4×
and 12×**, not 2× and 5×. The two readings cannot both be right. This
pre-registration therefore commits to reporting **all four** non-baseline points
(16, 26, 31, 66 bps round trip), so the requirement is satisfied under either
reading and no later reader has to guess which was meant. **The operator should
correct §0.4/§3(a) to one convention.**

### 7.2 Cost in R at each point

DERIVED, using MAP §0.4's formula `cost_R = round_trip_bps / 10,000 ÷ (stop_atr ×
ATR/price)` and its reference `ATR/price` of 2% (1.5% for `volatility_breakout`,
whose `contraction_max ≤ 0.75` filter selects a contracted ATR by construction).
The 11, 26 and 66 bps columns reproduce MAP §0.4 exactly, which is the check that
this arithmetic is the same arithmetic:

| Strategy | `stop_atr` | risk/price | **11 bps** | **16 bps (2×)** | 26 bps | **31 bps (5×)** | 66 bps |
|---|---|---|---|---|---|---|---|
| `trend_continuation.*` | 1.50 | 3.00% | 0.037R | 0.053R | 0.087R | 0.103R | 0.220R |
| `mean_reversion.short` | 2.00 | 4.00% | 0.028R | 0.040R | 0.065R | 0.078R | 0.165R |
| `relative_strength.med` | 2.50 | 5.00% | 0.022R | 0.032R | 0.052R | 0.062R | 0.132R |
| **`volatility_breakout`** | 1.75 | 2.63% | **0.042R** | **0.061R** | **0.099R** | **0.118R** | **0.251R** |

### 7.3 What it does to v6's edge — pre-registered before the run

DERIVED. Re-pricing shifts every trade by the same amount, so
`adjusted expectancy ≈ 0.0613R − (cost_R at the new level − 0.0419R)`:

| round trip | v6 OOS expectancy, re-priced |
|---|---|
| 11.0 bps (baseline) | **+0.0613R** |
| 16.0 bps (2×) | **+0.0423R** |
| 26.0 bps | **+0.0042R** |
| 31.0 bps (5×) | **−0.0149R** |
| 66.0 bps | **−0.1482R** |

**Pre-registered reading of this table.** At 31 bps round trip — a 25 bps quoted
spread, which is *above* `UniverseFilters.max_avg_spread_bps = 20.0`
(`config/research.py:135`), the spread the project's own live scan filter is
willing to tolerate — v6's entire out-of-sample edge is gone and gate 3 fails on
sign alone. At 26 bps (a 20 bps quoted spread, exactly the config ceiling) the
edge is +0.004R, indistinguishable from zero.

**A statistical caveat that cuts the other way.** This re-pricing is a
*deterministic accounting shift applied identically to every trade*, not a
sampled comparison, so the "under 2 SE is not evidence" rule does not apply to it
in the usual way — the shift is exact given the assumption. What is uncertain is
the **assumption** (the true spread), not the arithmetic. For scale: at the
projected n = 319, SE(v6 OOS) = 1.554/√319 = **0.087R**, so the 11→26 bps shift
of 0.057R is 0.66 SE and the 11→31 bps shift of 0.076R is 0.87 SE.

### 7.4 Reporting requirement

Every result reported on this snapshot carries the baseline number **and** the
four re-priced numbers, in one table, with the `slippage_bps` used stated
explicitly. **The gates themselves always run on the frozen cost model** —
`CostModel(slippage_bps=3.0, half_spread_fill_penalty=True)`,
`backtest/costs.py:13-16`, unchanged per R4. The sensitivity is a reported
diagnostic alongside the gate result, which MAP §1 R4 explicitly permits
("adding a stricter reported statistic is never a weakening").

---

## 8. Pre-registered expectations for a powered v6 re-run

Written **before** the data exists, so that none of these can later be presented
as a discovery. Confidence words are used deliberately.

| Gate | Trade set | Pre-registered expectation | Basis |
|---|---|---|---|
| 1 walk-forward | all pre-sealed | **PASS**, unchanged | passes today at 211 trades; more symbols only helps the per-fold floor of 15 |
| 2 min OOS trades | OOS | **PASS**, comfortably (51 → ~170–319) | §4.3 |
| 3 net expectancy | OOS | **PASS at baseline cost; expected to FAIL at 31 bps round trip** | §7.3 |
| **4 bootstrap CI** | OOS | **FAIL — predicted with high confidence** | required +0.1905R at n = 319 vs observed +0.0613R (§4.2); needs n ≈ 5,439 ≈ 2,560 symbols |
| 5 sensitivity | OOS per cell | **genuinely uncertain — no prediction offered** | cell counts stop being the binding issue (19 → ~119), but v6 passes at *exactly* 0.750 on snapshot 3 and already **fails at 0.556/0.500 on snapshot 4** (MAP §2.3). A different universe can flip it either way |
| 6 regime coverage | all pre-sealed | **plausibly fixed; must be measured** | bear bucket is 0 today. 6× more chances helps only if the true bear rate is non-zero, not if the rule structurally never fires in bear regimes (H12). **The unbucketed count must be reported alongside** — 14 today, 6.6% (MAP §0.6) |
| **7 benchmark Sharpe** | all pre-sealed | **FAIL expected; no directional prediction** | breadth does not move a risk-adjusted point estimate (MAP §3(a)); 0.666 vs SPY 0.719 today. Composition change could move it either way, so this is an expectation, not a forecast |
| 8 data/leakage | — | **PASS, conditional on W1-COMPLETE** (§6.4) | `NBIS`-style relistings are the named risk |
| 9 sealed | sealed year | **new sealed test; ~62 trades, SE ≈ 0.197R** | still weak: at that SE, gate 9 would reject a genuinely +0.30R strategy ~6% of the time and a genuinely +0.06R strategy ~38% of the time |

> **The headline pre-registration, stated plainly:** *a powered v6 re-run on the
> 150-symbol snapshot is expected to leave gates 4 and 7 failing.* If that is what
> happens, it is **confirmation of a prediction, not new information**, and no
> strategy change may be motivated by it. If gate 4 unexpectedly passes, the
> honest report is that the point estimate moved by ~3×, which would itself demand
> an explanation (composition shift, not more data).

**Which snapshot the v6 report leads with, pre-registered per R1.** Snapshot 3
`universe_24_ex_meta` remains the headline for v0.1.0 comparisons, because it is
the only snapshot on which gate 8 passes (MAP §0.1). The expanded snapshot is
reported as a **separate experiment**, never as an update to snapshot-3 numbers,
with the §0.1 four-draw table reproduced alongside.

### 8.1 Sealed-look accounting (R2)

FACT (MAP §0.1): the baseline count is **k = 5 per strategy** — four locked
sealed tests (one per existing snapshot) plus the pre-registered fifth look a
v0.2.0 on snapshot 3 would represent.

FACT (`db/models/research.py:263`): `StrategySealedTest` is unique per
`(strategy_version_id, dataset_snapshot_id)`, so evaluating **even an unchanged
v0.1.0** against the new snapshot creates a fresh sealed test — a genuine
additional look at the same calendar year through a different universe.

> **Pre-registered restriction, tighter than MAP §3(a)'s "every version goes to
> k = 6".** Only the versions that need the expanded universe are evaluated on it:
>
> | Version | Evaluate on the new snapshot? | Resulting k | Why |
> |---|---|---|---|
> | 6 `volatility_breakout.short_swing` | **yes** | 5 → **6** | W1 exists for it (MAP §4.1) |
> | 4 `mean_reversion.short_swing` | **yes, when its universe/power proposal is run** | 5 → **6** | its breadth-conditioning angle requires W1 (MAP §4.1) |
> | 3 `trend_continuation.medium_swing` | **no** | stays 5 | MAP §4.1 drops the universe angle for v3 |
> | 2 `trend_continuation.short_swing` | **NO — prohibited** | stays 5 | PAPER_APPROVED and live-scoped (§9.4) |
> | 5 `relative_strength.medium_swing` | **NO — prohibited** | stays 5 | PAPER_APPROVED and live-scoped (§9.4) |
>
> Building the snapshot **once**, with the rule frozen in this document, is the
> whole reason the cost is 1 look and not several.

---

## 9. Safeguards (MAP §4.3), and three hazards found while writing this

### 9.1 Source isolation (R6) — and a new, sharper version of the hazard

FACT (`data/repository.py:17-27, 47-65`): `_source_clause(None)` **applies no
filter at all**. FACT (queried): every one of the 150 symbols already has
`massive_grouped` rows for 2025-01-03 → 2026-09-08 — including `SPY` and `AAPL`
today.

> **Consequence, stated as sharply as it deserves: a research call on this
> snapshot that omits `source="massive"` silently loads BOTH sources, producing
> two bars for every session between 2025-01-03 and 2026-09-08 — i.e. duplicated
> bars sitting exactly inside the sealed window.** Every
> `evaluate_promotion` / `run_strategy_over_universe` / `PriceSeries.load` call
> against this snapshot **must** pass `source="massive"` explicitly, never a
> sequence, never `None`.

Mitigating FACTs: `cli.py:1339` sets `eval_source = get_settings().market_data_provider`
(= `"massive"`) for the CLI path, and this dual-source condition already exists
harmlessly today for the 24 approved symbols — gate 8 passes because
`validate_daily` is called with an explicit `source` (`promotion.py:808`). So the
expansion does not create the hazard; it multiplies the number of symbols exposed
to it from 24 to 150.

Also standing (MAP §0.1, R6): a symbol whose bars carry a non-`massive` source
fails gate 8 outright, as `META_CONT` does on snapshot 4. Everything in this
universe is ingested by `MassiveAdapter` and tagged `massive` (`ingest.py:240`);
nothing bridged, derived or continuity-mapped enters — and the base pool
already excludes continuity-mapped tickers (§2.2).

### 9.2 Snapshot-key shadowing — and the hazard that the CLI cannot target this snapshot

Standing rules (MAP §3(a), §4.3), all satisfied in §5: always pass the key
explicitly; verify the key against both auto-generators; check the symbol set
against every reusable snapshot first.

**New hazard (FACT, `cli.py:1330-1386`).** `signalforge evaluate-promotion`
resolves its snapshot in exactly two ways: `--dataset` maps through
`fb_meta_universe_comparison.resolve_variant`, which only knows
`baseline` / `ex_meta` / `meta_continuity_corrected` and builds them from
`cfg.universe`; or `--symbols`, in which case `snap` stays `None` and
`evaluate_promotion` falls through to `get_or_create_dataset_snapshot(session,
symbols=symbols)` **unkeyed** (`promotion.py:504-505`).

> **So `signalforge evaluate-promotion --symbols <the 150>` would mint
> `universe_auto_150sym_<fingerprint>` and would NOT use
> `research_150_massive_10y_2026-09-08`** — splitting the audit trail across two
> snapshot ids for the same universe, which is precisely the failure MAP §3(a)
> step 2 warns about, and creating the sealed tests against the wrong row.

Two acceptable resolutions; the operator picks one:

- **(A) In-process script (recommended, no `src/` change).** A small research
  script resolves the keyed snapshot and calls
  `evaluate_promotion(session, strat, symbols=…, source="massive",
  dataset_snapshot=<the keyed row>, …)` directly.
- **(B) Add a `--dataset-key` option to the CLI.** A promotion-path edit that
  makes an existing capability reachable without making any gate easier to pass —
  R4-permissible on the same reasoning as MAP §1's carve-outs — but it is a
  `src/` change and needs its own review.

Either way, a **pre-integration assertion** is required: after the run, confirm
`StrategyPromotionEvaluation.dataset_snapshot_id` equals the id of the keyed row,
and that no `universe_auto_150sym_*` row was created.

### 9.3 Sealed-test staleness (R3)

FACT (MAP §1 R3, `persistence.py:46-93`): editing strategy code without bumping
`VERSION` refreshes `spec_json`/`git_sha` on the same `StrategyVersion` row while
gate 9 replays the sealed result measured against the *old* code. Any v0.2.0
built on this snapshot ships as `VERSION = "0.2.0"`, and the pre-integration
check is that each v0.2.0's `StrategySealedTest.strategy_version_id` names a row
created by that run. Nothing in W1 itself bumps a version — W1 is data only.

### 9.4 The two live strategies must not be evaluated on this snapshot

FACT (MAP §1 R7b, `paper_probation.py:113-122`, `approval_scope.py:45-66`): the
probation dashboard selects which sealed test to display via
`scopes[0].dataset_snapshot_id`, and `approved_scopes` issues its `select` with
**no `order_by`**. It is deterministic today only because v2 and v5 each have
exactly two passing evaluations and **both are on snapshot 3**.

> A passing evaluation of v2 or v5 on the expanded snapshot would create a
> passing scope on a *different* snapshot and make `scopes[0]` order-dependent —
> changing what a **live** probation surface displays, as a side effect of a
> research action. **Prohibited.** v2 and v5 are not evaluated on
> `research_150_massive_10y_2026-09-08`, and this is why §8.1's per-version table
> exists.

Relatedly (MAP §4.3): `universe` is not compared in
`approval_scope.scan_scope_matches` (`approval_scope.py:88-93`), so an expanded
snapshot must never become live-scoped without that gap being addressed first.
W1 does **not** change `cfg.research.universe` or any approved scope.

### 9.5 Diagnostics that must accompany any result on this snapshot

- **Clustered / block bootstrap alongside the gate-4 iid CI**, with the ratio of
  the two half-widths reported as the effective-sample-size haircut (MAP §3(a);
  a reported diagnostic, permitted under R4). This matters *more* here, not less:
  the ETF share drops but `SPY`/`QQQ`/`XLK` still contain many of the 135, and
  `GOOG`/`GOOGL` are one company twice.
- **Gate 6's unbucketed trade count**, not just the three buckets (MAP §0.6).
- **Per-symbol IS/OOS boundary dates**, to demonstrate the alignment claim of
  §2.4.1 rather than assert it.
- **The variant count under R5.** W1 itself costs **zero** strategy variants: no
  rule, parameter or threshold changes.

---

## 10. Operator approval

Two separate approvals. The first is data only and creates no sealed test. The
second is irreversible in the sense that matters — sealed tests are locked
forever per `(version, snapshot)`.

### 10.1 Approval line 1 — the backfill (data only)

> **"Approved: run the W1 backfill. 126 paced GET requests to the Massive daily
> aggregates endpoint (one per new symbol,
> `/v2/aggs/ticker/{SYM}/range/1/day/2016-10-17/{today}`), approximately 26
> minutes of wall clock at the configured 12.1-second spacing — budget 35 minutes
> and up to 140 requests to cover retries. It writes `massive`-sourced
> `ohlcv_daily` rows, `instrument` rows, `raw_payload_cache` entries,
> `data_feed_status` updates and one `ingestion_run` row to
> `data/signalforge.sqlite` while the paper worker keeps running (one short write
> transaction per symbol; the write lock is never held across a paced network
> wait). No promotion evaluation, no sealed test, no change to
> `cfg.research.universe` and no change to any approved scope."**

Preconditions the operator should confirm: the killswitch is disengaged
(`ensure_not_engaged`, `cli.py:103`, `massive.py:110`); `MARKET_DATA_API_KEY` is
set; and the run is started at a time when a ~30-minute write-active window is
acceptable alongside the worker.

### 10.2 Approval line 2 — registering the snapshot and evaluating on it

> **"Approved: after the backfill passes the pre-registered completeness rule
> (W1-COMPLETE), create the `DataSnapshot`
> `research_150_massive_10y_2026-09-08` with the explicit key, and evaluate
> **only** `volatility_breakout.short_swing` (and later
> `mean_reversion.short_swing`) against it with `source="massive"` and
> `dataset_snapshot=` set to that row. No API calls. This creates one new locked
> sealed test per evaluated version, taking those versions from k = 5 to k = 6
> looks at the sealed calendar year; `trend_continuation.short_swing`,
> `trend_continuation.medium_swing` and `relative_strength.medium_swing` are NOT
> evaluated on this snapshot and stay at k = 5."**

### 10.3 What the operator is also being asked to decide

1. **§7.1's 2×/5× inconsistency** between MAP §0.4 and §3(a) — which convention
   is canonical. (This document reports all four points so the work is not
   blocked either way.)
2. **§9.2's resolution (A) or (B)** — in-process script, or a `--dataset-key`
   CLI option.
3. **Gate 7's docstring/code divergence** (MAP §0.2) remains open and unaffected
   by W1; all gate-7 statements here use *all pre-sealed trades*, as the code does.

---

## 11. The pre-registered universe

Full per-symbol detail — 60-session median dollar volume, overall and CS rank,
20-session screen mean, market cap, SIC group, list date, and whether `massive`
history already exists — is in `w1_universe_preregistration.json`.

### 11.1 ETF anchor (15) — already ingested, 0 API calls

`DIA, IWM, QQQ, SPY, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY`

### 11.2 Common stocks (135) — 9 already ingested, **126 to backfill**

Already ingested (9): `AAPL, AMZN, GOOGL, HD, JPM, MSFT, NVDA, UNH, XOM`

To backfill (126), alphabetically:

`AAL, ABBV, ABT, ACN, ADBE, ADI, AMAT, AMD, AMGN, ANET, APH, AVGO, AXP, AZO, BA,
BAC, BKNG, BLK, BMY, BRK.B, BSX, C, CAT, CDNS, CIEN, CLS, CMCSA, CME, COF, COHR,
COP, COST, CRM, CSCO, CVS, CVX, DE, DHR, DIS, ETN, F, FCX, FIX, FTNT, GE, GILD,
GLW, GOOG, GS, HON, HPE, IBM, INTC, INTU, ISRG, JNJ, KLAC, KO, LIN, LITE, LLY,
LOW, LRCX, MA, MCD, MCHP, MCK, MDT, MELI, MO, MPC, MPWR, MRK, MRVL, MS, MSTR, MU,
NBIS, NEE, NEM, NFLX, NKE, NOW, NXPI, ON, ORCL, PANW, PEP, PFE, PG, PM, PWR, PYPL,
QCOM, RCL, RTX, SBUX, SCHW, SHOP, SHW, SMCI, SNPS, SPGI, STM, STX, SYK, T, TER,
TGT, TJX, TMO, TMUS, TRV, TSLA, TXN, UNP, V, VLO, VRTX, VST, VZ, WDAY, WDC, WELL,
WFC, WMT`

### 11.3 Reserve list (CS ranks 136–160 of the filtered pool, strict rank order)

Used **only** by W1-COMPLETE (§6.4), in this order, one replacement per drop:

`CDE, LMT, ICE, SLB, HLT, AXTI, ADP, HL, EQIX, CB, CMI, PH, MAR, CMG, PSX, ROST,
ORLY, HCA, BX, PGR, CSX, WBD, REGN, MARA, TTWO`

---

## 12. Caveats on this document

1. **Every projected trade count is a projection**, resting on the assumption
   that per-symbol signal rates carry over. §4.3 shows the answer moves by 2× if
   the ETF:CS rate ratio is 3 rather than 1. Treat the `n` column of §4.2 as an
   order of magnitude.
2. **The per-trade sd = 1.554 is itself an inversion** of a percentile bootstrap
   under a normal approximation (MAP §0.3), good to ~2 significant figures. Every
   required-`n` and half-width inherits that.
3. **The bootstrap assumes iid trades and this universe still violates it**
   (MAP §3(a)). All CI figures here are too narrow and all required-`n` figures
   are lower bounds. §9.5's clustered bootstrap is the mitigation, and it is a
   reported diagnostic, not a gate.
4. **No spread data exists.** Every spread statement in §4.4 and §7 is a
   *modelling assumption*, not a measurement (`spread_filter_not_licensed`,
   `universe/screen.py:47`). The liquidity floor in §4.4 is a genuine measurement;
   the inference from it to spread is a HYPOTHESIS.
5. **`avg_dollar_volume` and the 60-session median both come from
   `massive_grouped`**, which spans only 2025-01-03 → 2026-09-08. Liquidity is
   measured over ~20 months and used to rank a 10-year backfill. A name that was
   illiquid in 2017 and is liquid now still enters. This is unavoidable with the
   available data and is disclosed rather than fixed.
6. **The universe is survivorship-biased and not point-in-time.** Discovery is
   active-tickers-only (`universe/screen.py` description text, MAP §3(a)); bars
   are split-adjusted as of the fetch date. Gate 8's own evidence blob already
   records the equivalent caveat for the current universe
   (`promotion.py:828-832`). Expansion from 24 to 150 does not reduce this bias —
   it applies it to six times as many names.
7. **Nothing here has been executed.** Every number describing the *result* of
   the backfill (bar counts, gate outcomes, trade counts) is a forecast.

---

## 13. Independent re-derivation (verification pass)

Every computed claim in this document was re-derived a second time, from
read-only `SELECT`s against `data/signalforge.sqlite` and independent arithmetic,
without reference to the first computation. **No API call and no database write
occurred in either pass.**

Reproduced **exactly**: the 60-session liquidity window (2026-06-12 → 2026-09-08,
60 sessions); screen run 3's counts (13,157 discovered / 10,746 in scope / 2,181
eligible = 1,599 CS + 582 ETF); `META`'s exclusion reasons
(`["market_cap_unverified", "corporate_action_continuity"]`); all 1,599 eligible
CS rankable at ≥ 57/60 sessions; the top-of-book medians (`MU` 35,744.1 $M,
`SPY` 33,680.4 $M, `NVDA` 26,569.2 $M); **the 135-name CS list and its exact rank
order**; the 25-name reserve list in rank order; the 26 names dropped by the
listing filter, in the order printed in §2.4; the liquidity floor (`XLRE`
213.8 $M least liquid overall, `TRV` 598.2 $M least liquid new name); the ten
existing `data_snapshot` keys and their `reusable` flags; and every figure in
§4.2, §4.3, §7.2 and §7.3.

Code facts re-checked at source: `settings.py:51` spacing 12.1 s;
`massive.py:42, 164, 179` one paced GET per symbol at `limit=50000`;
`massive.py:225-231` corporate actions and earnings return `()` without a
request; `engine.py:84-94, 143`; `backtest_runner.py:203-206` passes no
`spread_bps`, and the module contains **zero** `session.add`/`flush`/`commit`;
`validate.py:63` `_MISSING_SESSION_TOL_PCT = 2.0`; `promotion.py:339` and
`screen.py:259` key generators; `promotion.py:504-505` unkeyed fall-through;
`repository.py:17-27` `None` applies no source filter; `config/research.py:135`
`max_avg_spread_bps = 20.0` and `:139` `max_universe_size = 150`.

**One correction was applied.** §4.2's `N = 100` depth cell previously read
"1,053.8 $M (`VZ`)". `VZ` is CS rank **68**; under Rule W1-COMP an `N = 100`
universe is 15 ETFs + **85** CS, whose deepest member is **`GILD` at 887.3 $M**.
The cell now reads `GILD`. The `N = 150` and `N = 300` cells were already
correct, and the error was not load-bearing: §4.4's argument is that the
expansion adds no name less liquid than something already in the approved
dataset, and 887.3 $M is still **4.2×** `XLRE`'s 213.8 $M, so the conclusion and
the **N = 150** recommendation are unchanged.
