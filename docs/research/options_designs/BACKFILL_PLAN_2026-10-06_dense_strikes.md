# Bounded dense-strike backfill plan — SPY / QQQ / IWM (2026-10-06) — NOT EXECUTED

**Status: PLAN.** Nothing in this document has been run. No provider call was made, no row was
written, no snapshot was created, no strategy constant was changed. It records (A) whether the
missing exact-$8 wing in snapshot 17 was *never collected* or *never listed*, (B) a bounded
collection plan with hard caps, and (C) whether that plan would actually change the funnel in
`REJECTION_BREAKDOWN_2026-10-06_snapshot17.md`. The honest answer to (C) is at the end and it
is not favourable to running (B) as a route to entries.

Everything read for this plan is a count, a strike identity, a date, a run-provenance field or
source code. Sources: `src/signalforge/data/options_cycles.py`, `options_backfill.py`,
`adapters/massive_options.py`, `research/options_scope.py`, `research/options_evidence.py`,
`research/options_strategies/short_vertical.py`; `ingestion_run` 44's `gaps_json` and `notes`;
`data_snapshot` 16/17; `dbstat` page counts; D1 §3.3/§3.3a/§7.4/§7.5/§12; D5a Amendment 3;
IO2_RUNBOOK §0, §6, §9, §12.

---

## A. Uncollected, or never listed?

### A.1 What the 17-rung ladder requested

`LADDER_17` (D1 §3.3, `options_cycles.LADDER_17`) is defined in moneyness
`m = K/R - 1` against the cycle's point-in-time reference close `R` taken on the DTE-60
`entry_as_of` session:

```
m in { 0, +/-0.015, +/-0.030, +/-0.045, +/-0.060, +/-0.080, +/-0.100, +/-0.125, +/-0.150 }
```

`select_ladder` resolves each rung to the single **listed** strike nearest `R(1+m)` inside the
+/-15% band, de-duplicates, and requires >= 7 rungs per side. Run 44's provenance records the
result for every (underlying, cycle): `selected_calls = 17`, `selected_puts = 17` on every
covered cycle (IWM: 15-17), i.e. 34 contracts per cycle, 3,044 contracts in total for the three
index ETFs (SPY 1,088; QQQ 1,020; IWM 936), 124,806 bars.

Adjacent rungs are therefore `0.015R` apart near the money and `0.020R`-`0.025R` in the wings.
At `R ~ 500` (SPY) that is $7.50 / $10 / $12.50 before rounding to a listed strike; at
`R ~ 450` (QQQ) $6.75 / $9 / $11.25; at `R ~ 200` (IWM) $3 / $4 / $5. **The ladder contains a
pair exactly $8 apart only by rounding coincidence** — which is precisely what the funnel found:
SPY cycles at the 500-540 level and IWM cycles where two 3-4-dollar rungs compound to 8 are the
only cases that reached the credit floor. The stored grids in the breakdown's §2 confirm it:
SPY median spacing 7-10, QQQ 6-10, IWM 3-4.5; strike pairs exactly $8 apart exist on 16 of 21
SPY expiries, 7 of 19 QQQ, 21 of 21 IWM — but only at particular rungs, not at the rung the
delta rule selects.

### A.2 What the exchange listed — stored evidence

The listing endpoint is `GET /v3/reference/options/contracts?underlying_ticker=...
&expiration_date.gte=E&expiration_date.lte=E&limit=1000&sort=expiration_date&as_of=<entry>`
(`MassiveOptionsAdapter.fetch_contracts_page`). With `as_of` it returns **every contract live
on that date for that expiry**, paginated by `next_url`; the backfill records per cycle the
page count, whether `next_url` was exhausted, and the **unfiltered** listing's distinct-strike
count and `[min, max]` (`_select_cycle` → `ladder_rungs_seen`, `ladder_min_strike`,
`ladder_max_strike`). The raw JSON responses were **not** stored (`raw_payload_cache` holds only
`daily_bars/*` payloads), so the full as-of strike list is not in the database — only its
count and range.

From run 44's `gaps_json` (FACT, stored):

| underlying | covered cycles | distinct strikes listed as-of entry (min / median / max) | listing range example | pages | selected per cycle |
|---|---|---|---|---|---|
| SPY | 32 / 34 | 85 / 180 / 245 | 2023-11-17: 141 strikes over 210-560 | 1, `next_url` exhausted on every cycle | 34 |
| QQQ | 30 / 34 | 30 / 144 / 253 | 2023-11-17: 156 strikes over 160-515 | 1, exhausted | 34 |
| IWM | 30 / 34 | 52 / 104 / 183 | 2023-11-17: 119 strikes over 90-260 | 1, exhausted | 30-34 |

141 strikes over a $350 range is a mean spacing of $2.5 including the far wings; a listing with
$5 wings and $1 near the money fits that count, a uniform $5 or $10 grid does not. The vendor
listing is complete (one page, `next_url` exhausted, `rows_unparseable = 0`, basis
`vendor_as_of`), so the count is the exchange's point-in-time grid, not a truncation.

**INFERRED (labelled):** that the near-the-money increment is exactly $1.00 for all three ETFs
across the whole window. It follows from the stored counts plus exchange convention (SPY, QQQ
and IWM list $1 strikes near the money on monthly expiries; D1 §7.4 F48 recorded SPY's $1.00
ladder as established over +/-8% of a ~770 reference, and D1 §7.4 explicitly flagged "US index
ETFs commonly widen to $5 in the wings"). It is not read from stored strike lists, because the
lists were not stored. The dense run itself would make it FACT: the as-of listing is re-fetched
anyway and its full strike set would be recorded this time (§B.6).

### A.3 Verdict

**UNCOLLECTED.** The exact-$8 wing is missing from snapshot 17 because `LADDER_17` requested 17
strikes per side from a listing of 85-253, not because the strike does not exist:

* in all 44 stage-(d) stops the wing strike `K_short -/+ 8` lies inside the as-of listing's
  `[min, max]` for that cycle; on SPY and IWM it is an integer dollar strike (every stored
  strike is an integer), on QQQ it is an integer in 10 of 16 cases and a `.78` offset in the 6
  where the ladder picked an adjusted-series short strike (see §C.4);
* in 0 of 44 is the wing stored-but-illiquid;
* the ladder-selected counts (17 per side) versus the listed counts (85-253 per cycle) are
  stored facts; the $1 increment at the money is exchange convention, inferred.

Evidence quality: **FACT** for "requested 17 of 85-253 listed strikes per cycle, listing
complete"; **INFERRED** for "the specific $1 strike at `K_short -/+ 8` was among them". The
inference would fail only on a cycle whose as-of listing had a $5 or wider increment at the
0.20-delta strike — not consistent with the stored counts, and never observed on these ETFs.

---

## B. The bounded plan (not executed)

### B.1 Scope — identical cycle rule and window, three underlyings, a finer rung set

* Underlyings: **SPY, QQQ, IWM only** (Amendment 3's set; nothing is added).
* Window **2023-09-04 → 2026-09-04**, `monthly_third_friday`, `dte_entry 21-60`,
  `pre_entry_buffer_sessions 5`, `reference = massive close, staleness <= 3`,
  `strike_listing_basis = vendor_as_of`, `require_shares_per_contract = 100`: unchanged.
* The permitted response under D1 §12 `LADDER_SHORTFALL_RESPONSE` and IO2_RUNBOOK §9 is "drop
  the underlying **or pre-register a finer rung set**". Amendment 3 took the first; this plan is
  the second, applied to the already-dropped-to set. It is **not** a loosening of
  `MIN_RUNGS_PER_SIDE`, `LADDER_BRACKET_MIN_RUNGS` or any gate fraction — those stay as D1 §12
  states them and the dense set satisfies them trivially.

### B.2 Strike set — $1 spacing inside the band the frozen strategy can actually select from

Not the whole +/-15% chain. The band is derived from v0.1.2's own selection rule and declared
as a pre-registered constant **before** any dense row exists.

The short strike is the OTM strike whose own-print inverted IV gives
`|delta|` nearest 0.20 within +/-0.05 (`short_delta_target`, `delta_tolerance`), capped at
0.35. For Black-Scholes with dividend yield `q`, at `T = 35/365` (the signal DTE):

```
puts :  m_short(D, s) = -s*sqrt(T) * N^-1(1 - D) + (r - q + s^2/2) * T
calls:  m_short(D, s) = +s*sqrt(T) * N^-1(1 - D) + (r - q + s^2/2) * T
        D in [0.15, 0.25]   (0.20 +/- 0.05; the 0.35 cap is never the binding edge)
        s in [0.12, 0.45]   (Stage A design range, upper end trimmed from 0.60 — see note)
        r = 0.04, q = 0.013 (the index ETFs' derived q is 0.010-0.016 on the pre-sealed span)
```

giving `m_short` in **[-0.131, -0.024]** for puts and **[+0.025, +0.159]** for calls.
(`sqrt(T) = 0.3097`; `N^-1(0.85) = 1.036`, `N^-1(0.75) = 0.674`; at `s = 0.45`,
`s*sqrt(T) = 0.139`.) *Note on the 0.60 upper end:* at `s = 0.60` the 0.15-delta put sits at
`m = -0.17`, outside the +/-15% listing band the ladder itself is bounded by; the band below is
therefore stated at `s <= 0.45` and a cycle whose IV exceeds that at the signal session is
accepted as a possible stage-(c)/(d) non-entry and counted.

Add the wing, a reference-drift margin and one strike of slack:

```
W = 8.00           declared width (unchanged)
D = 0.05           drift of spot between the DTE-60 reference session and the DTE-35 signal
                   session (~1 sigma at s = 0.20 over 17 sessions: 0.20 * sqrt(25/365) = 0.052)
slack = 1 strike   so the rounding to the listed grid never clips the band edge

puts : K in [ R(1 + m_lo - D) - W - 1 ,  R(1 + m_hi + D) + 1 ]  =  [ 0.819 R - 9 ,  1.026 R + 1 ]
calls: K in [ R(1 + m_lo - D) - 1 ,      R(1 + m_hi + D) + W + 1 ]  =  [ 0.975 R - 1 ,  1.209 R + 9 ]
```

Rounded to whole dollars; **only strikes present in the as-of listing are requested** (no
synthetic strikes, no interpolation). The ITM side is deliberately not collected on either
right — the strategy sells OTM only, so ITM strikes can never be selected. A cycle whose spot
has moved more than `D` from `R` by the signal session may still miss its wing; that is
accepted and will show as a stage-(d) count, not patched after the fact (the 2025-04 cycle,
spot -14% from `R`, is the known instance).

Pre-registered constant for the new rung set (to be added to `options_cycles.py`, next to
`LADDER_17`, not replacing it):

```
DENSE_1USD_BAND_v1 = {
  "increment_usd": 1.00, "width_usd": 8.00, "drift_margin": 0.05, "strike_slack": 1,
  "put_band":  (0.819, -9.0, 1.026, +1.0),   # K in [a*R + b, c*R + d]
  "call_band": (0.975, -1.0, 1.209, +9.0),
  "sigma_range": (0.12, 0.45), "delta_range": (0.15, 0.25), "T_days": 35,
}
```

### B.3 Size estimate and HARD caps

Contracts per cycle at $1 spacing: `puts = 0.207 R + 10`, `calls = 0.234 R + 10`, total
`0.441 R + 20`, using the cycle reference prices already recorded in run 44 (pre-sealed
ranges: SPY 436-600, QQQ 365-560, IWM 173-230; whole-window averages ~520 / ~450 / ~205):

| underlying | contracts / cycle (avg R) | x 34 cycles | observed bars / contract (run 44) | rows |
|---|---|---|---|---|
| SPY | ~249 | ~8,470 | 39.7 | ~336,000 |
| QQQ | ~218 | ~7,420 | 41.2 | ~306,000 |
| IWM | ~110 | ~3,740 | 38.7 | ~145,000 |
| **total** | **~577** | **~19,600** | 41.0 | **~800,000** (D1's 48.09 sessions/contract upper figure: ~945,000) |

Storage at observed bytes per row (`dbstat`, live DB): `option_aggregate_daily` table
78,245,888 B / 428,070 rows = **183 B/row**; its six indexes 69,369,856 B = **162 B/row**;
**345 B/row all-in**. 1.1M rows → **~380 MB**. `option_contract`: 1,847,296 B / 13,816 rows =
134 B/row → 22,000 contracts ≈ 3 MB.

Requests: one aggregates call per contract (`fetch_option_aggregates`, whole fetch span in one
call) + one as-of listing per cycle (102) + retries (<= 5 per request, D1 §7.6). The three
ETFs' 3,044 ladder contracts are **re-fetched under the new label** (§B.5), so the total is
the full dense set.

| cap | value | what refuses the run |
|---|---|---|
| max contracts (new label, all three) | **22,000** | `_select_cycle` already raises when a cycle resolves above `max_contracts_per_cycle`; the dense ladder sets that guard to **320** per cycle and the run refuses (does not truncate) a cycle above it; the run-level total is checked before each cycle is fetched |
| max `option_aggregate_daily` rows written | **1,100,000** (~380 MB) | `max_total_bars` on the run — the existing `EXCL_BAR_BUDGET_EXHAUSTED` path stops at a committed cycle boundary; the ceiling is **per run** and is below D1 §12's 2,000,000 |
| max provider requests | **25,000** (19,700 + 102 + retry headroom) | a request counter in run provenance; reaching it ends the pass at the next cycle boundary with `stopped: max_requests` |
| pacing | **12.1 s** (`options_min_request_spacing_s`, the only pacing the repo has verified; recorded in `pacing_s_passes`) | a run resumed at a different pacing is recorded as such (`_carry_pacing_history`); the dataset identity does not depend on pacing |
| max wall-clock | 25,000 x 12.1 s = **84 h paced** → at most **9 passes x 590 min** (`RunBounds.max_minutes = 590`, IO2_RUNBOOK §3.2 nightly windows; one cycle ≈ 2 x 320 x 12.1 s ≈ 2.2 h worst case, so a pass may overrun by at most one cycle) | `RunBounds`, unchanged |
| provider tier | at 12.1 s the plan is ~68 h of paced requests. The vendor's paid options tiers remove the 5-requests/minute limit (D1 §7.5 OQ-2 — **unverified in this repo**; `docs/MARKET_DATA_SETUP.md` documents no options plan). If and only if a faster pacing is verified and recorded, the same request budget runs in hours rather than nights; the caps above do not move. |

### B.4 Resumability

Unchanged mechanics: `backfill_option_cycles(... resume_run_id=...)`, committed
`(underlying, cycle)` units, `_existing_dates_many` skipping bars already stored for the
label, `_refuse_parameter_drift` refusing a resume whose ladder/band/basis differ from the
run's recorded provenance, and the `_Phases` read / network / write discipline (no transaction
held across network I/O; worker lock respected). Route A (bulk file, merge back) as in
IO2_RUNBOOK §3/§7 is preferred; the merge re-keys the run and the new snapshot records the new
id.

### B.5 Provenance — what changes and what must NOT

**Changes (new identity):**

* A **new `IngestionRun`** (kind `options_cycle_backfill`) whose provenance records
  `ladder_id = "DENSE_1USD_BAND_v1"`, the band constants, `max_contracts_per_cycle = 320`,
  `max_total_bars = 1_100_000`, `max_requests = 25_000`, `strike_listing_basis = vendor_as_of`,
  and — new — the **full as-of strike list per cycle** (identities only), so A.2's inference
  becomes fact.
* A **distinct option-row label**, e.g. `source = "massive_options_dense1"`, on every
  `option_contract` / `option_aggregate_daily` row the run writes. This is load-bearing:
  `load_option_chain_series` loads **every** contract stored under `(underlying, option_source)`
  regardless of ingestion run, so dense rows written under `massive_options` would silently
  change what snapshot 17 loads while its key stayed the same. The label keeps snapshot 17
  byte-for-byte reproducible and makes the dense dataset a different dataset by construction
  (R6 per-data-kind no-blend). The 3,044 ladder contracts are re-fetched under the new label
  rather than copied, so the new dataset has one provenance.
* `build_options_scope` emits the chosen ladder's own definition (today it hard-codes
  `LADDER_17`'s offsets) → `options_scope_json.ladder` differs → `options_scope_hash` differs →
  a **new snapshot key** (`canonical_options_snapshot_key`), e.g.
  `options_idx3_massive_dense1_2023-09-04_2026-09-04_<hash>`.
* A **D5 Amendment 4** sibling file pre-registering `DENSE_1USD_BAND_v1` and the new label, at
  k = 0, before any dense row exists; D5 Appendix P gains one dated pointer line (the only
  change to D5, so `preregistration_digest` moves by that pointer and nothing else).

**Must NOT change:**

* `short_vertical.py`: no parameter, threshold, floor, width, tolerance, cost model, axis or
  OAT set. v0.1.2 stays v0.1.2.
* `OptionsEvaluationConfig` defaults — hence `options_config_hash`. The dense ladder is selected
  by an explicit CLI argument recorded in run provenance, **not** by a config default, because
  the evaluate pre-flight refuses any snapshot whose recorded `options_config_hash` differs
  from the config in force; a default change would make snapshot 17 un-evaluable.
* D1 §12 constants, including `LADDER_17` (kept, additive), the gate 0.c/0.d floors,
  `MIN_RUNGS_PER_SIDE`, `LADDER_BRACKET_MIN_RUNGS`, `BACKFILL_MAX_TOTAL_BARS = 2,000,000`.
* The D5 text and digest, except the Appendix P pointer.

**Preserved results:** `data_snapshot` 16 and 17 (rows, keys, `reusable_by_new_evaluations`),
`ingestion_run` 44 and 45 and their rows under `massive_options`, the merged bulk-file history,
and **k = 0** — a backfill is coverage-only (IO2_RUNBOOK §0) and the new snapshot's dry run,
like snapshot 17's, writes no evaluation row and spends no look. The OR-0c pooled/per-symbol
question is unchanged by this plan and still has to be decided by the operator for whichever
snapshot is evaluated.

### B.6 Order of operations (if the operator chooses to run it)

1. Commit Amendment 4 (constants, label, caps) — k = 0 attestation as in Amendment 3 §0.2.
2. Code: ladder registry + `--ladder DENSE_1USD_BAND_v1` + explicit label + per-cycle strike-list
   provenance + request counter + tests. No strategy file touched.
3. Route A bulk run, nightly windows, `coverage-report` only (IO2_RUNBOOK §6) between passes.
4. Merge, `options q-series` (idempotent), `options snapshot --dry-run` → new key.
5. `options_rejection_breakdown.py --snapshot-key <new>` — counts only, pre-sealed.
6. Only then decide whether a `--confirm` evaluation (look 1) is worth spending.

---

## C. Would it resolve stages (d) and (e)? — explicit

### C.1 Stage (d) — yes, mechanically

All 44 stage-(d) stops are "exact wing NOT STORED"; the wing strikes are integer dollars inside
each cycle's as-of listing range. With $1 strikes collected over §B.2's band, the frozen
`_pick_wing` finds a print-eligible strike at exactly `K_short -/+ 8` whenever that strike
printed with `volume >= 10` and `transactions >= 5` on the signal session. Expectation: 44 → ~0
at stage (d), subject to (e) below. The 6 stage-(b) and 2 stage-(c) stops are untouched by more
strikes (missing expiries; no delta match), so the ceiling is **55 of 63** sessions reaching
stage (d) with a wing available.

### C.2 Stage (e) — not binding so far; unknown for the new far-OTM $1 strikes

Stage (e) stopped 0 of 63 sessions, and on all 11 sessions where the exact $8 wing happened to
exist it was print-eligible. The dense set adds strikes further OTM and between the ladder's
rungs; whether a $1 wing 8 dollars below a 0.20-delta SPY strike prints 10 lots on a given
session is **inferred likely, not stored** (volume may never be inspected to find out — D1
§10.2). If it does not, the strategy's non-entry is `d` (no eligible wing), not a rewritten
width.

### C.3 Stage (f) — the stage the plan does NOT address, and it is the binding one

**Of the 11 pre-sealed sessions on which an exact $8 wing existed and was print-eligible, 0
cleared the credit floor** (`net_credit / 800 >= 0.150` at the adverse fill). That is the
frozen strategy's own verdict on the only sessions where the wing question did not arise, on
SPY (5), QQQ (1) and IWM (5), on signal sessions spread over 2023-12 to 2025-06. Moving the 44
stage-(d) sessions to stage (f) changes which gate stops them; nothing in the stored evidence
suggests it changes the count of selectable structures. The 11 are a biased sample (cycles
where LADDER_17's rounding happened to yield an $8 gap), but they are the only stored evidence,
and Amendment 2 §4 itself put the attainable adverse ratio at 0.094-0.181 against a 0.150 floor
— a band whose lower half is below the floor by construction.

**Explicit answer: more data resolves stage (d) and very probably leaves stage (e) clear, but
on the stored evidence it does not produce entries, because stage (f) — the pre-registered
credit floor at the adverse fill — has stopped every session that reached it. Expected
selectable count after the dense backfill, if the 0/11 rate holds: ~0 of 63.** Running §B
would convert a coverage question into a cleanly-measured credit-floor question (~55 sessions
at stage (f) instead of 11) at a cost of ~68 paced hours and ~380 MB; it would not, on present
evidence, make v0.1.2 evaluable with a non-zero population. Loosening the floor, the width or
the delta band in response is R4-forbidden; the pre-registered routes are a new version at a
fresh look (R3) or stopping.

### C.4 Two data-quality observations (counts/identities, for the record)

* QQQ's stored grid contains 69 non-integer strikes (`.78` / `.22`), adjusted-series contracts
  the ladder selected as "nearest" (`shares_per_contract = 100`, so gate 0.h did not refuse
  them). In 6 QQQ signal sessions the chosen short strike is one of them (414.78, 419.78,
  454.78, 474.78, 509.78, 494.78), and the nearest widths are then 5 / 9.78 / 10 — never 8. A dense run
  should record, not filter, them; whether the standard and adjusted series should be
  distinguished is a D1 question to pre-register, not a post-hoc exclusion.
* Six pre-sealed cycles have **no stored contracts**, and run 44's provenance says why:
  QQQ 2024-01-19 `insufficient_rungs_per_side` (91 strikes listed), QQQ 2024-02-16
  `reference_price_outside_ladder` (30 strikes listed), IWM 2025-09-19
  `insufficient_rungs_per_side` (68 listed), and **2025-04-17 for all three** —
  `no_contracts_returned` with `ladder_rungs_seen = 0`. The last is a **calendar defect in
  the backfill, not an empty exchange listing**: `options_cycles.third_friday` keys the cycle
  as 2025-04-18 (Good Friday, exchange closed) while the listed expiry is Thursday 2025-04-17
  (`options_calendar.monthly_expiry(2025, 4)` returns 04-17), so the as-of listing for
  `expiration_date = 2025-04-18` is genuinely empty. The same defect produces the
  `no_contracts_returned` exclusions for 2026-06-19 (Juneteenth) on all three. A dense run
  must key cycles on `options_calendar.monthly_expiry` (or request the holiday-adjusted date);
  that is a bug fix to the fetch path, recorded in provenance, and not a strategy change.
