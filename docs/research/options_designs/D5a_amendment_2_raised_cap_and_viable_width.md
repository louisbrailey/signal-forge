# D5 — Amendment 2: the raised per-structure cap (OP-1) and a cost-viable width

**Amends:** `docs/research/options_designs/D5a_amendment_1_reachable_credit_floor_and_fixed_R.md`
(and through it D5 rev 2).
**Applies to:** `options_short_vertical.medium_swing` **v0.1.2** (supersedes v0.1.1).
**Written:** 2026-09-23. **Status: PRE-REGISTRATION — amendment legitimate only at k = 0.**

---

## 0. Why a sibling file, why it is legitimate today, and what was read

### 0.1 Why a sibling file

D5a §0.1's argument applies here word for word. D5a's §0.2 attestation is scoped to the
pass that produced it, its §3.3 and §4 carry numbers this document supersedes, and its §6.4
closes with "No gate threshold is moved by this amendment". Editing D5a in place would make
those sentences unreadable as a record of what was fixed first. So D5a is left unchanged in
every pre-registered section. The only change to D5a is a **dated pointer appendix** appended
after §8, which moves nothing and exists so that a reader of D5a alone cannot act on a number
this document supersedes. D5 gets a matching one-line row in its existing pointer appendix.

### 0.2 Why it is legitimate now

**The operator's decision (FACT).** On 2026-09-23 the operator confirmed OP-1 at the
orchestrator's recommended values, in chat, with the words *"i want you to fully fix it any
use all the tools i have enabled you with to do so"*. The limits are now **per-structure max
loss $900.00** and **aggregate open max loss $3,600.00** (recorded in
`docs/research/DECISIONS_2026-09-12_wave3.md`, addendum 3). `collateral_cap_dollars`
($5,000) is **unchanged**; it is not part of OP-1.

This is the route D5a §4 named ("the single thing that can change that is OP-1") and D4 §2.8a
allows: the cap is raised **before** any gate result, not after one at a breaching width.

**k = 0 (documented, not re-queried).** D5a §0.2 established that no row in `strategy`
begins `options`. Since then the wave-3 record has stated "No options evaluation runs until
OP-1 is decided and D5a is re-derived if needed", and OP-1 was decided only today. The live
database was **not** opened by this pass (see §0.3), so k = 0 is carried from those records.
It was not re-measured. Whoever merges this should run `count_sealed_looks` for the family
read-only before the first evaluation, as the first look already requires.

### 0.3 Attestation for this pass (FACT)

- No database was opened, live or bulk. No provider API was called.
- No option price, IV, greek, credit, return or P&L from any real chain was read.
- Every number below is closed-form Black-Scholes arithmetic on the parameters D5, D5a and
  OP-1 fixed. It was computed from the **shipped** `src/signalforge/options/blackscholes.py`
  and `PREREGISTERED_COST_MODEL`, using the same helper logic as D5a's tests. The load-bearing
  numbers are reproduced as tests in `tests/research/test_options_short_vertical.py`.
- D5a's own tables were **recomputed first** at `width_usd = 2.00` and matched to the fourth
  decimal (bound table, quartiles, F14 table, minimum-width table). That confirms the method
  before it is applied to a new width.
- The declared inputs are unchanged from D5a §0.3: `U` = $660 / $590 / $240, `q` = 0.013 /
  0.006 / 0.013, $1.00 strike increment, `r` = 0.04, 35 DTE, the frozen cost model.
  Entry costs for one 2-leg structure are `2 × $0.65 + 2 × $0.15 = $1.60`.

### 0.4 What this amendment does NOT touch

`docs/PREREGISTRATION_execution_limits_v1.md` (the execution-layer arming limits: $250
per-structure, $1,000 aggregate, and the 0.5 % / 2 % percent forms that bind at $125 / $500)
is **not** changed. OP-1 is about research **promotion** qualification (gate 0.i and the paper
book's refusal limits). Arming is a separate, later gate. Its v1 limits would still refuse
every v0.1.2 structure ($801.60 > $125). That is a known, separate operator item (OP-5 family),
out of scope here.

---

## 1. What changes, in one table

| # | Item | v0.1.1 (D5a) | **v0.1.2 (this amendment)** | Section |
|---|---|---|---|---|
| 1 | per-structure cap (gate 0.i, paper book) | $250 | **$900** (OP-1) | §0.2 |
| 2 | aggregate cap | $1,000 | **$3,600** (OP-1) | §0.2 |
| 3 | `width_usd` | $2.00 | **$8.00** | §3.1 |
| 4 | `R_hard` | $201.60 | **$801.60** | §3.1 |
| 5 | target-win outcome at the declared width | negative in 9/9 F14 cells | **positive in 7/9** | §3.2 |
| 6 | attainable adverse credit/width | −0.2250 … +0.1550 | **0.0938 … 0.1813** | §4.1 |
| 7 | `min_credit_to_width` baseline / axis / OAT | 0.10 / (0.10, 0.13) / 0.05 | **0.150 / (0.150, 0.155) / 0.140** | §4.2 |
| 8 | OAT `width_usd` | (1.00, 2.00) | **(2.00, 8.00)** | §6.3 |
| 9 | floor comparison | bare `>=` | `>=` with `_RATIO_EPS = 1e-9` (exact-arithmetic `>=`) | §4.4 |

Found here and pre-registered before any look:

| # | Finding | Section |
|---|---|---|
| F14′ | F14 resolved in part: SPY and QQQ at sigma 0.30 stay cost-unviable under $900 | §3.2 |
| F15 | The call-side (bear) mirror enters **nothing** at the v0.1.2 band | §4.6 |
| — | Gate 0.i(ii): 4 concurrent structures at $3,600, and the concurrency cap is **not implemented** | §3.3 |

---

## 2. Method (unchanged from D5a)

Same helper logic as D5a §2.3. For each cell `(U, sigma)`:

1. Pick the short put strike on a $1.00 ladder whose `|delta|` is closest to 0.20, inside the
   0.05 tolerance and at or below 0.35.
2. Put the wing at exactly `K_short − width_usd`.
3. Price both legs at Black-Scholes.
4. Fill adversely: sell at `print − s` and buy at `print + s`, where `s = max($0.02, 3 % × print)`,
   rounded to tick away from the engine.
5. Report `adverse/W = (sell − buy) / width_usd`.

F14's target-win outcome is `0.5·C − F`. `C` is the adverse credit × 100. `F` is the
four-crossing friction `2 × 100 × (s_short + s_wing) + 4 × $0.65 + 4 × $0.15`. Both definitions
are exactly D5a's, and D5a's numbers reproduce from them.

---

## 3. The width, re-derived under the $900 cap

### 3.1 The ceiling

D5a §3.3's hard bound, the one no credit floor can breach because the strategy refuses
`net_credit <= 0`:

```
R_hard = width_usd × 100 + entry_costs = width_usd × 100 + $1.60   <=  $900.00
width_usd <= (900.00 − 1.60) / 100 = 8.984
widest multiple of the declared $1.00 increment:  floor(8.984 / 1.00) × 1.00 = $8.00
```

We round down, which is D5a's convention: the margin must hold inside the cap, and the wing must
be placeable.

| `width_usd` | gross `W` | `R_max` at f = 0.150 | `R_hard` (f = 0) | vs **$900** | $1.00 ladder |
|---|---|---|---|---|---|
| $2.00 (v0.1.1) | $200 | $171.60 | $201.60 | fits, +77.6 % | yes |
| $7.00 | $700 | $596.60 | $701.60 | fits, +22.0 % | yes |
| **$8.00** | **$800** | **$681.60** | **$801.60** | **fits, +10.9 % on the hard bound** | **yes** |
| $8.50 | $850 | $724.10 | $851.60 | fits | **no** — not a multiple of $1.00 |
| $9.00 | $900 | $766.60 | $901.60 | **breaches by $1.60 on the hard bound** | yes |
| $10.00 | $1,000 | $851.60 | $1,001.60 | breaches by 11.3 % | yes |

`$9.00` clears the cap at the baseline floor (`900 × 0.85 + 1.60 = $766.60`) but not on the
hard bound. D5a's rule is kept: the margin must hold at **every** parameter setting, not only
at the baseline floor. That rule is what `OptionsShortVertical.__init__`'s fail-closed guard
enforces, and it now reads the $900 cap. `$8.50` is rejected on placeability, as `$2.50` was.

> **Declared: `width_usd = $8.00`.** `R_scale = $800.00` on every underlying. Gate 0.5's
> `single_scale` and `scale_matches` pass by construction. `R_hard = $801.60` is inside the
> $900 cap with a 10.9 % margin that no parameter inside v0.1.2 can breach.

### 3.2 Cross-check against F14's viable range (F14′)

D5a quoted F14's viable range as **"$254–$842"**. Recomputing it shows those figures are the
**credit-net** R, `W×100 − C + $1.60`, at each cell's minimum viable width. The cap check uses
the hard bound. The same minimum widths on the hard bound cost:

| `U` | sigma 0.15 | sigma 0.20 | sigma 0.30 |
|---|---|---|---|
| 660 (SPY) | $6 → R_hard $601.60 ✓ | $8 → $801.60 ✓ | **$10 → $1,001.60 ✗** |
| 590 (QQQ) | $5 → $501.60 ✓ | $7 → $701.60 ✓ | **$9 → $901.60 ✗** |
| 240 (IWM) | $3 → $301.60 ✓ | $3 → $301.60 ✓ | $4 → $401.60 ✓ |

✓ = admitted under $900; ✗ = not.

**The $900 ceiling admits 7 of the 9 cells' viable widths**, and all 7 are ≤ $8. So one declared
width of $8.00 is cost-viable on each of them. The two exclusions are the index ETFs at
sigma 0.30. This corrects a figure in the OP-1 recommendation: "~$900 (SPY at sigma 0.30)" was
read off the credit-net column. On the hard bound SPY at sigma 0.30 needs **$1,001.60**, which
$900 does not admit. That is recorded here rather than silently absorbed.

Target-win outcome at the declared $8.00 (D5a §4's cells, plus QQQ 0.30):

| `U` | sigma | `C` | `F` | `0.5C − F` | R (credit-net) | **`w` (R)** |
|---|---|---|---|---|---|---|
| 660 | 0.15 | $120.00 | $36.63 | +$23.37 | $681.60 | **+0.034** |
| 660 | 0.20 | $120.00 | $49.80 | +$10.20 | $681.60 | **+0.015** |
| 660 | 0.30 | $125.00 | $80.14 | −$17.64 | $676.60 | **−0.026** |
| 590 | 0.15 | $122.00 | $32.78 | +$28.22 | $679.60 | **+0.042** |
| 590 | 0.20 | $124.00 | $44.84 | +$17.16 | $677.60 | **+0.025** |
| 590 | 0.30 | $125.00 | $70.74 | −$8.24 | $676.60 | **−0.012** |
| 240 | 0.15 | $99.00 | $15.29 | +$34.21 | $702.60 | **+0.049** |
| 240 | 0.20 | $111.00 | $17.65 | +$37.85 | $690.60 | **+0.055** |
| 240 | 0.30 | $131.00 | $27.17 | +$38.33 | $670.60 | **+0.057** |

> **F14′ (keyed before any look).** At the operator's $900 cap and `width_usd = $8.00`, the
> target-win outcome is **positive in 7 of 9** Stage A cells, where at $2.00 it was negative in
> all 9. It stays **negative for SPY and QQQ at sigma 0.30**, and no width inside the cap fixes
> that. The positive values are small (+0.015R to +0.057R), so the break-even hit rate remains
> demanding. D5 §6.2/§6.3's forecasts stay superseded (OQ-9 open). **The null option is no
> longer the derived disposition, but it is not ruled out.** Raising the cap again after a
> gate result is forbidden by D4 §2.8a and by this paragraph.

### 3.3 The aggregate leg of gate 0.i at the new numbers

This redoes D5a §3.5 (`14 × $201.60 = $2,822.40` vs $1,000 → 4 concurrent):

```
14 × R_hard = 14 × $801.60 = $11,222.40      vs the $3,600 aggregate cap
permitted concurrent structures = floor(3600 / 801.60) = floor(4.49) = 4
```

D5a §3.5 pre-registered both branches. Its threshold for the unrestricted branch scales to
`>= $11,225` here. $3,600 is below that, so **the pre-registered 4-structure concurrency cap
applies**: priority by ascending underlying symbol, excess entries counted
`skipped_portfolio_concurrency`, and D5 §6.3's required `n` not met.

The same arithmetic confirms `OptionsRiskLimits.max_open_structures = 5` is still dead
configuration: `floor(3600 / 900) = 4` full-cap structures (it was `floor(1000 / 250) = 4`), and
`floor(3600 / 801.60) = 4` at v0.1.2's bound.

**This is a trade the wider width makes, disclosed:**

| `width_usd` | cells viable (of 9) | `R_hard` | concurrent at $3,600 |
|---|---|---|---|
| 2 | 0 | $201.60 | 17 (all 14 fit) |
| 3 | 2 | $301.60 | 11 |
| 4 | 3 | $401.60 | 8 |
| 5 | 4 | $501.60 | 7 |
| 6 | 5 | $601.60 | 5 |
| 7 | 6 | $701.60 | 5 |
| **8** | **7** | **$801.60** | **4** |

No width is both cost-viable and able to hold all 14 underlyings open under $3,600. That would
need `W×100 + 1.60 <= 3600/14 = $257.14`, i.e. $2, which is cost-unviable everywhere. $8 is
chosen by D5a's rule (the widest compliant, placeable width), which also maximises viability.
The price is `n`.

> **Implementation gap (FACT, not a design choice).** The 4-structure concurrency cap D5a §3.5
> pre-registered is **not implemented**. No `skipped_portfolio_concurrency` counter or portfolio
> concurrency limit exists under `src/`. `research/options_evidence.py::_concurrent_open_r_max`
> measures concurrent open R from the trade list as given. A multi-underlying evaluation with
> more than 4 overlapping structures therefore **fails gate 0.i(ii) as the code stands**. This
> was equally true at v0.1.1 ($2,822.40 > $1,000). It blocks the first evaluation, not this
> amendment, and it must be built (default-off and outcome-independent, exactly as D5a §3.5
> specifies) before the first sealed look.

---

## 4. The credit-floor band, re-derived at $8.00

### 4.1 The bound table at the new width

The same cells as D5a §2.3. `W$ = 8.00`, baseline delta band, 35 DTE, `r = 0.04`. Reproduced by
`test_the_v012_bound_table_at_eight_dollars_is_reproduced`.

| `U` | sigma | `K_short` | `|delta|` | print/W | charge | **adverse/W** | (was, at $2) |
|---|---|---|---|---|---|---|---|
| 660 | 0.15 | 637 | 0.199 | 0.1758 | 0.0258 | **0.1500** | 0.0750 |
| 660 | 0.30 | 615 | 0.202 | 0.2078 | 0.0516 | **0.1563** | −0.0250 |
| 660 | 0.60 | 576 | 0.200 | 0.2438 | 0.1126 | **0.1313** | −0.2250 |
| 590 | 0.15 | 570 | 0.202 | 0.1736 | 0.0211 | **0.1525** | 0.1050 |
| 590 | 0.30 | 550 | 0.201 | 0.2047 | 0.0485 | **0.1563** | 0.0250 |
| 590 | 0.60 | 515 | 0.200 | 0.2416 | 0.0978 | **0.1438** | −0.1750 |
| 240 | 0.15 | 232 | 0.209 | 0.1327 | 0.0089 | **0.1238** | 0.1550 |
| 240 | 0.30 | 224 | 0.207 | 0.1800 | 0.0162 | **0.1638** | 0.1400 |
| 240 | 0.60 | 209 | 0.197 | 0.2203 | 0.0390 | **0.1813** | 0.0500 |

The charge `chi = 100 (s_short + s_wing) / W` scales as `1/W`. At four times the width it is
roughly a quarter of D5a's, so every cell turns positive. The print ratio also falls with width,
by D5a §2.1's mean-value argument: the average `dP/dK` is taken further toward the wing.

Over the full declared space (Stage A × sigma ∈ {0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40,
0.50, 0.60}, 30 cells), the attainable adverse ratio runs **0.0938 … 0.1813** and is **positive in
all 30**.

**§2.5's inversion, revisited.** At $2 the adverse ratio fell with IV everywhere, so the floor
excluded rich cycles. At $8 the shrunken charge partly undoes that. On IWM the ratio now
**rises** with IV (0.094 at sigma 0.12 to 0.181 at 0.60). SPY and QQQ are flat near 0.15 through
sigma 0.35 and fall only above 0.40. No compensating filter is added (OQ-10 unchanged). The print
ratio and charge stay recorded per entry and per non-entry.

### 4.2 The band: D5a's rule, and why its rounding step has to be finer here

D5a §2.4's rule: take the quartiles of the **positive** attainable adverse ratios at the baseline
delta and the declared width, and round **down**. p25 is the OAT loosening value, the median is
the baseline, and p75 is the axis's harder value.

| quantile | raw at $8 | D5a's step (0.01) | **step 0.005** | role |
|---|---|---|---|---|
| p25 | 0.14375 | 0.14 | **0.140** | OAT loosening value |
| median | 0.15188 | 0.15 | **0.150** | **baseline `min_credit_to_width`** |
| p75 | 0.15625 | **0.15** | **0.155** | axis 6's harder value |

At D5a's 0.01 step the median and p75 **collapse onto 0.15**. Axis 6 would then carry one value
twice, which is not an axis and fails the grid's two-values-per-axis shape. The interquartile
range at $8 is 0.0125, against D5a's 0.085 at $2. So the step is halved to **0.005**. The
direction is unchanged: still downward, never toward the unreachable side. This is the only
change to the rule. It is stated before any look, and it was forced by the arithmetic rather
than chosen.

**The band binds without emptying.** The 30-cell count admitted at each floor (exact arithmetic,
§4.4):

| floor | admitted, −15 % prices | **admitted, declared** | admitted, +15 % prices |
|---|---|---|---|
| 0.10 (v0.1.1 baseline) | 29 | **29** | 30 |
| 0.13 (v0.1.1 p75) | 27 | **28** | 26 |
| **0.140** (OAT) | 25 | **25** | 22 |
| **0.150** (baseline) | 22 | **19** | 17 |
| **0.155** (axis) | 16 | **13** | 7 |

Carried forward unchanged to $8, v0.1.1's band (0.10, 0.13) would be **near-inert** (29 and 28 of
30 cells). That is why the band must move with the width. At ±15 % in the price assumption, the
attainable maximum is 0.1825 / 0.1812. All three values stay strictly inside the reachable region,
and none empties the space. The +15 % quartiles (0.1381 / 0.1500 / 0.1537) put 0.155 slightly
above that scenario's p75: it binds hard, which is what the harder side of an axis is for.

### 4.3 The stop is still a real stop

D5 §3.4 requires `stop_multiple × c/W < 1`. The worst case anywhere at $8 is
`3.0 × 0.1813 = 0.544 < 1`. The stop binds at under 55 % of the width at every grid and OAT value.
At $2 the figure was `0.465`. `stop_multiple` stays an axis for D5a §6.2's reason.

### 4.4 The credit lattice, and an exact-arithmetic comparison (a code change)

Above a $3.00 print the tick is $0.05. At an $8 width the adverse credit per contract therefore
moves in $5.00 steps, and the ratio sits on a lattice of `5 / 800 = 0.00625`. The baseline 0.150
equals `$120 / $800`, which is exactly **on** that lattice. Three of the 30 cells land there, and
in floats `(sell − buy) × 100 / 800` evaluates to `0.15000000000000002` on two of them and
`0.1499999999999999` on the third. A bare `>=` would make a pre-registered entry decision depend
on float rounding.

v0.1.2 therefore compares `ratio >= min_credit_to_width − 1e-9` (`_RATIO_EPS`). This restores the
pre-registered **exact**-arithmetic `>=`. It cannot admit a genuinely lower ratio, because the
finest lattice step (the $0.01 tick below $3.00, `1/800 = 0.00125`) is six orders of magnitude
larger. `test_a_ratio_exactly_on_the_floor_is_admitted_whatever_the_float_rounding` pins it: with
the slack removed, the SPY sigma-0.35 cell is refused.

### 4.5 Disclosure: cheap underlyings rarely clear the floor

An $8 wing is 3.3 % of a $240 close and 6.7 % of a $120 close. On a synthetic $120 chain the
adverse ratio is 0.083–0.143 over sigma 0.20–0.40 and never clears 0.150. D5 §2.2's
single-name members below roughly $240 are therefore expected to contribute few or no entries.
Their price levels are not declared inputs of this derivation, so the effect is not quantified
per name. It is an `n` cost of the width, recorded in advance.

### 4.6 F15: the call-side mirror enters nothing at the v0.1.2 band

D5a derived the band from the **put** side only. The strategy sells the call-side mirror under
a lagged BEAR label, and at $8 the call side's attainable adverse ratio, over the same 30 cells,
is **0.050 … 0.135**:

| | puts | calls |
|---|---|---|
| range at $8 | 0.094 – 0.181 | 0.050 – 0.135 |
| cells ≥ 0.140 / 0.150 / 0.155 | 25 / 19 / 13 | **0 / 0 / 0** |

(For comparison: under v0.1.1, at $2 and a 0.10 floor, the call side cleared 7 of 30 cells.)

> **F15 (keyed before any look).** Under v0.1.2's band, a BEAR label produces **no entry** on
> any Stage A cell. Gate 6's bear bucket is expected **empty**, and the strategy's regime filter
> reduces in practice to "sell puts, or stand aside". Gate 7b therefore tests whether standing
> aside in a lagged bear beats always selling puts. That is a narrower claim than D5 §1's, and
> gate 6 is expected to fail on an empty bucket.

**Alternative, derived and not adopted** (an orchestrator/operator item before the first look,
see §7). Applying D5a's quartile rule to the **pooled** put + call space (60 cells, all positive)
gives quartiles 0.11375 / 0.13125 / 0.15156. Rounded down at 0.005 that is **0.110 / 0.130 /
0.150**. At a 0.130 baseline, puts admit 28 of 30 cells and calls 6 of 30, so the bear bucket is
reachable but thin. It is not adopted here, because it changes the population D5a's rule is
defined over, and that is a design choice for the orchestrator rather than arithmetic. Both
options are fully specified, and choosing either before the first look costs no sealed look.

---

## 5. What stays exactly as D5a left it

The underlying set, the window, every pricing input and the frozen cost model, the
`options_config_hash` rule, cycle and signal timing, the regime filter and its lag, strike
selection, the exact wing placement (`width_tolerance_pct = 0.0`), the exits, the R formula,
the horizon (MEDIUM_SWING, OQ-1 closed), the delta, DTE, profit-target and stop axes, every
gate-0 sub-threshold other than the two OP-1 caps, F1–F13, the arming preconditions, the variant
budget and the null option. The grid shape is still 6 axes and `3 × 2^5 = 96` points.

---

## 6. The v0.1.2 spec (deltas against D5a §6)

### 6.1 Parameters

```python
width_usd:           float = 8.00    # FIXED per version -- WAS 2.00 (§3.1)
min_credit_to_width: float = 0.150   # AXIS 6 baseline  -- WAS 0.10 (§4.2)
# every other field exactly as D5a §6.1
```

### 6.2 Grid (axis 6 only)

| # | Axis | v0.1.2 values | Baseline | Change |
|---|---|---|---|---|
| 6 | `min_credit_to_width` | **0.150, 0.155** | **0.150** | was (0.10, 0.13) |

Baseline cell = `(0.20, 0.35, 2.0, 35, 0.50, 0.150)`. One-step neighbours: 7, unchanged.

### 6.3 OAT table (deltas)

| Parameter | Fixed at | OAT values | Change |
|---|---|---|---|
| `width_usd` | **8.00** | **2.00, 8.00** | was (1.00, 2.00). The superseded v0.1.1 width is the narrower control. F14 predicts it cost-destroyed on every Stage A cell. It is reported, non-gating, and never selectable |
| `min_credit_to_width` | 0.150 (axis) | **0.140** | was 0.05 (the $2 p25); 0.140 is the $8 p25 |

### 6.4 Code

- `short_vertical.VERSION` `0.1.1` → **`0.1.2`**
- `OPTIONS_PER_STRUCTURE_MAX_LOSS` 250 → **900**
- `SENSITIVITY_GRID`, `OAT_PARAMETERS`, `ATTAINABLE_ADVERSE_RATIO_MAX` (0.155 → **0.1813**), and
  `CREDIT_TO_WIDTH_QUANTILES` updated as above
- `_RATIO_EPS` added to the floor comparison (§4.4)
- `OptionsGateThresholds.options_per_structure_max_loss` / `options_total_open_max_loss` →
  **900 / 3600**
- `OptionsRiskLimits.per_structure_max_loss_dollars` / `total_open_max_loss_dollars` →
  **900 / 3600**. These stay outside `SCOPE_HASH_FIELDS`, so `config_hash` does not move and no
  equity approval is re-scoped.

---

## 7. Open items after this amendment

- **OR-F15 (new; orchestrator, before the first look).** Keep the put-derived band (F15: bear
  bucket empty), or adopt the pooled put + call band 0.110 / 0.130 / 0.150 (§4.6). Either choice
  is k = 0 and costs no sealed look. Neither may be made after a result.
- **IMPL-3.3 (new; blocks the first evaluation).** Implement D5a §3.5's 4-structure portfolio
  concurrency cap (ascending-symbol priority, `skipped_portfolio_concurrency` counter). Without
  it, gate 0.i(ii) fails any run with more than 4 overlapping structures.
- **OQ-9** stays open: D5 §6.2/§6.3's `n` forecasts are not re-derived. F14′'s small positive
  `w` is the binding forecast input.
- **OQ-10** is unchanged; §4.1 records how the inversion moved.
- **Execution limits v1** (arming) are unchanged and would refuse every v0.1.2 structure. That
  is a separate operator decision before arming (§0.4).

---

## 8. Change record against v0.1.1

| Item | v0.1.1 (D5a) | **v0.1.2** |
|---|---|---|
| `VERSION` | `0.1.1` | **`0.1.2`** |
| per-structure / aggregate cap | $250 / $1,000 | **$900 / $3,600** (OP-1, 2026-09-23) |
| collateral cap | $5,000 | $5,000 (unchanged) |
| `width_usd` | $2.00 | **$8.00** |
| R scale / `R_hard` | $200.00 / $201.60 | **$800.00 / $801.60** |
| margin to cap | 19.4 % | **10.9 %** |
| F14 cells with positive target win | 0 / 9 | **7 / 9** |
| attainable adverse ratio | −0.2250 … 0.1550 | **0.0938 … 0.1813** |
| baseline / axis / OAT floor | 0.10 / (0.10, 0.13) / 0.05 | **0.150 / (0.150, 0.155) / 0.140** |
| rounding step of the band rule | 0.01 | **0.005** (0.01 collapses median and p75) |
| OAT width | (1.00, 2.00) | **(2.00, 8.00)** |
| concurrent structures at the aggregate cap | 4 (of 14) | **4 (of 14)** |
| call-side entries at the band | some (7/30 at 0.10) | **none (F15)** |
| expected disposition | null option, derived (F14) | **not derived as null; SPY/QQQ at sigma 0.30 and the bear bucket expected to fail (F14′, F15)** |

**R3 consequence.** This is a behavioural change and ships as a new version. Because k = 0, it
costs **no** sealed look. v0.1.1 was never evaluated and is withdrawn, not abandoned. D5 §10's
budget is untouched: 1 variant, hard cap 2, still available.
