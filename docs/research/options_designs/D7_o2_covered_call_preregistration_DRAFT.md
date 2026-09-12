# D7 — O2 covered-call pre-registration (DRAFT)

> **STATUS: DRAFT. NOT FROZEN. NOT A PRE-REGISTRATION YET.**
> Nothing in this document binds anything. No threshold here is committed, no parameter is
> fixed, and no evaluation may cite it as an R1 pre-registration until it is frozen by an
> explicit, dated commit that removes this banner. It is published as a draft precisely so
> that the arithmetic in §6 and §7 — which says the design **cannot be evaluated at all**
> under the currently taken capital limits — is on the record *before* anyone spends effort
> implementing it.

**Family (proposed):** `options_covered_call.medium_swing`
**Structure:** O2 — covered call (long 100 shares + one short call), per
`OPTIONS_EXECUTION_PROGRAM_MAP.md` §4.2.
**Version drafted here:** `v0.1.0`
**Written:** 2026-09-12. **k = 0** — see §0.3.
**Sequencing status:** `DECISIONS_2026-09-12_options_execution.md` decision 8 defers O2 behind
O3, and decision 12 makes O3 (`options_short_vertical.medium_swing`) the first structure.
This draft does not ask for that to be revisited. It exists so that the structure named in
`DECISIONS_2026-09-12_wave3.md` OP-1 as the program's fallback — *"If you keep $250, O3 is
expected to be the null result and the program's next structure is O2 (covered call) or O1
with a bear-regime carve-out"* — has its arithmetic done **before** it is reached for, not
after.

---

## 0. What this document is, and the state it was written in

### 0.1 Scope

This is a draft R1 pre-registration for a covered-call version that

1. can be implemented against the **existing** `OptionsStrategy` Protocol
   (`src/signalforge/research/options_evidence.py:189-213`) with no change to that Protocol,
   and
2. can be evaluated by the **existing** options ladder with **no code change to any gate
   function** in `src/signalforge/research/options_gates.py`.

Requirement 2 is the binding one, and it is what produces the two impossibility results in §6.
The gates are treated here exactly as R4 requires — as frozen code that the design must fit,
never as code the design may adjust.

Engine changes **are** in scope for O2 and are named in §3.6 and §15; they belong to D2, they
are strictly additive, and none of them touches a gate.

### 0.2 Attestation (FACT)

No database was opened during the pass that produced this document. `data/signalforge.sqlite`
was not read, no provider API was called, no file under `src/` or `tests/` was modified, and no
file outside `docs/research/options_designs/` was written. No option price, implied volatility,
greek, credit, return or P&L from any stored series was inspected.

Every number in §6, §7 and §14 is closed-form Black-Scholes arithmetic on **declared
assumptions** (§2.4), computed by read-only local evaluation of
`src/signalforge/options/blackscholes.py`, `src/signalforge/backtest/options_costs.py` and
`src/signalforge/backtest/costs.py`. This is the same discipline and the same provenance class
as `D5a_amendment_1_reachable_credit_floor_and_fixed_R.md` §0.2, which states its own
attestation in the same terms. **When this draft is frozen, every table in §6 and §7 must be
reproduced as a test**, exactly as D5a §0.2 requires of its own bound table; until then they are
arithmetic in a document and nothing more.

Line numbers are pinned to the branch head `e4112ef`. Symbols are named alongside line numbers
throughout §15 because line numbers do not survive commits and symbols do — D5 §13's convention.

**Seven citations inherited from D5 were stale at this head and are corrected here**, which is
the concrete reason that convention exists. D5 pins to `5b41a61` and warns at length about the
damage stale citations did; the tree has moved again since. Corrected:
`count_sealed_looks` `promotion.py:647 → :712`; the sensitivity call
`promotion.py:1171 → :1236`; gates 2/3/4's OOS reads
`promotion.py:1110,1111,1124,1137-1138 → :1175,:1176,:1189,:1202-1203`;
`_NOMINAL_SPREAD_BPS` `ledger.py:50 → :52`; `accept_candidate`
`ledger.py:129-141 → :132-144`; `mark_to_market` `ledger.py:266 → :287`;
`blackscholes` `price/greeks/implied_vol :48,:62,:93`. Every other line number in this document
was re-verified against `e4112ef` by reading the line, not by inheriting it. D5's own §2.3 and
OQ-8 record the same class of correction against the program map; this is that discipline applied
one generation further on.

### 0.3 Sealed-look position — k = 0, and it stays 0

**FACT.** `count_sealed_looks` keys on `Strategy.name`
(`src/signalforge/research/promotion.py:712`), and D5 §12's read-only census recorded six
`strategy` rows, none beginning `options`. `options_covered_call.*` is a **new family**, so
`k_prior = 0` for it by construction and no equity family and no `options_short_vertical` look
is touched by anything here.

**FACT that matters for this draft specifically.** A gate-0 failure never reaches gate 9, and
gate 9 is what writes a `strategy_sealed_test` row. So the deterministic gate-0.i failure
derived in §6.3 would cost **zero** sealed looks if the evaluation were run. It would also
produce zero evidence. Running it is not dangerous; it is merely pointless, and §11 records
that as the pre-registered expectation rather than leaving it to be discovered.

**Amendment legitimacy.** D5a §0.2 establishes the rule: a pre-registered parameter may be
changed freely before the first look and never after. This document is at the same k = 0
position, with the additional protection that it is not frozen at all. Every number below may
still move. Once it is frozen, D5a's rule applies to it unchanged.

### 0.4 Falsification-criterion namespace

D5 numbers its falsification criteria F1-F13 and D5a adds F14; those belong to the
`options_short_vertical` family. To make cross-document confusion impossible, this document's
criteria are prefixed **CC** (§9). A reader who sees "F14" is reading about the short vertical;
a reader who sees "CC-7" is reading about the covered call.

---

## 1. Mechanism, in market terms

**The claim being tested.** The same volatility risk premium D5 §1 describes — index and
large-cap options sold, on average, at an implied volatility above the volatility subsequently
realised — can be harvested by an investor who already wants the underlying exposure, by
selling an out-of-the-money call against 100 held shares. What is given up is the upside above
the short strike; what is received is the call premium, which cushions a fall by exactly the
credit and no more.

**What is different from O3, and it is not a detail.** A short vertical is a *pure* premium
trade: its entire P&L is the credit and the width, and its max loss is a structural constant.
A covered call is **not** a premium trade. It is a long equity position with a small premium
overlay. On the declared Stage-A levels (§2.4) the share leg's own 28-day standard deviation is
**$997 to $6,351 per structure** (§6.5), against a call credit of **$147 to $988**. The share
leg supplies 76-87% of the structure's variance, and it supplies essentially all of its mean.
Every difficulty in this document follows from that one fact.

**Why a regime input at all, and what it is for.** The filter is not a timing signal and it is
not a direction control — a covered call has no bearish mirror (the mirror would be short stock
plus a short put, a different `structure_type`, a different R formula, and a margin account).
The regime input instead modulates **how far out of the money the call is sold**: closer to the
money when the lagged broad-market proxy trend is bear (more premium, more cushion, and less
forgone upside actually at stake in a falling market), further out otherwise. The claim is
narrow and falsifiable: *shifting the short-call delta with the lagged trend produces a better
risk-adjusted result than selling a fixed delta every cycle.* Gate 7b (§8) is the exact test of
that claim and nothing else.

**Why the regime input never removes a trade.** Every eligible cycle produces an attempted
entry on every underlying, in every regime. §3.2 derives why this is load-bearing rather than
stylistic: it is the only thing that makes gate 6 reachable for a structure with no mirror.

**What would make this mechanism false, stated up front (R10).** Three things, and §6 derives
all three in advance:

> 1. **CC-1.** There is no per-structure risk budget that satisfies gate 0.5 and gate 0.i at the
>    same time (§6.3). The interval is empty by **16.8×** at decision 4's $250 cap and by
>    **4.0×** at OP-1's recommended $900.
> 2. **CC-2.** At any cap-compliant budget the stop sits at **0.03-0.20 of one 28-day standard
>    deviation** of the share leg, so it fires on noise before any premium is captured (§6.5).
> 3. **CC-3.** The account cannot hold the position. 100 shares of the cheapest Stage-A
>    underlying is **$24,000 against a $25,000 account and a $5,000 collateral cap** (§7).

None of the three is about whether covered calls make money. All three are about whether this
system, at its currently taken capital limits, can *measure* whether they do.

---

## 2. Declarations that would fix the evaluation

### 2.1 Identity

| Item | Drafted value | Source / note |
|---|---|---|
| Strategy family name | `options_covered_call` | new family; `count_sealed_looks` → k = 0 (`promotion.py:712`) |
| Horizon token | `Horizon.MEDIUM_SWING` ("2-8 weeks", `src/signalforge/domain.py:17`) | the same derivation D5a §5 ratifies for O3: the holding period, not the tenor, is what `Horizon` describes. At `dte_target = 35` and `time_stop_dte = 7` the longest hold is 28 days = 4.0 weeks; at the grid's 21-DTE cell it is 14 days = 2.0 weeks. `POSITION`'s floor (≈60.9 days) is **2.17×** the longest hold the baseline can produce, i.e. arithmetically impossible, exactly as D5a §5 shows for O3 |
| Strategy key | `options_covered_call.medium_swing` | |
| Version | `0.1.0` | R3: any behavioural change ships as `0.2.0` and costs a fresh look |
| `structure_type` | `COVERED_CALL` — **exactly one per version** | `src/signalforge/backtest/options_engine.py:59` already carries the enum member, marked *"deferred behind O3 (decision #8)"*. D4 §3 / gate 0.5 |
| R basis | `R = stop_usd × shares_per_contract × contracts − net_credit_received + entry_costs` | **not** max loss — §3.5 and §6.1 derive why, and why gate 0.5 leaves no alternative form |
| R scale | `stop_usd × M`, declared, fixed for the version, **never a grid axis** | D4 §3 clause (d); D5a §6.2 reason 1, which applies verbatim |

**Incomparability, stated here because gate 0.5 prints it on every report
(`options_gates.py:888-891`):** this R stream may not be pooled with, averaged against,
bootstrapped together with, or compared to the equity R stream, the `options_short_vertical` R
stream, or any other structure's. A covered-call +0.30R and a vertical +0.30R are two different
claims about two different amounts of money.

### 2.2 Underlying set

**Drafted rule: D5 §2.2's set, unchanged and unre-derived.** `{SPY, QQQ, IWM}` ∪ the 11
highest median-dollar-volume common stocks of DataSnapshot 11 over a pre-sealed liquidity
window = **14 underlyings**, with D5 §2.2's coverage-exclusion clause and its fire-once
shortfall ladder carried over verbatim.

Reusing D5's population rather than deriving a new one is deliberate and has a reason beyond
economy: it keeps the O2 and O3 *cycle* populations identical, so that the difference between
the two evaluations is the structure and nothing else. Introducing a new selection rule here
would make the comparison uninterpretable and would be a second, undisclosed selection channel.

**The consequence the reader must not skip.** §7 shows the paper stream can hold **zero** of
these 14 underlyings. The backtest population and the paper population are therefore not merely
different sizes (D5 §9.2's finding for O3) — for O2 the paper population is **empty**.

### 2.3 Window

Identical to D5 §2.3, unchanged: total option history 8 years (floor 6); sealed window 365 days
(`config/research.py` `sealed_window_days`, frozen, R4); pre-sealed span ≈ 7 years, comfortably
above `MIN_PRESEALED_DAYS = 350` (`promotion.py:106`) for gate 0.a; IS/OOS split = the last 40%
of each symbol's bars is out-of-sample (`research/backtest_runner.py:29` `_TRAIN_FRAC = 0.6`,
frozen), with gates 2/3/4 reading `full.out_of_sample` (`promotion.py:1175,1176,1189,1202-1203`);
proxy SPY, source `massive` (R6).

**Available `n`, carried over from D5 §6.3c because the cycle population is identical:**
14 underlyings × 84 pre-sealed cycle-months = 1,176 candidate cycles; at D5 §2.2's 55% net entry
assumption ≈ **647 pre-sealed entries**; the frozen 40% split gives ≈ **259 OOS trades** over
≈ **34 OOS cycle-months**; the sealed year gives ≈ **92 entries** over **12 cycle-months**.
§6.6 reads the required `n` against these figures.

One entry-rate note that is **not** carried over: O2's entry conditions are strictly weaker than
O3's — one option leg instead of two, no wing to place on a listed ladder, and no exact-width
condition (D5a §3.4's `width_tolerance_pct = 0.0`, which for O3 converts every coarse ladder into
a non-entry). O2's realised net entry rate should therefore be **higher** than 55%, not lower.
That is a prediction stated in advance; it is measured by the non-entry census (§9) and it does
not change any threshold.

### 2.4 Pricing inputs, and the declared price levels

| Input | Drafted value | Class |
|---|---|---|
| `U` SPY | **$764.29** | **The only anchored level in this table.** D4 §3 records the read-only query `select o.close … where i.symbol = 'SPY' order by o.session_date desc limit 1` → **764.29**, session 2026-09-11, source `massive`, with stored `option_contract` strikes spanning 709-831. Cited from D4; no database was read here |
| `U` QQQ / IWM | **$590 / $240** | **assumption, unanchored.** Taken from D5a §0.3's declared set. See the discrepancy note below |
| `q` SPY / QQQ / IWM | 0.013 / 0.006 / 0.013 | assumption **for this derivation only**; at evaluation time `q` is sourced per underlying per session (decision 11, gate 0.g) and an unsourced `q` is still a non-entry |
| `σ` grid | 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60 | assumption, identical to D5a §2.3's declared design space |
| listed strike increment | **$1.00** on SPY/QQQ/IWM monthly third-Friday chains | market-structure assertion, same class as `tick_grid` (D2 §6.3). A **coarser** realised ladder is the conservative direction: it produces non-entries, never a rewritten strike |
| `r`, DTE, option cost model | 0.04, 35, `PREREGISTERED_COST_MODEL` | unchanged from D5 §2.4 and frozen (R4). FACT: `short_vertical.py:161-171` — $0.65/contract commission, $0.15/contract exchange fee, spread `max($0.02, 0.03 × last_print)`, `spread_multiplier` 1.0 or 2.0 only (`options_costs.py:62-63`) |
| **share-leg cost model (NEW, and O2-specific)** | the frozen equity `CostModel`: `commission_per_share = 0.0`, `slippage_bps = 3.0`, `half_spread_fill_penalty = True` over a nominal 5.0 bps spread → **5.5 bps per side, 11.0 bps round trip** | FACT: `config/research.py:672-675`; `backtest/costs.py:12-27`; `paper/ledger.py:52` `_NOMINAL_SPREAD_BPS = 5.0`; and the per-side figure is read directly off `backtest/engine.py:94`, `slip = (cm.slippage_bps + spread_bps / 2) / 10_000` = `(3.0 + 2.5) / 10_000`. Frozen by R4. At the 2× setting of gate 4b the share spread doubles too (D4 §4.2: 4b applies to **both** asset classes) → 8.0 bps per side, 16.0 bps round trip |
| Fill model | print-plus-**full**-spread on the option leg, adverse, per leg per crossing (1 leg × 2 sides = **two** full modelled spreads); equity convention on the share leg | map §2.4(1a); D5 §2.4 |
| Print eligibility | `volume ≥ 10` and, where non-null, `transactions ≥ 5` | D5 §2.4, carried over unchanged. Applies to the **option leg only**; the share leg's continuity is gate 0.b's existing `OHLCVDaily` check |
| Missing bar | a liquidity fact, never a fill (map §2.4(3)) | a session on which the option leg lacks a print-eligible bar is a **non-entry**; an exit signal defers, `exit_deferred_sessions` recorded |
| `shares_per_contract` | read per leg, asserted `== 100` at entry, contract refused otherwise | map §2.3, gate 0.h; `options_engine.py:141-146` already enforces it |

**The price-level discrepancy, recorded rather than smoothed over.** D5a §0.3 declares SPY at
**$660**; D4 §3 records a read-only query returning **$764.29** for the session 2026-09-11.
The two differ by **15.8%** (764.29 / 660 = 1.158). This document anchors SPY to D4's recorded
figure because it is a recorded observation rather than a declaration, and declares QQQ and IWM
from D5a's set because **no anchored level for either exists anywhere in the repo** (§16, item
1). The ±15% sensitivity band run throughout §6 and §7 is therefore not a formality: it is
almost exactly the size of the error already demonstrated on the one level that can be checked.
Every conclusion in §6 and §7 is reported at 0.85 / 1.00 / 1.15 and **none of them changes sign
anywhere in that band.**

### 2.5 Where the constants are hashed

D5 §2.5's rule is adopted verbatim and for the same reasons. The options constants do **not**
join `ResearchConfig.SCOPE_HASH_FIELDS` (`config/research.py:717-733` and the tuple around it):
adding a key to the hashed payload changes the equity `config_hash` and repeats the 2026-09-11
scope incident that commit `0cc4cf4` fixed. They live in `OptionsEvaluationConfig`, and
`options_config_hash` is computed over **both** that section and `ResearchConfig.options` so
that the strike-shaping `risk_free_rate` is inside it. Every evaluation additionally records the
verbatim `PromotionThresholds` payload, because `promotion: PromotionThresholds` is outside
`SCOPE_HASH_FIELDS` too.

**One O2-specific addition.** The **share-leg cost convention** (11.0 bps round trip, and its 2×
form) and the declared `stop_usd` must be inside `options_config_hash`. Both are strike- and
R-shaping: `stop_usd` *is* the R scale, and the share friction enters `entry_costs` and
therefore R. Leaving either outside the hash would let the R denominator move without a new
snapshot key — the exact silent-drift failure §2.5 exists to prevent. Gate 0.i already refuses
to pass unless `limits_in_options_config_hash` is `true`
(`options_gates.py:775,792-793`), so this is enforced mechanically rather than by policy.

---

## 3. The strategy, as a deterministic function

No LLM is consulted anywhere (import-linter S3). Given the data and the params, entry, strike
selection and exit are a pure function.

### 3.1 Cycle, entry timing, and the share leg

1. **Cycle.** One monthly third-Friday expiry per underlying, resolved by
   `data/options_calendar.py`. No weeklies in v0.1.0.
2. **Signal session `t`.** The first NYSE session on which `DTE(expiry) ≤ dte_target`.
   Deterministic, exactly one per (underlying, cycle).
3. **Eligibility window.** `DTE(expiry) ∈ [dte_window_lo, dte_window_hi]` on session `t`; a
   cycle falling outside is skipped and counted.
4. **Fill session.** Entry fills on session `t+1`'s prints — the share leg at `t+1`'s open-based
   equity convention and the option leg at `t+1`'s print-plus-adverse-spread, matching
   `backtest/engine.py:85-151`. **Both legs fill on the same session or neither does**: a
   partially-filled covered call is a naked short call, which
   `OPTIONS_EXECUTION_PROGRAM_MAP.md` §4.5 bans outright ("no finite max loss ⇒ no well-defined
   R"). This is pre-registered as an atomic condition, and a session on which the option leg
   is not print-eligible is a **non-entry**, never a bare share purchase.
5. **The share leg is acquired for the structure, not overlaid on an existing position.** FACT:
   `paper_position` has 0 rows (D5 §12), and decision 13 puts options in a **separate** $25,000
   SIMULATED account, so there is nothing to overlay. Map §4.2's description of O2 as an
   "overlay on an existing paper equity position" does not describe what decision 13 makes
   possible. The structure is therefore **standalone**: buy 100 shares, sell one call, close
   both together. §3.5 records the overlay reading as a mandatory paired diagnostic rather than
   discarding it.
6. **Concurrency.** At most one open structure per **underlying**
   (`options_max_structures_per_underlying = 1`, keyed on the underlying not the
   `instrument_id` — map §3.6). D5 §3.1(5)'s tie-break is adopted verbatim: exits scheduled on
   session `t` settle **before** eligibility is tested on `t`. D5 §3.1(5)'s arithmetic — that
   at `dte_target = 45` the signal session always falls before the prior cycle's time stop, so
   every cycle is skipped — carries over unchanged, which is why **45 is excluded by derivation
   from the `dte_target` axis** here too.
7. **Size.** Exactly 1 contract and exactly 100 shares per structure in the backtest. The
   backtest is position-count-unconstrained by design (map §3.1); the paper stream is not, and
   §7 shows what that costs.

### 3.2 The regime input — and how gate 6 is reachable for a long-delta structure

This is the section the structure's evaluability turns on, so the argument is given in full.

**The problem.** D5 §1 and map §5.3 make gate 6 reachable for O3 by the **call-side mirror**:
the structure has a bearish form, so a bear-regime cycle still produces a trade. A covered call
has no mirror. It is long roughly +75 delta per structure (100 long shares less a 0.25-delta
short call) and there is no bearish covered call. Whatever the regime input does, it cannot flip
the structure's direction.

**FACT about what gate 6 actually counts.** `gate_6_regime` (`options_gates.py:1137-1189`)
computes `covered = sum(1 for c in buckets.values() if c >= th.min_trades_per_regime)` over
`census.trend_buckets`, and passes on `covered >= th.min_regimes_covered` (3 of 3, ≥10 each).
The census buckets **closed trades by their entry date** under `backtest/regime.py`'s labels.
It is a census of trades that happened. It knows nothing about why they happened.

**Therefore the reachability condition is exactly one thing: the strategy must not skip.** If
every eligible cycle produces an attempted entry regardless of the regime label, the gate-6
census is taken over the *whole* entry-date population, and bull/bear/range coverage becomes a
property of the census labels over that population — a property O3 and O2 share identically,
because §2.2 gives them the same cycles and §2.3 the same window. D5 §6.4 records that an
8-year window ending 2026-09 starts ≈ 2018-09 and therefore contains 2018Q4, 2020 and 2022; one
bear-labelled cycle-month supplies 14 trades against a ≥10 floor.

**Drafted rule — the regime input modulates the strike, never the entry.**

```
label  = regime_from_proxy(proxy, t-1)                    # research/regime.py:62, lagged one session
shift  = regime_delta_shift  if label.trend is Trend.BEAR # research/regime.py:20-23
         else 0.0                                          # BULL or NEUTRAL
target_eff = min(short_delta_target + shift, max_short_delta)
```

The one-session lag is D5 §3.2's, for D5 §3.2's reason: `regime_from_proxy` is already
point-in-time for its own `t` (docstring: *"uses only `proxy` bars at indices <= `t`"*), so the
extra lag is strictly more conservative and removes any dependence on a close the signal session
itself produced. `RegimeState.risk_off` (`research/regime.py:41-43`) is deliberately not used:
it is `BEAR or HIGH vol`, and volatility does not tell direction.

**Why `target_eff` is *clamped* to the cap rather than refused, and why that is load-bearing.**
At `short_delta_target = 0.35` with `regime_delta_shift = 0.10` the shifted target is 0.45. With
`max_short_delta = 0.33` and `delta_tolerance = 0.05` no strike lies within tolerance of 0.45,
so a refusal rule would make every **bear** cycle in that grid cell a non-entry — which would
destroy the no-skip property in exactly the regime gate 6 is thinnest in, and would do it only
in some cells, silently confounding grid axis 2 with regime coverage. Clamping instead lets the
cap **compress** the shift: the trade still happens, at 0.33 rather than 0.45, and the grid
measures the credit-versus-directional-risk trade-off that map §3.2's Rule asks for rather than
measuring cycle availability. This is D5 §4.3's distinction — an inert *value* is not an inert
*parameter* — applied in the opposite direction.

**The two-partition cross-tab is still mandatory evidence.** FACT: `gate_6_regime` takes
`partition: RegimePartitionDisclosure` as a **required** argument (`options_gates.py:1140`) and
prints `partition.mismatch_fraction` in its own detail string. The filter reads
`research/regime.py` (`Trend.BEAR` ⇔ `sma50 < sma200` and the 200-SMA not rising,
`regime.py:71-77`); the census reads `backtest/regime.py::label_regimes` (bear ⇔ the 200-session
SMA fell; `range_bound` ⇔ close within ±3% of that SMA, short-circuited **before** the vol label
is attached). D4 §5.1a's option **(b)** is taken — measure and disclose — and the cross-tab of
`research/regime.py` trend × `backtest/regime.py` census label over the pre-sealed sessions is a
gate-6 evidence field.

**But for O2 the mismatch is no longer load-bearing, and saying so is the point.** D4 §5.1a's
correction is that O3's reachability claim was argued from the partition the strategy *filters*
on while gate 6 counts the partition the census *reads* — so a mirror-fired bear cycle can be
counted `range`. For O2 there is no filter to mismatch: the trade happens either way, so the
census counts whatever it counts and the mismatch fraction changes **which bucket** a trade
lands in, never **whether** it exists. O2's gate-6 reachability is therefore strictly stronger
than O3's, and it is the one respect in which this structure is easier to evaluate than the one
that ships first. The cross-tab is still reported, because a large mismatch tells the reader
that the strategy's own notion of "bear" and the gate's differ — which matters for interpreting
the bear bucket's expectancy even when it does not matter for the count.

**Gate 6b (joint trend × vol).** D4 §5.3's predicate is adopted unchanged: each vol marginal
≥10, each of the four joint cells ≥5, `range_bound` reported as its own vol-**unlabelled** cell,
census closure asserted. `gate_6b_joint` (`options_gates.py:1192-1233`) computes exactly this
and the thresholds are already its defaults (`min_vol_marginal_trades = 10`,
`min_joint_cell_trades = 5`, `options_gates.py:169-170`). `bear_lowvol` is rare by construction
and is the cell predicted, in advance, to bind.

### 3.3 Strike selection

For underlying close `U_t` on session `t` and expiry `E`:

1. **Delta per candidate strike.** `greeks(s=U_t, k=K, t=(E−t)/365, r=0.04, sigma=σ_K,
   call=True, q=q_t).delta` (`options/blackscholes.py:62`), with `σ_K` inverted from that
   contract's own **print-eligible** print on `t` (`implied_vol`, `:93`) where it has one, else
   read off D5 §5.3's same-session surface. A strike with neither is **not selectable**.
   Realised volatility is **never** a fallback (map §2.4b) — it sits below implied on average,
   which is precisely the quantity being harvested.
2. **Print eligibility at entry.** D5 §3.3(1a) verbatim: a leg whose signal-session bar fails
   the `volume ≥ 10` / `transactions ≥ 5` floor may not set an IV and may not fill; the cycle is
   a **non-entry**, counted `non_entry_thin_print`.
3. **Short strike.** Among **OTM call** strikes (`K > U_t`) with `delta ≤ max_short_delta`, pick
   the one whose delta is closest to `target_eff` (§3.2); tie-break **further OTM**, the
   conservative side — further OTM forgoes less upside and is the lower-credit choice, so the
   tie-break can never inflate the credit. If no strike lies within `±delta_tolerance` of
   `target_eff`, **no entry**, counted.
4. **Credit floor.** Compute the net credit at the **adverse modelled fill**, not at the print,
   and require
   `net_credit / (U_t × shares_per_contract) ≥ min_credit_pct_of_spot`, else **no entry**,
   counted. §4.3 derives the floor's values from the attainable distribution rather than
   choosing them. Applying the floor to the adverse credit rather than the print is D5 §3.3(4)'s
   deliberate conservatism and it is kept: moving it to the print credit would be a **loosening**
   and R4 forbids it.
   **Why the floor is a fraction of spot and not of the R scale.** A floor expressed against the
   declared `stop_usd × M` scale would be a different economic test on every underlying, because
   the scale is a fixed dollar amount while the credit scales with price. Premium yield —
   credit over share notional — is the quantity a covered-call seller is actually paid, it is
   the standard measure, and §4.3 shows it is **the one threshold in this design that is
   insensitive to the §2.4 price assumption**.
5. **Deliverable integrity.** `shares_per_contract == 100`, else the contract is refused and
   counted (gate 0.h). Already enforced at `options_engine.py:141-146`.
6. **No post-entry exclusion, ever.** D5 §3.3(6)'s rule is adopted in full: every entered
   structure stays in the evaluation; an option leg that cannot be priced from a print on the
   realised force-close session is marked at the conservative intrinsic floor, flagged
   `forced_intrinsic_mark`, and the fraction is gate-8 evidence. Exclusion is reserved strictly
   for conditions decidable **at or before entry**. Excluding on a post-entry condition is a
   survivorship channel whose *sign* no ceiling can bound.

### 3.4 Exits, the time stop, and assignment

Evaluated on each session close. The structure is opened and closed **as a unit** — the shares
are sold on the same session the call is bought back, for the reason in §3.1(4): a structure
half-closed into a bare short call is an undefined-risk position the program bans.

| Rule | Trigger | Drafted value |
|---|---|---|
| Profit target | option buy-back at the adverse fill ≤ `(1 − profit_target_pct) × entry_credit` | `profit_target_pct = 0.50` |
| **Stop** | **the underlying's session close ≤ `entry_share_basis − stop_usd`** | `stop_usd` declared, §6.1 |
| Time stop | `DTE ≤ time_stop_dte` | `time_stop_dte = 7` |
| Force close | the `expiry − 1` session | hard boundary (D3 §8 item 1) |

Whichever fires first. Execution defers to the next session on which the option leg prints
(map §2.4(3)); `exit_deferred_sessions` is recorded per trade.

**The stop is on the underlying's close, and that is forced, not chosen.** §6.1 shows gate 0.5
admits only one R identity, and that identity requires the loss at the stop to be a declared
constant less the credit. A stop on the *structure's* net P&L would make the declared scale
`R + credit`, which varies per trade, and `single_scale` (`options_gates.py:840`) refuses it.
So the stop must be a share-price level. It is explicitly a **close-basis** stop: there is no
intrabar option data and, under the 11 bps equity convention, no intrabar share data is used
either, so `backtest/engine.py:154-184`'s gap handling has no analogue and is **not** simulated.
The string `"close_basis_stop; no_intrabar_data; stop_not_a_live_order"` is carried in
`fill_model` on every trade.

**And here the covered call is materially worse than the vertical, which must be said plainly.**
For O3, `R_hard = width_usd × M + entry_costs` is a bound **no parameter setting inside the
version can breach** (D5a §3.3), because the structure's max loss is the width. For O2 there is
**no such bound**: the true max loss is `S₀ × M − credit` — the shares going to zero — which on
SPY at $764.29 is ≈ **$75,916**, or **380× the declared $200 scale**. A gap through the stop is
limited only by the share price. The `r_clamped` counter and CC-9's ceiling therefore measure
something different here than F9 does for O3: for O3 a clamp means the cost model and the exit
rule disagree; for O2 a clamp means the stop did not bind, which is the *expected* case, not the
exceptional one.

**Assignment handling (D3 §8, and the three paths it supports).**

1. **Force-close at `expiry − 1`.** Never held through expiry (D3 §8 item 1). The option leg is
   priced with the per-leg **intrinsic floor** — a short leg is never bought back below its
   intrinsic value — and the modelled spread is applied adversely (D3 §8 item 2). If the leg has
   no print on that session, the close is at the intrinsic floor with no print component,
   flagged `forced_close_no_print`, and is **not** excluded from the sample (D3 §8 item 3).
2. **Expire worthless.** The modal outcome for an OTM short call is a buy-back at the intrinsic
   floor of zero plus one modelled spread. This is the force-close path, not a separate branch.
3. **Assignment settled at intrinsic.** If the short call is ITM on the force-close session, the
   buy-back at intrinsic plus the share sale is **arithmetically identical to assignment**, to
   within one session's share move and the modelled spread:
   `−(S − K)·100` (buy back the call at intrinsic) `+ S·100` (sell the shares) `= K·100`, which
   is exactly the assignment proceeds. This identity is worth stating because it means the
   force-close approximation costs O2 far less than it costs O3: for a covered call the
   approximated event and the modelled event settle at the same number.
4. **Reaching expiry raises and halts.** `process_option_expiries` raises `OptionExpiryUnhandled`
   rather than guessing (D3 §8 item 6). FACT: `OptionContract.exercise_style` defaults to
   `'american'` and `options_engine.py:147-151` already refuses any other style.
5. **Early assignment is not modelled, and its bias is disclosed with its direction.** The real
   case for a short call is dividend-driven early exercise the day before an ex-date, which
   costs the seller the dividend. Not modelling it is biased **in the strategy's favour**. Note
   that `q` is doubly load-bearing for O2: it prices the call (map §2.4a) *and* it is the only
   input that lets the run even **rank** which short calls were at risk. Decision 11 sources `q`
   per underlying per session, so the ranking is available; the path is still not modelled in
   v0.1.0 and is disclosed at gate 8 on every evaluation.

### 3.5 P&L, R, and the two reported bases

```
declared_scale = stop_usd × shares_per_contract                     # FIXED for the version
R (dollars)    = declared_scale − net_credit_received + entry_costs # known at entry
entry_costs    = option commission+fee on 1 contract-side ($0.80)
                 + share entry friction (100 × S₀ × 5.5 bps)
pnl_r          = realised_pnl_dollars / R
```

`net_credit_received` is the credit at the adverse modelled fill, so R is the larger,
conservative denominator. `dte_at_entry` and `dte_at_exit` are recorded per trade and the gate-1
walk-forward and gate-5 sensitivity reports are stratified by DTE bucket (21-30 / 31-45), per
map §2.2.

**The clamp.** D5 §3.5's Option 1 is adopted: report the **unclamped** `pnl_r` as the gated
series (`OptionTrade.pnl_r` is already documented as unclamped, with `pnl_r_clamped` a
supplementary reported line — `options_engine.py:260-262,298-301`), record `r_clamped`, and
report the clamp count and the unclamped minimum at gate 8. §3.4 explains why the clamp rate
means something different here.

**The overlay-delta diagnostic, which map §4.2 asks for and this design cannot gate on.**
Map §4.2 recommends evaluating a covered call "as an **overlay delta** against the same equity
position held naked, not as a standalone R stream". That is the economically right question and
it is **not** the gating basis here, for two reasons that are both structural:

- gate 0.5 admits exactly one R basis per version (`options_gates.py:839-844`), and a difference
  stream against a naked-share benchmark is a second basis; and
- decision 13's standalone $25,000 options account means the paper stream would actually pay the
  share round trip, so charging it is what the account would experience.

**Drafted rule.** The standalone basis **gates**. The overlay delta — the same structures'
P&L less the P&L of 100 naked shares held over the identical entry-to-exit window, divided by
the same R — is a **mandatory paired diagnostic**, reported beside it. **If the two disagree in
sign, the disposition is NO-SHIP regardless of the gate verdicts** (CC-12). This is the standing
D5 §3.3(6) and §5.2 already give their paired diagnostics, and it is strictly more searching than
either convention alone (R4).

### 3.6 What the engine must gain, and what it must not

**FACT — the engine refuses this structure today.** `OptionStructure.__post_init__`
(`options_engine.py:152-159`) dispatches to `_validate_vertical_credit` for `VERTICAL_CREDIT`
and raises `StructureRefused` for anything that is not `VERTICAL_DEBIT`:
*"`covered_call` is not implemented in Phase 1 (decision #12: the short vertical credit spread
ships first)."* And `OptionLeg.contract` is a `ContractRef` (`data/option_chain.py:42-60`) —
an option contract — so **the 100 shares cannot be expressed as a leg**.

**Drafted resolution — implicit share leg, no new field.** `structure_type = COVERED_CALL`
*implies* `+100 × contracts` shares of `underlying_symbol`, held for the structure's life. The
engine already receives the underlying's `PriceSeries` and each session's `underlying_close`, so
the share leg can be priced from data already in hand. The changes are:

| # | Change | Where | Why it is not a gate change |
|---|---|---|---|
| E1 | a `_validate_covered_call` branch: exactly 1 leg, `right is CALL`, `qty == −1` per structure, `strike > entry share price` | `options_engine.py:152-159` | a constructor validator |
| E2 | share-leg pricing and mark, on the frozen equity `CostModel` convention | the options engine's fill/mark path | additive; the equity engine is untouched |
| E3 | `net_credit_at_print` / `r_at_print` populated on the same identity gate 0.5 recovers | `OptionTrade` construction | the gate's arithmetic is unchanged; only the values it reads |
| E4 | collateral reservation for the share leg | `paper/options_ledger.py`, D3 §3.2's fourth row, which today reads *"the underlying shares, not cash — **out of Phase 1 scope**"* | paper-side; gate 0.i reads a number, not a ledger |

**Explicitly unchanged:** the `OptionsStrategy` Protocol (`options_evidence.py:189-213` — O2
satisfies `key`, `horizon`, `selection_cost_model`, `__call__`, `sensitivity_axes`,
`oat_parameters`, `structure_identity`, `mechanical_benchmark`, `mechanical_spec` exactly as
`OptionsShortVertical` does), `OptionsEntrySignal`, `OptionCostModel`, every threshold in
`OptionsGateThresholds`, and **every gate function in `options_gates.py`**. If freezing this
draft ever requires editing a gate, the correct response is to abandon the structure, not the
gate (R4).

---

## 4. Parameters and the sensitivity grid

### 4.1 Baseline parameters

Per D5 §4.1: these live in a frozen `params` dataclass interpolated into the spec's **text**
fields, exactly as `TrendParams` and `ShortVerticalParams` do, and must never become
`StrategySpec` fields — `persistence.spec_json_hash` hashes every spec field but
`{git_sha, status, notes}`, so adding one would change the hash of every existing strategy and
put both live PAPER_APPROVED versions out of their own approval scope. FACT:
`promotion.py:1236` passes `baseline_params=_asdict(strategy.params)` to the sensitivity run, so
**every grid axis must be a field of this dataclass.**

```python
@dataclass(frozen=True, slots=True)
class CoveredCallParams:
    short_delta_target:      float = 0.25    # AXIS 1
    max_short_delta:         float = 0.40    # AXIS 2
    regime_delta_shift:      float = 0.10    # AXIS 3  — the only thing the signal claims
    dte_target:              int   = 35      # AXIS 4
    profit_target_pct:       float = 0.50    # AXIS 5
    min_credit_pct_of_spot:  float = 0.011   # AXIS 6  — derived in §4.3
    stop_usd:                float = <UNRESOLVED — §6.3>   # FIXED per version; the R scale
    time_stop_dte:           int   = 7       # FIXED
    dte_window_lo:           int   = 28      # FIXED
    dte_window_hi:           int   = 45      # FIXED
    delta_tolerance:         float = 0.05    # FIXED
    min_leg_volume:          int   = 10      # FIXED — print eligibility
    min_leg_transactions:    int   = 5       # FIXED — print eligibility
```

`stop_usd` carries no value in this draft **on purpose**. §6.3 shows no value exists that
satisfies gate 0.5 and gate 0.i together at the currently taken caps, and writing a placeholder
there would let a reader implement a version whose R scale was chosen by nobody.

**`stop_usd` is FIXED, never an axis, and the reason is D5a §6.2's reason 1 verbatim.**
`stop_usd × M` *is* the R scale. An axis on it puts two R scales into one gate-5
`positive_fraction` / `neighbour_positive_fraction` statistic — the exact pooling gate 0.5's own
evidence string forbids (`options_gates.py:888-891`), and D4 §3 clause (d) states it
prescriptively: the scale is "a declared constant, evaluated one value per run, never selected
per trade." It appears in §4.4's OAT table instead, where a "best cell" reading cannot select it.

### 4.2 The grid — 6 axes, 96 points

**FACT that determines the shape:** `research/sensitivity.py:29` `MAX_GRID_POINTS = 120`,
enforced at `:178-181` by a `ValueError`, over the **full Cartesian product**. The smallest full
factorial over seven axes is `2⁷ = 128 > 120`, so seven free axes are arithmetically impossible;
six is the maximum and only with at most one three-valued axis (`3 × 2⁵ = 96 ✓`;
`3 × 3 × 2⁴ = 144 ✗`).

| # | Axis | Values | Baseline | Why these values |
|---|---|---|---|---|
| 1 | `short_delta_target` | **0.15, 0.25, 0.35** | 0.25 — centred, two one-step neighbours | the parameter map §3.2 warns gate 5 will optimise along (the credit floor is satisfied most easily where the strike is closest and most upside is surrendered); it gets the only three-value slot so both directions are probed |
| 2 | `max_short_delta` | **0.33, 0.40** | 0.40 | map §3.2's Rule honoured literally — the credit floor is always paired with a delta cap and **both** are axes. 0.33 binds on every `short_delta_target = 0.35` cell (truncating the band `[0.30, 0.40]` to `[0.30, 0.33]`) and on every bear-shifted cell via §3.2's clamp; it is inert at 0.15 and 0.25, which `_axis_movement` tolerates because it tests an axis **globally** (`sensitivity.py:120-153`). 0.30 was rejected on D5 §4.3's reasoning: it would leave only the exact boundary selectable at target 0.35 and **empty** those cells rather than bind on them |
| 3 | `regime_delta_shift` | **0.05, 0.10** | 0.10 | the only parameter that carries the strategy's claim (§1). 0.05 is the weaker-signal side. A shift of 0.0 is not a grid cell — it is gate 7b's mechanical benchmark (§8), and offering it as a selectable cell would let gate 5 "choose" to have no signal |
| 4 | `dte_target` | **21, 35** | 35 | 21 is the thin-theta / high-gamma end. **45 is excluded by derivation, not preference** — D5 §3.1(5)'s expiry-spacing arithmetic, unchanged here |
| 5 | `profit_target_pct` | **0.50, 0.75** | 0.50 | 0.75 is the tail-*increasing* direction (later take, more days of share exposure per trade) and therefore the direction that makes gate 5's 60%-positive / 75%-neighbour thresholds **harder**. 0.25 is the easier direction and moves to §4.4 |
| 6 | `min_credit_pct_of_spot` | **0.011, 0.016** | 0.011 | derived in §4.3 from the attainable distribution, not chosen. 0.016 is the thinning direction — fewer, richer cycles, more cells at risk of the 15-trade floor |

`3 × 2 × 2 × 2 × 2 × 2 = 96 ≤ 120` ✓. Baseline cell = `(0.25, 0.40, 0.10, 35, 0.50, 0.011)`.
One-step neighbours (`sensitivity.py:105-118` `_is_neighbour`: differs on exactly one axis by
exactly one index): **7**.

**Gate-5 evaluability floor, adopted from D5 §5.5.** FACT
(`sensitivity.py:218-223,236`): `pos_frac = len(positive) / len(evaluable)` where `evaluable` is
the subset with `n_trades ≥ 15`, and the only guard is `len(evaluable) < 3` — so a grid where 92
of 96 points are too thin can report "100% positive" off four cells. Gate 5 is read as failing
on evaluability unless `n_evaluable ≥ 58` (= 60% of 96), which is already the shipped threshold
`sensitivity_min_evaluable = 58` (`options_gates.py:165`).

**The cells predicted in advance to fall below 15 trades**, so that a thin corner is a
prediction and not an excuse: `short_delta_target = 0.15` combined with
`min_credit_pct_of_spot = 0.016` — a 0.15-delta call rarely yields 1.6% of spot in 35 days
below σ ≈ 0.30 — across both values of axes 2, 3, 4 and 5: **16 of 96 cells**, leaving a
predicted `n_evaluable ≈ 80`. The `max_short_delta = 0.33` cells are **not** in the at-risk list,
which is why 0.33 and not 0.30 was chosen.

### 4.3 Deriving the credit floor rather than choosing it

D5a §2.4's rule is adopted verbatim, because the defect it repairs (a floor set by taste that
turns out to sit outside the attainable region, so the version enters nothing anywhere) is
exactly the defect this design is most exposed to:

> **Rule.** Take the quartiles of the attainable **adverse** premium yield
> `net_credit / (U × 100)` over the declared design space (§2.4: three underlyings × the ten-σ
> grid, at the baseline `short_delta_target = 0.25` under the `max_short_delta = 0.35` cap,
> 35 DTE). Round **down** to the nearest 0.001 — rounding up moves toward the unreachable side.
> p25 is the OAT loosening value, the median is the baseline, p75 is the grid's harder value.

Attainable adverse premium yield over 90 cells: **min 0.0051, p25 0.0079, median 0.0119,
p75 0.0169, max 0.0249.**

| quantile | raw | rounded down | role |
|---|---|---|---|
| p25 | 0.0079 | **0.007** | §4.4 OAT loosening value |
| median | 0.0119 | **0.011** | **baseline `min_credit_pct_of_spot`** |
| p75 | 0.0169 | **0.016** | axis 6's harder second value |

**Sensitivity to the §2.4 price assumption — and a derived property worth recording.**

| price scale | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| 0.85 (−15%) | 0.0051 | 0.0079 | 0.0117 | 0.0169 | 0.0246 |
| **1.00 (declared)** | 0.0052 | **0.0079** | **0.0119** | **0.0169** | 0.0249 |
| 1.15 (+15%) | 0.0052 | 0.0078 | 0.0119 | 0.0169 | 0.0246 |

The quantiles move by at most **0.0002** across the whole ±15% band. That is not luck: for a
delta-targeted strike, `credit / (U × 100)` is homogeneous of degree zero in `U`, so the floor is
structurally insensitive to the price level. **`min_credit_pct_of_spot` is the only threshold in
this design that the §2.4 discrepancy cannot move**, and it is the reason the floor is expressed
as a fraction of spot rather than against the declared R scale (§3.3(4)), which would have made
it price-dependent and exposed it to the full 15.8% error already demonstrated on SPY.

At the 2× spread setting (gate 4b form (a), where selection is frozen and only friction is
re-priced) the same quantiles read p25 0.0076 / median 0.0115 / p75 0.0163 — the floor values
stay strictly inside the attainable region at both settings.

### 4.4 Parameters held fixed, and the disclosed one-at-a-time table

Reported, non-gating diagnostics at the baseline cell. Every parameter of the design is either a
gate-5 axis or listed here, because under R5 "abandoned variant" is definable only as "a
pre-registered cell that was not reported" — a parameter in neither list is invisible to both
mechanisms.

| Parameter | Fixed at | OAT values | Reason it is not an axis |
|---|---|---|---|
| **`stop_usd`** | §6.3 (unresolved) | the cap-compliant value and 2× it | it **is** the R scale; an axis would pool two R scales in one gate-5 statistic (D4 §3(d), D5a §6.2). Reported so the R-scale sensitivity is visible without being selectable |
| `regime_delta_shift` (third value) | 0.10 (axis) | **0.15** | the stronger-signal direction; the grid carries 0.05 and 0.10 |
| `profit_target_pct` (second OAT value) | 0.50 (axis) | **0.25** | the *easier* direction (less share exposure per trade); the grid carries the harder 0.75 |
| `min_credit_pct_of_spot` (second OAT value) | 0.011 (axis) | **0.007** | map §3.2's named failure mode — loosening the floor to reach for credit. Reported, never offered as a selectable cell. It is §4.3's derived p25 |
| `time_stop_dte` | 7 | 5, 7, 14 | binds only when neither target nor stop fires; reported with `skipped_concurrency` alongside because the two interact (D5 §3.1(5)) |
| `dte_window_lo/hi` | 28 / 45 | (24,50), (28,45), (31,42) | a guard around `dte_target`, not an independent lever |
| `delta_tolerance` | 0.05 | 0.03, 0.05, 0.08 | a selection tolerance. **Reported jointly with axis 2 and axis 3**, since §3.2's clamp makes all three interact by construction |
| `min_leg_volume` / `min_leg_transactions` | 10 / 5 | (5,3), (10,5), (25,10) | a data-eligibility floor, not a strategy parameter; reports entry-count sensitivity and the change in the `\|close − vwap\| / close` distribution |
| **share-leg friction** | 11.0 bps round trip | 11.0, 22.0 bps | the frozen equity convention (R4) and its gate-4b double. Reported because §6.4 shows it is 0.09-0.39 R at a cap-compliant scale — a first-order term, not a rounding error |
| `r` (risk-free) | 0.04 | 0.02, 0.04, 0.06 | an input assumption; reports delta-selection stability. Inside `options_config_hash` because it is strike-shaping |
| `contracts` / shares | 1 / 100 | — | fixed by the structure; 100 shares per contract is what "covered" means |
| regime-shift direction | bear → closer strike | (no alternative) | the alternative **is** gate 7b's mechanical benchmark (§8) |

**Interpretation rule, pre-registered.** If the best cell of the gate-5 grid is the
highest-delta cell (`short_delta_target = 0.35`) or the loosest cap (`max_short_delta = 0.40`),
that is reported as the map §3.2 warning it is — the credit floor being satisfied most easily
where the most upside is surrendered — and it **does not move the baseline**. Moving the
baseline is a behavioural change, i.e. a new version and a new sealed look under R3, which §11's
budget does not fund.

---

## 5. Gate 0 sub-thresholds

All fixed before any coverage summary exists, per map §1.5 and §7. Each is additive to gate 0
and therefore strictly *more* searching, which R4 permits. Where the threshold is
structure-specific it is derived here rather than inherited.

**0.a — window.** Unchanged: pre-sealed ≥ `min_presealed_days = 350` on top of
`sealed_window_days = 365` (`options_gates.py:138-139`), `min_dte_at_entry = 1`. Satisfied by
construction at §2.3's 8 years. `Horizon.MEDIUM_SWING` does not enter gate 0's INTRADAY branch.

**0.b — underlying coverage.** Continuous `OHLCVDaily` from source `massive` across the whole
window for each underlying (R6). **O2-specific weight:** for O3 the underlying series only sets
the strike search and the regime label. For O2 it is **half the position**, so a gap in the
underlying series is not a nuisance, it is an unpriced share leg. `UNDERLYING_ADJUSTED = False`
(`options_evidence.py:179`) still holds — a listed strike is an unadjusted number — and splits
are handled by exclusion (D1 §7), which for a share-carrying structure also means the share
quantity is never silently re-based.

**0.c — cycle bracketing: ≥ 0.90** (`bracket_fraction_min`, `options_gates.py:142`). The
threshold is D5 §5.1's and does not move; the **definition** is structure-specific and is
weaker than O3's, which is a real and derivable difference:

> A (underlying, monthly cycle) pair brackets **iff** (1) listed **call** strikes exist both
> above and below the `target_eff` strike, so the delta search is not truncated by the edge of
> the stored chain; **and** (2) the selected contract has `shares_per_contract == 100`; **and**
> (3) the selected contract has a print-eligible bar on the signal session; **and** (4) the
> underlying has a bar on the signal session.

O3's definition additionally requires a listed strike at exactly `K_short ∓ width_usd`
(D5 §5.1 clause 2, tightened by D5a §3.4 to exact placement). O2 has no wing, so clause 2 does
not exist and the coarse-ladder non-entry channel that dominates O3's entry rate is absent.
Clause 4 is new and is the share leg's analogue. Derivation, as a design judgement and not an
empirical one: below ~90%, strike selection is being rewritten by data availability in more than
one cycle in ten, at which point the reported `short_delta_target` is a label rather than a
parameter and gate 5's delta axis measures coverage.

**0.d — bar continuity: 0.80 evaluation-wide, 0.60 per-structure stratification**
(`bar_continuity_min`, `thin_continuity_floor`, `options_gates.py:143-144`). D5 §5.2's rule
adopted verbatim, including the correction that the 0.60 floor is a **flag and a paired
diagnostic, never an exclusion**: realised continuity is decidable only after the holding period
and correlates with the outcome. Structures below 0.60 are flagged `thin_continuity`, counted,
and OOS expectancy is reported with and without them; a sign disagreement, or a flagged fraction
above 15%, is NO-SHIP (CC-12). **O2-specific:** the held-session denominator counts the option
leg and the underlying bar; with one option leg instead of two, O2's continuity is structurally
easier to satisfy than O3's.

**0.e — greeks/IV provenance.** `local_bs_inverted` first, `same_session_surface` as the only
fallback, `pct_otm_proxy` **never** (`pct_otm_proxy_max_fraction = 0.0`,
`options_gates.py:146`). D5 §5.3's surface floor adopted unchanged: ≥5 print-eligible contracts
on that (underlying, expiry, session), ≥3 distinct strikes **on the call side**, OLS quadratic in
log-moneyness per expiry, **no extrapolation outside the convex hull**, term structure linear in
`σ²T` between two qualifying expiries. `surface_n_floor = 5`,
`surface_min_distinct_strikes = 3` are already the shipped values (`options_gates.py:147-148`).
Realised volatility is never a fallback; a run that falls back to it is **void**, not failed
(CC-10).

**0.f — fill provenance, with one addition O3 does not need.** The disclosure that NBBO is
unavailable under the active entitlement for options **and** equities (7 of 7 batches, map §0.3
item 3) is carried as today. **The O2 addition:** the share leg's 11.0 bps round trip is a
*modelled* spread against an equally unobserved quote — `/v3/quotes/{sym}` is 403 — and for this
structure the share spread is a **larger** cost term than the option spread at every declared
level (§6.4: $26.40-$96.68 share versus $10.72-$71.65 option). The evaluation record must name
it as modelled, not observed, with the same prominence the options spread gets.

**0.g — dividend-yield provenance.** `q` sourced and recorded per underlying per session
(decision 11); `q_defaulted_count` must be 0; a session with no `q` produces no entry. For O2 `q`
is load-bearing twice over — it prices the call *and* it is the only handle on dividend-driven
early assignment (§3.4 item 5). A run that used `q = 0.0` by default fails gate 0 outright.

**0.h — deliverable integrity.** `shares_per_contract == 100` at entry, refusals counted.
Already enforced at `options_engine.py:141-146`. The caveat recorded at
`data/option_chain.py:45-50` applies: the adapter writes
`int(r.get("shares_per_contract", 100))`, so a vendor omission is indistinguishable from a
vendor-confirmed 100, and the refusal counter is the only visible handle on it.

**0.i — risk-limit fit. This is the gate this structure fails, and §6.3 derives it.**

---

## 6. The R arithmetic, and the two impossibility results

Every figure in this section is closed-form arithmetic on §2.4's declared inputs, reported at
0.85 / 1.00 / 1.15 on the price level. No conclusion in it changes sign anywhere in that band.

### 6.1 Gate 0.5 admits exactly one R identity, and it is not max loss

**FACT.** `gate_0_5_structure` (`options_gates.py:834-844`) computes

```python
observed_widths = sorted({round(t.r_at_print + t.net_credit_at_print, 6) for t in trades})
single_scale    = len(observed_widths) <= 1
scale_matches   = math.isclose(observed_widths[0], identity.r_scale_usd, rel_tol=1e-6)
```

with `r_scale_usd = width_declared × m_declared` (`options_gates.py:304-306`). So the gate
hard-codes the identity

```
r_at_print + net_credit_at_print  ==  declared_scale,   identically, for every trade
```

and requires `declared_scale` to be a **constant of the version**. Three consequences follow,
and none of them is negotiable without editing the gate:

1. **R = max loss is impossible.** A covered call's max loss is `S₀ × M − credit`, so
   `r_at_print + credit = S₀ × M`, which would require `width_declared = S₀` — one scale per
   underlying **and per cycle**. Across §2.2's 14 underlyings over 96 cycles that is hundreds of
   distinct values and `single_scale` refuses on the first two. **The R definition map §2.6 uses
   for every other structure cannot be used here at all.**
2. **R must take the form `declared_scale − credit`.** The credit must *subtract*. A risk budget
   that did not subtract the credit — the more conservative reading — would make
   `r_at_print + credit = budget + credit`, which varies per trade, and `single_scale` refuses
   that too.
3. **Therefore `declared_scale > max credit over the declared design space`**, or R is zero or
   negative on some trades and `pnl_r` is meaningless. This is the constraint that collides with
   gate 0.i.

The honest reading of `R = stop_usd × M − credit + entry_costs` is: *the loss if the share leg
falls `stop_usd` per share and the short call is closed for nothing.* It is a **declared
per-structure risk budget**, not a structural bound. §3.4 states what it does not bound.

### 6.2 The credit is large, and that is the whole problem

Adverse net credit `(BS price − max($0.02, 0.03 × price)) × 100` at 35 DTE over the declared
design space (three underlyings × ±15% × σ 0.12-0.60, at `short_delta_target` ∈ {0.12, 0.25,
0.35} under the 0.35 cap):

| underlying | min credit | max credit |
|---|---|---|
| SPY | $134.49 | **$3,379.18** |
| QQQ | $104.50 | $2,607.45 |
| IWM | $39.85 | $1,044.70 |
| **whole space** | **$39.85** | **$3,379.18** |

At the baseline `short_delta_target = 0.25` and declared levels the credit reads $513.04 (SPY,
σ 0.15), $987.61 (SPY, σ 0.30), $396.98 (QQQ, σ 0.15), $147.39 (IWM, σ 0.15), $314.02
(IWM, σ 0.30).

**Compare D5a §3.3's equivalent for O3: a $2.00-wide vertical's entire gross width is $200, and
its adverse credit is bounded by the attainable ratio 0.155 at $31.** O2's *credit alone* is
1.3× to 13.5× O3's entire R scale. That is the structural difference, in one line.

### 6.3 CC-1 — gate 0.5 and gate 0.i are jointly unsatisfiable

**FACT.** `gate_0i_risk_limits` (`options_gates.py:772-776`) passes only if

```
av.r_max_observed_usd        <= th.options_per_structure_max_loss     # $250 (options_gates.py:150)
av.concurrent_open_r_max_usd <= th.options_total_open_max_loss        # $1,000 (:151)
av.structures_breaching_per_structure_cap == 0
av.limits_in_options_config_hash is True
```

The bound no parameter setting inside the version can breach — D5a §3.3's `R_hard`, applied here
— is `R_hard = declared_scale + entry_costs`, because the strategy refuses `net_credit ≤ 0`
outright. Putting §6.1(3) and gate 0.i together:

```
max_credit  <  declared_scale  <=  options_per_structure_max_loss − entry_costs
```

`entry_costs` = $0.80 (one option contract-side) + `100 × U × 5.5 bps`, so it varies with the
price level: **$12.02 (IWM −15%) to $49.14 (SPY +15%)**.

| per-structure cap | underlying | scale must exceed | scale must not exceed | interval |
|---|---|---|---|---|
| **$250** (decision 4) | SPY @ $764.29 | $3,379.18 | $207.16 | **EMPTY** |
| $250 | QQQ @ $590.00 | $2,607.45 | $216.75 | **EMPTY** |
| $250 | IWM @ $240.00 | $1,044.70 | $236.00 | **EMPTY** |
| **$900** (OP-1's recommendation) | SPY @ $764.29 | $3,379.18 | $857.16 | **EMPTY** |
| $900 | QQQ @ $590.00 | $2,607.45 | $866.75 | **EMPTY** |
| $900 | IWM @ $240.00 | $1,044.70 | $886.00 | **EMPTY** |

Empty in all nine cells, and in all nine at −15% and +15% as well.

> **CC-1 (falsification criterion, keyed before any look).** At decision 4's $250 per-structure
> cap there is **no value of `stop_usd`** that satisfies gate 0.5's single-positive-R-scale
> requirement and gate 0.i's per-structure cap simultaneously, on any Stage-A underlying, at any
> σ in the declared grid, at any price level within ±15%. The interval is empty by a factor of
> **16.8×** ($3,379.18 required versus $200.86 permitted). At OP-1's recommended **$900** it is
> still empty, by **4.0×**. The smallest per-structure cap that makes the interval non-empty is
> **> $3,428.32** for the full Stage-A set, **> $2,645.57** for QQQ + IWM, and **> $1,060.68**
> for **IWM alone**. D4 §2.8a forbids raising the cap after a gate result, so this must be
> decided before the first evaluation or not at all.

**What this is not.** It is not a finding that covered calls lose money; this document measures
no returns and asserts none. It is a finding that at the taken capital limits the ladder cannot
be given a well-posed R unit for this structure, and a ladder that cannot be given a unit cannot
produce evidence.

### 6.4 Cost viability — the one test O2 passes where O3 fails

D5a §4's F14 kills O3 because the winning outcome is negative in R at every cap-compliant width:
the friction is set by the leg prints and is nearly independent of the width, while the credit
scales with the width, so the $250 cap forbids a width large enough to cover the cost. **The
covered call has the opposite cost profile**, and the arithmetic should be recorded because it
is the one respect in which O2 is the better structure.

Round-trip friction `F` = option (2 crossings × full modelled spread × 100, plus $1.60
commission+fees) + share (100 × U × 11.0 bps). The premium-harvest half of the trade is
`0.5 × C` at the 50% profit target. At `short_delta_target = 0.25`, 35 DTE, declared levels:

| U | σ | credit C | 0.5 C | F option | F share | F total | **0.5C − F** |
|---|---|---|---|---|---|---|---|
| SPY 764.29 | 0.15 | $513.04 | $256.52 | $33.33 | $84.07 | $117.41 | **+$139.11** |
| SPY 764.29 | 0.20 | $674.38 | $337.19 | $43.31 | $84.07 | $127.39 | **+$209.80** |
| SPY 764.29 | 0.30 | $987.61 | $493.81 | $62.69 | $84.07 | $146.76 | **+$347.05** |
| QQQ 590.00 | 0.15 | $396.98 | $198.49 | $26.16 | $64.90 | $91.06 | **+$107.44** |
| QQQ 590.00 | 0.30 | $755.58 | $377.79 | $48.34 | $64.90 | $113.24 | **+$264.55** |
| IWM 240.00 | 0.15 | $147.39 | $73.70 | $10.72 | $26.40 | $37.12 | **+$36.58** |
| IWM 240.00 | 0.30 | $314.02 | $157.01 | $21.02 | $26.40 | $47.42 | **+$109.59** |

Positive in **27 of 27** cells across the three underlyings × three price scales × three σ, and
at the **2× spread setting** (both asset classes doubled, per D4 §4.2) positive in **8 of 9** —
the single negative is IWM at σ = 0.15, at **−$1.22**, which is a genuine knife-edge and is
recorded as such.

> **CC-4 (recorded, and it is a pass).** The covered call's premium-harvest component covers its
> own round-trip friction with room to spare at the baseline spread on every declared cell, and
> at the 2× spread on 8 of 9. D5a §4's F14 — the finding that no cap-compliant O3 width is
> cost-viable — **does not carry over.** What kills this structure is not cost.

**One term worth naming separately.** The **share** leg supplies $26.40-$96.68 of the friction,
which is 0.09-0.39 R at a $250 scale and 0.03-0.11 R at $900 (§4.4 lists it as an OAT row for
this reason). It is the largest single cost term in the structure at every declared level and it
is charged against a modelled, unobserved equity spread. Any reader treating the equity 11 bps as
"the proven side" should note that `/v3/quotes/{sym}` is 403 in 7 of 7 entitlement batches, so
this number is exactly as unverified as the options one.

### 6.5 CC-2 — a cap-compliant stop is smaller than the noise

Even granting a cap-compliant scale, the stop distance it implies is not an economically
meaningful level. At the declared σ, the share leg's standard deviation over the 28-day hold
(`dte_target = 35` → `time_stop_dte = 7`) is:

| U | σ | 1-day sd / share | 28-day sd / share | 28-day sd / structure | a $2.00 stop, in 28-day sd | P(touch) |
|---|---|---|---|---|---|---|
| SPY 764.29 | 0.15 | $7.22 | $31.75 | **$3,175.28** | 0.063 | 0.950 |
| SPY 764.29 | 0.20 | $9.63 | $42.34 | $4,233.71 | 0.047 | 0.962 |
| SPY 764.29 | 0.30 | $14.44 | $63.51 | $6,350.56 | 0.032 | 0.975 |
| QQQ 590.00 | 0.15 | $5.57 | $24.51 | $2,451.18 | 0.082 | 0.935 |
| QQQ 590.00 | 0.30 | $11.15 | $49.02 | $4,902.37 | 0.041 | 0.968 |
| IWM 240.00 | 0.15 | $2.27 | $9.97 | **$997.09** | 0.201 | 0.841 |
| IWM 240.00 | 0.30 | $4.54 | $19.94 | $1,994.18 | 0.100 | 0.920 |

`P(touch)` is the driftless first-passage probability `2Φ(−b̃ / σ√T)` under the declared σ — an
assumption of the same class as D5 §6.2b's assumed `p_m`, stated in advance to make the design
falsifiable, not a measurement.

> **CC-2.** At a $2.00-per-share stop — the largest round figure that fits the $250 cap after
> entry costs — the stop sits at **0.03 to 0.20 of one 28-day standard deviation** of the share
> leg and is touched with probability **0.84 to 0.98** over the hold. The structure is
> force-closed on noise before either the profit target or the time stop can fire. The stop
> distance needed to sit at **one** 28-day σ implies a scale of **$997 (IWM, σ 0.15) to $6,351
> (SPY, σ 0.30)**, and at **half** a σ, **$499 to $3,175** — every one of which gate 0.i refuses
> at $250 and all but the two cheapest at $900.

And the expectancy bound follows directly. With `P(stop) = p` and the gain capped by the short
strike, the mean is bounded above by `(1−p) × max_gain/R − p`. At SPY, σ 0.15, a $200 scale:
the credit ($513.04) **exceeds the scale**, so `R = 200 − 513.04 + 42.84 = −$270.20` — a
negative denominator, which is CC-1 restated from the other end. On the one declared cell where
a $200 scale yields a positive R (IWM at σ 0.15: `R = $66.61`), the max gain is
`(249 − 240) × 100 + 147.39 = $1,047.39 = 15.72 R` against `P(stop) = 0.841`, giving a mean
bounded above by `+1.659 R` — a figure that only looks survivable until §6.6 divides it by the
standard deviation that produced it.

### 6.6 Gate 4 — the deciding gate, and the required `n`

Gate 4 (`min_bootstrap_ci_low_r = 0.02`, `options_gates.py:159`; `gate_4_bootstrap` at `:954`)
is approximately `mean − 1.96·sd/√n > 0.02`, so `n > (1.96·sd / (mean − 0.02))²`. The sd that
matters is the share leg's, because §1 establishes it supplies most of the variance. Expressed
in R units:

| sd of the trade series | mean = 0.05 R | mean = 0.10 R | mean = 0.25 R | mean = 0.50 R |
|---|---|---|---|---|
| **1.06 R** (O3's, for scale: D5a's R varies only $170.60-$181.60) | 4,796 | 674 | 82 | 19 |
| **4.0 R** (IWM, σ 0.15, $250 scale) | 68,295 | 9,604 | 1,162 | 267 |
| **12.7 R** (SPY, σ 0.15, $250 scale) | 688,457 | 96,814 | 11,713 | 2,689 |
| **25.4 R** (SPY, σ 0.30, $250 scale) | 2,753,830 | 387,257 | 46,852 | 10,757 |

Read against §2.3's available `n`:

| available `n` | sd = 4.0 R | sd = 12.7 R | sd = 25.4 R |
|---|---|---|---|
| 259 OOS trades | mean must exceed **+0.507 R** | **+1.567 R** | **+3.113 R** |
| 92 sealed-year trades | **+0.837 R** | **+2.615 R** | **+5.210 R** |

At $900 the sds fall to 1.11-7.06 R and the required means to +0.155 to +0.880 R at n = 259 —
better, and still far above anything a premium overlay produces.

**And gate 8's clustering makes it worse, both ways, because ruling R-1 makes both units bind.**
`DECISIONS_2026-09-12_wave3.md` R-1: gate 8's CI uses the **D4 unit**, `(underlying, expiry
cycle)` (`options_evidence.py:167` `CLUSTER_UNIT_D4`, key function
`cluster_key_underlying_cycle` at `:236-238`), with the ICC and design effect disclosed; and
D5 §6.3b's **F11** stays a separate NO-SHIP rule on the coarser unit, the **cycle-month pooled
across underlyings** (`options_evidence.py:169` `CLUSTER_UNIT_F11`,
`cluster_key_cycle_only` at `:241-243`). A version ships only if neither fails. The clustered
bootstrap is seeded at `OPTIONS_CLUSTER_BOOTSTRAP_SEED = 20260912` over 2,000 resamples at 95%
(`options_evidence.py:162-164`) — a seed pinned separately from
`montecarlo.bootstrap_ci`'s, because two resamplers sharing one seed would look like agreement
where there is none. The design effect is `DEFF = 1 + (m̄ − 1)ρ` with `m̄ = 14` structures per
cycle-month on the F11 unit, so at ρ = 0.15 the required raw `n` is **2.95×** the figures above,
and at ρ = 0.30, **4.90×**. For a book of 14 simultaneously long-equity structures on correlated
large-cap and index underlyings, ρ is not small.

> **CC-5.** The required OOS `n` at any cap-compliant R scale is between **10³ and 10⁶** trades
> before clustering and 3-5× that after it, against **≈259** obtainable from §2.2's population
> over §2.3's maximum window. No window this program can buy closes gate 4 for this structure at
> a cap-compliant scale. This is not a statement about the strategy's edge; it is a statement
> that an R unit 4-25× smaller than the series' own standard deviation cannot be measured.

### 6.7 CC-6 — the R denominator is not comparable across trades

Gate 0.5 records `r_scale_dispersion` (max/min observed R) as evidence and D4 §3 requires it to
be "explained entirely by the credit, never by the width". At a declared scale it formally is —
but the magnitude matters:

| version | scale | credit range | R range | dispersion |
|---|---|---|---|---|
| O3 (D5a v0.1.1) | $200.00 | $20.00-$31.00 | $170.60-$181.60 | **1.06×** |
| O2 at the smallest feasible scale, $3,400 | $3,400 | $39.85-$3,379.18 | $69.96-$3,372.17 | **48.2×** |
| O2, IWM-only at $1,060.69 | $1,060.69 | $39.85-$1,044.70 | $31.97-$1,032.86 | **32.3×** |

> **CC-6.** Even at a scale large enough for gate 0.5 to pass, the R denominator varies by
> **32× to 48×** within one version, against O3's 1.06×. Gate 0.5 passes formally — the
> dispersion *is* explained by the credit — while `bootstrap_ci`, which takes a bare
> `Sequence[float]` (`backtest/montecarlo.py:15-33`), pools trades whose dollars-at-risk differ
> by a factor of 48. This is the same defect D4 §3's correction identifies at 3.3× inside a
> single O3 version and rejects, reappearing here an order of magnitude larger. It is reported
> as a gate-8 finding; whether it should be a NO-SHIP rule in its own right is left open for
> the freeze (§16, item 4).

---

## 7. Collateral — how many structures actually fit

**FACT (the limits).** Decision 13: a separate options paper account, initial **$25,000
SIMULATED**. Decision 4: collateral cap **$5,000**, aggregate open max loss **$1,000**.
`account_equity_basis = 25_000.0` is already the shipped gate threshold
(`options_gates.py:152`). D3 §3.2's reservation table's fourth row reads, today: *"covered call
— the underlying shares, not cash — **out of Phase 1 scope** (decision 8 defers O2)."* This
section is that row, filled in.

A covered call reserves **100 shares × the share price**, per structure.

| underlying | price | 100-share notional | × the $25,000 account | fit the **account** | fit the **$5,000 collateral cap** |
|---|---|---|---|---|---|
| SPY | $649.65 (−15%) | $64,964.65 | 2.60× | **0** | **0** |
| SPY | **$764.29** | **$76,429.00** | **3.06×** | **0** | **0** |
| SPY | $878.93 (+15%) | $87,893.35 | 3.52× | **0** | **0** |
| QQQ | $501.50 (−15%) | $50,150.00 | 2.01× | **0** | **0** |
| QQQ | **$590.00** | **$59,000.00** | **2.36×** | **0** | **0** |
| QQQ | $678.50 (+15%) | $67,850.00 | 2.71× | **0** | **0** |
| IWM | $204.00 (−15%) | $20,400.00 | 0.82× | **1** | **0** |
| IWM | **$240.00** | **$24,000.00** | **0.96×** | **1** | **0** |
| IWM | $276.00 (+15%) | $27,600.00 | 1.10× | **0** | **0** |

> **CC-3.** On the $25,000 options paper account the covered call admits **zero** SPY structures
> and **zero** QQQ structures at every price level in the ±15% band. IWM admits **one** at or
> below the declared level, consuming **96%** of the account — and **zero** at +15%. Against
> decision 4's **$5,000 collateral cap** it admits **zero on all three, at every level**.
> The maximum share price that fits one structure is **$50.00** under the collateral cap and
> **$250.00** under the account alone.

**The task framing "at most one SPY/QQQ structure" is optimistic by a factor of three.** At the
levels recorded and declared in §2.4 the answer for SPY and QQQ is **none**, not one: 100 SPY
shares cost 3.06× the whole account.

**IWM-only is not a rescue either, and it should be said plainly.** One IWM structure fits the
*account* and fails the *collateral cap* by 4.8×. A one-underlying, one-position-at-a-time paper
stream would in any case give ≈12 entries a year against decision 10's ≥20 closed paper trades
before any arming — a two-year probation — and §2.2's population would have to shrink from 14
underlyings to 1, which collapses gate 6's bear bucket (14 trades per bear cycle-month becomes 1)
and gate 6b's joint cells outright. **There is no viable IWM-only version.**

**This is the same wall D3 §3.3 records for the cash-secured put**, and the coincidence is not
one: a covered call and a CSP both reserve roughly one share-lot of notional, so both hit the
$50-per-share ceiling. D3 §3.3 states it for the CSP — *"the CSP cannot be paper-traded on this
account at any strike above $50"* — and the identical sentence is true of the covered call.
Decision 12 put O3 first partly because it escapes that wall (a $2.00-wide vertical reserves
≈$181.60). O2 does not escape it.

**The aggregate cap, quantified.** §2.2's 14 underlyings all signal on the same monthly cycle,
so the worst case is 14 simultaneously open structures:

| quantity | value | vs the cap |
|---|---|---|
| 14 × R_hard at a $200 scale | $2,800 | vs $1,000 aggregate → **5** concurrent permitted |
| 14 × R_hard at the smallest feasible $3,400 scale | $47,600 | vs $1,000 → **0**; vs OP-1's $3,600 → **1** |
| share collateral, 14 concurrent at IWM $240 | $336,000 | **13.4×** the account |
| share collateral, 14 concurrent at SPY $764.29 | $1,070,006 | **42.8×** the account |
| share collateral, 14 concurrent at the Stage-A mean $531.43 | $744,002 | **29.8×** the account |

**Gate 10 is void, and that is a pre-registered statement rather than a discovery.** D5 §9.2
pre-registers, for O3, that if more than 50% of backtest-eligible cycles are refused in paper
the gate-10 stream is non-representative and probation does not confirm the version. For O2 the
refusal fraction is **100%** on 13 of 14 underlyings and 100% on all 14 under the collateral cap.

> **CC-3b.** No options `PaperTrade` for this structure can be created on the $25,000 account at
> any Stage-A price level. Gate-10 evidence for `options_covered_call` v0.1.0 is therefore
> **void by construction**, independently of D5 §9.1's separate hard precondition (that no
> options `PaperTrade` may exist until `accept_candidate` itself refuses non-`stock`/`etf`
> instruments fail-closed at the shared entry point — `paper/ledger.py:132-144` today calls only
> `ensure_not_engaged()`). Both preconditions bind; neither blocks Phase D.

---

## 8. Gate 7, gate 7b, and the benchmark a covered call deserves

**Gate 7 is KEPT** (`gate_7_benchmark`, `options_gates.py:1239-1273`,
`require_beat_benchmark_sharpe = True`): strategy Sharpe > SPY buy-and-hold Sharpe over the
matched span, on **all** pre-sealed structures. D4 §6.1 forbids replacing it, and for this
structure the reason is sharper than usual: a covered call is a long-equity position with a
variance-reducing overlay, so it has a *structural* argument for a higher Sharpe than
buy-and-hold **without having any edge at all**. The gate the reader would be tempted to drop is
precisely the one that would catch a variance-reduction artefact being sold as a signal.

Note the asymmetry `BenchmarkPair` records (`options_gates.py:339-345`): the market benchmark is
computed from raw proxy closes and pays **no cost at all**, while the strategy pays 11 bps of
share friction plus two option crossings. Gate 4b gates this comparison at the stressed setting
for that reason.

**Gate 7b, specified now so it cannot be chosen to flatter the outcome** (`gate_7b_mechanical`,
`options_gates.py:1276+`; its docstring states the rule: the mechanical configuration is *one*
configuration, named before any outcome was looked at). The mechanical benchmark is the
identical structure, identical underlyings, identical window, identical cost models, identical
fill, print-eligibility, marking and non-entry rules, with

- `short_delta_target = 0.25`, `max_short_delta = 0.40`, `dte_target = 35`,
  `profit_target_pct = 0.50`, `time_stop_dte = 7`, `min_credit_pct_of_spot = 0.011`, the same
  `stop_usd`, **and**
- **`regime_delta_shift = 0.0`** — a fixed delta every cycle, in every regime.

So the benchmark differs from the strategy in exactly one thing, the regime shift, which is the
only thing the strategy claims (§1). Implemented, per the Protocol, as
`mechanical_benchmark()` returning the same class constructed with the shift zeroed — the same
shape `OptionsShortVertical.mechanical_benchmark` uses (`short_vertical.py:447-466`).
**Both gate 7 and gate 7b must pass.** R4 permits adding 7b; it does not permit dropping 7.

---

## 9. Falsification criteria (R10) and the gate-8 evidence fields

Each names an observation that kills the design. Sealed numbers may inform disposition only,
never design (R1). CC-1, CC-2, CC-3, CC-3b, CC-5 and CC-6 are **already determined** by §6 and
§7 arithmetic; the rest await data that does not exist.

| # | Killing observation | Consequence |
|---|---|---|
| **CC-1** | No `stop_usd` satisfies gate 0.5 and gate 0.i together (§6.3) | **already true** at $250 and at $900. The design cannot be evaluated. The only cure is an operator cap decision, taken **before** any evaluation (§13, §14) |
| **CC-2** | The cap-compliant stop is below 0.25 of one 28-day σ of the share leg (§6.5) | **already true** at every declared cell. Dead as specified |
| **CC-3** | Fewer than 1 structure fits the paper account, or 0 fit the collateral cap (§7) | **already true**. Gate 10 is void |
| **CC-3b** | Any options `PaperTrade` created before D5 §9.1's `accept_candidate` precondition is met | gate-10 evidence VOID |
| **CC-4** | *(a pass)* premium harvest covers round-trip friction (§6.4) | positive in 27/27 at baseline, 8/9 at 2× — recorded, not a kill |
| **CC-5** | Required OOS `n` exceeds the obtainable `n` by more than an order of magnitude (§6.6) | **already true** at any cap-compliant scale |
| **CC-6** | `r_scale_dispersion` above 5× | **already true** (32-48×). Reported at gate 8; see §16 item 4 |
| **CC-7** | OOS expectancy ≤ 0 at the baseline spread | dead. No parameter change is attempted in response |
| **CC-8** | OOS expectancy > 0 at baseline but ≤ 0, or CI low ≤ 0.02 R, at **2× spread, form (a)** | dead as COST-FRAGILE. The response is the null option or more data — **never** a smaller spread constant. Form (a) — selection frozen, friction re-priced — is the **gating** form; form (b), full re-selection at 2×, is a reported diagnostic (D5 §6.2c). `SealedAtNonBaselineCost` (`options_gates.py:411`) makes a stressed seal raise rather than seal |
| **CC-9** | `r_clamped` rate > 10% of trades, **or** > 20% of losing trades close worse than the stop level | reported at gate 8 and treated as NO-SHIP. Note §3.4: for O2 a clamp means the stop did not bind, which is the expected case — so this criterion is **weaker evidence here than F9 is for O3**, and that is disclosed rather than relied on |
| **CC-10** | A synthetic mark set a **fill** price, or realised volatility was used as an IV fallback | the run is **void**, not failed — re-run after the defect is fixed |
| **CC-11** | Clustered-bootstrap CI low ≤ 0.02 R on **either** unit — the D4 `(underlying, expiry cycle)` unit **or** F11's cycle-month pooled across underlyings | **NO-SHIP regardless of the iid gate-4 verdict.** Ruling R-1: both bind. Realised `DEFF` and ρ reported with each |
| **CC-12** | The §3.5 overlay-delta diagnostic disagrees in **sign** with the standalone basis; **or** the §5 `thin_continuity` paired diagnostic disagrees in sign or exceeds 15% of trades; **or** the D5 §3.3(6) with/without-exclusion pair disagrees in sign | NO-SHIP. The design's answer must not depend on which of two defensible conventions was chosen |
| **CC-13** | Pinned fraction > 15%, or expectancy positive only with pinned trades included | dead — modelling artefact. `pinned_fraction_max = 0.15` (`options_gates.py:179`). Pin band: ±0.5% of the underlying or ±1 listed strike increment, whichever is narrower, applied to the short strike on the force-close session |
| **CC-14** | `n_evaluable < 58` of 96 grid points | gate 5 fails on evaluability, reported as such and never as a pass on a thin grid |

**Gate-8 evidence fields.** Everything D5 §8 lists, unchanged — corporate-action exclusions, the
`shares_per_contract != 100` refusal count, the synthetic-**mark** fraction (there is no synthetic
*fill* fraction; map §2.4(3) forbids them), the non-entry count **by reason**, the exit-deferral
distribution, the `r_clamped` count and the unclamped `pnl_r` minimum, the `forced_intrinsic_mark`
fraction and its paired expectancy, the `thin_continuity` fraction and its paired expectancy, the
pinned fraction and its separate R distribution, the realised outcome mix, the
`|close − vwap| / close` distribution per entered leg and the `transactions`-null fraction, the
`iv_source` / `q_source` / `greeks_source` mix, the `fill_model` string, the verbatim
`PromotionThresholds` payload and `options_config_hash`, the American-exercise approximation
**with its direction of bias**, the NBBO-unavailable-on-both-asset-classes disclosure, gate 4b
forms (a) and (b) side by side, and the clustered bootstrap on **both** units with `DEFF` and ρ.

**Plus five fields this structure needs and O3 does not:**

1. `share_leg_friction_r` — the share round trip in R units, per trade (§6.4 shows it is
   0.09-0.39 R at a $250 scale — a first-order term).
2. `share_notional_usd` and `share_notional_over_account_equity` per structure, so §7's wall is
   in the record rather than in this document only.
3. `overlay_delta_expectancy_r` — the §3.5 paired diagnostic, and its sign agreement flag.
4. `stop_distance_in_28d_sd` per trade — §6.5's ratio, computed from the entry-session σ, so
   CC-2 is a measured quantity and not only a forecast.
5. `r_scale_dispersion` read explicitly against CC-6's 5× threshold rather than only printed.

---

## 10. What a pass would and would not authorise

**FACT.** `StrategyStatus` has exactly three values — EXPERIMENTAL, PAPER_APPROVED, DISABLED —
and there is **no ARMED state anywhere** (`src/signalforge/domain.py`). A gate-ladder pass writes
PAPER_APPROVED and an approved scope. It authorises **no order**. Decision 10 additionally
requires ≥20 closed paper trades with non-negative expectancy under the health monitor before any
arming; §7 shows this structure cannot produce them. Operator decisions 2 (broker), 3 (options
approval level) and 4 (capital limits) are unresolved. The kill switch blocks opening and never
blocks closing; nothing is armed by default; no LLM ever decides an order.

D5 §9.1's hard precondition is inherited in full and restated because it binds O2 identically:
no options `PaperTrade` may be created, and any gate-10 evidence derived from one is **VOID**,
until `accept_candidate` itself refuses every instrument whose type is not `stock`/`etf` —
fail-closed at the shared entry point, not only in the auto path. FACT:
`paper/ledger.py:132-144` calls only `ensure_not_engaged()` and then sizes with equity share
arithmetic, and `mark_to_market` (`:287`) values the position off the **underlying**. For a
covered call that last point is a trap with a friendly face: `mark_to_market` would price the
share half *correctly* and the option half not at all, producing a number that looks plausible
and is wrong. D3 §7's type assertion on `mark_to_market` must land **before** any options
position can exist.

Two guards D3 owns by name, restated with O2's values: a per-structure R cap emitting
`refused_r_cap`, and **underlying-keyed** concurrency emitting `refused_concurrency` — FACT: the
existing `auto_simulate.py` check is keyed on `instrument_id` and would not catch a structure
spanning a share position and a contract row.

**An ACCEPTED `PaperTrade` is not evidence that anything was gated.**

---

## 11. Variant budget, stopping rule, and the null-result declaration

**Budget: 1 variant. Hard cap 2.** The multiplicity cost is paid per family and is visible
automatically for *sealed* looks via `count_sealed_looks(session, "options_covered_call")`
(`promotion.py:712`), captured as `k_prior`, surfaced as gate-9 evidence and printed by the CLI.

**`count_sealed_looks` cannot see a pre-sealed abandonment**, and this document's stopping rules
are entirely pre-sealed abandonments — CC-1 through CC-3 fire before a single trade is
simulated. D5 §10's accounting rule is adopted verbatim: any pre-sealed abandonment of a version
in this family is written as a numbered disposition record under `docs/research/dispositions/`
**before the next version is run**, naming the version, the criterion that fired, and the figures
that fired it; and every subsequent version's gate-9 evidence cites

```
k_effective = count_sealed_looks(family) + n_presealed_abandonments(family)
```

with both components shown separately. `k_effective`, not `k_prior`, is what the stopping rule is
read against.

- **Variant 1 = `v0.1.0`**, as drafted here — **and it cannot be run at all** until an operator
  cap decision resolves CC-1. Its expected disposition is the null option, derived rather than
  guessed.
- **Variant 2 = `v0.2.0`, pre-specified now so it is not invisible under R5:** identical except
  that `stop_usd` is raised to the smallest value at which the stop sits at **0.5 of one 28-day
  σ** on the median Stage-A underlying (§6.5: ≈$16/share on SPY, ≈$5/share on IWM), with the
  per-structure cap raised to match. It may be taken **only if** the operator has raised the cap
  under §14 **and** `v0.1.0` failed at the pre-sealed stage for a stop-binding reason
  specifically — never in response to any sealed number (R1). If `v0.1.0` fails for any other
  reason, the program stops at the null option.
- **Stopping rule.** After at most 2 looks for this family — counted as `k_effective` — the
  program stops. A third requires an explicit operator decision recorded in
  `docs/research/dispositions/`, naming `k_effective = 2`, its two components, and the structure
  type and R basis.
- **Every abandoned cell is disclosed.** A cell of §4.2's 96-point grid or §4.4's OAT table that
  was run and not reported is an R5 violation. A parameter combination in neither list may not be
  run at all — that is what makes "abandoned variant" definable here.

### The null-result declaration

> **If `v0.1.0` (and at most `v0.2.0`) fail, the disposition is: NO COVERED-CALL STRATEGY SHIPS.**
> The options data, engine, calendar, cost model and gate wiring remain as infrastructure and as
> a recorded negative result. The program does **not** reach for a different structure to rescue
> the outcome: a different structure is a different family starting at k = 0, permitted in
> principle but explicitly **outside this pre-registration's budget**, and it would require a
> fresh pre-registration document and an operator decision. Nothing is armed; the
> default-disabled posture, the kill-switch semantics and the credential rules are unchanged.
>
> **§6 and §7 state in advance that the null option is the *expected* outcome at the currently
> taken capital limits, and that it is expected for reasons that have nothing to do with whether
> the strategy has an edge.** The design fails on unit definition (CC-1), on stop scale (CC-2),
> on collateral (CC-3) and on statistical power (CC-5) before any return series exists. Saying so
> before the data exists is the point of writing it down.

---

## 12. Which gates are satisfiable under the current caps

Summary of §5-§7. "Satisfiable" means the gate can pass on a well-formed evaluation of this
structure; it makes no claim that it *would* pass.

| Gate | Under decision 4's $250 / $1,000 / $5,000 | Note |
|---|---|---|
| **0.a** window | **YES** | §2.3's 8 years; `MEDIUM_SWING` does not enter the INTRADAY branch |
| **0.b** underlying coverage | **YES**, data-dependent | the underlying series is half the position for O2, not just a label source |
| **0.c** bracketing ≥0.90 | **YES**, and more easily than O3 | one strike, no wing to place; D5a §3.4's exact-placement non-entry channel does not exist |
| **0.d** continuity 0.80 / 0.60 | **YES**, and more easily than O3 | one option leg, not two |
| **0.e** IV provenance | **YES** | same path, same surface floor |
| **0.f** fill provenance | **YES**, with one added disclosure | the share leg's 11 bps is modelled against an equally unobserved quote and is the **larger** cost term |
| **0.g** dividend `q` | **YES** | decision 11; doubly load-bearing here |
| **0.h** deliverable integrity | **YES** | already enforced in the engine |
| **0.i** risk-limit fit | **NO — CC-1** | the feasible `stop_usd` interval is empty by 16.8× at $250 and 4.0× at $900 |
| **0.5** structure singularity | **NO in conjunction with 0.i — CC-1** | passes alone only at a scale > $3,428.32, which 0.i then refuses. The two gates are jointly unsatisfiable, and neither is at fault |
| **1** walkforward | unreachable (0.i fails first); shape OK | ~162 trades/fold ≫ 15; the binding half is the sign in 2 of 4 folds |
| **2** min_oos_trades ≥30 | **YES** on raw trades (~259) | ~34 in cluster units — a 1.1× margin, which is the honest reading |
| **3** net expectancy > 0 | **NO at a cap-compliant scale — CC-2** | the mean is bounded above by a near-certain stop-out |
| **4** bootstrap CI low > 0.02R | **NO — CC-5** | required `n` is 10³-10⁶ against ~259 |
| **4b** dual spread | **YES on cost — CC-4** | positive in 27/27 at baseline and 8/9 at 2×. The one gate O2 clears where O3 does not |
| **5** sensitivity | **YES** in shape | 96 points ≤ 120; predicted `n_evaluable ≈ 80` ≥ 58 |
| **6** regime coverage | **YES, by construction** | no skip branch (§3.2); reachability no longer depends on the partition mismatch, unlike O3 |
| **6b** joint trend × vol | **YES**, with `bear_lowvol` predicted to bind | D4 §5.3's ≥10 marginal / ≥5 joint, already the shipped defaults |
| **7** vs SPY buy-and-hold | reachable, and **structurally flattering** | a variance-reducing overlay can beat buy-and-hold on Sharpe with no edge, which is why 7b exists |
| **7b** vs the mechanical structure | **YES**, specifiable (§8) | differs in exactly `regime_delta_shift = 0.0` |
| **8** data quality | **YES** as a disclosure surface | except where CC-6's 32-48× dispersion bites |
| **9** sealed test | unreachable — 0.i fails first | and therefore costs **no** sealed look |
| **10** live paper probation | **VOID — CC-3, CC-3b** | zero structures fit the account; zero fit the collateral cap |

---

## 13. Open questions for the operator

These are the only items on this document's list that are the operator's — money and account
permissions. Everything else in this draft is a research-design question and is answered here or
recorded in §16 as unresolved by me.

**OP-CC-1 — the per-structure max-loss cap, and it is the blocking one.**
Decision 4 sets `options_per_structure_max_loss = $250` and reserves the right to change it
before arming. §6.3 shows the feasible interval for a covered call's R scale is **empty** at
$250 and still empty at the **$900** recommended in `DECISIONS_2026-09-12_wave3.md` OP-1. The
smallest cap that makes it non-empty is **> $3,428.32** for the Stage-A set (> $2,645.57 for
QQQ+IWM, > $1,060.68 for IWM alone). D4 §2.8a forbids raising it after a gate result, so it must
be decided **before** any covered-call evaluation or not at all.
*This is a capital limit on an account that would eventually trade real money. It is not mine to
set, and nothing in §6 should be read as a recommendation to raise it — §14 shows what raising it
does and does not buy.*

**OP-CC-2 — the options paper account size, and whether it should hold share lots at all.**
Decision 13 sizes the options paper account at $25,000 SIMULATED. §7 shows that 100 shares of the
cheapest Stage-A underlying is $24,000 — 96% of it — and 100 shares of SPY is 3.06× it. A
covered-call program on this population needs an account in the **$750,000-$1,070,000** range to
hold §2.2's 14 concurrent structures in shares, or a single-underlying program on a sub-$50 stock
to fit the $5,000 collateral cap. Both are operator decisions about capital, and both change what
"paper and live share one population" (decision 13) means.

**OP-CC-3 — the collateral cap.** Decision 4's $5,000 collateral cap admits **no** covered call
on any underlying priced above $50/share (§7). D3 §3.3 already records that the same cap makes
the cash-secured put impossible above a $50 strike; the covered call inherits the identical wall
for the identical reason.

**OP-CC-4 — options approval level.** Every design assumes Level 2 (decision 3). A covered call
is the lowest options permission there is and is typically available below Level 2, so this
blocks less here than elsewhere — but it is still an account permission and still the operator's
to state.

**OP-CC-5 — broker and paper API keys.** Unchanged (decision 2, Alpaca paper assumed). Blocks
arming, not evaluation.

---

## 14. What changes if OP-1 raises the cap

`DECISIONS_2026-09-12_wave3.md` OP-1 recommends raising `options_per_structure_max_loss` to
**$900** and `options_total_open_max_loss` to **$3,600** for the $25,000 options paper account
(3.6% / 14.4%). Taken at face value, applied to O2:

| Consequence | At $250 / $1,000 | At $900 / $3,600 | At the smallest cap that works for O2 |
|---|---|---|---|
| CC-1 — feasible `stop_usd` interval | **empty by 16.8×** | **still empty, by 4.0×** | non-empty only above **$3,428.32** per structure |
| CC-2 — stop, in 28-day σ of the share leg | 0.03-0.20 σ | 0.11-0.71 σ (SPY σ 0.15: 0.28 σ) | ≥0.5 σ requires a $499-$3,175 scale |
| gate-4 sd, SPY σ 0.15 | 12.70 R | **3.53 R** | 0.93 R at a $3,400 scale |
| mean required at n = 259 (sd as above) | +1.567 R | **+0.532 R** | +0.135 R |
| CC-3 — structures fitting the account | 0 / 0 / 1 (SPY/QQQ/IWM) | **unchanged** — the aggregate R cap is not the binding constraint; **share notional is** | unchanged |
| aggregate cap, 14 concurrent at a feasible scale | 0 permitted | **1** permitted | 1 permitted at $3,600 |
| gate 10 | VOID | **still VOID** | still VOID |

**The honest summary: OP-1's $900 helps O2 materially on statistical power and not at all on
feasibility.** It cuts the gate-4 sd by 3.6× and the required mean by 2.9×, which is a real
improvement. It does **not** open the CC-1 interval, because the binding quantity there is the
*option credit* ($3,379.18 at the top of the declared design space), not the stop; and it does
**not** touch CC-3, because the binding quantity there is the *share notional* ($24,000-$87,893),
which no max-loss cap constrains at all.

**Three things would have to move together for a covered call to become evaluable on this
program**, and all three are operator decisions:

1. `options_per_structure_max_loss` above **$3,428.32** (Stage A) or **$1,060.68** (IWM only) —
   OP-CC-1;
2. `options_total_open_max_loss` to at least `14 × scale` if §2.2's population is kept, or the
   population reduced and gate 6/6b's coverage re-derived under the smaller `n` — OP-CC-1;
3. an options paper account able to hold share lots — roughly **$750k-$1.07M** for 14 concurrent
   structures, or a sub-$50 underlying set — OP-CC-2, OP-CC-3.

**And a raise decided *after* any evaluation is forbidden** (D4 §2.8a; D5a §4 states the same
rule for O3's width). That is why this arithmetic is published as a draft now rather than
produced when O2 is next reached for.

**If the caps do not move**, the pre-registered disposition is §11's null option, and this
document's contribution is a derived negative result: *the covered call is not a cheaper
fallback from O3 — it is a structurally more expensive one, cheaper only in cost and more
expensive in every unit that matters here.*

---

## 15. Code touchpoints

Reading only; nothing was modified. Symbols are named alongside line numbers because line
numbers do not survive commits and symbols do.

| Touchpoint | What it fixes here |
|---|---|
| `src/signalforge/research/options_gates.py:834-844` | `gate_0_5_structure`'s `single_scale` / `scale_matches` — **the constraint that forces the R identity** (§6.1) |
| `src/signalforge/research/options_gates.py:304-306` | `StructureIdentity.r_scale_usd = width_declared × m_declared` |
| `src/signalforge/research/options_gates.py:772-776` | `gate_0i_risk_limits`'s four-part predicate (§6.3) |
| `src/signalforge/research/options_gates.py:150-152` | `options_per_structure_max_loss = 250.0`, `options_total_open_max_loss = 1000.0`, `account_equity_basis = 25_000.0` |
| `src/signalforge/research/options_gates.py:1137-1189` | `gate_6_regime` — census over `trend_buckets`, `partition` a **required** argument (§3.2) |
| `src/signalforge/research/options_gates.py:1192-1233` | `gate_6b_joint` — five labels, `range_bound` vol-unlabelled |
| `src/signalforge/research/options_gates.py:1239-1296` | `gate_7_benchmark` kept, `gate_7b_mechanical` and its "one configuration, named in advance" rule (§8) |
| `src/signalforge/research/options_gates.py:138-182` | every `OptionsGateThresholds` value this draft reads |
| `src/signalforge/research/options_gates.py:411` | `SealedAtNonBaselineCost` — a stressed run that tried to seal raises (CC-8) |
| `src/signalforge/research/options_evidence.py:189-213` | the `OptionsStrategy` Protocol O2 must satisfy unchanged (§0.1, §3.6) |
| `src/signalforge/research/options_evidence.py:162-169,236-243` | cluster seed / resamples, `CLUSTER_UNIT_D4` and `CLUSTER_UNIT_F11`, and their key functions (§6.6, CC-11) |
| `src/signalforge/backtest/options_engine.py:55-59` | `StructureType.COVERED_CALL` already exists, marked deferred behind O3 |
| `src/signalforge/backtest/options_engine.py:133,141-159` | single-underlying / single-expiration checks, the `== 100` and `american` assertions, and **the `StructureRefused` branch that refuses `covered_call` today** (§3.6 E1) |
| `src/signalforge/backtest/options_engine.py:251-301` | `OptionTrade`'s fields, and `pnl_r` being the **unclamped** gated series with `pnl_r_clamped` a reported line (§3.5) |
| `src/signalforge/data/option_chain.py:42-60` | `ContractRef` — an **option** contract, which is why the share leg cannot be an `OptionLeg` (§3.6) |
| `src/signalforge/backtest/options_costs.py:91-103` | the full modelled spread, `max(floor, pct × print) × spread_multiplier` |
| `src/signalforge/backtest/costs.py:12-27` and `src/signalforge/config/research.py:672-675` | the frozen equity `CostModel`: `slippage_bps = 3.0`, `half_spread_fill_penalty = True`, `commission_per_share = 0.0` (§2.4's share-leg convention) |
| `src/signalforge/backtest/engine.py:94` | `slip = (cm.slippage_bps + spread_bps / 2) / 10_000` — the **5.5 bps per side** of §2.4's share-leg convention, read off the source rather than assembled from two documents |
| `src/signalforge/paper/ledger.py:52` | `_NOMINAL_SPREAD_BPS = 5.0` — the other half of the 11.0 bps |
| `src/signalforge/paper/ledger.py:132-144,287` | `accept_candidate` calling only `ensure_not_engaged()`; `mark_to_market` pricing off the underlying (§10) |
| `src/signalforge/research/regime.py:20-23,41-46,62-96` | `Trend`, `risk_off`, `regime_from_proxy` and its point-in-time docstring (§3.2) |
| `src/signalforge/research/sensitivity.py:29,105-118,120-153,178-181,218-223,236` | `MAX_GRID_POINTS = 120`, `_is_neighbour`, `_axis_movement`'s **global** axis test, the `evaluable` denominator (§4.2) |
| `src/signalforge/research/promotion.py:712,1236` | `count_sealed_looks` keying on `Strategy.name`; `baseline_params=_asdict(strategy.params)` forcing every axis to be a dataclass field |
| `src/signalforge/backtest/montecarlo.py:15-33` | `bootstrap_ci` resamples a bare `Sequence[float]` **iid** — it cannot see CC-6's 48× dispersion |
| `src/signalforge/options/blackscholes.py:48,62,93` | `price`, `greeks`, `implied_vol` — every §6 figure |
| `src/signalforge/research/options_strategies/short_vertical.py:161-171,405-482` | `PREREGISTERED_COST_MODEL`; the `sensitivity_axes` / `oat_parameters` / `structure_identity` / `mechanical_benchmark` / `mechanical_spec` shape O2 copies |

---

## 16. What this draft could not derive

Listed so that freezing the document requires closing them, and so no reader mistakes a gap for
a decision.

1. **QQQ and IWM price levels have no anchor anywhere in the repo.** SPY is anchored to D4 §3's
   recorded read-only query ($764.29, 2026-09-11, source `massive`). QQQ ($590) and IWM ($240)
   are carried from D5a §0.3's declared set — the same set that put SPY at $660, which the one
   checkable member of it misses by **15.8%**. Every §6/§7 conclusion is reported at ±15% and
   none changes sign, so the gap does not alter this draft's findings; it must still be closed
   before the document is frozen, by a read-only query of the same shape D4 §3 records.
2. **The realised σ regime of each underlying over the 8-year window.** §6.5's `P(touch)` and
   §6.6's sd figures are computed at declared σ ∈ {0.15, 0.20, 0.30} under a driftless GBM
   assumption. That is the same class of declared assumption as D5 §6.2b's `p_w` and `p_m`, and
   it is stated to make the design falsifiable, not measured. The gate-8 field
   `stop_distance_in_28d_sd` (§9) turns it into a measured quantity at evaluation time.
3. **The realised intra-cluster correlation ρ**, on either the D4 unit or the F11 unit. §6.6
   tabulates `DEFF` at ρ ∈ {0, 0.05, 0.15, 0.30} by reference to D5 §6.3b's ladder; the realised
   value is a measurement and is reported, never assumed. For a book of 14 long-equity structures
   on correlated underlyings it is plausibly at the top of that range, which would make §6.6's
   required `n` worse by a further 4.9×.
4. **Whether CC-6 (the 32-48× R-denominator dispersion) should be a NO-SHIP rule in its own
   right, and at what threshold.** D4 §3's correction rejects 3.3× dispersion inside an O3
   version as the very defect gate 0.5 exists to prevent, but gate 0.5 as coded checks only that
   the *scale* is single, not that the dispersion is bounded — so O2 passes it formally at 48×.
   Adding a numeric ceiling would be strictly more searching and therefore permitted by R4, but
   choosing the number requires a derivation this draft does not have. It is recorded as a gate-8
   finding and left open.
5. **The exact non-entry rate for O2.** §2.3 predicts it is **higher** than D5's 55%, since O2 has
   no wing-placement or exact-width channel, but the prediction is not quantified — doing so needs
   the I-O2 coverage summary, which does not yet exist. §2.2's fire-once shortfall ladder is
   carried over and would govern.
6. **Whether the share leg should be marked and stopped on the same session basis as the option
   leg when the two disagree** — i.e. the underlying prints but the option does not, or the
   reverse. §3.4 defers the exit to the next session on which the **option** leg prints, on the
   grounds that the structure closes as a unit; the alternative (close the shares immediately and
   carry a bare short call for one session) creates an undefined-risk position the program bans,
   so the choice is forced. But the deferral's cost for a structure whose share half is liquid
   and whose option half is not has no analogue in O3 and is not quantified here.
7. **Whether a covered call is the right *fallback* at all.** `DECISIONS_2026-09-12_wave3.md`
   OP-1 names O2 or "O1 with a bear-regime carve-out" as the next structure if O3 is the null
   result. This draft shows O2 shares the CSP's collateral wall (§7) and adds a unit-definition
   problem O1 does not have (§6.1 — a cash-secured put's max loss *is* `strike × M − credit`,
   which fails `single_scale` for the same reason but at least has an economically meaningful
   value). Comparing the two fallbacks properly is a separate document and an orchestrator
   decision, not mine.
