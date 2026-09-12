# D5 — Amendment 1: a reachable credit floor, a version-fixed R, and OQ-1 ratified

**Amends:** `docs/research/options_designs/D5_first_strategy_preregistration.md` (rev 2).
**Applies to:** `options_short_vertical.medium_swing` **v0.1.1** (supersedes v0.1.0).
**Written:** 2026-09-12. **Status: PRE-REGISTRATION — amendment legitimate only at k = 0.**

---

## 0. Why this is a sibling file and not an edit to D5, and why it is legitimate today

### 0.1 Why a sibling file

D5 has no explicit amendment clause, so the question is settled by reading its own disclosure
discipline. Three things in D5 forbid editing it in place:

1. **§0's attestation is scoped to the pass that produced the document** ("During the pass that
   produced this document the only database access was read-only `SELECT` … no file under `src/`
   or `tests/` touched"). This amendment is produced by a pass that *does* change `src/` and
   `tests/`. Writing the two passes into one document makes the attestation unreadable — a
   reader can no longer tell which sentence was written under which discipline.
2. **§0 pins every line number to commit `5b41a61`** and warns at length about the damage stale
   citations did. New citations resolved against a different tree do not belong inside that pin.
3. **§14.3 closes with a load-bearing claim: "No frozen threshold is moved anywhere in this
   document, in either revision."** This amendment **moves frozen thresholds** —
   `min_credit_to_width` 0.25 → 0.10, `width_pct` → `width_usd`, and the axis membership of the
   grid. Putting those inside D5 would make §14.3 false, and §14.3 is exactly the sentence a
   later reader uses to decide whether D5 can be trusted as a record of what was fixed *first*.

The R1 value of a pre-registration is that the superseded numbers stay legible. So: D5 is left
byte-identical in every pre-registered section, and this file carries the amendment. The single
change made to D5 is a **dated pointer appendix appended after §14**, which moves no threshold,
asserts nothing new, and exists only so that a reader of D5 alone cannot act on a number this
document supersedes. §14.3's claim survives it verbatim.

### 0.2 Why an amendment is legitimate now and never again

**FACT.** `count_sealed_looks` keys on `Strategy.name`
(`src/signalforge/research/promotion.py:647`) and no row in `strategy` begins `options`
(D5 §12). **k = 0 for `options_short_vertical.*`.** No sealed look has been consumed, no
options evaluation has been run, no option price, IV, greek, credit, return or P&L has been
inspected by this pass either.

Changing a pre-registered parameter before the first look costs nothing and buys correctness.
Changing one after the first look is the R1 violation the whole ladder exists to prevent. D4
§2.8a states the same rule in its own words for exactly this defect: *"Re-specify the widths in
D5, before any outcome is observed. Narrower widths … is a design choice and is legitimate
now."* — and names the forbidden alternative, *"raising the cap after a gate-3/gate-4 result at
a width that breached it."* This amendment takes the permitted route.

**Attestation for this pass (FACT).** No database was opened. The worktree this amendment was
written in contains no `data/` directory at all, so `data/signalforge.sqlite` was not, and could
not have been, read. No provider API was called. Every number below is closed-form
Black-Scholes arithmetic on the parameters D5 and the decisions record already fixed, computed
by `scripts`-free local evaluation of `src/signalforge/options/blackscholes.py` and
`src/signalforge/backtest/options_costs.py`, and every one of them is reproduced as a test
(`tests/research/test_options_short_vertical.py::test_the_credit_to_width_bound_table_*`) so the
amendment cannot be silently reverted.

### 0.3 Declared inputs that are assumptions, not measurements

Because no database was read, the Stage A price levels are **declared assumptions**, and the
band derived from them is reported with its sensitivity to a ±15 % error in them (§2.4).

| Input | Declared value | Class |
|---|---|---|
| `U` SPY / QQQ / IWM | **$660 / $590 / $240** | assumption, 2026-09-12 approximate levels; sensitivity in §2.4 |
| `q` SPY / QQQ / IWM | 0.013 / 0.006 / 0.013 | assumption **for this derivation only**; at evaluation time `q` is sourced per underlying per session (D5 §2.4, decision 11) and an unsourced `q` is still a non-entry |
| listed strike increment on SPY/QQQ/IWM monthly third-Friday chains | **$1.00** | market-structure assertion, same class as `tick_grid` (D2 §6.3); a **coarser** realised ladder is the conservative direction — it produces non-entries, never a rewritten width |
| `r`, DTE, cost model | 0.04, 35, `PREREGISTERED_COST_MODEL` | unchanged from D5 §2.4, frozen (R4) |

---

## 1. The four defects, and what this amendment does with each

| # | Defect (source: `docs/research/DECISIONS_2026-09-12_wave2_findings.md`) | Resolution | Section |
|---|---|---|---|
| 1 | `min_credit_to_width` floor 0.25 and grid values 0.25 / 0.30 are **unreachable**: the credit/width of an arbitrage-free defined-risk short vertical is bounded near the short delta, and the adverse spread charge takes a further 20-48 % out of it | floor band **derived** from the Black-Scholes bound minus the adverse charge; baseline **0.10**, axis **(0.10, 0.13)**, OAT loosening value **0.05** | §2 |
| 2 | D4 §3(d) (fixed R per version) vs D5 §4.1 (`width_pct` as a fraction of `U`): R scales with price, so a multi-underlying v0.1.0 **fails gate 0.5** | width redeclared as **`width_usd = $2.00` of strike distance per contract**, fixed for the version; R scale **$200.00** identical on every underlying; wing placement becomes exact | §3 |
| 3 | Gate 0.i: two of three declared widths breach decision 4's **$250** per-structure cap | `width_usd = $2.00` → hard max loss **$201.60**, a **19.4 %** margin no parameter inside the version can breach; `$3.00` rejected by arithmetic, `$2.50` rejected on ladder placeability | §3.3 |
| 4 | **OQ-1** — `MEDIUM_SWING` vs `POSITION`, baked into the family name and hence into `count_sealed_looks` | **ratified `MEDIUM_SWING`**; `POSITION` is arithmetically impossible for this structure | §5 |

Two further items this arithmetic forces into the open, neither of which was on the list:

| # | Found here | Section |
|---|---|---|
| 5 | At the cap-compliant width the **target-win outcome is negative in R** on every Stage A cell computed. No width exists that is simultaneously cap-compliant and cost-viable. Pre-registered as **F14**, before the first look. | §4 |
| 6 | Gate 0.i's **aggregate** leg ($1,000) admits **4** concurrent structures against a 14-underlying declared population. Deterministic behaviour pre-registered under both operator rulings. | §3.5 |

---

## 2. The reachable `min_credit_to_width` band, derived

### 2.1 The upper bound is the Black-Scholes bound, and it is the short delta

For a put credit spread the net credit per share is `P(K_short) − P(K_long)`, and

```
dP/dK = e^{-rT} N(-d2)          # the risk-neutral probability of finishing ITM at K
```

which is **monotone decreasing** as `K` moves further OTM toward the wing. By the mean value
theorem the credit over a width `W$ = K_short − K_long` is `dP/dK` evaluated somewhere strictly
inside the strike range, hence

```
credit_print / W$   <=   e^{-rT} N(-d2) |_{K_short}   ~   |delta_short| + (N(-d2) - N(-d1) gap)
```

The ratio is therefore **bounded above by roughly the short delta and sits below it for any
width worth trading**. Measured at 35 DTE, `r = 0.04`, `W$ = 2.00`, over the Stage A price
levels × IV 0.15/0.30/0.60 (full table in §2.3):

| declared `short_delta_target` | `|delta|` selected | `credit_print / W$` observed |
|---|---|---|
| 0.12 | 0.118 - 0.123 | **0.109 - 0.158** |
| 0.20 | 0.197 - 0.209 | **0.196 - 0.253** |
| 0.30 (cap 0.35) | 0.296 - 0.306 | **0.281 - 0.364** |
| 0.30 (cap 0.28) | 0.265 - 0.279 | **0.251 - 0.341** |

**Every value of D5's axis 6 (0.25, 0.30) and of D5 §4.4's OAT table (0.20) sits at or above the
*print* ceiling of the baseline delta band — before a single cent of spread is charged.** That
is the defect, stated as arithmetic.

### 2.2 The adverse charge, and why it is large

D5 §3.3(4) applies the floor to the credit at the **adverse modelled fill**, not to the print —
a deliberate conservatism this amendment does not touch. The charge is

```
chi = 100 * ( s_short + s_wing ) / W          s = max($0.02, 0.03 * last_print)
```

`s` depends on the **leg prints**, not on the width, so `chi` scales as `1/W`. At `W$ = 2.00`
and `|delta| = 0.20`, `chi` ranges from **0.041** (IWM, sigma 0.15, legs at $1.35/$0.96) to
**0.478** (SPY, sigma 0.60, legs at $15.04/$14.53). This is the term D5 §6.2a's representative
structure understated: it assumed legs of $1.95/$0.62 against a $500 width, a (sigma, strike)
pair that no 35-DTE 0.20-delta chain on a $500 underlying admits.

### 2.3 The bound table — reproduced as a test

`adverse_ratio = credit_print/W$ − chi`, 35 DTE, `r = 0.04`, `W$ = 2.00`, baseline delta band.
Reproduced by `test_the_credit_to_width_bound_table_is_reproduced`.

| `U` | sigma | `K_short` | `|delta|` | print/W | charge | **adverse/W** |
|---|---|---|---|---|---|---|
| 660 | 0.15 | 637 | 0.199 | 0.2025 | 0.1275 | **+0.0750** |
| 660 | 0.30 | 615 | 0.202 | 0.2231 | 0.2481 | **−0.0250** |
| 660 | 0.60 | 576 | 0.200 | 0.2527 | 0.4777 | **−0.2250** |
| 590 | 0.15 | 570 | 0.202 | 0.2033 | 0.0983 | **+0.1050** |
| 590 | 0.30 | 550 | 0.201 | 0.2216 | 0.1966 | **+0.0250** |
| 590 | 0.60 | 515 | 0.200 | 0.2515 | 0.4265 | **−0.1750** |
| 240 | 0.15 | 232 | 0.209 | 0.1957 | 0.0407 | **+0.1550** |
| 240 | 0.30 | 224 | 0.207 | 0.2192 | 0.0792 | **+0.1400** |
| 240 | 0.60 | 209 | 0.197 | 0.2438 | 0.1938 | **+0.0500** |

Over the full declared design space — Stage A × sigma ∈ {0.12, 0.15, 0.18, 0.20, 0.25, 0.30,
0.35, 0.40, 0.50, 0.60}, 30 cells — the attainable adverse ratio runs **−0.2250 … +0.1550**, and
is **positive in 21 of 30 cells**.

> **The reachable region is `(0, 0.155]`.** D5's floor (0.25) misses it by **at least 61 %**;
> its harder grid value (0.30) by **94 %**; its OAT loosening value (0.20) by **29 %**. v0.1.0
> as pre-registered enters nothing, anywhere, at any IV. This confirms the implementers'
> finding by construction rather than by observation.

### 2.4 The two grid values, derived rather than chosen

A floor must **bind** — D5 §1 makes it the design's only richness filter — without **emptying**
the design space, which is precisely the failure D5 §4.3 rejected `max_short_delta = 0.25` for.
The derivation therefore reads the values off the distribution of the attainable ratio over the
declared design space, at the baseline cell, with a stated rounding rule:

> **Rule.** Take the quartiles of the *positive* attainable adverse ratios over Stage A × the IV
> grid at the baseline `short_delta_target = 0.20` and `width_usd = 2.00`. Round **down** to the
> nearest 0.01 — rounding up moves toward the unreachable side, which is the entire defect being
> repaired. p25 is the OAT loosening value, the median is the baseline, p75 is the grid's harder
> second value.

| quantile | raw | rounded down | role |
|---|---|---|---|
| p25 | 0.0500 | **0.05** | §4.4 OAT loosening value (replaces 0.20) |
| median | 0.1000 | **0.10** | **baseline `min_credit_to_width`** (replaces 0.25) |
| p75 | 0.1350 | **0.13** | axis 6's harder second value (replaces 0.30) |

**Sensitivity to the §0.3 price assumption** (the only non-derived input):

| price scale | attainable max | p25 | median | p75 |
|---|---|---|---|---|
| 0.85 (−15 %) | 0.1600 | 0.0750 | 0.1200 | 0.1400 |
| **1.00 (declared)** | **0.1550** | 0.0500 | **0.1000** | **0.1350** |
| 1.15 (+15 %) | 0.1400 | 0.0500 | 0.0750 | 0.1300 |

Both grid values stay strictly inside the reachable region at ±15 %. At +15 % the harder value
0.13 is 93 % of the attainable maximum (0.14) — it binds hard, as the harder side of an axis is
supposed to, and is not empty. Had p75 been rounded *up* to 0.14 it would have sat **exactly at**
the attainable maximum at +15 %, i.e. would have been a one-cell axis endpoint of the kind D5
§4.3 rejected `max_short_delta = 0.25` for. That is why the rounding rule rounds down, and it is
stated before the fact rather than after it.

### 2.5 Two consequences that must be disclosed, not smoothed over

1. **The credit floor is no longer a volatility filter; it is a cost filter, and its sign is
   inverted.** D5 §1 argued "a cycle whose options are too cheap cannot clear the credit floor",
   so the floor *was* the high-IV filter and no `iv_rank` axis was needed. With a **dollar**
   width the print ratio still rises with IV (0.2025 → 0.2527 at `U` = 660) but the charge rises
   faster (0.1275 → 0.4777), so the **adverse** ratio *falls* with IV. At `width_usd = 2.00` the
   floor now excludes the *rich* cycles and admits the quiet ones. This reverses the mechanism's
   own selection logic and it is recorded here, in advance, rather than discovered in a gate-8
   diagnostic. **No compensating filter is added** — adding one would be a new lever chosen
   without evidence. Instead: the **print** credit-to-width ratio and the realised charge are
   recorded per entry *and per non-entry*, so the inversion is a measured quantity at gate 8.
2. **The floor stays on the adverse credit.** Moving it to the print credit would restore the
   intended direction and would be a **loosening** — it would admit structures whose realistic
   credit is smaller than the floor. R4 forbids it and this amendment does not do it.

### 2.6 A constraint that the amended floor *relaxes*

D5 §3.4: the stop is a real stop only while `stop_multiple × c/W < 1`. At D5's floors the high
OAT value was near-degenerate (`3.0 × 0.30 = 0.90`, and effectively inert wherever a realised
credit reached `0.33 × width`). At the amended band the worst case anywhere in the design space
is `3.0 × 0.155 = 0.465 < 1`: **the stop binds at under half the width at every grid and OAT
value, on every cell.** §6 uses this.

---

## 3. R fixed per version: `width_usd`, not `width_pct`

### 3.1 What gate 0.5 actually requires (FACT)

`gate_0_5_structure` (`src/signalforge/research/options_gates.py:822-895`) recovers each trade's
gross width as `r_at_print + net_credit_at_print` and **fails unless every trade in the list
produces the same value and that value equals `identity.width_declared × identity.m_declared`**
(`single_scale`, `scale_matches`). `width_pct × U` produces one width per underlying, so a
multi-underlying run fails on `single_scale` — not as a bug, as the gate doing its job.

### 3.2 The two candidate resolutions, and the one rejected

**Rejected — widths declared per underlying price tier.** It keeps `R` bounded but puts several
R scales into one evaluation. Three reasons, in order:

1. **It does not satisfy gate 0.5 at all.** The gate admits exactly one scale per run. Tiers
   would require one run, one `StructureIdentity`, one sealed look and one `k` **per tier** —
   and `count_sealed_looks` keys on the family name, so three tiers under one name would
   understate `k` by 3× on the first evaluation.
2. **It fragments `n` on the axis that is already binding.** D5 §6.3b makes clustered
   cycle-months, not trades, the unit gate 4 can spend, and §6.3c shows the CI barely closes on
   the full population. Splitting it three ways guarantees it does not close.
3. **Tier boundaries are a free parameter with no derivation**, and they would sit on price —
   which correlates with the underlying set's liquidity selection, i.e. with the population.

**Adopted — one declared width in dollars of strike distance per contract.**

```
width_usd  =  $2.00        # strike distance, per contract, FIXED for v0.1.1
R_scale    =  width_usd * shares_per_contract  =  $200.00
R          =  R_scale - net_credit_received + entry_costs        # unchanged formula (D5 §3.5)
```

Identical on SPY, on QQQ, on IWM and on every single name in the §2.2 set. Gate 0.5's
`single_scale` and `scale_matches` both pass **by construction**, and
`width_selected_adaptively` stays `False`.

### 3.3 Choosing the number: the $250 cap and the strike ladder, jointly

Max loss is worst when the realised credit is smallest. The credit is bounded below twice: by
the floor `f`, and — because the strategy refuses `net_credit <= 0` outright
(`short_vertical._credit_floor_clears`) — by zero. So

```
R_max  =  width_usd * 100 * (1 - f) + entry_costs        entry_costs = $1.60 (2 legs)
R_hard =  width_usd * 100            + entry_costs        # the bound no floor can breach
```

| `width_usd` | gross `W` | `R_max` at f = 0.10 | `R_hard` (f = 0) | vs the **$250** cap | placeable on a $1.00 ladder |
|---|---|---|---|---|---|
| $1.00 | $100 | $91.60 | $101.60 | fits, +59.4 % margin | yes |
| **$2.00** | **$200** | **$181.60** | **$201.60** | **fits, +19.4 % margin on the hard bound** | **yes** |
| $2.50 | $250 | $226.60 | $251.60 | fits at f = 0.10 (+9.4 %) | **no** — not a multiple of $1.00 |
| $3.00 | $300 | $271.60 | $301.60 | **breaches by 8.6 % even at f = 0.10** | yes |
| $5.00 | $500 | $451.60 | $501.60 | **breaches by 80.6 %** | yes |

`$3.00` would need `f >= 0.172` to clear the cap at all and `f >= 0.255` for a 10 % margin;
§2.3 puts the attainable maximum at **0.155**, so no floor exists that makes `$3.00` compliant.
`$2.50` is rejected on **placeability**, not on the cap: the wing must land on a listed strike,
and $2.50 is not a multiple of the declared $1.00 increment.

> **Declared: `width_usd = $2.00`.** Gate 0.i's per-structure leg passes with a **19.4 % margin
> on a bound that no parameter setting inside v0.1.1 can breach** — not merely at the baseline
> floor. `structures_breaching_per_structure_cap` is **0 by construction**, and that is asserted
> by a test rather than left to a run.

**A fail-closed guard, not a comment.** `OptionsShortVertical.__init__` refuses any `width_usd`
whose `R_hard` exceeds `options_per_structure_max_loss`, exactly as it already refuses
`dte_target = 45`. A future width that breaches the cap is a `ValueError` at construction, not a
gate failure discovered after a backtest.

### 3.4 Exact wing placement replaces the 50 % width tolerance

D5 §3.3(3) allowed a realised width within ±50 % of `width_pct × U`. Under a declared dollar
scale that tolerance **is** the gate-0.5 failure: a run whose widths vary by ±50 % has three R
scales in it. So:

> **The wing is the listed strike at exactly `K_short ∓ width_usd`. If no such strike is
> listed, the cycle is a non-entry, counted `non_entry_width_not_placeable`.**
> `width_tolerance_pct` is fixed at **0.0**.

This is strictly more searching (R4): it can only remove entries, never add one. The coarse-
ladder hazard D5 §3.3(3) wrote the tolerance for is handled *better* by exactness — a $5.00
ladder cannot silently deliver a $5.00 width where $2.00 was declared; it delivers a non-entry.

### 3.5 The aggregate leg of gate 0.i — quantified, and deterministic under both rulings

Gate 0.i(ii) requires `max concurrent open R <= options_total_open_max_loss` ($1,000, decision
4). D5 §2.2 declares **14 underlyings**, all of which signal on the same monthly third-Friday
cycle, so the worst case is 14 simultaneously open structures:

```
14 * R_hard  =  14 * $201.60  =  $2,822.40        vs the $1,000 aggregate cap
permitted concurrent structures  =  floor(1000 / 201.60)  =  4
```

D4 §2.8a saw this coming ("admits one to five concurrent structures depending on width") and
never resolved it. A pre-registration may not bind on a rule it flags as unresolved (D5 §2.5's
own principle), so both branches are fixed **now**:

- **If the operator raises `options_total_open_max_loss` to `>= $2,825` (OP-4 below)**, the
  evaluated population is exactly as D5 §2.2 declares and nothing else changes.
- **Otherwise** the evaluation applies a portfolio concurrency cap of **4** open structures,
  priority by **ascending underlying symbol**. The priority rule is deliberately the dullest
  outcome-independent one available: any rule keyed on credit, IV, delta, width-fit or price
  would select on a quantity that correlates with the outcome, which is a selection channel.
  Entries beyond the cap are non-entries counted `skipped_portfolio_concurrency`, the count is
  gate-8 evidence, and D5 §6.3's required `n` is **not** met — an outcome §10's null option
  already anticipates and which is therefore not a surprise.

---

## 4. F14 — the cost-coverage finding, pre-registered before the first look

D5 §6.2b's target-win outcome in R is `w = 0.5·C/R − F/R`, where `F` is the four-crossing
round-trip friction. `F` is set by the **leg prints** and is nearly independent of the width;
`C` is proportional to the width. So `w > 0` requires a width, and the $250 cap forbids it.

At `width_usd = $2.00`, `short_delta_target = 0.20`, 35 DTE:

| `U` | sigma | `C` | `F` | `0.5C − F` | **`w` (R)** |
|---|---|---|---|---|---|
| 660 | 0.15 | $15.00 | $42.64 | −$35.14 | **−0.188** |
| 660 | 0.20 | $10.00 | $56.25 | −$51.25 | **−0.268** |
| 660 | 0.30 | −$5.00 | $87.44 | −$89.94 | **−0.435** |
| 590 | 0.15 | $21.00 | $38.67 | −$28.17 | **−0.156** |
| 590 | 0.20 | $10.00 | $51.24 | −$46.24 | **−0.241** |
| 240 | 0.15 | $31.00 | $17.02 | −$1.52 | **−0.009** |
| 240 | 0.20 | $30.00 | $21.71 | −$6.71 | **−0.039** |
| 240 | 0.30 | $28.00 | $33.18 | −$19.18 | **−0.111** |

**The winning outcome is a loss in every cell.** The minimum width at which `w` turns positive,
and the max loss it implies:

| `U` | sigma 0.15 | sigma 0.20 | sigma 0.30 |
|---|---|---|---|
| 660 (SPY) | $6 → R $513 | $8 → R $682 | $10 → R $842 |
| 590 (QQQ) | $5 → R $426 | $7 → R $595 | $9 → R $757 |
| 240 (IWM) | $3 → R $255 | $3 → R $254 | $4 → R $335 |

> **F14 (falsification criterion, keyed before any look).** At decision 4's $250 per-structure
> cap and D5 §2.4's frozen cost model, **no width exists that is simultaneously cap-compliant
> and cost-viable** for a 35-DTE short vertical at the declared delta band. The cheapest
> cost-viable structure in the table implies a max loss of **$254** — above the cap — and the
> Stage A index ETFs need **$426 to $842**. v0.1.1 is therefore pre-registered with the **§10
> null option as its expected disposition**, and the single thing that can change that is
> **OP-1**: the operator exercising decision 4's reserved right to raise
> `options_per_structure_max_loss` to at least **~$550** (SPY at sigma 0.15) or **~$900** (SPY
> at sigma 0.30). Raising it *after* seeing a gate-3 or gate-4 result at a breaching width is
> forbidden by D4 §2.8a and by this paragraph.

This does not make the evaluation pointless. It runs, it produces the count of entries the
amended floor admits, and it measures the inverted filter of §2.5 — all of which is evidence
about the structure. It makes the *disposition* predicted in advance, which is what R10 asks
for.

---

## 5. OQ-1 ratified: `Horizon.MEDIUM_SWING`

**FACT.** `Horizon` is a holding-period vocabulary and says so in the source
(`src/signalforge/domain.py:15-18`): `SHORT_SWING` "2-10 trading days", `MEDIUM_SWING`
"2-8 weeks", `POSITION` "2-6 months". It describes the period a position is *held*, not the
tenor of the instrument.

**The argument.** The holding period of this structure is bounded by its own **time stop**, not
by its DTE. Entry is on the first session with calendar DTE at or below `dte_target` inside
`[dte_window_lo, dte_window_hi]`; the time stop closes at `DTE <= time_stop_dte = 7`. So the
longest hold the baseline can produce is `35 − 7 = 28` calendar days = **4.0 weeks**, and at the
grid's other DTE value the bound is `21 − 7 = 14` days = 2.0 weeks. The `expiry − 1` force close
binds only where a print deferral carried the exit past the time stop and caps the hold at 34
days ≈ 4.9 weeks. Every one of those sits **inside** `MEDIUM_SWING`'s 2-8 weeks.

`POSITION` is not merely the worse fit — it is **arithmetically impossible**. Its lower bound is
2 months ≈ 60.9 days, which is **2.17×** the longest hold the baseline can produce (28 days),
**1.79×** even the deferral-extended force-close bound (34 days), and **4.35×** the bound at the
grid's 21-DTE cell (14 days). No trade the strategy can generate could be a POSITION trade under
any cell of the pre-registered grid. The map §1.1/§5.4's assumption was made on the instrument's
tenor rather than the holding period, and the reason it gave — "POSITION has no registered
strategy" — is a convenience about the registry, not a property of the trade.

**Mechanical consequence: none.** The only branch in the ladder keyed on horizon is gate 0's
INTRADAY branch (`promotion.py:981-1010`), which neither value enters. `MEDIUM_SWING` is in
`ResearchConfig.enabled_horizons` (`config/research.py:616-621`), and the choice additionally
preserves the standing fact that `POSITION` still has no registered strategy.

> **Ratified: `Horizon.MEDIUM_SWING`. The family name `options_short_vertical.medium_swing` and
> the strategy key are confirmed, `count_sealed_looks` keeps `k = 0`, and OQ-1 is closed.**

---

## 6. The amended `v0.1.1` spec

### 6.1 Parameters (supersedes D5 §4.1)

```python
@dataclass(frozen=True, slots=True)
class ShortVerticalParams:
    short_delta_target:   float = 0.20    # AXIS 1   unchanged
    max_short_delta:      float = 0.35    # AXIS 2   unchanged
    stop_multiple:        float = 2.0     # AXIS 3   PROMOTED from FIXED (§6.2)
    dte_target:           int   = 35      # AXIS 4   unchanged
    profit_target_pct:    float = 0.50    # AXIS 5   unchanged
    min_credit_to_width:  float = 0.10    # AXIS 6   WAS 0.25 -- unreachable (§2)
    width_usd:            float = 2.00    # FIXED per version -- WAS width_pct = 0.010 (§3)
    time_stop_dte:        int   = 7       # FIXED    unchanged
    dte_window_lo:        int   = 28      # FIXED    unchanged
    dte_window_hi:        int   = 45      # FIXED    unchanged
    delta_tolerance:      float = 0.05    # FIXED    unchanged
    width_tolerance_pct:  float = 0.0     # FIXED    WAS 0.50 -- exact placement (§3.4)
    min_leg_volume:       int   = 10      # FIXED    unchanged
    min_leg_transactions: int   = 5       # FIXED    unchanged
```

### 6.2 The grid — still 6 axes, still 96 points (supersedes D5 §4.2)

`MAX_GRID_POINTS = 120` and the grid is the full Cartesian product, so the shape constraint is
unchanged: six axes, at most one of them three-valued. `3 × 2 × 2 × 2 × 2 × 2 = 96 <= 120` ✓.

| # | Axis | v0.1.1 values | Baseline | Change from D5 §4.2 |
|---|---|---|---|---|
| 1 | `short_delta_target` | 0.12, 0.20, 0.30 | 0.20 | none |
| 2 | `max_short_delta` | 0.28, 0.35 | 0.35 | none |
| 3 | **`stop_multiple`** | **2.0, 3.0** | **2.0** | **new axis**, see below |
| 4 | `dte_target` | 21, 35 | 35 | none; 45 still excluded by derivation |
| 5 | `profit_target_pct` | 0.50, 0.75 | 0.50 | none |
| 6 | `min_credit_to_width` | **0.10, 0.13** | **0.10** | was (0.25, 0.30) — unreachable (§2.4) |

**`width_pct` leaves the grid and `stop_multiple` takes the slot.** Two independent reasons, and
the first is dispositive:

1. **Gate 0.5 forbids a width axis.** Its own evidence carries the rule verbatim: *"this R
   stream may not be pooled, averaged, bootstrapped together, or compared with any other
   structure's R stream."* A width axis puts two R scales into one gate-5
   `positive_fraction` / `neighbour_positive_fraction` statistic — the exact pooling the gate
   exists to prevent. `width_pct` was a legal axis in D5 only because that document had not yet
   noticed that R varied across its own baseline cell. D4 §3(d) says the same thing
   prescriptively: width is "a declared constant, evaluated one value per run, never selected
   per trade."
2. **D5 §4.2 named `stop_multiple` as the seventh parameter that deserved an axis** and was
   forced into the OAT table only by the 120-point cap. The slot is now free. Its second stated
   reason for exclusion — that the high value is near-degenerate (`3.0 × 0.30 = 0.90` of width)
   — **no longer holds at the amended floor**: §2.6 shows `3.0 × 0.155 = 0.465 < 1` everywhere,
   so 3.0 is a live, informative setting rather than an inert one.

`stop_multiple`'s second value is **3.0**, not 1.5, by D5 §4.2's own rule that the grid carries
the *harder* side: a looser stop leaves more tail in each trade, which makes gate 5's
60 %-positive and 75 %-neighbour thresholds harder to clear. 1.5 (the tighter, easier direction)
moves to the OAT table.

Baseline cell = `(0.20, 0.35, 2.0, 35, 0.50, 0.10)`. One-step neighbours: **7**, unchanged.

### 6.3 The OAT table (supersedes D5 §4.4, deltas only)

| Parameter | Fixed at | OAT values | Change |
|---|---|---|---|
| **`width_usd`** | **2.00** | **1.00, 2.00** | **new entry.** The cap-compliant alternative. §2.3/§4 predict in advance that 1.00 is cost-destroyed on SPY/QQQ (adverse ratio −0.05 at `U` = 660, sigma 0.15) and marginal on IWM; it is reported, non-gating, and is **not** offered as a selectable grid cell precisely because a "best cell" reading could select it |
| `stop_multiple` | 2.0 (now an axis) | **1.5** | the tighter direction; the grid carries the harder 3.0 |
| `min_credit_to_width` | 0.10 (axis) | **0.05** | was 0.20, which is outside the reachable region; 0.05 is the derived p25 and remains map §3.2's named failure mode (loosening the floor to reach for credit) |
| `width_tolerance_pct` | **0.0** | **(0.0)** | was 0.50 with OAT (0.35, 0.50). Exact placement is now structural (§3.4), so the parameter is degenerate by design; it stays listed so that R5's "a parameter in neither list is invisible" invariant holds |
| `profit_target_pct`, `time_stop_dte`, `dte_window_lo/hi`, `delta_tolerance`, `min_leg_volume`, `min_leg_transactions`, `r`, `contracts`, structure side rule | unchanged | unchanged | none |

### 6.4 Everything D5 fixes that this amendment does **not** touch

The underlying set and its fire-once shortfall ladder (§2.2), the window (§2.3), every pricing
input and the frozen cost model (§2.4), the `options_config_hash` rule (§2.5), cycle and signal
timing (§3.1), the regime filter and its one-session lag (§3.2), strike selection other than
wing placement (§3.3), the exits (§3.4), the R formula and the `−1R` clamp (§3.5), every gate-0
sub-threshold (§5), gate 7b's benchmark (§7), F1-F13 (§8), the arming preconditions (§9), the
variant budget and the null option (§10). **No gate threshold is moved by this amendment.**
Every change is either a correction of arithmetic that could not be satisfied, or a condition
that removes entries.

### 6.5 Numbers in D5 that are now superseded arithmetic

D5 §6.1, §6.2a-c and §6.3's forecasts were computed at `C/W = 0.25` and a $500 width. They are
**not re-derived here**, because the R-space break-even is scale-invariant — `w − l = 1.5·C/R`
and the pre-cost break-even stays 66.7 % at any floor — while the *cost* terms are not, and §4
supersedes them with the number that matters: at a cap-compliant width the target win is
negative in R. The gate-4 required-`n` tables in D5 §6.3 should be read as **upper bounds on
optimism**, and §4's F14 as the binding forecast. This is recorded as **OQ-9**.

---

## 7. Open questions after this amendment

- **OQ-1 — closed** (§5, ratified `MEDIUM_SWING`).
- **OQ-9 (new).** D5 §6.2/§6.3's forecast tables are superseded by §4 and are not re-derived.
  Whoever builds the gate-4 sizing runner must key it to §4, not to D5 §6.3. Blocks nothing
  today; blocks the first evaluation's report.
- **OQ-10 (new).** §2.5's inversion — the credit floor is now a cost filter with the opposite
  sign to the one D5 §1 argued for. No compensating filter is added here. If a future version
  wants an explicit IV filter it is a **behavioural change**, i.e. `0.2.0` and a fresh sealed
  look under R3, and the §10 budget must fund it.
- **OQ-5b, OQ-6, OQ-7, OQ-8** — unchanged, as D5 §11 states them.
- **OQ-2 — effectively closed by implementation**: `OptionsShortVertical` declares its axes and
  `_merge_declared_axes` validates them; `_sensitivity_plan` keeps returning `None` for the
  options key, which stays an honest gate-5 failure on the equity path.

**Operator items**

- **OP-1 (§4, now quantified).** `options_per_structure_max_loss` is $250. The cheapest
  cost-viable structure needs **$254**; SPY needs **$513-$842**. Raising it is decision 4's
  reserved right and must be exercised **now** or not at all — D4 §2.8a forbids raising it after
  a gate result at a breaching width. Blocks the design's viability, not the evaluation.
- **OP-2, OP-3** — unchanged (broker/keys, approval level, history entitlement).
- **OP-4 (new, §3.5).** `options_total_open_max_loss` is $1,000 against a worst case of
  **$2,822.40** for the 14-underlying declared population at `R_hard = $201.60`. Either raise it
  to `>= $2,825` or the pre-registered 4-structure concurrency cap applies and `n` falls
  accordingly. Blocks gate 0.i(ii) only.

---

## 8. Change record against v0.1.0

| Item | v0.1.0 (D5) | **v0.1.1 (this amendment)** |
|---|---|---|
| `VERSION` | `0.1.0` | **`0.1.1`** |
| `min_credit_to_width` baseline | 0.25 | **0.10** |
| axis 6 values | (0.25, 0.30) | **(0.10, 0.13)** |
| OAT loosening value | 0.20 | **0.05** |
| width parameter | `width_pct = 0.010` of `U` | **`width_usd = $2.00` per contract** |
| width as grid axis | yes, (0.010, 0.020) | **no — OAT (1.00, 2.00)** |
| `stop_multiple` | FIXED, OAT (1.5, 2.0, 3.0) | **AXIS (2.0, 3.0)**, OAT (1.5) |
| grid shape | 6 axes, 96 points | **6 axes, 96 points** (unchanged) |
| `width_tolerance_pct` | 0.50 | **0.0 — exact placement** |
| R scale | `width_pct × U × 100`, varies $75-$525 | **$200.00, identical everywhere** |
| gate 0.5 | fails `single_scale` on any multi-underlying run | **passes by construction** |
| gate 0.i per-structure | breaches $250 above `U ≈ $333` | **$201.60 hard bound, +19.4 % margin** |
| horizon | `MEDIUM_SWING`, unratified (OQ-1) | **`MEDIUM_SWING`, ratified** |
| expected disposition | §10 null option (D5 §6.2b) | **§10 null option, now derived (F14)** |

**R3 consequence, stated plainly.** This is a behavioural change and it ships as a new version.
Because `k = 0`, it costs **no** sealed look: the first sealed evaluation of the family will be
look 1 for `v0.1.1`, and `v0.1.0` was never evaluated. **v0.1.0 is withdrawn, not abandoned** —
under D5 §10's `k_effective` accounting a variant that was never evaluated and is superseded
before the first look is not a spent variant. The §10 budget is untouched: **1 variant, hard cap
2, still available.**
