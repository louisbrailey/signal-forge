# W1-SEL re-derived on a PRE-SEALED liquidity window (approval A0)

**Status: RE-DERIVATION ONLY.** Read-only `SELECT`s and read-only computation over
`data/signalforge.sqlite`. **Nothing was ingested, no provider API was called, and nothing
was written to the live database.** The only files written are this document and its
machine-readable companion `w1_selection_presealed.json` (same directory).

**What this implements.** Operator approval **A0** of
`docs/research/designs/volatility_breakout_short_swing.md` §0.1(1) / §7.2(1) / §13, which
found the blocking R1 defect in `docs/research/diagnostics/w1_universe_preregistration.md`
§2.1: Rule **W1-SEL(2)** ranked the 150 symbols by median dollar volume over
**2026-06-12 → 2026-09-08**, a statistic computed *entirely inside the sealed window*
(2025-09-08 → 2026-09-08) that gate 9 measures. A0 re-derives step (2) — and only step (2) —
on the **60 most recent PRE-SEALED sessions**. Rule W1-COMP (15 ETFs + 135 CS), the listing
filter, the tie-break and Rule W1-COMPLETE are **unchanged**.

**This document supersedes `w1_universe_preregistration.md` §2.1(2), §11.1–§11.3 and §5's
snapshot key.** Everything else in that document — §3 composition, §4 the N = 150 arithmetic,
§6 ingestion mechanics, §7 spread sensitivity, §8 pre-registered expectations, §9 safeguards —
stands as written and is not re-opened here.

Claim labelling: **FACT** = verified against a file:line or a query run for this document.
**DERIVED** = arithmetic on FACTs, derivation shown. **HYPOTHESIS** = an inference a later
phase must test.

---

## 1. The re-derived rule

> **Rule W1-SEL-P** (pre-sealed selection; replaces W1-SEL(2), everything else unchanged).
>
> 1. **Base pool** — unchanged: the `universe_member` rows of `universe_screen_run` **id 3**
>    (`screen_date` 2026-09-08, 420 archived `massive_grouped` sessions, `status = ok`) with
>    `eligible = 1`. **FACT (queried): 2,181 members — 1,599 CS, 582 ETF.**
> 2. **Liquidity statistic — CHANGED.** For each pool member, the **median** of
>    `close × volume` over the **60 most recent PRE-SEALED `massive_grouped` sessions**, i.e.
>    the last 60 sessions with `session_date ≤ 2025-09-07`: **2025-06-11 → 2025-09-05**
>    inclusive. A symbol must be present in **≥ 55 of those 60** sessions to be rankable.
> 3. **Composition** — unchanged (W1-COMP): the 15 snapshot-3 ETFs verbatim + the top 135
>    common stocks by (2).
> 4. **Listing filter (common stocks only)** — unchanged: `universe_ticker.list_date ≤
>    2016-10-17`.
> 5. **Ties** — unchanged: higher median wins; exact ties break by ticker ascending.
>    **FACT: no tie occurred** (135 distinct values among the 1,240 filtered CS).
> 6. **Reserve** — the next **20** filtered CS by rank (ranks 136–155), strict rank order.
>    (The sealed-window pre-registration reserved 25; the orchestrator's instruction for this
>    re-derivation is 20. §7 lists ranks 156–160 so the deeper list remains available.)

### 1.1 The window is genuinely pre-sealed

**FACT (queried).** `ohlcv_daily` source `massive_grouped` spans **2025-01-03 → 2026-09-08**
and holds **420** distinct sessions, of which **168** are `≤ 2025-09-07`. The 60 most recent
pre-sealed sessions are **2025-06-11 → 2025-09-05**. **No row with
`session_date ≥ 2025-09-08` entered the statistic** — the sealed window contributes nothing
to the ranking.

**FACT (queried).** Coverage is not a binding constraint here: **all 2,181 base-pool members
are present in all 60 of those sessions**. The `≥ 55 of 60` floor therefore excludes nobody in
the pool; it binds only on symbols outside it. (The design doc's "2,312 symbols carry ≥ 55 of
them" is reproduced exactly: 2,312 distinct instruments have rows in the window, and every one
of them has all 60.)

### 1.2 Control: the same pipeline reproduces the sealed-window pre-registration byte-for-byte

Before trusting the new numbers, the identical code was run on the **old** window
(2026-06-12 → 2026-09-08, coverage floor 57/60).

**FACT (computed):** it reproduces `w1_universe_preregistration.json` exactly — the 135 common
stocks in the same rank order, and the 25-name reserve (ranks 136–160) in the same order.
Spot-checked medians agree to the last stored decimal (`SPY` 33,680,440,522.19;
`MU` 35,744,050,121.77; `NVDA` 26,569,237,305.82; `TRV` 598,214,241.13; `XLRE` 213,846,718.86).

So every difference reported in §5 is attributable to the **window change alone**, not to a
reimplementation drift. This is the main reason to believe the re-derivation.

---

## 2. Counts

| Quantity | Value |
|---|---|
| Base pool (`universe_screen_run` 3, `eligible = 1`) | **2,181** (1,599 CS, 582 ETF) |
| Pre-sealed sessions available (`≤ 2025-09-07`) | **168** |
| Liquidity window | **2025-06-11 → 2025-09-05**, 60 sessions |
| Pool members rankable (≥ 55 of 60 present) | **2,181** (100%) |
| CS rankable | **1,599** |
| CS surviving the listing filter (`list_date ≤ 2016-10-17`) | **1,240** |
| CS dropped by the listing filter | **359** |
| Listing-filter drops from the *unfiltered* pre-sealed top 135 | **25** |
| **Selected: ETFs (anchor, verbatim)** | **15** |
| **Selected: common stocks (top 135 filtered)** | **135** |
| **Total N** | **150** |
| Reserve (CS ranks 136–155) | **20** |
| Of the 150, already hold `source='massive'` rows | **24** |
| **Symbols to backfill** | **126** |

**DERIVED:** the listing filter drops these 25 from the unfiltered pre-sealed top 135 —
`PLTR, COIN, HOOD, APP, UBER, GEV, HIMS, SOFI, CRWD, SPOT, OKLO, RDDT, CVNA, RBLX, RKLB, VRT,
IONQ, NU, SNOW, DASH, ALAB, CEG, DDOG, DELL, FLUT` — and pulls in the next 25 by rank —
`TGT, CLS, SPGI, UPS, BLK, CME, DHI, MCHP, VRTX, CCL, NXPI, FSLR, REGN, XYZ, BMY, CHTR, FCX,
JCI, STX, TT, CSX, CDNS, MCK, SLB, HBAN`. The rationale (per-symbol IS/OOS alignment under
`_TRAIN_FRAC = 0.6`, regime breadth, IPO-cohort bias) is unchanged from
`w1_universe_preregistration.md` §2.4 and is not re-argued here.

### 2.1 Every selected common stock verified as a U.S. common stock

**FACT (queried, all 135, zero failures).** For each of the 135: `universe_ticker.security_type
= 'CS'`, `universe_ticker.locale = 'us'`, `universe_ticker.active = 1`, `universe_member.
security_type = 'CS'` for run 3, and `list_date ≤ 2016-10-17` (non-null). Primary exchanges:
**76 XNYS, 59 XNAS** — no OTC, no foreign locale, no ETF/ETN/ADR-typed row among them.
**FACT:** all 15 anchor ETFs verify as `security_type = 'ETF'`, `locale = 'us'`, `active = 1`.

**Disclosed, not fixed:** `GOOG` and `GOOGL` are two share classes of one issuer and both
appear (CS ranks 9 and 7). That is inherited from W1-COMP and is the same double-count the
sealed-window list carried.

**FACT:** the new 150 remains a **strict superset of dataset snapshot 3**
(`universe_24_ex_meta`) — all 24 of its symbols are present; the 9 single names sit at CS ranks
1 (`NVDA`), 3 (`AAPL`), 4 (`MSFT`), 6 (`AMZN`), 7 (`GOOGL`), 11 (`UNH`), 16 (`JPM`),
22 (`XOM`) and 34 (`HD`) — all comfortably inside the top 135. The composition-decomposition argument of
`w1_universe_preregistration.md` §3.2(1) therefore survives the re-derivation.

### 2.2 Sector composition (disclosed, not steered)

**DERIVED** (2-digit SIC group counts among the 135): `73` business services 20, `36`
electronics 16, `28` chemicals/pharma 13, `35` industrial/computer equipment 12, `38`
instruments 7, `37` transport equipment 6, `60` depository institutions 6, `62` securities 6,
`48` communications 6, then a long tail. **Maximum single-group share 14.8%**, inside the
screen's own 25% ceiling. No sector rebalancing is applied on top.

---

## 3. Liquidity floor

| | Ticker | 60-session **pre-sealed** median $ volume |
|---|---|---|
| Least liquid member overall | `XLRE` (ETF anchor) | **261.8 $M** |
| Least liquid common stock (CS rank 135) | `HBAN` | **483.9 $M** |
| First excluded common stock (CS rank 136) | `UAL` | 482.7 $M |

The pre-sealed floor is **483.9 $M/day** against the sealed-window list's 598.2 $M/day
(`TRV`). **DERIVED:** the deepest name is ~19% less liquid than under the old window, which
makes `w1_universe_preregistration.md` §4.4's cost argument *slightly weaker*, not stronger —
it must be restated with this number, not the old one. It remains far above the screen's own
$20M ADV floor and above the `XLRE` anchor, so the qualitative conclusion (the marginal cost
increment is dominated by the flat 5 bps model assumption, not by the new names' depth) is
unchanged. **The 2×/5× spread stress at 26 and 66 bps round trip (MAP §0.4 convention) is
unaffected by this re-derivation** — `backtest_runner.py:205-206` charges a flat, universe-
independent spread.

**Fragility of the cut, disclosed.** **FACT:** rank 135 (`HBAN`, 483.93 $M) and rank 136
(`UAL`, 482.68 $M) differ by **0.26%** — ratio 1.0026. The 135/136 boundary is not a
meaningful liquidity distinction; the marginal five or six names are interchangeable. This is
an argument for treating the reserve list as a genuine continuation of the ranking (which
Rule W1-COMPLETE already does) and against reading anything into the identity of the last few
members.

---

## 4. The re-derived universe

### 4.1 ETF anchor (15) — verbatim from snapshot 3, not re-ranked, 0 API calls

| Ticker | pre-sealed median $M | rank among all 2,181 eligible | sealed-window median $M (for reference) |
|---|---|---|---|
| `DIA` | 1,670.3 | 44 | 1,830.6 |
| `IWM` | 7,087.8 | 10 | 5,880.4 |
| `QQQ` | 24,524.1 | 4 | 25,483.2 |
| `SPY` | 42,994.2 | 1 | 33,680.4 |
| `XLB` | 577.7 | 181 | 590.6 |
| `XLC` | 613.4 | 168 | 611.1 |
| `XLE` | 1,354.0 | 54 | 1,693.1 |
| `XLF` | 1,947.7 | 34 | 1,764.2 |
| `XLI` | 1,600.8 | 45 | 1,211.1 |
| `XLK` | 1,544.9 | 46 | 1,497.6 |
| `XLP` | 1,216.0 | 67 | 882.8 |
| `XLRE` | 261.8 | 442 | 213.8 |
| `XLU` | 921.0 | 102 | 856.8 |
| `XLV` | 1,851.4 | 36 | 1,471.7 |
| `XLY` | 1,143.3 | 75 | 777.9 |

### 4.2 Common stocks (135), in strict pre-sealed rank order

`Δ rank` is *sealed-window CS rank − pre-sealed CS rank*, both computed over the
**listing-filtered** CS pool by the identical pipeline (§1.2); a **negative** Δ means the name
ranked *better* under the sealed window. "In sealed 150" says whether the name was also in
`w1_universe_preregistration.json`.

**Rank-convention warning.** `w1_universe_preregistration.json`'s own `per_symbol[*].rank_cs`
field is the rank among the **unfiltered** 1,599 CS (e.g. `TRV` 164, `NBIS` 19); every CS rank
in this document and in `w1_selection_presealed.json` — for **both** windows — is the rank
among the **listing-filtered** pool (`TRV` 135, `NBIS` 17). The two are not comparable; do not
subtract one from the other.

| CS rank | Ticker | pre-sealed median $M | rank (all) | sealed CS rank | Δ rank | list_date | exch | in sealed 150 |
|---|---|---|---|---|---|---|---|---|
| 1 | `NVDA` | 27,487.6 | 2 | 2 | 1 | 1999-01-22 | XNAS | yes |
| 2 | `TSLA` | 27,297.3 | 3 | 6 | 4 | 2010-06-29 | XNAS | yes |
| 3 | `AAPL` | 10,115.9 | 5 | 3 | 0 | 1980-12-12 | XNAS | yes |
| 4 | `MSFT` | 9,240.6 | 7 | 5 | 1 | 1986-03-13 | XNAS | yes |
| 5 | `AMD` | 8,400.9 | 8 | 4 | -1 | 1973-01-02 | XNAS | yes |
| 6 | `AMZN` | 8,186.2 | 9 | 8 | 2 | 1997-05-15 | XNAS | yes |
| 7 | `GOOGL` | 6,182.0 | 11 | 9 | 2 | 2004-08-19 | XNAS | yes |
| 8 | `AVGO` | 5,121.9 | 12 | 10 | 2 | 2009-08-06 | XNAS | yes |
| 9 | `GOOG` | 4,362.6 | 14 | 11 | 2 | 2004-08-19 | XNAS | yes |
| 10 | `MSTR` | 4,141.4 | 15 | 36 | 26 | 1998-06-11 | XNAS | yes |
| 11 | `UNH` | 4,107.7 | 16 | 35 | 24 | 1984-10-17 | XNYS | yes |
| 12 | `NFLX` | 3,416.0 | 20 | 21 | 9 | 2002-05-23 | XNAS | yes |
| 13 | `ORCL` | 2,672.6 | 24 | 14 | 1 | 1986-03-12 | XNYS | yes |
| 14 | `LLY` | 2,503.3 | 26 | 20 | 6 | 1970-07-09 | XNYS | yes |
| 15 | `MU` | 2,295.6 | 28 | 1 | -14 | 1984-06-01 | XNAS | yes |
| 16 | `JPM` | 2,159.7 | 29 | 24 | 8 | 1969-03-05 | XNYS | yes |
| 17 | `BRK.B` | 2,104.5 | 30 | 31 | 14 | 1996-05-09 | XNYS | yes |
| 18 | `V` | 2,013.0 | 33 | 22 | 4 | 2008-03-19 | XNYS | yes |
| 19 | `COST` | 1,942.4 | 35 | 37 | 18 | 1982-03-02 | XNAS | yes |
| 20 | `CRM` | 1,819.5 | 38 | 27 | 7 | 2004-06-23 | XNYS | yes |
| 21 | `INTC` | 1,778.3 | 39 | 7 | -14 | 1971-10-13 | XNAS | yes |
| 22 | `XOM` | 1,716.9 | 42 | 30 | 8 | 1920-03-25 | XNYS | yes |
| 23 | `BAC` | 1,715.1 | 43 | 40 | 17 | 1973-01-02 | XNYS | yes |
| 24 | `SMCI` | 1,542.6 | 47 | 48 | 24 | 2007-03-29 | XNAS | yes |
| 25 | `WMT` | 1,475.2 | 49 | 23 | -2 | 1970-10-01 | XNAS | yes |
| 26 | `BA` | 1,414.4 | 51 | 66 | 40 | 1952-05-23 | XNYS | yes |
| 27 | `MA` | 1,410.8 | 52 | 42 | 15 | 2006-05-25 | XNYS | yes |
| 28 | `JNJ` | 1,343.5 | 55 | 38 | 10 | 1944-09-25 | XNYS | yes |
| 29 | `GS` | 1,342.4 | 56 | 39 | 10 | 1999-05-04 | XNYS | yes |
| 30 | `ADBE` | 1,330.2 | 58 | 56 | 26 | 1986-08-20 | XNAS | yes |
| 31 | `GE` | 1,315.5 | 59 | 51 | 20 | 1900-01-01 | XNYS | yes |
| 32 | `CVX` | 1,309.5 | 60 | 45 | 13 | 1970-01-02 | XNYS | yes |
| 33 | `NOW` | 1,259.3 | 63 | 28 | -5 | 2012-06-29 | XNYS | yes |
| 34 | `HD` | 1,258.9 | 64 | 52 | 18 | 1981-09-22 | XNYS | yes |
| 35 | `CSCO` | 1,249.2 | 65 | 29 | -6 | 1990-02-16 | XNAS | yes |
| 36 | `C` | 1,248.3 | 66 | 46 | 10 | 1986-06-02 | XNYS | yes |
| 37 | `PEP` | 1,209.3 | 68 | 63 | 26 | 1919-12-18 | XNAS | yes |
| 38 | `WFC` | 1,190.9 | 69 | 61 | 23 | 1962-12-10 | XNYS | yes |
| 39 | `TXN` | 1,155.5 | 72 | 34 | -5 | 1953-10-01 | XNAS | yes |
| 40 | `AMAT` | 1,150.7 | 73 | 13 | -27 | 1972-10-12 | XNAS | yes |
| 41 | `INTU` | 1,146.5 | 74 | 55 | 14 | 1993-03-12 | XNAS | yes |
| 42 | `QCOM` | 1,137.7 | 76 | 32 | -10 | 1991-12-13 | XNAS | yes |
| 43 | `MRVL` | 1,137.5 | 77 | 12 | -31 | 2000-06-27 | XNAS | yes |
| 44 | `PG` | 1,131.9 | 78 | 57 | 13 | 1950-03-22 | XNYS | yes |
| 45 | `TMO` | 1,094.6 | 81 | 70 | 25 | 1972-06-01 | XNYS | yes |
| 46 | `PANW` | 1,087.5 | 82 | 33 | -13 | 2012-07-20 | XNAS | yes |
| 47 | `CAT` | 1,079.9 | 83 | 25 | -22 | 1929-12-02 | XNYS | yes |
| 48 | `BKNG` | 1,039.0 | 85 | 64 | 16 | 1999-03-31 | XNAS | yes |
| 49 | `IBM` | 1,031.2 | 87 | 41 | -8 | 1949-01-28 | XNYS | yes |
| 50 | `ACN` | 1,030.3 | 88 | 69 | 19 | 2001-07-19 | XNYS | yes |
| 51 | `MRK` | 1,026.3 | 89 | 58 | 7 | 1949-04-20 | XNYS | yes |
| 52 | `KO` | 1,013.5 | 92 | 49 | -3 | 1924-09-26 | XNYS | yes |
| 53 | `MCD` | 1,011.7 | 93 | 59 | 6 | 1966-07-05 | XNYS | yes |
| 54 | `ANET` | 995.6 | 96 | 54 | 0 | 2014-06-06 | XNYS | yes |
| 55 | `TMUS` | 988.2 | 97 | 90 | 35 | 2007-04-19 | XNAS | yes |
| 56 | `LRCX` | 976.0 | 98 | 19 | -37 | 1984-05-04 | XNAS | yes |
| 57 | `PFE` | 936.2 | 99 | 72 | 15 | 1951-06-22 | XNYS | yes |
| 58 | `ABBV` | 923.8 | 101 | 53 | -5 | 2012-12-10 | XNYS | yes |
| 59 | `PM` | 918.7 | 103 | 86 | 27 | 2008-03-31 | XNYS | yes |
| 60 | `ISRG` | 895.3 | 105 | 77 | 17 | 2000-06-13 | XNAS | yes |
| 61 | `SHOP` | 865.5 | 108 | 78 | 17 | 2015-05-21 | XNAS | yes |
| 62 | `KLAC` | 857.5 | 109 | 26 | -36 | 1980-10-08 | XNAS | yes |
| 63 | `NKE` | 845.8 | 110 | 80 | 17 | 1980-12-02 | XNYS | yes |
| 64 | `DIS` | 835.5 | 111 | 76 | 12 | 1962-01-02 | XNYS | yes |
| 65 | `T` | 832.4 | 112 | 62 | -3 | 1946-11-01 | XNYS | yes |
| 66 | `VST` | 803.3 | 115 | 128 | 62 | 2016-09-28 | XNYS | yes |
| 67 | `PGR` | 798.5 | 116 | 155 | 88 | 1972-06-01 | XNYS | **NEW** |
| 68 | `AXP` | 781.6 | 120 | 83 | 15 | 1972-06-01 | XNYS | yes |
| 69 | `ADI` | 774.5 | 122 | 47 | -22 | 1972-06-01 | XNAS | yes |
| 70 | `UNP` | 769.8 | 123 | 111 | 41 | 1969-06-20 | XNYS | yes |
| 71 | `APH` | 765.8 | 125 | 75 | 4 | 1991-11-08 | XNYS | yes |
| 72 | `AAL` | 762.6 | 127 | 50 | -22 | 1972-06-01 | XNAS | yes |
| 73 | `MELI` | 762.0 | 130 | 112 | 39 | 2007-08-10 | XNAS | yes |
| 74 | `F` | 754.5 | 131 | 122 | 48 | 1972-06-01 | XNYS | yes |
| 75 | `LULU` | 751.1 | 132 | 265 | 190 | 2007-07-27 | XNAS | **NEW** |
| 76 | `VZ` | 747.6 | 133 | 68 | -8 | 1983-11-21 | XNYS | yes |
| 77 | `MS` | 744.7 | 134 | 74 | -3 | 1986-03-21 | XNYS | yes |
| 78 | `ETN` | 743.5 | 135 | 98 | 20 | 1948-12-01 | XNYS | yes |
| 79 | `SCHW` | 738.4 | 136 | 94 | 15 | 1987-09-30 | XNYS | yes |
| 80 | `CMG` | 724.2 | 139 | 149 | 69 | 2006-01-26 | XNYS | **NEW** |
| 81 | `LIN` | 721.7 | 140 | 67 | -14 | 1992-06-01 | XNAS | yes |
| 82 | `SBUX` | 715.2 | 141 | 119 | 37 | 1992-06-26 | XNAS | yes |
| 83 | `SNPS` | 712.2 | 142 | 114 | 31 | 1992-03-03 | XNAS | yes |
| 84 | `MARA` | 711.5 | 143 | 159 | 75 | 2011-03-09 | XNAS | **NEW** |
| 85 | `COF` | 706.8 | 144 | 97 | 12 | 1994-11-16 | XNYS | yes |
| 86 | `DHR` | 703.8 | 145 | 108 | 22 | 1978-12-29 | XNYS | yes |
| 87 | `LMT` | 687.9 | 147 | 137 | 50 | 1995-03-16 | XNYS | **NEW** |
| 88 | `BSX` | 687.0 | 148 | 87 | -1 | 1992-05-18 | XNYS | yes |
| 89 | `WBD` | 681.0 | 149 | 157 | 68 | 2005-07-06 | XNAS | **NEW** |
| 90 | `HON` | 680.0 | 150 | 106 | 16 | 1929-09-19 | XNAS | yes |
| 91 | `ABT` | 679.1 | 151 | 73 | -18 | 1949-04-19 | XNYS | yes |
| 92 | `GILD` | 674.9 | 152 | 85 | -7 | 1992-01-22 | XNAS | yes |
| 93 | `PYPL` | 673.6 | 153 | 123 | 30 | 2015-07-20 | XNAS | yes |
| 94 | `ELV` | 667.1 | 155 | 192 | 98 | 2001-10-30 | XNYS | **NEW** |
| 95 | `RTX` | 662.9 | 156 | 93 | -2 | 1951-05-25 | XNYS | yes |
| 96 | `CMCSA` | 659.1 | 157 | 117 | 21 | 1973-01-02 | XNAS | yes |
| 97 | `RCL` | 659.0 | 158 | 133 | 36 | 1993-04-27 | XNYS | yes |
| 98 | `NEE` | 646.1 | 161 | 81 | -17 | 1972-06-30 | XNYS | yes |
| 99 | `NEM` | 645.2 | 162 | 96 | -3 | 1951-12-21 | XNYS | yes |
| 100 | `COP` | 619.6 | 165 | 100 | 0 | 1972-06-30 | XNYS | yes |
| 101 | `MDT` | 616.9 | 166 | 116 | 15 | 1972-06-01 | XNYS | yes |
| 102 | `TJX` | 612.2 | 169 | 88 | -14 | 1965-11-17 | XNYS | yes |
| 103 | `LOW` | 597.7 | 172 | 127 | 24 | 1972-06-01 | XNYS | yes |
| 104 | `BX` | 594.2 | 173 | 154 | 50 | 2007-06-22 | XNYS | **NEW** |
| 105 | `TTD` | 587.2 | 175 | 320 | 215 | 2016-09-21 | XNAS | **NEW** |
| 106 | `NBIS` | 586.3 | 176 | 17 | -89 | 2011-05-24 | XNAS | yes |
| 107 | `SHW` | 584.7 | 177 | 125 | 18 | 1964-02-11 | XNYS | yes |
| 108 | `DE` | 584.1 | 178 | 121 | 13 | 1958-08-04 | XNYS | yes |
| 109 | `AMGN` | 583.5 | 179 | 79 | -30 | 1983-06-17 | XNAS | yes |
| 110 | `WDAY` | 580.9 | 180 | 130 | 20 | 2012-10-12 | XNAS | yes |
| 111 | `TGT` | 574.9 | 182 | 132 | 21 | 1972-06-01 | XNYS | yes |
| 112 | `CLS` | 571.8 | 184 | 118 | 6 | 1998-06-30 | XNYS | yes |
| 113 | `SPGI` | 560.4 | 186 | 99 | -14 | 1929-02-14 | XNYS | yes |
| 114 | `UPS` | 560.1 | 187 | 181 | 67 | 1999-11-10 | XNYS | **NEW** |
| 115 | `BLK` | 559.1 | 188 | 105 | -10 | 1999-10-01 | XNYS | yes |
| 116 | `CME` | 557.3 | 189 | 124 | 8 | 2002-12-06 | XNAS | yes |
| 117 | `DHI` | 555.6 | 190 | 277 | 160 | 1992-06-12 | XNYS | **NEW** |
| 118 | `MCHP` | 545.3 | 192 | 89 | -29 | 1993-03-26 | XNAS | yes |
| 119 | `VRTX` | 528.7 | 194 | 126 | 7 | 1991-07-31 | XNAS | yes |
| 120 | `CCL` | 526.8 | 195 | 166 | 46 | 1987-07-24 | XNYS | **NEW** |
| 121 | `NXPI` | 521.6 | 198 | 71 | -50 | 2010-08-06 | XNAS | yes |
| 122 | `FSLR` | 515.1 | 200 | 206 | 84 | 2006-11-17 | XNAS | **NEW** |
| 123 | `REGN` | 513.5 | 201 | 158 | 35 | 1991-04-02 | XNAS | **NEW** |
| 124 | `XYZ` | 509.9 | 202 | 235 | 111 | 2015-11-19 | XNYS | **NEW** |
| 125 | `BMY` | 509.7 | 203 | 129 | 4 | 1952-06-23 | XNYS | yes |
| 126 | `CHTR` | 507.5 | 205 | 268 | 142 | 1999-11-08 | XNAS | **NEW** |
| 127 | `FCX` | 506.5 | 207 | 82 | -45 | 1995-08-01 | XNYS | yes |
| 128 | `JCI` | 505.0 | 208 | 185 | 57 | 1965-10-11 | XNYS | **NEW** |
| 129 | `STX` | 496.3 | 210 | 15 | -114 | 2002-12-11 | XNAS | yes |
| 130 | `TT` | 493.9 | 211 | 177 | 47 | 1948-06-09 | XNYS | **NEW** |
| 131 | `CSX` | 492.4 | 212 | 156 | 25 | 1980-11-03 | XNAS | **NEW** |
| 132 | `CDNS` | 490.5 | 214 | 113 | -19 | 1987-06-10 | XNAS | yes |
| 133 | `MCK` | 485.3 | 217 | 95 | -38 | 1987-08-03 | XNYS | yes |
| 134 | `SLB` | 484.7 | 218 | 139 | 5 | 1962-02-02 | XNYS | **NEW** |
| 135 | `HBAN` | 483.9 | 220 | 225 | 90 | 1973-01-02 | XNAS | **NEW** |

---

## 5. Differences vs the sealed-window list

**DERIVED (set comparison against `w1_universe_preregistration.json`):**

| | Count | Fraction |
|---|---|---|
| **Overlap, full 150** | **129** | **86.0%** |
| Overlap, 135 common stocks | 114 | 84.4% |
| Overlap, 15 ETFs | 15 | 100% (anchor is fixed by rule) |
| Added by the re-derivation | 21 | |
| Removed by the re-derivation | 21 | |

**86.0% of the universe is unchanged.** The disagreement is entirely in the bottom third of
the CS ranking, which §3 has just shown is a near-tie region.

**Added (in the pre-sealed 150, not in the sealed 150) — 21 names**, with the sealed-window CS
rank they *would* have held (all outside the top 135, which is why they were absent):

`LMT` (137), `SLB` (139), `CMG` (149), `BX` (154), `PGR` (155), `CSX` (156), `WBD` (157),
`REGN` (158), `MARA` (159), `CCL` (166), `TT` (177), `UPS` (181), `JCI` (185), `ELV` (192),
`FSLR` (206), `HBAN` (225), `XYZ` (235), `LULU` (265), `CHTR` (268), `DHI` (277), `TTD` (320).

Nine of these 21 (`LMT, SLB, CMG, BX, PGR, CSX, WBD, REGN, MARA`) were already on the
sealed-window **reserve** list, so they were pre-registered as admissible replacements even
under the old rule.

**Removed (in the sealed 150, not in the pre-sealed 150) — 21 names**, with the pre-sealed CS
rank they now hold:

`MO` (139), `FTNT` (145), `AZO` (155), `ON` (156), `CVS` (158), `SYK` (160), `WDC` (172),
`MPWR` (180), `WELL` (185), `VLO` (191), `PWR` (202), `TER` (211), `HPE` (219), `TRV` (229),
`MPC` (231), `COHR` (268), `GLW` (288), `LITE` (292), `FIX` (331), `STM` (354), `CIEN` (457).

**HYPOTHESIS (the substantive point, and the reason A0 mattered).** The removed set is
conspicuously an **AI/optical/semiconductor-capex and utility-capex cohort** — `CIEN`, `LITE`,
`COHR`, `FIX`, `STM`, `TER`, `MPWR`, `ON`, `GLW`, `WDC`, `PWR`, `VLO`, `MPC` — i.e. exactly the
names whose dollar volume expanded *during the sealed year*. Ranking inside the sealed window
loaded the universe with that year's turnover leaders; ranking before it does not.

The same signature shows in the rank movers **among the 114 common stocks present in both
lists** (so that "moved" is not confounded with "added"). **FACT (computed, both ranks on the
listing-filtered CS pool, §4.2's convention):** ranking *better* under the sealed window —
`STX` −114, `NBIS` −89, `NXPI` −50, `FCX` −45, `MCK` −38, `LRCX` −37, `KLAC` −36, `MRVL` −31;
ranking *better* before it — `VST` +62, `F` +48, `UNP` +41, `BA` +40, `MELI` +39, `SBUX` +37,
`RCL` +36, `TMUS` +35. Mean absolute rank change over those 114 names **17.8**; rank
correlation **0.7933**. Over all 135 (including the 21 added names) the mean absolute change is
**28.1** and the correlation **0.7419**.

Whether this composition difference moves any gate is unknown and is Stage A's job to measure —
it must **not** be assumed to be small merely because the overlap is 86.0%.

**The top of the list moved too**, which the overlap fraction hides. **FACT (filtered CS
ranks):** the sealed window's top five are `MU` (35,744 $M), `NVDA`, `AAPL`, `AMD`, `MSFT`,
with `INTC` at 7; the pre-sealed window's top five are `NVDA` (27,488 $M), `TSLA`, `AAPL`,
`MSFT`, `AMD`, with `MU` at **15** and `INTC` at **21**. Any per-symbol weighting or reporting
that leans on the head of the ranking is affected even though every one of those names remains
in the 150.

### 5.1 Reserve list, and how it differs

Only 5 of the 20 pre-sealed reserve names (`MO, FTNT, AZO, ON, CVS`) were in the sealed 150,
and 2 (`ADP`, `HCA`) were on the sealed reserve; the rest are new to both lists.

---

## 6. Reserve list (CS ranks 136–155, strict rank order)

Used **only** by Rule W1-COMPLETE (`w1_universe_preregistration.md` §6.4) to replace a symbol
dropped for a **data-quality** reason, in strict rank order. Never a performance rule.

| CS rank | Ticker | pre-sealed median $M | list_date | exch | status in the sealed-window lists |
|---|---|---|---|---|---|
| 136 | `UAL` | 482.7 | 1969-08-01 | XNAS | neither |
| 137 | `CI` | 475.6 | 1982-04-01 | XNYS | neither |
| 138 | `MMM` | 468.8 | 1946-01-14 | XNYS | neither |
| 139 | `MO` | 468.6 | 1972-06-01 | XNYS | in sealed 150 |
| 140 | `NSC` | 468.4 | 1982-06-02 | XNYS | neither |
| 141 | `EBAY` | 464.8 | 1998-09-24 | XNAS | neither |
| 142 | `USB` | 462.7 | 1973-01-02 | XNYS | neither |
| 143 | `AMT` | 461.2 | 1998-02-27 | XNYS | neither |
| 144 | `ZTS` | 456.0 | 2013-02-01 | XNYS | neither |
| 145 | `FTNT` | 452.4 | 2009-11-18 | XNAS | in sealed 150 |
| 146 | `KKR` | 448.9 | 2010-07-15 | XNYS | neither |
| 147 | `MDLZ` | 448.2 | 2001-06-13 | XNAS | neither |
| 148 | `ADP` | 447.6 | 1968-01-31 | XNAS | sealed reserve |
| 149 | `HCA` | 447.6 | 2011-03-10 | XNYS | sealed reserve |
| 150 | `FICO` | 447.2 | 1987-07-31 | XNYS | neither |
| 151 | `SO` | 447.0 | 1949-10-04 | XNYS | neither |
| 152 | `URI` | 443.9 | 1997-12-18 | XNYS | neither |
| 153 | `BDX` | 440.6 | 1963-09-25 | XNYS | neither |
| 154 | `KEY` | 438.1 | 1975-02-18 | XNYS | neither |
| 155 | `AZO` | 437.0 | 1991-04-02 | XNYS | in sealed 150 |

**FACT:** CS ranks 156–160, available if more than 20 replacements are ever needed, are
`SO, URI, BDX, KEY, AZO`. Extending the reserve beyond 20 would be a change to a
pre-registered rule and should be decided before, not after, a drop occurs.

### 6.1 `NBIS` remains the named W1-COMPLETE drop candidate

**FACT:** `NBIS` (Nebius Group, `list_date = 2011-05-24` — the former Yandex listing, halted
for roughly two and a half years) is **still inside the top 135**, at pre-sealed CS rank
**106**, having been sealed-window CS rank **17** — an 89-place deterioration once the sealed
year is removed, the second largest in the list after `STX`. It passes the listing filter and
will very likely fail Rule
W1-COMPLETE's `session_completeness` check or its (c) clause (first `massive` bar later than
2018-09-08). It is named here in advance, exactly as in the sealed-window pre-registration, so
that dropping it is a pre-registered data-quality action and not a post-hoc choice. Its
replacement, if dropped, is `UAL` (reserve rank 136).

---

## 7. What A0 does **not** fix — and one thing it turns out not to cost

A0 changes step (2) only. Three residual exposures remain, and one of them is now bounded.

1. **The base pool is still screened as of 2026-09-08 — but this is measurably costless at
   this liquidity level.** The eligibility criteria (`last_close ≥ $5`, 20-session mean dollar
   volume `≥ $20M`, market cap `≥ $2B` **verified**, presence in ≥ 95% of the 420 archived
   sessions, active listing) are all evaluated at the *end* of the sealed year, so membership
   still requires being alive and liquid then. **FACT (computed for this document):** of the
   **131** symbols that traded in the pre-sealed window with `massive_grouped` coverage but are
   **not** in the eligible pool, **zero** reach the rank-135 liquidity floor of 483.9 $M/day —
   the most liquid excluded name is `AI` at **136.7 $M/day**, 3.5× below the floor. So the
   base pool's sealed-window screening removes no name that the pre-sealed liquidity rule would
   have selected. **This bounds the residual selection contamination at exactly zero symbols,
   conditional on item 2.**
2. **Survivorship is untouched and is the binding limitation.** **FACT (queried):** **no**
   `massive_grouped` instrument has a last session earlier than 2026-09-08 — the archive is a
   pure survivor set built from active-tickers-only discovery, and 359 of its 2,655 instruments
   have a *first* session later than 2025-01-03. A company that delisted, was acquired or
   failed between 2016 and 2026 can never enter this universe under either window. Item 1's
   "zero" is therefore conditional on the archive itself, and **the size of the survivorship
   effect is unmeasurable with the data held**. This must be disclosed verbatim in every report
   on this snapshot.
3. **Bars remain split-adjusted as of the fetch date, not point-in-time**, and
   `validate.py:180-205`'s `adjustment_behaviour` check is a **no-op** for this source because
   `massive.py:212` sets `adj_close = close`. Expansion applies this known bias to 150 names.

**Conclusion.** The R1 defect that A0 targeted — *sealed data motivating a universe choice* —
is removed from the liquidity ranking, and the residual base-pool exposure is bounded at zero
selected symbols. Survivorship and adjustment bias remain and are disclosed, not fixed.

---

## 8. Backfill: the exact call count

**FACT (queried).** `source = 'massive'` currently holds **26 instruments**: the 24 of dataset
snapshot 3, plus `META` (1,215 bars, 2021-06-30 →) and `FB` (1,446 bars, 2016-09-12 →
2022-06-08). `META` and `FB` are **not** in the re-derived 150 (`META` is excluded by the base
pool: `exclusion_reasons = ["market_cap_unverified", "corporate_action_continuity"]`).

Of the re-derived **150**:

| | Count |
|---|---|
| Already hold **any** `source='massive'` rows | **24** — the 15 anchor ETFs + `AAPL, AMZN, GOOGL, HD, JPM, MSFT, NVDA, UNH, XOM` |
| Already hold the **full ingested depth** (first bar `2016-10-17`, 2,488 bars to 2026-09-10) | **23** |
| Short but complete-for-its-life | **1** — `XLC`, 2,068 bars from **2018-06-19** (the ETF's inception was 2018-06-18; **no backfill can extend it**) |
| Hold **≥ 10.0 calendar years** of `massive` history, read literally | **0** — 2016-10-17 → 2026-09-10 is **9.90** years; 10.0 years back from today is 2016-09-10 and no in-universe symbol has a bar before 2016-10-17 |
| Hold **zero** `massive` rows | **126** |

> **So the exact number of symbols to backfill is 126, and the exact number of provider GETs
> is 126.** This is unchanged in *count* from the sealed-window plan (`w1_universe_preregistration.md`
> §6.1) but **21 of the 126 tickers are different** — the added names of §5 replace the removed
> ones.

**FACT (`data/adapters/massive.py:164-210`):** `fetch_daily_bars` issues exactly **one**
`GET /v2/aggs/ticker/{SYM}/range/1/day/{start}/{stop}` per symbol for the whole range;
~2,490 bars is ~5% of the 50,000 limit, so no pagination is expected.
**FACT (`massive.py:225-231`):** `fetch_corporate_actions` and `fetch_earnings` both `return ()`
without a request — **1 API call per symbol, not 3**.
**FACT:** runtime `market_data_min_request_spacing_s = 12.1`; the first call is unpaced, so
**DERIVED: 125 × 12.1 s = 1,512.5 s ≈ 25.2 minutes**. **Budget 35 minutes.**
**FACT (`massive.py:44`):** `_MAX_ATTEMPTS = 5`, so the hard ceiling is 630 requests if every
symbol needed all five attempts. **The number to approve is 126; budget ≤ 140.**

### 8.1 The exact ingest command

```
signalforge data ingest-history \
  --since 2016-10-17 \
  --symbols "AAL,ABBV,ABT,ACN,ADBE,ADI,AMAT,AMD,AMGN,ANET,APH,AVGO,AXP,BA,BAC,BKNG,BLK,BMY,BRK.B,BSX,BX,C,CAT,CCL,CDNS,CHTR,CLS,CMCSA,CME,CMG,COF,COP,COST,CRM,CSCO,CSX,CVX,DE,DHI,DHR,DIS,ELV,ETN,F,FCX,FSLR,GE,GILD,GOOG,GS,HBAN,HON,IBM,INTC,INTU,ISRG,JCI,JNJ,KLAC,KO,LIN,LLY,LMT,LOW,LRCX,LULU,MA,MARA,MCD,MCHP,MCK,MDT,MELI,MRK,MRVL,MS,MSTR,MU,NBIS,NEE,NEM,NFLX,NKE,NOW,NXPI,ORCL,PANW,PEP,PFE,PG,PGR,PM,PYPL,QCOM,RCL,REGN,RTX,SBUX,SCHW,SHOP,SHW,SLB,SMCI,SNPS,SPGI,STX,T,TGT,TJX,TMO,TMUS,TSLA,TT,TTD,TXN,UNP,UPS,V,VRTX,VST,VZ,WBD,WDAY,WFC,WMT,XYZ"
```

**FACT (`cli.py:92-141`):** this resolves the primary adapter from `market_data_provider`
(runtime value `massive`), calls `ingest_daily_history` (`data/ingest.py:355`) inside
`session_scope(write=True)`, and records one `IngestionRun` row. Every bar is written with
`source = adapter.provider_name = "massive"` (`ingest.py:240`), which is what R6 and gate 8
require. `--since 2016-10-17` is pre-registered rather than letting `discover_history_depth`
probe, so the `_TRAIN_FRAC = 0.6` boundary lands on the same calendar date for every symbol.

**Why `ingest_daily_history` and not `ingest_universe`** (unchanged from
`w1_universe_preregistration.md` §6.2): **FACT (`ingest.py:296-317`)** `ingest_universe` writes
**no** `IngestionRun` row and supports no resume; **FACT (`ingest.py:355-372, 404-430`)**
`ingest_daily_history` persists the requested window, discovered earliest date, actual
coverage, per-symbol gaps and failures, and supports `resume_run_id`.

**Pacing, commits and concurrency (FACT, `ingest.py:171-186, 296-307`):** the network fetch
happens **before** the write transaction and the loop commits **once per symbol**, so the
SQLite write lock is never held across a 12.1 s paced wait. This is the same path that built
the existing 26 symbols and is what makes it safe to run while the paper worker holds its own
connection (`docs/SQLITE_CONCURRENCY.md`). **It is still a write to the live database and is
the orchestrator's action under approval A1 — no agent executes it.**

**Resume (FACT, `ingest.py:404-430`):** `signalforge data ingest-history --resume <run_id>`
skips symbols already in `symbols_ok`. Re-running without `--resume` is idempotent for bars —
`ingest_symbol` pre-reads the existing `(instrument, date, source)` set and counts repeats as
`bars_skipped` (`ingest.py:211-224`). One failing ticker does not abort the run
(`ingest.py:185-198`).

**Note (`cli.py:77`, `:99`):** every `data` command calls `ensure_not_engaged()` first, so the
backfill will refuse to start while the kill switch is engaged. Check it before scheduling
35 minutes of paced calls.

### 8.2 Then, and only then: Rule W1-COMPLETE

Unchanged from `w1_universe_preregistration.md` §6.4. After the backfill, run in-process,
read-only:

```python
validate_daily(session, <the 150 symbols>, source="massive", persist=False)
```

the *same function* gate 8 calls (`promotion.py:808`). Drop a candidate iff (a) it has no
`massive` rows at all, (b) more than 2.0% of the XNYS sessions between its own first and last
`massive` bar are absent, or (c) its first `massive` bar is later than **2018-09-08**. Replace
each drop with the next name in the §6 reserve, in strict rank order; that replacement is
ingested and must pass the same test. **Record every drop, reason and replacement before any
backtest is run.** `NBIS` is the named candidate (§6.1).

**Two source-wide hazards worth repeating.** **FACT (`validate.py:66-224`):** `db_unique_bars`
scans **every** `(instrument, date, source='massive')` group and `chronological_order` /
`no_duplicate_sessions` run over all listed symbols — a single duplicated bar anywhere in the
`massive` source fails gate 8 for the whole snapshot, including in the `META`/`FB` rows that
are not in this universe. **FACT:** omitting `source="massive"` anywhere downstream loads
`massive_grouped` too, duplicating every session 2025-01-03 → 2026-09-08 — **inside the sealed
window**. `source="massive"` must be asserted explicitly at every call site.

---

## 9. The keyed `DataSnapshot`

> **Key: `research_150_massive_10y_presealed_sel`**

**FACT (`db/models/research.py:237`):** `DataSnapshot.key` is `String(64)`; this key is
**38** characters.

**Collision check against both auto-generators (FACT):**

| Generator | Pattern | Can it produce this key? |
|---|---|---|
| `get_or_create_dataset_snapshot` unkeyed mint (`promotion.py:339`) | `universe_auto_{n}sym_{10-hex}` | **No** — fixed `universe_auto_` prefix |
| `run_screen` (`universe/screen.py:259`) | `liquid_us_{ISO date}_{8-hex}` | **No** — fixed `liquid_us_` prefix |

**Collision check against existing rows (FACT, queried read-only):** `data_snapshot` holds
exactly **10** rows, ids 1–10 (`universe_25_baseline_legacy`, `universe_25_baseline`,
`universe_24_ex_meta`, `universe_25_meta_continuity_corrected`, `liquid_us_2026-09-08`,
`universe_auto_2551sym_34051c18e4`, `liquid_us_2026-09-08_300d727a`,
`universe_auto_2312sym_300d727a6e`, `liquid_us_2026-09-08_ea6db586`,
`universe_auto_2181sym_ea6db58608`). **No row carries this key, and no row carries the
superseded key `research_150_massive_10y_2026-09-08` either** — nothing was created for the
sealed-window list, so there is no stale row to reconcile.

**Shadowing check (FACT, queried):** the reusable snapshots are ids 2 (25 symbols), 3 (24),
4 (25), 6 (2,551), 8 (2,312), 10 (2,181). **None has 150 symbols**, so no existing
`reusable_by_new_evaluations` row can absorb an unkeyed call on this set; and the live scan
universe is 25 symbols, so `research/scan.py:165`'s unkeyed mint cannot collide either. That is
today's state, not a guarantee — re-run both checks immediately before creating the row.

### 9.1 How to create it

Only **after** W1-COMPLETE passes and the final symbol list is fixed:

```python
get_or_create_dataset_snapshot(
    session,
    key="research_150_massive_10y_presealed_sel",     # EXPLICIT — never omit
    symbols=<the final 150, post-W1-COMPLETE>,        # list[str]
    description=(
        "150-symbol research universe, selection re-derived on a PRE-SEALED liquidity "
        "window under approval A0 (docs/research/diagnostics/w1_selection_presealed.md): "
        "the 15 ETFs of universe_24_ex_meta verbatim plus the top 135 U.S. common stocks by "
        "60-session median dollar volume over 2025-06-11..2025-09-05 (the 60 most recent "
        "massive_grouped sessions on or before 2025-09-07) among the eligible members of "
        "universe_screen_run 3, restricted to list_date <= 2016-10-17. No sealed-window "
        "(>= 2025-09-08) data entered the selection. Selection frozen before any backtest. "
        "Bars are split-adjusted AS OF the fetch date, NOT point-in-time; discovery was "
        "active-only, so the set is survivorship-biased."
    ),
    source_note="massive daily; END_OF_DAY; per-symbol history 2016-10-17..",
)
```

**`reusable` flag.** `get_or_create_dataset_snapshot` does not expose it; **FACT
(`db/models/research.py`, the column default):** `reusable_by_new_evaluations` defaults to
**`1` (true)**, which is what this row should carry — it is a live research universe meant to
be reused across Stage A/B, not an audit-history row like id 1. **Leave the default; do not set
it to 0.** Its being reusable is harmless to the shadowing check *in the direction that
matters*: shadowing only bites when a caller omits the key, and §9.2 below makes omitting the
key impossible in practice.

**FACT (`promotion.py:310-329`):** passing the key makes the row immutable-by-contract — a
later keyed call with a **different** symbol set raises `ValueError` rather than silently
reusing it. If W1-COMPLETE forces a drop **after** the row exists, the correct action is a
**new key** (`research_150_massive_10y_presealed_sel_r2`), never an edit. This is the reason to
create the row only after W1-COMPLETE, not before.

### 9.2 The CLI cannot target this snapshot — do not use it

**FACT (`cli.py:1330-1386`):** `signalforge evaluate-promotion` resolves its snapshot only via
`--dataset` (which maps through `fb_meta_universe_comparison.resolve_variant` and knows only
`baseline` / `ex_meta` / `meta_continuity_corrected`) or via `--symbols`, in which case `snap`
stays `None` and `evaluate_promotion` falls through to
`get_or_create_dataset_snapshot(session, symbols=symbols)` **unkeyed** (`promotion.py:504-505`).

> **`signalforge evaluate-promotion --symbols <the 150>` would mint
> `universe_auto_150sym_<fingerprint>` and would NOT use
> `research_150_massive_10y_presealed_sel`** — splitting the audit trail across two snapshot
> ids for the same universe and pinning the sealed test to the wrong row.

Use the in-process route: resolve the keyed row, then call
`evaluate_promotion(session, strat, symbols=…, source="massive", dataset_snapshot=<the keyed
row>, …)` directly. **Pre-integration assertion:** after any run, confirm
`StrategyPromotionEvaluation.dataset_snapshot_id` equals the keyed row's id and that **no
`universe_auto_150sym_*` row was created**.

**Standing (unchanged):** the two `PAPER_APPROVED` strategies (version ids 2 and 5) must
**not** be evaluated on this snapshot, and Stage B (the sealed look for
`volatility_breakout.short_swing` v0.2.0) remains deferred until Stage A evidence exists. Under
the orchestrator's look-count convention, the next sealed evaluation for that family is
**look 6** (k = 5 existing `StrategySealedTest` rows across all versions and snapshots).

---

## 10. Machine-readable companion

`docs/research/diagnostics/w1_selection_presealed.json` carries `snapshot_key`, `etfs` (15),
`common_stocks` (135, in strict rank order), `reserve` (20, in strict rank order),
`selection_window`, the full `criteria` block, the `liquidity_floor`, the
`comparison_vs_sealed_window` block (overlap, added, removed), the `ingestion` block (the 126
tickers to backfill), and `per_symbol` / `per_symbol_reserve` records carrying, for each
ticker: the pre-sealed median dollar volume, sessions present in the window, rank among all
eligible, CS rank under **both** windows, `list_date`, exchange, locale, active flag, SIC code
and group, market cap, the screen's own 20-session mean ADV, and whether the name was in the
sealed-window 150.
