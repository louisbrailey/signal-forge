# D4 — Options gate spec

**Status: DESIGN DOCUMENT ONLY.** No code, config, schema, migration, threshold, or database
row was changed to produce it. Every read against `data/signalforge.sqlite` was a `SELECT`
issued through `sqlite3 -readonly`; no provider API was called; no package was installed.

Workstream D4 of `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` §7 Phase D ("Options gate
spec", evidence architect). Binding inputs, read in full before writing:

- `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` — §0, §1.5, §2.4, §2.4a, §2.6, §2.7, §3.5,
  §3.6, §4.3, §4.4, §5 (all), §7.
- `docs/research/DECISIONS_2026-09-12_options_execution.md` — the orchestrator's 13 decisions.
  **Binding; not re-litigated here.** The ones D4 depends on: #5 (no NBBO purchase → gate 4b is
  permanent), #7 (local BS inversion + same-session surface → gate 0.e), #11 (source and record
  `q` per underlying, no allowlist → gate 0.g), #12 (O3 short vertical ships first), #13
  (separate options paper account, $25,000 SIMULATED).
- `docs/research/STRATEGY_COMPLETION_MAP.md` §1 R1–R10.

Labelling convention, as required by the brief: **FACT** carries a `file:line` or a read-only
query; **HYPOTHESIS** is a design proposal nothing in the repo yet establishes. Where this
document *corrects* the program map, the correction is marked **CORRECTION TO MAP §x**.

Written 2026-09-11. **Revision 3 (same day), against commit `5b41a61` on `main`.**

**Line-number policy (revision 2).** Revision 1 inherited its `promotion.py`, `cli.py` and
`config/research.py` citations from the program map without re-resolving them; they were stale by
+36 to +475 lines and several landed inside the wrong function. Every `file:line` in this document
has now been re-resolved by hand against `5b41a61`. Where a citation could not be re-resolved it
was deleted rather than carried. `backtest_runner.py`, `backtest/costs.py`, `backtest/engine.py`,
`backtest/regime.py`, `persistence.py` and `db/models/research.py` citations were already exact and
are unchanged.

**What revision 2 changed (and what it announced but did not apply).** Revision 2 rewrote §1
(the ladder-shape test assertions), §2.1 (the INTRADAY gate-0 correction), §2.3 (the
`eligible_cycles` denominator), §2.6 (the `OptionCostModel` constants) and §2.9/§2.9a/§2.9b/§2.9c
(the snapshot-key protection and the `schema_version` precondition), and re-resolved the
citations in those sections. **Its own change summary also announced changes to §3, §4.1, §4.2,
§4.3, §4.5, §6.3, §10 and §11 that were not in fact present in the body, and it announced a
Judge responses appendix that did not exist.** A summary that overstates its own document is a
legitimacy defect in its own right, so it is recorded here rather than quietly corrected.

**What revision 3 changes, and why (summary; each is worked at its own section).**
§4.1 now **gates** gates 2/3/4 **and 7 and 7b** at the stressed spread, because gate 7's
benchmark is computed from raw proxy closes and pays no cost at all (`promotion.py:346-365`), so
it is the single most cost-sensitive comparison in the ladder and was the one exempted. §4.2
states the equity/options cost-multiple asymmetry (`spread_bps = 10.0` is **1.45×** total equity
cost, not 2×) and moves the equity stress onto **total round-trip cost** at `spread_bps = 16.0`.
§4.3 touchpoint 3 is rewritten: the stress parameter **must not reach** `_get_or_create_sealed_test`
(`promotion.py:1316-1330`), which takes the same `cost_model` object and would seal at a
non-baseline cost assumption. §4.5 step 1 is rewritten from a post-hoc row-count check into a
mechanism, because a mis-targeted `evaluate_promotion` call would *take* a sealed look on a live
PAPER_APPROVED family before the check could detect it. §3 restates the cash-secured-put
arithmetic at the live SPY close and adds a fourth, **R-scale** clause to the structure-identity
test, because `width` [3, 5, 10] is a declared grid axis and a pooled R stream spanning it is
3.3× incomparable inside one version. **New §2.8a adds gate 0.i**: the evaluated population must
fit the pre-registered per-structure and aggregate max-loss limits — at decision #4's $250 /
$1,000 on decision #13's $25,000 account, *every* width in the 108-cell grid breaches the
per-structure cap, and the ladder must not certify a population the arming limits refuse. §5.1's
two-regime-system warning is carried into §7.4 and §7.6, because gate-6 reachability (which
decided O3 ships before O1) rests on a partition the census does not read. §6.3 items 3 and 9
are repaired (item 3 was non-binding by construction; item 9 silently changed map §5.2a's
denominator). §10 and §11 are brought into line with §2.6, §2.3, §4.2 and §2.8a, and §11's
"D6: Nothing" is replaced with three fail-closed invariants. OQ-4 is downgraded: R2 already
settles it in binding text. Every remaining `promotion.py` / `cli.py` / `config/research.py`
citation in §3–§10 has been re-resolved against `5b41a61`. A **Judge responses** appendix
records what was rejected and why.

---

## 0. What D4 fixes, and the six corrections it makes to map §5 / §1.5

D4 specifies the gate ladder for the options family: the pass/fail predicate of every new or
extended gate, the evidence each writes, the plumbing touchpoints each needs, and the
pre-registration items each hands to D5. It does **not** choose strategy parameters (D5), does
not design the engine (D2), and does not design collateral or limits (D3).

Six things in map §5 / §1.5 do not survive contact with the source and are corrected below. Each
is flagged again at its own section. (C5 corrects revision 1 of *this* document rather than the
map, and is kept in the table because the claim it corrects is the one a reader is most likely to
have relied on.) Corrections revision 3 makes to revisions 1/2 of this document — the gate-7 cost
exemption, the equity cost multiple, the sealed call site, the structure-identity R scale, the
gate-6 reachability claim, gate-8 items 3 and 9, and the missing gate 0.i — are each flagged at
their own section and summarised in the header above.

| # | Map §5 said | Source says | Where |
|---|---|---|---|
| C1 | Gate 6 joint bucketing is "3 trend × 2 vol = **6** cells" | `backtest/regime.py:59-62` short-circuits on `range_bound` **before** the vol label is attached, so the emitted label set is `{bull_highvol, bull_lowvol, bear_highvol, bear_lowvol, range_bound, warmup}` — **5** non-warmup cells, and the range cell carries **no vol label at all** | §5 below |
| C2 | Gate 4b's equity plumbing is "only `paper/ledger.py:50` needs lifting into config" | The **backtest** side is not plumbed either: `research/backtest_runner.py:205-207` calls `run_backtest(...)` **without** `spread_bps`, so `engine.py:90`'s keyword default of `5.0` is the only value that ever reaches the engine, and `evaluate_promotion` (`promotion.py:868-879`) has no spread parameter to pass. Four touchpoints, not one | §4 below |
| C3 | The gate 0.c/0.d fractions are "folded into `config_hash` so they cannot move silently" | `ResearchConfig.config_hash` hashes **only** `SCOPE_HASH_FIELDS` (`config/research.py:392-409`, hash computed at `:411-415`), and the comment at `:370-391` names **`options`** explicitly among the sections deliberately excluded, precisely so options changes "can never silently un-scope a live PAPER_APPROVED strategy". Putting options fractions into `SCOPE_HASH_FIELDS` re-creates incident `0cc4cf4` | §2.9 below |
| C6 | Map §5.2a's stop-non-binding measure is "the count and fraction of **trades**" that closed worse than `stop_multiple × credit` (`OPTIONS_EXECUTION_PROGRAM_MAP.md:1142-1146`) | A single denominator cannot carry the claim: the all-trade fraction is diluted by winners, the losing-trade fraction is the one an expectancy claim rests on, and the two are not convertible without the loss count. **Both** are recorded, and the 0.25 ceiling is stated against the losing-trade fraction | §6.3 below |
| C4 | Gate numbers 0.5 / 4b / 7b | `Gate.number` is typed `int` (`research/promotion.py:114`); `0.5`, `4b`, `7b` are not expressible, and three runtime consumers read it (`cli.py:1388`, `cli.py:1566`, `app/templates/strategy_promotion.html:67`) — **plus two test assertions on the ladder's exact shape**, which revision 1 missed | §1 below |
| C5 | The gate-0 fractions "cannot move silently" because a change produces a new `DataSnapshot` key (revision 1's own §2.9 substitute for C3) | **`DataSnapshot` identity is a function of the SYMBOL SET alone.** The auto key is `f"universe_auto_{len(symbols)}sym_{_symbols_fingerprint(symbols)}"` and `_symbols_fingerprint` is a `sha256` over the sorted symbols (`promotion.py:567-570`, key built at `:632`); the unkeyed lookup matches *any* `reusable_by_new_evaluations` snapshot with an identical symbol set (`:624-630`). No config hash of any kind enters snapshot identity, so moving `bracket_fraction_min` from 0.90 to 0.70 leaves the key byte-identical and `_get_or_create_sealed_test` (`:763`, existing-row return at `:788-796`) replays the locked row. Revision 1's invariant was **false**, and weaker than the `config_hash` it declined to use | §2.9 below |

---

## 1. Gate identity — how 0.5, 4b and 7b are actually represented

**FACT.** `Gate` is a frozen dataclass with `number: int`, `name: str`, `passed: bool`,
`detail: str`, `evidence: dict` (`research/promotion.py:112-127`, `to_dict` at `:120-127`). Its `to_dict()` is what lands
in `strategy_promotion_evaluation.gates_json` (`db/models/research.py:314`).

**FACT.** The overall verdict is `passed = bool(gates) and all(g.passed for g in gates)`
(`research/promotion.py:1440`). It does **not** require unique or contiguous gate numbers, and it
does not index by number — so adding gates with a repeated `number` cannot break *the verdict*.

**FACT (three runtime readers).** `cli.py:1388`
(`next((g for g in result.gates if g.number == 9), None)` — takes the first match),
`cli.py:1566` (display: `f"  [{mark}] {g.number}. {g.name}: {g.detail}"`),
`app/templates/strategy_promotion.html:67` (display).

**CORRECTION TO REVISION 1 — the ladder's shape is asserted in tests, and 4b breaks those
assertions.** Revision 1 wrote "adding gates with a repeated `number` cannot break it" and listed
three touchpoints. That is true of the verdict and false of the suite. FACT, at `5b41a61`:

| # | Touchpoint | Assertion | Effect of a `number=4` gate 4b |
|---|---|---|---|
| 4 | `tests/research/test_promotion.py:91-92` | `len(result.gates) == 10` **and** `all(g.number == i + 1 for i, g in enumerate(result.gates))` | fails on **both** conjuncts |
| 5 | `tests/research/test_promotion_intraday_gate0.py:182` | `[g.number for g in result.gates] == list(range(11))` | fails |

(`tests/research/test_promotion.py:116` carries the same `len(result.gates) == 10` and fails too.)

This matters because §4.2 declares gate 4b **permanent and applicable to equities**, so the
duplicate-numbered gate lands in the equity ladder, not only the options one. The contiguity
contract must therefore be **replaced deliberately, not broken incidentally**:

- the ladder's shape is asserted on ordered `(number, label)` pairs, with the exact expected list
  written out per horizon — e.g. daily equities become
  `[(1,""),(2,""),(3,""),(4,""),(4,"4b"),(5,""),(6,""),(7,""),(7,"7b"),(8,""),(9,""),(10,"")]`;
- the assertion is edited in the same commit that adds gate 4b, and the commit message names the
  contract change. A test edited to accommodate a gate is a ladder change under R3/R4 and is
  disclosed as one — **the assertion may be re-specified, never deleted**.

**HYPOTHESIS — the representation, chosen to be additive and R4-safe.** Add one field to `Gate`:

```
label: str = ""        # "" means str(number); otherwise the human gate id
```

and emit it from `to_dict()`. Sub-gates then carry the **parent integer** in `number` and the
human id in `label`:

| Gate | `number` | `name` | `label` |
|---|---|---|---|
| structure singularity | `0` | `structure_singularity` | `0.5` |
| dual spread pass | `4` | `dual_spread_pass` | `4b` |
| mechanical-structure benchmark | `7` | `mechanical_benchmark` | `7b` |
| joint trend×vol coverage | `6` | `regime_coverage_joint` | `6b` |

Why this shape and not the alternatives:

- Changing `number` to `str` breaks `cli.py:1388`'s `== 9` comparison and re-types every
  historical `gates_json` reader. Rejected.
- Renumbering the options ladder to fresh integers (11, 12, 13…) severs the visual link to the
  equity gate it extends, which is the thing a reviewer needs most. Rejected.
- The repeated-`number` ordering is safe for `cli.py:1388` because gate 9 is appended exactly
  once (`promotion.py:1354`) and no sub-gate uses `number=9`.

**R4 check.** Adding a field and adding gates makes the ladder strictly more searching and
removes no threshold. `STRATEGY_COMPLETION_MAP.md` §1 R4 permits "a change to the promotion path
… when it makes a gate *runnable or more faithful* without making it *easier to pass*." This
qualifies. **No existing threshold number in `PromotionThresholds` (`config/research.py:83-128`)
moves anywhere in this document.**

**Touchpoints (design only; no code written here):** `research/promotion.py:112-127`
(dataclass + `to_dict`), `cli.py:1566` (print `g.label or g.number`),
`app/templates/strategy_promotion.html:67` (same), `tests/research/test_promotion.py:91-92`
and `:116`, `tests/research/test_promotion_intraday_gate0.py:182` (ladder-shape assertions,
re-specified as ordered `(number, label)` pairs).

---

## 2. Gate 0 — data availability for options (0.a – 0.i)

Gate 0 is the **fail-fast** gate: it returns before gates 1–10 are attempted. FACT (re-resolved
at `5b41a61`): the precedent is `promotion.py:992-1023`, where an INTRADAY run queries
`intraday_rth_coverage` and, when coverage is incomplete, appends a failing `Gate(0, …)` and
returns through `_finalize` with no other gate evaluated; the second precedent is the window check
at `promotion.py:954-979`. Both are the shape gate 0.a–0.h must copy: **one failing
`Gate(0, …)` and an immediate `_finalize` return**, never a fabricated pass on absent data.

Below, each sub-check gets: the predicate, the evidence keys it writes, and the failure mode it
exists to catch. `M` denotes `OptionContract.shares_per_contract`.

### 2.1 Gate 0.a — horizon and window arithmetic (unchanged mechanism)

**Predicate (FACT, reused verbatim from `promotion.py:954`):**
`sealed_start > start` **and** `(pre_sealed_end - start).days >= MIN_PRESEALED_DAYS`.

**FACT:** `MIN_PRESEALED_DAYS = math.ceil(TREND_LOOKBACK * 365.25 / 252) + 60`
(`promotion.py:106`) with `TREND_LOOKBACK = 200` (`backtest/regime.py:20`)
= `ceil(289.88) + 60` = **350** calendar days.
**FACT:** `sealed_window_days = 365` (`config/research.py:127`).
**Floor = 350 + 365 = 715 calendar days** of continuous coverage, minimum, before an options
evaluation is even attempted.

**CORRECTION TO REVISION 1 — the INTRADAY auto-fail no longer exists, so 0DTE needs its own
rule after all.** Revision 1 wrote "`spec.horizon is Horizon.INTRADAY` auto-fails
(`promotion.py:892-901`)" and concluded that 0DTE was therefore structurally ungateable with no
options-specific rule required. **That was true at the commit revision 1 cited and is false at
`5b41a61`.** FACT: commit `9b7e7c3` ("Gate 0 for INTRADAY is a real `ohlcv_intraday` query, not an
unconditional fail") replaced it; `promotion.py:992-1032` now runs `intraday_rth_coverage(...)`
over the pre-sealed span and appends a **passing** `Gate(0, "data_availability", True, …)` when
coverage is complete (`:1024-1032`). An INTRADAY horizon is now a data question, not a verdict.

**Consequence, and it is a real gate-0 requirement, not a footnote.** 0DTE is now blocked only by
the absence of intraday option data, which is a condition that can change. The options ladder
therefore carries its own predicate: **an options strategy declaring `Horizon.INTRADAY`, or a
`dte_target`/`dte_window` that admits an entry-to-expiry distance of 0 sessions, fails gate 0.a
unconditionally in Phase 1** — there is no intraday option bar anywhere in the schema
(`OptionAggregateDaily` is daily-only), so an intraday or same-session options structure would be
priced entirely by model. D5 pre-registers the minimum admissible DTE at entry as a positive
integer, and gate 0.a records it.

**Evidence keys:** `window`, `presealed_days`, `min_presealed_days`, `sealed_window_days`.

**Measured against today's DB: FAILS.** FACT (read-only):
`option_aggregate_daily` spans `2026-07-31 .. 2026-09-04` — **36 calendar days** against a floor
of 715.

### 2.2 Gate 0.b — underlying coverage

**Predicate:** every underlying named in the evaluation's `options_scope_json` (§3.5 of the map)
has continuous `OHLCVDaily` across `[start, end]` from source `massive` **only**.

**FACT (R6, `STRATEGY_COMPLETION_MAP.md` §1):** research reads source `massive` only; a symbol
whose bars carry a non-`massive` tag (`META_CONT` at `continuity_bridge:1`) **fails gate 8**
outright. So a blended or bridged underlying must fail gate 0.b *before* gate 8 sees it —
gate 0 is fail-fast and gate 8 is not reached.

**FACT (existing mechanism to reuse, not rebuild):** `promotion.py:1286` already calls
`validate_daily(session, symbols, source=provider, persist=True)` for gate 8, and
`promotion.py:1280-1285` already resolves a single provider tag from a `SourceFilter` sequence
by taking `source[0]`. Gate 0.b reuses the same resolution and asserts the underlying set is
single-source.

**Evidence keys:** `underlyings`, `underlying_source`, `underlying_first_bar`,
`underlying_last_bar`, `underlying_gap_sessions` (per underlying).

**Measured against today's DB: FAILS.** FACT: `option_contract` holds **one** underlying
(`SPY`, 888 rows) against §1.1's ten.

### 2.3 Gate 0.c — cycle bracketing

**Predicate.** For each `(underlying, cycle)` in the pre-sealed + sealed window, the stored chain
**brackets the structure's target strike on the entry date**: for a short vertical, contracts
exist both at-or-beyond the target short strike **and** at-or-beyond the long wing, **on BOTH
sides (put and call)**, at each pre-registered DTE. Revision 1 wrote "on the side the regime
filter selects", which imported the strategy's filter into the numerator while the surrounding
prose claimed the filter was excluded from the denominator; the two halves must be measured on the
same, filter-free basis or the fraction is not interpretable. Pass requires

```
bracketed_cycles / eligible_cycles  >=  0.90        (PRE-REGISTERED, D5)
```

**Derivation of 0.90 (design judgement, not empirical — map §1.5, restated here so the number is
on the record before any coverage is observed).** Below ~90%, the strike-selection rule is being
silently rewritten by data availability in ≥1 cycle in 10: the evaluation is then measuring
"whatever strikes happened to be stored", not the pre-registered rule. There is no empirical
basis for the exact figure and none is claimed.

**The failure mode it catches.** Silent under-coverage: a chain that stores only near-ATM
contracts turns a 0.20-delta short strike into a 0.35-delta short strike whenever the wing is
missing, which manufactures credit and manufactures edge. This is the check with no equity
analogue.

**CORRECTION TO REVISION 1 — the denominator must be strategy-independent, and revision 1's
clause (iii) was not.** Revision 1 defined eligibility as (i) the underlying passes 0.b over that
cycle, (ii) the cycle's expiry falls inside the evaluation window, **and (iii) the cycle's entry
session falls inside the DTE window the strategy declares** — while justifying the exclusion of
the regime filter with "otherwise the denominator moves with the strategy and the fraction means
nothing". The DTE window is a strategy design choice in exactly the way the regime filter is, and
worse: `dte_target` is a **pre-registered grid axis** (`[21, 35, 45]`,
`OPTIONS_EXECUTION_PROGRAM_MAP.md:973`; one of the four axes of §8.5's 108-cell grid). Under
clause (iii) the 0.90 fraction is computed on a **different denominator in every grid cell**, and
map §7 explicitly permits a person to read the coverage summary before D5 is committed — so a cell
whose DTE window happens to clear 0.90 could be selected after the coverage summary was read. That
is a pre-registration hole, and it is the one this gate exists to close.

**Definition of `eligible_cycles` (strategy-independent; pre-registered, D5).** A cycle is
eligible iff **(i)** the underlying passes 0.b over that cycle, and **(ii)** the cycle's expiry
falls inside the evaluation window. Nothing else. Neither the regime filter, nor the DTE window,
nor the delta target, nor the width enters the denominator.

**`bracket_fraction` is reported as a MATRIX, not a number.** One cell per
`(dte_target, side)` over the complete pre-registered DTE grid — for O3 that is
`3 DTE × 2 sides = 6` cells — plus the strategy-independent aggregate. The 0.90 floor binds on
**every cell of the pre-registered DTE grid that the strategy's own declared `dte_target` and its
one-step sensitivity neighbours occupy**, so gate 5's grid cannot be run through a DTE whose
coverage was never gated. Cells outside that set are recorded, not gated.

**Evidence keys:** `cycles_eligible`, `cycles_bracketed`, `bracket_fraction` (aggregate),
`bracket_fraction_matrix` (`{dte: {put, call}}`), `bracket_fraction_min` (0.90),
`bracket_fraction_gated_cells` (the explicit list of `(dte, side)` pairs the floor binds on),
`bracket_failures_by_underlying`, `bracket_failures_by_side`, `eligible_cycle_definition`
(the literal clause text, so a later widening is visible in a diff).

### 2.4 Gate 0.d — bar continuity per selected contract

**Predicate.** For each contract actually selected by the strategy, daily bars exist for

```
sessions_with_bar / sessions_entry_to_exit  >=  0.80   per leg   (PRE-REGISTERED, D5)
```

with every gap enumerated.

**Derivation of 0.80 (design judgement).** Below 80%, more than one session in five is priced by
a model rather than a print, which exceeds the synthetic-**mark** ceiling gate 8 enforces anyway
(§6.3 below). The two numbers are deliberately the same phenomenon measured from two ends and
must be pre-registered together.

**Interaction with map §2.4(3) — and this is the part that makes 0.d honest.** A missing bar is
**never** a fill. Entry on a session where any leg lacks a bar is a **non-entry** (the cycle is
skipped and counted); an exit signalled on such a session is **deferred** to the next session on
which every leg prints, with `exit_deferred_sessions = n` recorded. So 0.d's fraction measures
*mark* coverage, not *fill* coverage — there is no such thing as a synthetic fill in this design,
and gate 8 has no "synthetic fill fraction" field because the model must not be able to express
one.

**Evidence keys:** `bar_continuity_fraction` (min, median, per-leg), `bar_continuity_min`,
`non_entry_count`, `non_entry_reasons`, `exit_deferral_histogram`, `gap_sessions`.

### 2.5 Gate 0.e — greeks / IV provenance

**Predicate.** The run records, per evaluation, the fraction of trades whose delta/IV came from
each of exactly four named paths, and **fails** if any trade used an unnamed path:

| `iv_source` | Meaning | Admissible in Phase 1? |
|---|---|---|
| `local_bs_inverted` | IV inverted from the contract's own print via `options/blackscholes.py` | Yes — decision #7 |
| `same_session_surface` | Map §2.4b's same-session surface, subject to its N floor (D5 pre-registers the floor) | Yes — decision #7 |
| `vendor` | A genuinely dated vendor value | Yes, where one exists |
| `pct_otm_proxy` | Percent-OTM standing in for delta | **Recorded, and capped by a D5-pre-registered ceiling** |

**FACT:** vendor IV/greeks are documented as "usually absent on this entitlement"
(`db/models/market.py:264`), and today exist for exactly one timestamp — read-only query:
`option_quote_snapshot` = **878 rows, `count(distinct as_of) = 1`**. So `vendor` is, today, a
path that can cover at most one session in the whole history.

**FACT:** `OptionAggregateDaily` carries only OHLCV + `vwap` + `transactions` + `quality_flags`
(schema read from the live DB) — **no IV, no greeks, no open interest, no bid/ask**. A
delta-targeted strategy therefore has no historical delta input except `local_bs_inverted` /
`same_session_surface`, which is why decision #7 exists.

**Evidence keys:** `iv_source_mix` (fraction per path, summing to 1.0),
`iv_source_unnamed_count` (must be 0), `surface_n_floor`, `surface_n_actual_min`.

### 2.6 Gate 0.f — fill-price provenance and the NBBO disclosure

**Predicate.** The run records (i) that NBBO is unavailable **for options and for equities**, and
(ii) the exact modelled-spread function and its constants.

**FACT (the disclosure, and it is a gate-0 field, not a footnote):** `entitlement_check` across
7 distinct `batch_id`s (2026-09-07 18:13 → 2026-09-09 06:34) records
`/v3/quotes/{O:contract}` → http 403 `not_authorized` in **7 of 7**, **and**
`/v3/quotes/{sym}` (equities NBBO) → 403 `not_authorized` in **7 of 7**
(map §0.3 item 3). `docs/CAPABILITY_MATRIX.md` records the same: greeks/IV/trades DELAYED,
OI END_OF_DAY, NBBO UNSUPPORTED.

**FACT:** decision #5 — no NBBO purchase now; modelled spreads stay a disclosed assumption on
both asset classes and **gate 4b becomes permanent**.

**Required `fill_model` string content (HYPOTHESIS, D2 owns the wording):** the model id
(`print_plus_full_spread` per map §2.4(1a)), the spread function
`spread = max(abs_floor_cents, pct_of_last_print × last_print)` with both constants, the
statement that the reference price is a **last-trade print** (`OptionAggregateDaily.close`) and
**not a mid**, and the statement that the stop is a **close-basis** stop (§6.2 below).

**CORRECTION TO REVISION 1 — the commission and fee constants were missing, and they are the
biggest single lever on gates 3 and 4.** Revision 1's gate-0.f evidence recorded only the two
*spread* constants. FACT: map §2.5 (`OPTIONS_EXECUTION_PROGRAM_MAP.md:558-565`) specifies
`OptionCostModel` with `commission_per_contract`, `commission_min_per_order`,
`exchange_fee_per_contract`, `spread_pct_of_last_print`, `spread_abs_floor_cents`,
`assignment_fee` and `exercise_fee`; notes that cost scales with **legs × contracts**, so a 2-leg
vertical carries **four** contract-commissions round trip; and states that the object "must be
made **before** the first evaluation and then frozen identically". On a short vertical collecting
$0.50 of credit on a $5 width, four contract-commissions at any realistic retail rate is a
double-digit percentage of the credit, and therefore of the gate-3 expectancy and the gate-4 CI
lower bound. An unrecorded, unfrozen cost constant is precisely the R4 cost-model-conservatism
surface, and revision 1 left it unrecorded.

**Rule.** The **complete** `OptionCostModel` field set is a gate-0.f evidence block, is frozen for
the program at D5 commit, and **may only ever be raised, never lowered.** A lowered constant after
any outcome is observed is the R1/R4 forbidden move, whatever it is called.

**Evidence keys:** `nbbo_available_options` (false), `nbbo_available_equities` (false),
`entitlement_batches_checked`, `fill_model`, `spread_pct_of_last_print`,
`spread_abs_floor_cents`, `spread_multiple` (1.0 baseline / 2.0 for the 4b leg),
`option_cost_model` = `{commission_per_contract, commission_min_per_order,
exchange_fee_per_contract, spread_pct_of_last_print, spread_abs_floor_cents, assignment_fee,
exercise_fee}` (every field, no defaults elided), `option_cost_model_frozen_at` (the D5 commit
sha), `cost_per_structure_roundtrip_usd` (derived: 4 × contract commission + 4 × exchange fee +
4 × modelled spread, at the baseline multiple), and the same at the stressed multiple.

### 2.7 Gate 0.g — dividend-yield provenance

**Predicate.** A `q` source is recorded **per underlying**. An evaluation in which any underlying
used `q = 0.0` **by default** fails gate 0 outright.

**FACT:** `options/blackscholes.py:48-101` takes a continuous dividend yield `q` whose default
is the thing map §2.4a warns about; decision #11 resolves the choice as **source and record `q`
per underlying, no allowlist**, explicitly so SPY/IWM stay in scope (which §5.3's trade
arithmetic needs).

**Distinction that must not be lost:** a *recorded, sourced* `q = 0.0` for a genuinely
non-dividend-paying underlying is a pass; an *unset* `q` that fell through to the default is a
fail. The evidence must distinguish them, so the field is a `(value, source, as_of)` triple, not
a float.

**Evidence keys:** `q_by_underlying` = `{sym: {value, source, as_of}}`, `q_defaulted_count`
(must be 0).

**Measured against today's DB: FAILS.** No dividend series is ingested anywhere.

### 2.8 Gate 0.h — deliverable integrity

**Predicate.** Every contract traded in the evaluation had `shares_per_contract == 100` at
entry. Any contract that did not was **refused**, and the refusals are counted and recorded.

**FACT (today's baseline, read-only query):** `select distinct shares_per_contract from
option_contract` → **100**, uniformly, across all 888 rows. So the refusal count is zero today —
which is exactly why the check must be written now, while it is free, rather than after the first
split or special settlement produces a 10-share deliverable and a 10× P&L error.

**Evidence keys:** `deliverable_refusal_count`, `deliverable_refusals` (ticker, session, M).

### 2.8a Gate 0.i — the evaluated population must fit the pre-registered risk limits

**The defect this closes.** Without it, the ladder certifies an R stream that the arming limits
refuse, and the first thing anyone wants to move after a pass is the limit. That is the R1/R4
move the whole ladder exists to block, arrived at by omission rather than by decision.

**FACT (the limits).** `DECISIONS_2026-09-12_options_execution.md` row 4 sets, as the taken
defaults: **per-structure max loss $250**, **aggregate open max loss $1,000**, collateral cap
$5,000, per-order notional $1,000, daily order cap 10, arming expiry 7 days — "Operator may
change any of these before arming." Decision #13 sets the options paper account at **$25,000
SIMULATED**. Map §3.2's own table is percentage-based (`options_per_structure_max_loss_pct`
0.5%, `options_total_open_max_loss_pct` 2%) and is explicitly a *grid centre for evaluation,
not a recommendation*; the decisions record is the binding absolute form.

**FACT (the arithmetic, from §3's own R basis and the declared grid).** R = `width × M − credit`,
`M = 100`, and `width` is a declared sensitivity axis of **[3, 5, 10] strikes**
(`OPTIONS_EXECUTION_PROGRAM_MAP.md:972`). At a 0.20-delta short strike the credit is roughly
25–40% of width (map §4.3's `min_credit_to_width = 0.25`):

| `width` | gross max loss | credit at 0.25–0.40 of width | **R (max loss)** | vs $250 cap |
|---|---|---|---|---|
| 3 | $300 | $75 – $120 | **$180 – $225** | fits only at the wide end of the credit range |
| 5 | $500 | $125 – $200 | **$300 – $375** | **breaches** |
| 10 | $1,000 | $250 – $400 | **$600 – $750** | **breaches** |

So **two of the three declared widths cannot be opened at all** under decision #4's $250
per-structure cap, and the third only clears it when the credit is rich. The $1,000 aggregate cap
admits **one to five** concurrent structures depending on width — against §7.4's arithmetic, which
assumes `U = 10` underlyings at `s = 1` structure each, i.e. **up to ten concurrent**. A version
can therefore clear gates 0–8 on a backtest population that gate 10 and decision #10's "≥ 20
closed paper trades" can never reproduce.

**Predicate (HYPOTHESIS; pre-registered in D5 before any outcome is seen).**

```
(i)   max R per structure over the evaluated trade list  <=  options_per_structure_max_loss
(ii)  max concurrent open R over the evaluated span      <=  options_total_open_max_loss
(iii) the limit VALUES used are the pre-registered ones, recorded literally
```

Both limits are read from the pre-registered options limit set — **not** from whatever config
happens to hold at run time — and the **whole limit set is folded into `options_config_hash`
(§2.9b)**, so it cannot move without changing the mandatory snapshot key and therefore taking a
new sealed look.

**The two honest resolutions if the grid does not fit, and the one that is forbidden.**

- **Re-specify the widths in D5, before any outcome is observed.** Narrower widths (or a width
  expressed as a fraction of the cap rather than in strikes) is a design choice and is
  legitimate *now*.
- **Raise the limits in D5, before any outcome is observed**, with the operator's written
  decision recorded — decision #4 explicitly leaves this to the operator.
- **Forbidden:** raising the cap *after* a gate-3/gate-4 result at a width that breached it. That
  is fitting the risk limit to the backtest, and no amount of documentation makes it something
  else. Gate 0.i exists so that this choice has to be made in the open, and early.

**Relation to D3.** D3 owns collateral and the limit mechanics; gate 0.i owns only the
*consistency assertion* between the evaluated population and the pre-registered limits. It is
where §11's previous "D3: nothing gates on collateral" was wrong.

**Evidence keys:** `options_per_structure_max_loss`, `options_total_open_max_loss`,
`account_equity_basis` (25000), `r_max_observed_usd`, `r_max_by_width`,
`concurrent_open_r_max_usd`, `structures_breaching_per_structure_cap`,
`width_grid_declared`, `limits_source` (the D5 pre-registration section, verbatim),
`limits_in_options_config_hash` (must be `true`).

### 2.9 CORRECTION TO MAP §1.5 — where the 0.c / 0.d fractions are actually hashed

**Map §1.5 and §5.2 both say the fractions are "folded into `config_hash` so they cannot move
silently". Doing that literally would re-create the incident of commit `0cc4cf4`.**

**FACT.** `ResearchConfig.config_hash` is a hash over `SCOPE_HASH_FIELDS` **only**
(field tuple at `config/research.py:392-409`; the hash itself at `:411-415`,
`config_hash({k: payload[k] for k in self.SCOPE_HASH_FIELDS if k in payload})`):

```
SCOPE_HASH_FIELDS = ("schema_version", "watchlist", "etf_universe", "allow_short_candidates",
  "enabled_horizons", "intraday_bar_size", "liquidity", "risk", "events", "data_quality",
  "quality_gates", "universe_filters", "commission_per_share", "commission_min_per_order",
  "slippage_bps", "half_spread_fill_penalty")
```

**FACT.** The comment immediately above it (`config/research.py:370-391`) names the excluded
sections explicitly — "adding or changing an unrelated section — agents, news, **options**, the
universe pipeline, the health monitor, the alert cap, or promotion thresholds … can never
silently un-scope a live PAPER_APPROVED strategy" — and states that adding a field to
`SCOPE_HASH_FIELDS` "is a deliberate re-approval event."

**FACT.** `OptionsConfig` (`config/research.py:194-217`) is reachable as `config.options` and is
**not** in `SCOPE_HASH_FIELDS`.

**FACT (memory, and the reason this matters):** adding an `agents` section to `ResearchConfig`
silently changed the config hash used in the five-part approved-scope match, causing live scans
to match no approved scope; it was masked only because those scans produced zero qualified
candidates, and was fixed by scoping the hash to signal-shaping fields only (`0cc4cf4`).

### 2.9a CORRECTION TO REVISION 1 — the substitute protection revision 1 invented does not exist

Revision 1 concluded point 2 with: *"changing a fraction creates a **new `DataSnapshot` key** and
therefore a **new sealed test**, which is a stronger protection than a config-hash diff"*, and
stated the invariant *"an options gate fraction can never be changed without producing a new
snapshot key and therefore a new sealed look."* **Both are false.** Verified at `5b41a61`:

- **FACT.** `_symbols_fingerprint(symbols)` is `sha256` over `",".join(sorted(s.upper() for s in
  symbols))`, truncated to 10 hex characters (`promotion.py:567-570`). The auto-generated key is
  `f"universe_auto_{len(symbols)}sym_{_symbols_fingerprint(symbols)}"` (`promotion.py:632`). It is
  a function of the **symbol set and nothing else**.
- **FACT.** With `key=None`, `get_or_create_dataset_snapshot` iterates every snapshot marked
  `reusable_by_new_evaluations` and returns the first whose sorted, upper-cased `symbols_json`
  equals the requested set (`promotion.py:624-630`). No hash of any configuration is consulted.
- **FACT.** `evaluate_promotion` takes the unkeyed path whenever `dataset_snapshot` is omitted:
  `if dataset_snapshot is None: dataset_snapshot = get_or_create_dataset_snapshot(session,
  symbols=symbols)` (`promotion.py:917-918`).
- **FACT.** `_get_or_create_sealed_test` (`promotion.py:763`) looks up
  `(strategy_version_id, dataset_snapshot_id)` and, on a hit, returns the existing row with
  `reused=True` and the comment "locked — never recomputed, never overwritten"
  (`promotion.py:788-795`).

**Therefore:** moving `bracket_fraction_min` from 0.90 to 0.70 changes no symbol, so the snapshot
key is byte-identical, the same `(version, snapshot)` sealed row is replayed, and the fraction
change is invisible to **every** mechanism revision 1 named. The proposed protection was not
stronger than `config_hash`; it was *none*.

### 2.9b The resolution that actually holds

Point 1 of §2.9 survives unchanged and is correct: the fractions live on a new `OptionsGateConfig`
section (or on `OptionsConfig`) that stays **out** of `SCOPE_HASH_FIELDS`, so
`config_hash` — computed as `{k: payload[k] for k in SCOPE_HASH_FIELDS if k in payload}`
(`config/research.py:411-415`) — is left **byte-identical** and no live scope is disturbed. Point 3
survives: `ResearchConfig.full_config_hash` (`config/research.py:417-420`) hashes **every**
section including `options` and is documented "for audit trails, never for scope matching"; the
options evaluation records it alongside, for audit.

Point 2 is replaced by an **explicit snapshot key**, which is a mechanism that exists:

1. **Every options evaluation MUST pass an explicit `key=`.** The unkeyed symbol-match fallback is
   **FORBIDDEN** for options, because it is symbol-only and two runs at different gate fractions
   would collide on it. The key is
   `options_<program>_<underlying_set_fingerprint>_<options_config_hash[:12]>`,
   where `options_config_hash` covers the gate-0 fractions, the map §2.4/§2.5 fill-model and
   `OptionCostModel` constants, **and the §2.8a risk-limit set**. Changing any of them changes the key, which forces a new
   `DataSnapshot` row, which forces a fresh `(version, snapshot)` pair and therefore a genuinely
   new sealed look.
2. **The mechanism is reachable today, and is new code only in the caller.** FACT:
   `get_or_create_dataset_snapshot` has taken `key: str | None` since before this program
   (`promotion.py:573-581`, the `key` parameter at `:576`), `evaluate_promotion` accepts an
   explicit `dataset_snapshot` (`promotion.py:877`), and `evaluate-promotion --snapshot-key`
   exists on the CLI (`cli.py:1425-1436`, applied at `:1512-1532`). Its own help text states the
   hazard verbatim: "an UNKEYED evaluation resolves its snapshot by exact symbol-set match among
   reusable snapshots" (`cli.py:1444-1449`). D2/D5 build the key **string**; they do not build the
   mechanism.
3. **State the guard's limit, so it is not mistaken for the protection.** FACT: the `ValueError`
   at `promotion.py:604-617` fires only when a key's stored `symbols_json` — or its
   `continuity_mapping_id` — differs from what was just requested. It does **not** and cannot fire
   on a key reused with a changed options hash, because no options hash is stored on
   `DataSnapshot`. The protection is that the hash is **inside the key string**; the guard is a
   second line against a typo, not the first line against a silent fraction change.
4. **Disclosure is the third line, and it is not optional.** Every options evaluation records
   `options_config_hash`, the resolved `dataset_snapshot.key`, and the literal fraction values in
   `gates_json`. A reviewer can therefore detect a moved fraction from the stored evidence alone,
   without trusting the key convention.

**The invariant D5 may state, and no more than this:** *an options gate fraction, fill-model
constant or `OptionCostModel` constant cannot change without changing `options_config_hash`;
because `options_config_hash` is embedded in the mandatory explicit snapshot key, it cannot change
without producing a new `DataSnapshot` and therefore a new sealed look. This holds only for as
long as every options evaluation passes an explicit key — it is a convention enforced by the
evaluation entry point and by disclosure, not by the snapshot layer, which sees symbols only.*

### 2.9c The precondition on "byte-identical", which revision 1 left unstated

The claim that adding an `OptionsGateConfig` section leaves the equity `config_hash` byte-identical
is true **of the field set** and has one precondition revision 1 did not name. FACT:
`schema_version` **is** in `SCOPE_HASH_FIELDS` (`config/research.py:393`; the field itself at
`:302`), and adding a config section is exactly the change that invites a `schema_version` bump. If
it is bumped, the equity `config_hash` moves, `assert_auto_simulate_allowed`'s scope match fails
(`paper/ledger.py:506-514`), and live auto-simulation silently stops qualifying — incident
`0cc4cf4` again, in the same direction.

**Rule:** `schema_version` is **NOT** bumped by the commit that adds the options gate section, and
that commit carries a regression assertion pinning the current `config_hash` of the two live
PAPER_APPROVED strategies' approved scopes across it. `tests/unit/test_scope_hash.py` is the
existing home for that assertion.

### 2.10 Gate 0 verdict against today's database

Run today, an options gate 0 fails **0.a, 0.b, 0.c, 0.d, 0.e and 0.g simultaneously.** All six
verified read-only:

| Sub-check | Requirement | Today | Source |
|---|---|---|---|
| 0.a | ≥715 calendar days | 36 days of option bars (`2026-07-31 .. 2026-09-04`) | `select min(session_date), max(session_date) from option_aggregate_daily` |
| 0.b | 10 underlyings, continuous `massive` | 1 underlying (`SPY`) | `select distinct underlying_symbol from option_contract` |
| 0.c | ≥90% of cycles bracket | 9 distinct expirations, 4 of them weeklies inside 7 days; no monthly cycle history at all | `select expiration_date, count(*) from option_contract group by 1` → `2026-09-08:2, 09-09:2, 09-10:2, 09-11:2, 09-14:2, 09-30:246, 10-02:218, 10-09:218, 10-16:196` |
| 0.d | ≥80% session coverage per leg | 110 bar rows over **10** distinct contracts | `select count(*), count(distinct option_ticker) from option_aggregate_daily` |
| 0.e | named IV path per trade | 878 snapshot rows at **1** `as_of` | `select count(*), count(distinct as_of) from option_quote_snapshot` |
| 0.g | `q` sourced per underlying | no dividend series ingested | repo-wide: no `q` source exists |
| 0.h | `M == 100` | 100 uniformly — **would pass** | `select distinct shares_per_contract from option_contract` → `100` |
| 0.i | R per structure ≤ the pre-registered cap | **NOT MEASURABLE today** — 0.i is computed over an evaluated trade list and there is none. But the *arithmetic* is already decidable from the declared grid alone, and §2.8a shows two of three declared widths breaching decision #4's $250 cap **before any data exists.** That is a D5 decision to take now, not a measurement to wait for. | §2.8a; `OPTIONS_EXECUTION_PROGRAM_MAP.md:972` |

**This is the correct outcome and must not be worked around.** R4 permits making gates more
searching; 0.c–0.h are additions.

---

## 3. Gate 0.5 — one structure type per strategy version

**Predicate.** A strategy version declares exactly one `structure_type`. The gate fails if the
evaluation's trade list contains more than one, or if the declared `structure_type` is absent
from the version's `spec_json`.

**Why it is a gate and not a convention (map §5.1, restated because it is the load-bearing
point).** R is max loss (map §2.6), and max loss is a property of the **structure**:

**CORRECTION TO REVISION 1/2 — the CSP figure was stale by ~70%, and the corrected number is
stronger.** Revision 1 and 2 both quoted a $450 SPY strike and `R ≈ $44,500 (~100×)`, inherited
from `OPTIONS_EXECUTION_PROGRAM_MAP.md:707-709`. **FACT (read-only):**
`select o.close from ohlcv_daily o join instrument i on i.id = o.instrument_id where
i.symbol = 'SPY' order by o.session_date desc limit 1` → **764.29** (session `2026-09-11`, source
`massive`); stored `option_contract` strikes span **709 – 831**. The live arithmetic:

```
5-wide put credit spread on SPY :  R ≈   5 × 100 − credit     ≈ $   440
cash-secured put on SPY, ATM    :  R ≈ 764 × 100 − credit     ≈ $76,000    (~173×)
cash-secured put on SPY, 0.20Δ  :  R ≈ 725 × 100 − credit     ≈ $72,000    (~164×)
```

**And the corrected number says something the stale one did not: a single SPY cash-secured put
cannot be opened on the options paper account at all.** Decision #13 sizes that account at
**$25,000 SIMULATED**; one CSP reserves ~3× the entire account. This is a second, independent
reason O1 could not have shipped first (decision #12), and it is now a fact rather than a ratio.

`min_net_expectancy_r = 0.0` and `min_bootstrap_ci_low_r = 0.02` (`config/research.py:102,105`)
are stated **in R**. The same +0.02R is $8.80 on one structure and ~$1,440 on the other. So a
pooled R sequence has no common unit, and `bootstrap_ci` (`backtest/montecarlo.py:15-21`, which
takes a bare `Sequence[float]` and cannot know the difference) would return a number that means
nothing.

**Consequences, stated as rules:**

1. **`bootstrap_ci` is never handed a mixed-structure R sequence.** Gate 4's input is one
   structure type's R stream or it is invalid.
2. **A second structure is a different strategy version with its own sealed test**, and the
   multiplicity cost is paid automatically through `count_sealed_looks` (`promotion.py:647-663`).
   This is more searching, not less, and it costs look budget — which is the point.
3. **Every options gate report carries `structure_type` and the R basis formula** (map §5.1
   item 2). An equity +0.30R, a vertical +0.30R and a CSP +0.30R are three different claims and
   must be printed as such.
4. **Normalising R to a common basis is out of scope for Phase 1** (map §5.1 item 3): it would
   change what gates 3 and 4 mean for the **equity** strategies too, which R3/R4 make a
   version-bump-level event.

**HYPOTHESIS — the test for "same structure type", which D5 needs and the map does not give.**
Two constructions share a `structure_type` **iff** (a) their R formula is identical *in form*,
(b) their leg count is identical, (c) their per-leg sign pattern (short/long) is identical, **and
(d) their R *scale* is fixed within the version** — see the correction immediately below.
Strike side (put vs call) and regime-conditional direction are **not** part of structure identity.

**CORRECTION TO REVISION 1/2 — clauses (a)–(c) alone are purely formal, and re-admit at 3.3× the
incomparability gate 0.5 exists to prevent.** Under (a)–(c) every short vertical is one
`structure_type` *regardless of width*. But R = `width × M − credit`, so on the same underlying a
3-wide is R ≈ $180–225 and a 10-wide is R ≈ $600–750 (§2.8a's table) — a **3.3× spread in dollars
at risk inside one pooled R stream** — and `width` [3, 5, 10] is one of O3's four declared grid
axes (`OPTIONS_EXECUTION_PROGRAM_MAP.md:972`). That is the same failure this section rejects at
~170× between a CSP and a vertical, reproduced at 3.3× *inside a single version*, and
`bootstrap_ci` (`backtest/montecarlo.py:15-21`, a bare `Sequence[float]`) cannot see it. The
put/call mirror is genuinely fine — same width, same `M`, same scale. Width is not.

**Clause (d), stated precisely.** Within one strategy version, `width`, `M`, and the collateral
basis are **declared constants, never selected per trade**. `width` is a grid axis evaluated
**one value per run** — which costs nothing, because gate 5 already re-runs the whole backtest at
each grid point (`promotion.py:1166-1181`) and therefore never pools two widths into one R
stream. **A version whose entry rule chooses width adaptively (by credit, by IV, by available
strikes) fails gate 0.5**, because its R stream has no fixed scale and gates 3 and 4 are then
computed on a unit that moves with the data.

This matters immediately and concretely: **O3's call-side mirror is the same `structure_type` as
its put-side construction** (`short_vertical`: two legs, one short one long, `R = width × M −
credit` in both cases). It therefore lives inside **one** version — which is exactly what map
§5.3's fix for gate 6 requires, since the mirror is what produces bear-regime trades. Had the
mirror been ruled a second structure type, gate 0.5 would have forced it into a second version
and gate 6 would have become unpassable again. The test above is what makes those two rules
consistent.

By the same test: O4's long vertical (debit) is a **different** `structure_type` — R is the debit
paid, a different formula in form — and so is a cash-secured put (one leg). Both are separate
versions with separate sealed looks.

**Evidence keys:** `structure_type`, `r_basis_formula`, `structure_types_observed` (must be a
single-element list), `legs_per_structure`, `leg_sign_pattern`, **`width_declared`**,
**`widths_observed`** (must be a single-element list), **`m_declared`** (100),
**`r_scale_usd`** (`width × M`, the version's fixed R scale),
**`r_scale_dispersion`** (max/min observed R; must be explained entirely by the credit, never by
the width), **`width_selected_adaptively`** (must be `false`).

---

## 4. Gate 4b — dual spread-assumption pass, on BOTH asset classes

### 4.1 Predicate

Gates **2, 3, 4, 7 and 7b** must clear at **both** spread settings:

```
baseline  :  spread_multiple = 1.0     (options: the §2.6 modelled spread as specified)
stressed  :  spread_multiple = 2.0     (options: 2× that spread; equities: see §4.2 — the
                                        equity stress is specified on TOTAL round-trip cost,
                                        which is spread_bps = 16.0, NOT 10.0)
```

Gate 4b passes iff `gate2_pass ∧ gate3_pass ∧ gate4_pass ∧ gate7_pass ∧ gate7b_pass` holds **at
the stressed setting** (the baseline result is already those gates themselves). A fail at the
stressed setting is a gate-4b fail, which is a ladder fail via the verdict
`passed = bool(gates) and all(g.passed for g in gates)` (`promotion.py:1440`).

**Why 2/3/4.** Those are the three gates whose inputs are P&L in R: `promotion.py:1110` assigns
`oos = full.out_of_sample`, and gates 2/3/4 are appended at `:1112`, `:1125`, `:1139`.

**CORRECTION TO REVISION 1/2 — gate 7 was exempted from the cost stress, and it is the one
comparison in the ladder with a cost-free benchmark.** Revision 1 and 2 gated 2/3/4 and merely
*reported* 1–7 at 2×, on the rationale that the other gates' "binding constraint is not cost
realism". **That is exactly backwards for gate 7.** FACT: `_benchmark_metrics`
(`promotion.py:346-365`) computes the buy-and-hold comparison from raw proxy closes —
`closes = np.asarray(proxy.close[...])` at `:358`, `rets = np.diff(closes) / closes[:-1]` at
`:359` — with **no commission, no slippage and no spread anywhere**. Doubling the modelled spread
therefore moves the strategy's Sharpe and leaves the benchmark's Sharpe **untouched**. Gate 7 is
the single most cost-sensitive comparison in the ladder, and it was the one left out. A strategy
that clears gate 7 at the baseline cost and fails it at the stressed cost would have been
recorded as 4b evidence and promoted anyway. **Gate 7 is therefore gated at the stressed
setting.**

**Gate 7b is gated too, and for the opposite reason.** 7b's mechanical benchmark pays the *same*
modelled spread on the *same* structure (§6.2), so both sides move together and the 2× comparison
is not skewed — which is precisely what makes "does the signal's edge survive cost realism?" a
meaningful question there and a partly rhetorical one at gate 7. 7b is new and additive, so
gating it at the stressed setting removes no existing threshold and is R4-clean. **Keep both:
gate 7 answers "does it still beat the market after costs", gate 7b answers "does the signal
still beat mechanical harvest after costs". Neither substitutes for the other.**

**Gates 1, 5 and 6 stay reported-only.** They read `full.trades` and their counts shift slightly
under cost, but their binding constraints are fold coverage, grid-point trade counts and regime
coverage — none of which a spread multiple can make *easier*. **HYPOTHESIS:** run and **report**
all of 1–7 at the stressed setting as evidence; **gate** on 2/3/4/7/7b. D5 may tighten this to
the full ladder; it may not loosen it.

### 4.2 Why it applies to equities too — and why "permanent"

**FACT.** `/v3/quotes/{sym}` (equities NBBO) is 403 `not_authorized` in **7 of 7** entitlement
batches, exactly as the options endpoint is (map §0.3 item 3). The equity 11 bps round trip
(3.0 bps `slippage_bps` + half of a 5.0 bps spread, twice) is **exactly as unobserved** as any
options spread model. Exempting equities from a gate whose justification is "we cannot see the
spread" is incoherent.

**FACT.** Decision #5: no NBBO purchase now → modelled spreads stay a disclosed assumption on
both asset classes → **gate 4b is permanent**, not a transitional diagnostic.

**CORRECTION TO REVISION 1/2 — "`spread_multiple = 2.0`" is a true 2× on options and only 1.45×
on equities, and revision 2 said so in its summary without applying it.** The two asset classes
do not share a cost formula, so one knob labelled "2×" means two different stresses:

**FACT (equities).** `CostModel` is `slippage_bps = 3.0`, `half_spread_fill_penalty = True`
(`backtest/costs.py:11-16`), and `run_backtest` computes
`slip = (cm.slippage_bps + spread_bps / 2) / 10_000` (`backtest/engine.py:94`). So the spread is
only *part* of the adverse adjustment:

| setting | `spread_bps` | per side | **round trip** | multiple of baseline |
|---|---|---|---|---|
| baseline | 5.0 | 3.0 + 2.5 = **5.5 bps** | **11.0 bps** | 1.00× |
| naive "2× the spread" | 10.0 | 3.0 + 5.0 = **8.0 bps** | **16.0 bps** | **1.45×** |
| **genuine 2× total cost** | **16.0** | 3.0 + 8.0 = **11.0 bps** | **22.0 bps** | **2.00×** |

**FACT (options).** Under map §2.4(1a) the modelled spread is the *whole* adverse adjustment —
a full spread per leg per side, with no `slippage_bps` addend — so on options `spread_multiple =
2.0` really is a 2× cost stress.

**Rule.** The equity stress is specified on **total round-trip cost**, not on the spread field:
`spread_bps = 16.0` for the stressed leg, so that both asset classes are stressed at the same
*realised* multiple of 2×. This is the **tighter** of the two readings, so R4 permits it; the
1.45× form is the weaker one and is not used. Both the baseline and the stressed **realised**
round-trip costs are recorded as gate-4b evidence
(`cost_bps_roundtrip_baseline` = 11.0, `cost_bps_roundtrip_stressed` = 22.0,
`cost_multiple_realised` = 2.00), so no reader of the 4b evidence block can mistake a spread-field
multiple for a cost multiple. For options the same three keys are recorded from the
`OptionCostModel` round-trip figure of §2.6 (`cost_per_structure_roundtrip_usd` at each setting),
because bps is not the options unit.

### 4.3 CORRECTION TO MAP §5.2 — the equity plumbing is four touchpoints, not one

Map §5.2 says the backtest side is free because "`run_backtest(spread_bps=...)` is already a
parameter (`engine.py:90`); only `paper/ledger.py:50 _NOMINAL_SPREAD_BPS` needs lifting into
config." **The parameter exists but nothing plumbs it.** Verified:

| # | Touchpoint | What is there now | What 4b needs |
|---|---|---|---|
| 1 | `backtest/engine.py:90` | `spread_bps: float = 5.0` — a keyword default on `run_backtest` | unchanged; it is already the right shape |
| 2 | `research/backtest_runner.py:205-207` | `run_backtest(series, fn, cost_model=cost_model, warmup=min_bars // 2)` — **`spread_bps` is not passed**, so the `5.0` default is the only value that ever reaches the engine | accept and forward a `spread_bps` argument on `run_strategy_over_universe` (`backtest_runner.py:167-182`) |
| 3 | `research/promotion.py:868-879` | `evaluate_promotion` has **no** `cost_model` and **no** `spread_bps` parameter; the cost model is built inside at `promotion.py:911-916` from `config.commission_per_share`, `commission_min_per_order`, `slippage_bps`, `half_spread_fill_penalty` | a `spread_bps` (or `spread_multiple`) argument, forwarded to the **pre-sealed** call sites ONLY — `promotion.py:1042-1054` (the `full` run) and `:1166-1181` (sensitivity). **It must NOT reach `_get_or_create_sealed_test` — see §4.3a.** |
| 4 | `paper/ledger.py:50` | `_NOMINAL_SPREAD_BPS = 5.0`, a module constant with no override, used at `:163`, `:166`, and reported at `:185` | lifted into config so the live paper fill price is not a hard-coded literal |

**FACT confirming the "both doors" claim in map §0.4:** `CostModel` (`backtest/costs.py:11-16`)
has `commission_per_share=0.0`, `commission_min_per_order=0.0`, `slippage_bps=3.0`,
`half_spread_fill_penalty=True`, and `spread_cost()` (`costs.py:25-28`) halves the passed
`spread_bps`. So 3.0 + 5.0/2 = 5.5 bps per side, **11 bps round trip**, universe-independent.

**FACT:** `spread_bps` is **not** a field of `CostModel` and **not** a field of `ResearchConfig`.
It exists only as `run_backtest`'s keyword default and as `paper/ledger.py`'s module constant.

### 4.3a CORRECTION TO REVISION 1/2 — the stress parameter must never reach the sealed call site

**FACT (the hazard, and it is one line of plumbing away).** The third call site revision 1 named
is the **sealed** one: `_get_or_create_sealed_test` (`promotion.py:763`) is invoked at
`promotion.py:1316-1330` and is handed `cost_model=cost_model` — the *same object* the pre-sealed
runs use — and it calls `run_strategy_over_universe` itself at `:797-808`. Threading a
`spread_multiple` through `evaluate_promotion` "to the three call sites" therefore threads it into
gate 9.

**FACT (why the unique constraint does not save us here).**
`uq_strategy_sealed_test_strategy_version_id` on `(strategy_version_id, dataset_snapshot_id)`
(`db/models/research.py:263`) protects a pair that is **already sealed**. For the options family,
which §8.1 establishes starts at **k = 0 with no rows at all**, a single
`evaluate_promotion(..., spread_multiple=2.0)` would **create** a `StrategySealedTest` at a
non-baseline cost assumption and consume a sealed look — permanently, under R7.

**Rule (three parts, structural before procedural).**

1. **The sealed call site is pinned to the baseline.** `_get_or_create_sealed_test` receives the
   baseline cost model and `spread_multiple = 1.0`, structurally — it does not take the argument.
   A sealed record is always a baseline-cost record, on both asset classes, forever.
2. **The stressed leg runs through a pre-sealed-only entry point that cannot reach gate 9.** It
   computes gates 2/3/4/7/7b over `[start, pre_sealed_end]` and returns evidence; it has no path
   to `_get_or_create_sealed_test`.
3. **A stressed run that would insert a `StrategySealedTest` row RAISES.** The assertion is on the
   *intent*, not on the aftermath: if the stressed path is ever reached with a sealed window
   argument, it fails loudly rather than sealing. The row-count check of §8.3 item 4 stays as a
   second line, never as the first.

**Why 4b's stressed leg is still a *gate* and not merely a diagnostic despite this.** Gate 4b is
evaluated on **pre-sealed** data at both settings, and gate 9 is evaluated on **sealed** data at
the baseline setting. Those are different questions on different spans. Nothing about 4b requires
a sealed 2× number, and the design deliberately makes one unreachable.

### 4.4 The config-hash trap in touchpoint 4, and how to avoid it

`slippage_bps` and `half_spread_fill_penalty` **are** in `SCOPE_HASH_FIELDS`
(the fields themselves at `config/research.py:360-361`; their `SCOPE_HASH_FIELDS` entries at
`:407-408`). If a new `spread_bps` field is added to `ResearchConfig`
**and** to `SCOPE_HASH_FIELDS`, the equity `config_hash` changes and every live approved scope
stops matching — incident `0cc4cf4`, again.

**HYPOTHESIS — the rule:**

- The **stressed** 2× run is never a config default. It is a per-run argument
  (`--spread-multiple 2.0` on the evaluation script), and its result is recorded as gate-4b
  evidence inside the *same* evaluation's `gates_json`. `config_hash` never moves, no scope is
  disturbed, and no separate evaluation row is created for the stress leg.
- Lifting `_NOMINAL_SPREAD_BPS` into config (touchpoint 4) is a **separate, deliberate change**
  that must either keep the field out of `SCOPE_HASH_FIELDS` (accepting that the live paper fill
  price is then outside the approved-scope hash) **or** be shipped as an explicit re-approval
  event with both live strategies re-scoped. **This is Open Question OQ-3.** It is not D4's to
  decide, and it must not be bundled into the 4b commit.

### 4.5 The R1/R3-compatible way to apply 4b to the two live equity strategies

This is the part map §5.2 states as a constraint and does not give a procedure for. Here is the
procedure, with the facts that force each step.

**FACT (the hard constraint).** `StrategySealedTest` is unique on
`(strategy_version_id, dataset_snapshot_id)` (`db/models/research.py:262-263`), and
`_get_or_create_sealed_test` **reads an existing row rather than ever recomputing or overwriting
one** (`promotion.py:763-795`, the existing-row return at `:794-795`; the model docstring at
`db/models/research.py:252-260` states the same).
A 2×-spread re-run therefore **cannot** alter an existing sealed record, and any attempt to make
it do so would require deleting a row — which R7 forbids ("v0.1.0 rows, sealed tests and approved
scopes are never mutated, re-run or purged").

**FACT (the strategies in question).** `trend_continuation.short_swing` v0.1.0 (sealed test **11**,
+0.2982R, n=109) and `relative_strength.medium_swing` v0.1.0 (sealed test **14**, +0.2935R,
**n=16**), both on snapshot 3 — read-only query confirms sealed rows `11` and `14` on
`dataset_snapshot_id = 3`, windows `2025-09-08..2026-09-08`, both `passed = 1`.

**The four-step procedure (HYPOTHESIS):**

1. **Pre-seal only — and this is a MECHANISM, not a check.**

   **CORRECTION TO REVISION 1/2 — the previous step 1 detected a stolen sealed look instead of
   preventing one.** It said "run gate 4b on the pre-sealed span … verify afterwards … the row
   count must be unchanged". FACT (the hazard, verified read-only): sealed tests **11** and **14**
   sit on `dataset_snapshot_id = 3`, which holds **24** symbols; the same live DB also holds
   snapshot **11** (`research_150_massive_10y_presealed_sel`, 150 symbols, reusable) and three
   reusable `universe_auto_*` snapshots of 2,551 / 2,312 / 2,181 symbols. If the 4b re-run were
   executed through `evaluate_promotion` under **any** universe other than the exact 24-symbol
   set, `get_or_create_dataset_snapshot` would resolve a **different** snapshot by symbol-set
   match (`promotion.py:624-630`), `_get_or_create_sealed_test` would find no `(version, snapshot)`
   row, and it would **compute and lock a new sealed test** — a fresh look on a live
   PAPER_APPROVED family, permanent under R7 ("v0.1.0 rows, sealed tests and approved scopes are
   never mutated, re-run or purged"). The post-hoc row count would then report the violation
   *after* it was unrecoverable.

   **The mechanism.** The 4b pre-sealed run calls **`run_strategy_over_universe` directly** over
   `[start, pre_sealed_end]` (`backtest_runner.py:167-182`) and computes gates 2/3/4 — and 7/7b
   from `full.trades` — **inside the diagnostic script**. It **MUST NOT call
   `evaluate_promotion`.** `evaluate_promotion` is the only function that can reach
   `_get_or_create_sealed_test` (`promotion.py:1316-1330`), and nothing else in the ladder can
   seal.

   **If `evaluate_promotion` is used at all** — it should not be, and D4 recommends against it —
   then both of the following are required **before** the call, not after: (a) pass the explicit
   `dataset_snapshot` object for snapshot **3** (`evaluate_promotion(..., dataset_snapshot=snap3)`,
   `promotion.py:877`), never the unkeyed path; **and** (b) assert read-only that a
   `StrategySealedTest` row already exists for `(version_id, 3)`, so the call can only ever hit
   the locked-replay branch at `promotion.py:794-795`.

   **No sealed window is touched by the recommended mechanism, so no sealed look is taken and
   `count_sealed_looks` does not move.** The read-only row-count query of §8.3 item 4 is run
   afterwards as a **second line**, and its failure is a reportable incident, never the primary
   control.
2. **Publish as evidence.** The result is published as a diagnostic record under
   `docs/research/diagnostics/`, naming both strategies, both spread settings, and the exact
   `run_backtest` / `run_strategy_over_universe` arguments used. It is evidence, not a verdict.
3. **A fail at 2× is a disposition input under R1.** R1 permits sealed data to inform *whether to
   ship, whether to stop trying, or whether to declare a documented fail*. A pre-sealed 2× fail is
   not even sealed data — it is strictly weaker, and it is a legitimate input to a decision to
   **stop** (downgrade to EXPERIMENTAL, or suspend probation). What it may **never** do is
   motivate a parameter, filter, exit, entry or universe change to make the 2× number pass: that
   is R1's forbidden direction, and the 2× number is exactly the kind of target R1 names.
4. **Shipping 4b as a *ladder* gate for equities is a version bump under R3.** The moment gate 4b
   is added to the ladder that decides `PAPER_APPROVED`, the gate set that certified v0.1.0 is no
   longer the gate set in force. FACT: `upsert_strategy_version` (`persistence.py:46-93`) refreshes
   `spec_json` and `git_sha` on the **same row** when the version string is unchanged and never
   touches `status` — so re-running an unchanged v0.1.0 through a *changed* ladder recomputes
   gates 1–8 against the new ladder while gate 9 **replays the old sealed result**. That is R3's
   named silently-invalid pass. The only clean forms are: (a) leave v0.1.0's approval exactly as
   it stands, with the 4b diagnostic attached as a disclosure, or (b) ship a v0.2.0 that is
   evaluated under the 4b ladder from gate 0 and earns its own fresh sealed look.

**What is forbidden, stated so it cannot be arrived at by accident:** re-sealing v0.1.0 on
snapshot 3 at 2× spread. It is blocked structurally (the unique constraint plus
read-before-recompute), and it would be an R3 and R7 violation if the block were removed.

**Evidence keys (gate 4b):** `spread_multiple_baseline` (1.0), `spread_multiple_stressed` (2.0),
`baseline` = `{n_oos, expectancy_r, ci_low_r, gate2, gate3, gate4}`, `stressed` = same,
`spread_source` (`modelled — NBBO 403 on options and equities`), `applied_to`
(`options` | `equities`), `touchpoints` (the four of §4.3, for reproducibility).

---

## 5. Gate 6 — joint trend × volatility buckets

### 5.1 CORRECTION TO MAP §5.2 / §5.3 — there are five joint cells, not six, and the range cell has no volatility label

**FACT.** `backtest/regime.py:35-62`, the function gate 6 actually reads:

```python
trend = "bull" if sma_now >= sma_prev else "bear"          # :41
vol   = "highvol" if window_vol > med_vol else "lowvol"    # :57
if abs(close[i] - sma_now) / sma_now <= RANGE_BAND:        # :59  RANGE_BAND = 0.03  (:22)
    out[proxy.dates[i]] = "range_bound"                    # :60  <-- vol discarded
else:
    out[proxy.dates[i]] = f"{trend}_{vol}"                 # :62
```

The `range_bound` branch returns **before** the compound label is formed. `vol` is computed and
thrown away. So the complete emitted label set is:

```
warmup            (i < TREND_LOOKBACK = 200,  regime.py:36-38)
range_bound       (no vol component)
bull_highvol   bull_lowvol   bear_highvol   bear_lowvol
```

— **five** non-warmup labels, and the range cell is **vol-unlabelled by construction**.
`segment_key` (`regime.py:66-79`) agrees: `segment_key("range_bound")` returns `["all", "range"]`
with **no** vol segment, because `"range_bound"` ends with neither `"highvol"` nor `"lowvol"`.

Map §5.2/§5.3's "3 trend × 2 vol = 6 joint cells × 10 = 60 minimum" therefore describes a bucket
space the code does not emit. A sixth cell (`range_highvol` / `range_lowvol`) would require
editing `regime.py:59-62`, which **changes the gate-6 bucketing for every equity strategy too**
— a ladder change, hence R3/R4 territory and a version-bump event for anything re-evaluated
under it. **Recommendation: do not touch `regime.py`.** Specify gate 6b against the labels the
code already emits. The vol dimension stays free, which was the whole point.

**FACT (what gate 6 does with these labels today).** `_regime_census` (`promotion.py:406-440`)
maps `range_bound → "range"`, `startswith("bull") → "bull"`, `startswith("bear") → "bear"`, and
counts `warmup` / `no_proxy_bar` / `unlabelled` separately — **the vol half is discarded at
`promotion.py:425-431`**. Gate 6 then requires `covered >= min_regimes_covered`
(`promotion.py:1207-1208`) with `min_regimes_covered = 3` and `min_trades_per_regime = 10`
(`config/research.py:112-113`, whose comment reads "all three required, not 'at least two of
three'").

**FACT (a second, distinct regime system exists — do not confuse them).**
`research/regime.py` defines `RegimeState(Trend{BULL,BEAR,NEUTRAL}, Vol{LOW,HIGH})`
(`research/regime.py:20-46`) and is what `run_strategy_over_universe` uses to *gate signals*
(`backtest_runner.py:184`) and to key its own `by_regime` dict as `f"{trend}/{vol}"`
(`backtest_runner.py:216-218`). **Gate 6 does not read it.** Gate 6b must be specified against
`backtest/regime.py`, the one `_regime_census` consumes, or it will silently measure a different
partition of the same trades.

### 5.1a CORRECTION TO REVISION 1/2 — the two-system warning was never carried into the gate-6 reachability claim

Revision 1 and 2 both stated the warning above and then, in §3 and §7.4, made the load-bearing
claim that gate 6 is "reachable **only** because O3's call-side mirror produces bear trades"
(map §4.3, §5.3) — **which is a claim about the partition the census reads, argued from the
partition the strategy filters on.** They are not the same partition.

**FACT.** The strategy's signal gating uses `research/regime.py`'s
`RegimeState(Trend{BULL, BEAR, NEUTRAL}, Vol{LOW, HIGH})` (`research/regime.py:20-46`,
consumed at `backtest_runner.py:184`). The census reads `backtest/regime.py`'s labels, where
**any** session within ±3% of the 200-SMA is `range_bound` regardless of trend
(`RANGE_BAND = 0.03` at `regime.py:22`; the short-circuit at `:59-60`).

**Therefore the mirror does not guarantee `bear >= 10`.** A cycle on which the strategy fires the
call-side mirror — because `research/regime.py` says BEAR — can be counted **`range`** by the
census, because `backtest/regime.py` says the close sits inside the ±3% band. The two partitions
overlap but do not coincide, and gate-6 reachability is the thing that decided O3 ships before O1
(decision #12). **It is therefore unverified, and D4 must stop asserting it.**

**Rule — one of the two, chosen by D2/D5 and recorded:**

- **(a) Make the filter and the census read the same function.** The options runner passes
  `backtest/regime.py`'s `label_regimes` output to the structure's regime gate, so the partition
  the strategy trades on is the partition gate 6 counts. This is a **D2 requirement**, listed in
  §11. It is available because the options engine is a sibling module (map §2.1), not a
  generalisation of the equity runner — so adopting it changes nothing for equities.
- **(b) Measure and disclose the mismatch.** If (a) is not taken, the evaluation records a
  **cross-tabulation** of `research/regime.py` trend label × `backtest/regime.py` census label
  over the pre-sealed sessions, and gate 6's evidence carries `regime_partition_mismatch_fraction`
  — the fraction of the strategy's bear-filtered entries that the census counts as `range`. A
  mismatch fraction above a D5-pre-registered ceiling is a disclosed **gate-6 risk**, stated in
  the disposition record.

In **either** case, §7.6's pre-registration block must carry the bear-session count **from the
proxy labels alone and before any outcome is looked at** — see §7.6.

**Evidence keys (gate 6, additive):** `regime_label_source` (`backtest/regime.py:label_regimes`),
`signal_regime_label_source` (`research/regime.py:regime_lookup`, or the same as above under
option (a)), `regime_partition_mismatch_fraction`, `regime_partition_crosstab`.

### 5.2 Gate 6 — unchanged

`bull`, `bear`, `range` each ≥ `min_trades_per_regime = 10`, all 3 of 3 covered. No threshold
moves. The census-closure identity (`_RegimeCensus.closes`, `promotion.py:399-403` — "a trade
must never vanish between the census and the trade list it was built from") continues to hold and
is reported.

### 5.3 Gate 6b — the joint extension (new, additive)

**Predicate (HYPOTHESIS, pre-registered in D5 before any outcome is seen):**

```
(i)   each MARGINAL vol bucket  >= 10 trades :  highvol, lowvol
           highvol = bull_highvol + bear_highvol
           lowvol  = bull_lowvol  + bear_lowvol
(ii)  each of the 4 JOINT cells >=  5 trades :  bull_highvol, bull_lowvol,
                                                bear_highvol, bear_lowvol
(iii) range_bound reported as its own cell with its count, explicitly recorded as
      vol-unlabelled — it contributes to NEITHER vol marginal
(iv)  census closure holds:  sum(joint cells) + range + warmup + no_proxy_bar
                             + unlabelled  ==  n_trades
```

**Why ≥10 marginal and ≥5 joint, and not ≥10 everywhere.** Map §5.3's own arithmetic shows why:
`bear_lowvol` is rare by construction (bear markets are high-vol), so a flat ≥10 on every joint
cell would fail on that one cell even with ample total trades, and the predictable response would
be to quietly abandon the rule the first time it binds. A rule that is abandoned when it binds is
worse than no rule. The ≥10 marginal / ≥5 joint split keeps the vol dimension genuinely binding
while leaving the thin corner reachable. **The tercile variant (3 × 3 = 9 cells) is rejected for
Phase 1**: it is a new computation *and* triples the trade requirement, and map §5.3 already
judges it "very unlikely to close at 10 underlyings over 3 years."

**Minimum implied trade count:** `4 × 5 = 20` in joint cells, `≥10` in each vol marginal, plus
gate 6's own `≥10 × 3`. Against §6.4's ~216 pre-sealed trades this is feasible; against a
6-underlying or 1-year dataset it is not, which is the same conclusion §5.3 reached for gate 6.

**A consequence worth stating plainly.** If a strategy's trades concentrate in `range_bound`, the
vol marginals are computed on a **strict subset** of the trade list — 6b can fail on the vol
marginals while gate 6 passes comfortably on the trend buckets. That is the gate doing its job
for a short-premium strategy, whose regime is volatility and not trend. It is not a defect.

**Evidence keys:** `joint_cells` = `{bull_highvol, bull_lowvol, bear_highvol, bear_lowvol}`,
`range_bound_count`, `range_bound_vol_labelled` (false, with the `regime.py:59-62` citation),
`vol_marginals` = `{highvol, lowvol}`, `min_joint_cell_trades` (5),
`min_vol_marginal_trades` (10), `census_closes` (bool), `unbucketed` (reusing
`_unbucketed_evidence`, `promotion.py:447` def, called at `:1210-1220`).

**Touchpoint:** `_regime_census` (`promotion.py:406-440`) gains a joint-bucket dict alongside the
existing trend-only one. The existing `buckets` dict and the gate-6 pass computation are **not**
modified — 6b is an additional `Gate`, so a bug in the new census cannot change gate 6's verdict.

---

## 6. Gates 7, 7b and 8

### 6.1 Gate 7 — KEPT, and now cost-stressed

**FACT.** Gate 7 is `pm_strategy.sharpe > bench["sharpe"]` where
`bench = _benchmark_metrics(proxy_full, eff_start, eff_end)` — SPY buy-and-hold Sharpe over the
**matched** span (`promotion.py:1250-1272`), with `require_beat_benchmark_sharpe = True`
(`config/research.py:120`).

**FACT (a subtlety that must be preserved verbatim for options).** Gate 7 reads `full.trades` —
**every** pre-sealed trade, in-sample and out-of-sample together — not `full.out_of_sample`
(`promotion.py:1254`, and the comment at `:1238-1249` states this is deliberate). And both sides
are annualised over the **proxy's actually-available dates** (`eff_start`/`eff_end`,
`promotion.py:1251-1255`) to stop a shorter provider entitlement from biasing the comparison.
The options gate 7 must use the identical span resolution or the comparison is not like-for-like.

**FACT (the asymmetry that makes gate 7 the cost-stress gate, see §4.1).** `_benchmark_metrics`
(`promotion.py:346-365`) builds its return series as `rets = np.diff(closes) / closes[:-1]`
(`:359`) from raw proxy closes — **no commission, no slippage, no spread**. The strategy side pays
every modelled cost; the benchmark side pays none. That is why gate 7 is **gated at the stressed
spread setting** under §4.1 and was wrong to be exempt. It is also a standing caveat on the
existing equity gate 7 and is recorded as one in the disposition block (§9 §4).

**Map §5.2's correction stands and is restated as a rule: replacing gate 7 with a
mechanical-structure benchmark is a relaxation wearing the costume of a replacement, and R4
forbids it.** A short-premium strategy can beat a mechanical premium-harvest benchmark while
losing to simply holding SPY. Dropping the market benchmark removes exactly the comparison that
would catch it.

### 6.2 Gate 7b — mechanical-structure benchmark (new, additive)

**Predicate.** `strategy_sharpe > mechanical_sharpe`, both computed by
`compute_portfolio_metrics` over `full.trades` with the **same** `eff_start`/`eff_end` gate 7
uses.

**The mechanical benchmark is defined by subtraction, and its definition is pre-registered in D5
before any outcome is seen.** It is the same strategy with the *signal* removed:

| Component | Strategy | Mechanical benchmark |
|---|---|---|
| `structure_type` | declared | **same** |
| `short_delta` / `long_delta` | grid centre | **same, fixed** |
| `dte_target` | grid centre | **same, fixed** |
| regime filter | as designed | **removed** — trade every eligible cycle |
| `min_credit_to_width`, `max_short_delta` | as designed | **removed** (the hard risk cap of D3/§3.2 stays) |
| entry timing | as designed | first eligible session of each cycle |
| exits | as designed | **same** (profit target, stop, `time_stop_dte`) |
| `OptionCostModel`, fill model, spread multiple | as designed | **same** |
| universe, span, `M`, force-close/entry-eligibility rules | as designed | **same** |

So 7b asks exactly one question: **does the signal add anything over mechanical premium
harvest?** Everything else is held constant.

**For O4 (long vertical as a directional overlay) the mechanical benchmark is different and
better.** FACT: O4 re-expresses an already-evaluated equity signal
(`trend_continuation.short_swing` or `relative_strength.medium_swing`, map §4.4). Its benchmark is
the **share expression of the same signal** — which is `run_backtest` on the underlying with the
parent strategy's `signal_fn` (`backtest_runner.py:204-206`), i.e. existing, already-validated
machinery. The question becomes "does the options expression beat the share expression of the
same signal", which is a far tighter question than "does this signal work".

**Anti-gaming rule, and it is the one that decides whether 7b means anything.** The mechanical
configuration is **one** configuration, named in D5 **before** any outcome is looked at. Choosing
the mechanical benchmark after seeing results — picking the weakest mechanical variant — turns
7b from a test into a rubber stamp. R1 covers this: the benchmark definition is a design choice
and may not be informed by any outcome, sealed or pre-sealed.

**Both gate 7 and gate 7b must pass.** R4 permits adding 7b; it does not permit dropping 7.

**Evidence keys:** `strategy_sharpe`, `benchmark_sharpe_market` (gate 7),
`benchmark_sharpe_mechanical` (7b), `mechanical_spec` (the full frozen parameter set),
`mechanical_n_trades`, `span` = `{eff_start, eff_end}`, `both_pass` (bool).

### 6.3 Gate 8 — additions

Gate 8 today is `validate_daily(...)` + `_leakage_self_check(...)` with
`require_data_validation_pass` and `require_leakage_check_pass` both `True`
(`promotion.py:1286-1313`, `config/research.py:122-123`). It already carries a `known_caveats`
list (`promotion.py:1307-1310`) — the natural home for the options disclosures.

The additions, each with its field, its pass rule, and the map section that forces it:

| # | Field | Pass rule | Forced by |
|---|---|---|---|
| 1 | `corporate_action_exclusions` | recorded; count and reasons enumerated | map D7 / §5.2 |
| 2 | `deliverable_refusal_count` | recorded; gate 0.h already refused them, gate 8 reports | map §2.3 |
| 3 | `synthetic_mark_fraction_trade_weighted` | **≤ 0.10**, pre-registered, **trade-weighted** — strictly tighter than gate 0.d's complement; see the correction below | map §5.2 |
| 4 | *(no synthetic-fill field exists)* | by construction — map §2.4(3) forbids synthetic fills; `synthetic=True` on a fill must not be expressible in the model | map §2.4(3) |
| 5 | `non_entry_count`, `non_entry_reasons` | recorded | map §2.4(3) |
| 6 | `exit_deferral_distribution` | recorded (histogram of `exit_deferred_sessions`) | map §2.4(3) |
| 7 | `r_clamped_count`, `r_clamped_fraction`, `pnl_r_min_unclamped` | clamp fraction **≤ a D5-pre-registered ceiling**; HYPOTHESIS centre **0.05** | map §2.6 Option 1 |
| 8 | `pinned_fraction`, `pinned_r_distribution` | recorded, **and** the expectancy sign must survive removing the pinned trades | map §2.7 |
| 9 | `stop_non_binding_count`, `n_losing_trades`, `stop_non_binding_fraction_all_trades`, `stop_non_binding_fraction_of_losers` | **both** denominators recorded; the **0.25** ceiling binds on `..._of_losers`; the map's own quantity (`..._all_trades`) is recorded alongside — see the correction below | map §5.2a |
| 10 | `assignment_approximation_disclosed`, `assignment_risk_count` | must be `true`; the force-close rule *approximates early assignment away* and the bias is **in the strategy's favour** — stated, not buried | map §2.7 |
| 11 | `nbbo_unavailable_options`, `nbbo_unavailable_equities` | both `true` | map §0.3 item 3 |
| 12 | `clustered_bootstrap_ci` | reported **alongside** the iid CI; not a pass/fail | map §5.2 |

**Note on #7 and #9 — they measure the same phenomenon from opposite ends, deliberately.**
`r_clamped` counts trades whose realised loss exceeded max loss (per-leg exit spread under map
§2.4(1a), or the intrinsic floor of §2.7 — map §2.6(a)/(b)). `stop_non_binding` counts trades
whose realised loss exceeded the *stop*. A strategy whose expectancy depends on the stop binding,
in a sample where it frequently did not, has not demonstrated what it claims.

**Note on #8's rule, which is stronger than "report it".** A count alone can be read past. The
rule "expectancy sign must survive removing the pinned trades" is a falsification condition in
R10's sense: it names in advance the observation that kills the result. A strategy whose edge
concentrates in pinned trades has demonstrated a modelling artefact, not an edge.

**CORRECTION TO REVISION 1/2 — item 3 was non-binding by construction.** Revision 1 and 2 set
`synthetic_mark_fraction <= 0.20` and described it as "the complement of gate 0.d's 0.80". **That
is precisely why it could never fail.** Gate 0.d already requires
`sessions_with_bar / sessions_entry_to_exit >= 0.80` **per leg** (§2.4, evidence key
`bar_continuity_min`), so every leg's synthetic-mark fraction is already ≤ 0.20 and any aggregate
over legs is too — and gate 0 is **fail-fast** (§2), so gate 8 is only ever reached when 0.d has
already passed. The item added zero searching power while presenting as a pass/fail ceiling.
**Repair:** item 3 is re-specified as a **trade-weighted** fraction with a **strictly tighter**
pre-registered ceiling of **0.10**, which a trade whose legs each sit at 0.81 continuity can
genuinely fail. The per-leg quantity stays where it belongs, at gate 0.d.

**CORRECTION TO REVISION 1/2 — item 9 silently changed map §5.2a's denominator.** Map §5.2a item
2 requires "the count and fraction of **trades** that closed worse than `stop_multiple × credit`"
(`OPTIONS_EXECUTION_PROGRAM_MAP.md:1142-1146`); revision 1 and 2 reported the fraction **of
losing trades** against a 0.25 ceiling. For a fixed ceiling that change is in the *conservative*
direction — the losing-trade denominator is smaller, so the fraction is larger and the ceiling
harder — so it is **not a weakening**. But the headline number D4 gates on was then not the
quantity the map named, and the two are not convertible without the loss count. **Repair:** record
`stop_non_binding_count`, `n_losing_trades`, `stop_non_binding_fraction_all_trades` **and**
`stop_non_binding_fraction_of_losers`, and state explicitly — here and in the disposition record —
that the **0.25 ceiling applies to `stop_non_binding_fraction_of_losers`**.

**Note on #12 — do not repeat the equity omission.** FACT: the iid-violation problem is already
acknowledged and unresolved on the equity side (`STRATEGY_COMPLETION_MAP.md` §4.3: "Every CI here
is too narrow and every required-n is a lower bound", clustered bootstrap recommended and **not
yet computed** for either approved strategy). FACT: `bootstrap_ci`
(`backtest/montecarlo.py:15-21`) resamples a bare float sequence with `n_resamples=2000`,
`seed=20240101`, `ci=0.95` — iid by construction. Options trades on overlapping monthly cycles of
the **same** underlying are *more* correlated than equity swing trades, not less. The clustering
unit for options (HYPOTHESIS, D5 pre-registers it): **(underlying, expiry cycle)**.

**The gate-8 pass rule stays conservative.** Items 3, 7, 8 and 9 are pass/fail — item 8 against
a falsification condition, items 3, 7 and 9 against pre-registered ceilings, **all three of which
are now capable of failing on data that cleared gate 0** (item 3 was not, before the correction
above). The rest are recorded. No existing gate-8 condition is relaxed: `validate_daily` and the
leakage self-check still bind exactly as they do today.

---

## 7. The §5.3 arithmetic, as a re-run template on a coverage summary

Map §7 Phase I is explicit about what may be seen before D5 is committed: **the only output of
I-O2 visible before D5 is a coverage summary** — per `(underlying, cycle)`, whether the chain
brackets the target, contract counts per side, bar-continuity fractions, exclusion counts,
`shares_per_contract != 100` counts, and `IngestionRun` gaps. **No price, IV, greek, return,
credit or P&L series may be inspected — by a person or by a script — until D5 is committed.**

So §5.3's arithmetic must be re-runnable from **counts alone**. Below is that template. Every
input is either a FACT already cited or a field of the coverage summary; nothing in it requires
an outcome.

### 7.1 Inputs (all from the coverage summary or from source)

| Symbol | Meaning | Source |
|---|---|---|
| `U` | underlyings passing gate 0.b | coverage summary |
| `C` | eligible cycles per underlying over the pre-sealed span (§2.3's definition) | coverage summary |
| `b` | bracket fraction (gate 0.c measured) | coverage summary |
| `d` | fraction of selected structures meeting gate 0.d per-leg continuity | coverage summary |
| `e` | force-close eligibility survival: fraction of structures whose every leg prints on the `expiry − 1` session (map §2.7 — a structure that cannot be priced there **may not be entered**) | coverage summary |
| `f` | regime-filter trade rate — fraction of eligible cycles the filter would trade | **strategy design (D5), not data** |
| `s` | structures per underlying per cycle | `options_max_structures_per_underlying = 1` (map §3.2) |
| `TRAIN_FRAC` | 0.6 — OOS is the **last 40% of bars** per symbol | `research/backtest_runner.py:29`, `:158-160`, `:208-212` |

### 7.2 The formulas

```
N_presealed  =  U × C × s × b × d × e × f
N_oos        ≈  N_presealed × (1 − TRAIN_FRAC)   =  N_presealed × 0.40
N_fold       =  N_presealed / min_walkforward_folds            (= /4)
```

**FACT on the split:** `_is_boundary` (`backtest_runner.py:158-160`) cuts at
`max(1, min(int(len(series) * 0.6), len(series) - 2))` **per symbol, on bars**, and trades are
assigned by `entry_date <= boundary` (`backtest_runner.py:211-212`). Gates 2/3/4 read
`full.out_of_sample` (`promotion.py:1110-1152`); gates 1, 6, 7 read `full.trades`
(`promotion.py:1064-1108`, `:1206`, `:1254`).

### 7.3 Gate-by-gate pass conditions on counts

| Gate | Condition on counts | Threshold source |
|---|---|---|
| 1 | `N_fold ≥ 15` in ≥ 2 of 4 folds (plus positive expectancy — an edge question, not a count question) | `config/research.py:97,109`; `promotion.py:1093-1106` |
| 2 | `N_oos ≥ 30` | `config/research.py:99` |
| 5 | `≥ 15` trades at **every evaluable grid point**, including the corners | `config/research.py:109`; `promotion.py:1180,1190` |
| 6 | `≥ 10` in each of bull / bear / range | `config/research.py:112-113` |
| 6b | `≥ 10` in each vol marginal; `≥ 5` in each of 4 joint cells | §5.3 above (pre-registered) |
| 4 | see §7.5 — the only gate where counts alone are not enough | `config/research.py:105` |

### 7.4 Worked instance, at map §1.1's target dataset

`U = 10`, `C = 36` (12 monthly cycles × 3 pre-sealed years), `s = 1`, `f ≈ 0.60`, and
`b = d = e = 1.0` **assumed only to reproduce map §5.3's figure** — the whole point of the
template is that `b`, `d`, `e` come from the coverage summary and will be below 1:

```
N_presealed = 10 × 36 × 1 × 1.0 × 1.0 × 1.0 × 0.60  =  216
N_oos       = 216 × 0.40                            ≈   86
N_fold      = 216 / 4                               ≈   54
```

Gate 1: 54 ≥ 15 ✓ (counts). Gate 2: 86 ≥ 30 ✓, ~2.9× margin. Gate 5: ~216 per grid point
nominally, **corners must be checked, not assumed** — a tighter `short_delta` or narrower
`dte_window` selects fewer qualifying cycles, and `n_evaluable` is already reported
(`promotion.py:1190`). Gate 6b: 20 + marginals, feasible at 216.

**Gate 6: reachability is NOT established by the mirror alone, and revision 1/2 asserted that it
was.** The claim inherited from map §4.3/§5.3 — "reachable only because O3's call-side mirror
produces bear trades" — argues from `research/regime.py`'s BEAR to `backtest/regime.py`'s `bear`
bucket, and **those are different partitions** (§5.1a). A cycle the mirror fires on can be counted
`range` by the census whenever the proxy close sits inside the ±3% SMA band. **The honest
statement is:** the mirror is a *necessary* condition for bear-bucket trades and is not by itself
a *sufficient* one; sufficiency is a count question, answered before any outcome is seen, by the
§7.6 pre-registration block's bear-session census. Until that count is on the record, gate-6
reachability is **UNKNOWN**, not PASS — and it is the reachability of gate 6 that decided O3
ships before O1 (decision #12).

**Sensitivity of the verdict to the coverage summary — this is what the template is for.** Every
one of `b`, `d`, `e` multiplies. At a plausible `b = 0.90` (the gate-0.c floor), `d = 0.90`,
`e = 0.85`:

```
N_presealed = 216 × 0.90 × 0.90 × 0.85  ≈  149
N_oos       ≈  60          N_fold  ≈  37
```

Gates 1, 2 and 6b still clear; **gate 4's bar rises sharply** (§7.5). At `U = 6` or a 1-year span
the arithmetic does not close at all — map §5.3's conclusion, unchanged.

### 7.5 Gate 4 — the bar, tabulated, because counts alone do not decide it

The CI condition is approximately `mean − 1.96 · sd/√n > 0.02`, i.e.
**`mean > 0.02 + 1.96 · sd / √n`**. Required OOS mean expectancy in R:

| `n_oos` | `sd = 0.4` | `sd = 0.5` | `sd = 0.6` | `sd = 0.8` |
|---|---|---|---|---|
| 40 | 0.144 | 0.175 | 0.206 | 0.268 |
| 60 | 0.121 | 0.147 | 0.172 | 0.222 |
| 86 | 0.105 | 0.126 | 0.147 | 0.189 |
| 120 | 0.092 | 0.109 | 0.127 | 0.163 |
| 200 | 0.075 | 0.089 | 0.103 | 0.131 |

For comparison, FACT: the two live equity strategies sealed at **+0.2982R** (n=109) and
**+0.2935R** (n=16).

**Two warnings about this table.**

1. **It is a planning device, not the gate.** The gate runs a percentile bootstrap
   (`bootstrap_ci`, `backtest/montecarlo.py:15-21`, `n_resamples=2000`, `seed=20240101`,
   `ci=0.95`), not a normal approximation.
2. **HYPOTHESIS, and the direction matters:** credit-spread R-multiples are heavily **left**-skewed
   and bounded above by `credit/R` (~0.25–0.40 for a 0.20-delta 5-wide). For left-skewed data the
   bootstrap distribution of the mean is itself left-skewed, so its 2.5th percentile sits
   **further below** the mean than the normal approximation implies. The real bar is therefore
   **harder** than this table, not easier. Do not read the table as a target.

**This remains the gate most likely to decide the program** — and it is an *edge* bar, not a
*data* bar. More data lowers the required mean along a row but does not create an edge.

### 7.6 The template's own output — a required section of the D5 pre-registration

The re-run produces exactly this block, filled from the coverage summary, and it is committed
**before** any price/IV/return series is inspected:

```
coverage summary <id>, IngestionRun <id>, generated <ts>
U = __   C = __   s = 1   b = __   d = __   e = __   f = __  (design, D5 §__)
N_presealed = __   N_oos = __   N_fold = __

-- proxy regime census, from backtest/regime.py:label_regimes ALONE, no outcome ---------
-- (this is a label count over SPY sessions; it contains no price, IV, return or P&L)
pre-sealed sessions by census label:
  bull_highvol = __   bull_lowvol = __   bear_highvol = __   bear_lowvol = __
  range_bound  = __   warmup      = __
  bear TOTAL   = __   (the gate-6 bear bucket's entire supply of sessions)
regime-partition cross-tab (research/regime.py trend x backtest/regime.py label): __
  fraction of research/regime.py BEAR sessions the census calls `range` = __
gate 6 bear reachability: PASS / FAIL / UNKNOWN  (needs >= 10 bear-labelled ENTRIES,
  which requires bear TOTAL sessions x the mirror's trade rate >= 10)
-----------------------------------------------------------------------------------------

gate 1 counts: PASS/FAIL      gate 2: PASS/FAIL      gate 5 corners: PASS/FAIL/UNKNOWN
gate 6 (bull/bear/range reachable given the regime filter AND the census partition): PASS/FAIL
gate 6b (vol marginals >=10, joint cells >=5): PASS/FAIL
gate 4: required mean at (n_oos, assumed sd) = __R   [planning figure only]
verdict: the arithmetic {closes | does not close} on counts
```

**Why the bear-session census belongs in the pre-registration and not in the results.** It is a
count of *labels on proxy sessions*, computed by a function that reads only the proxy's closes
(`backtest/regime.py:35-62`). It contains no option price, no IV, no credit, no return and no
P&L, so it is admissible under map §7's rule about what may be seen before D5 is committed — and
it is the only thing that can turn §7.4's gate-6 reachability from an assertion into a fact
**before** the design is frozen. If it says gate 6 is unreachable, the pre-registered responses
of §7.6's closing paragraph apply in order: fix the regime filter or re-sequence the structure,
now; get more data; **never** a lower floor.

**If it does not close, the pre-registered responses are, in order: fix the regime filter or
re-sequence the structure (a design decision, made now); get more data; never a lower floor.**

---

## 8. Sealed-look accounting for the options family, from k = 0

### 8.1 What already exists — nothing is built here

**FACT.** `count_sealed_looks(session, strategy_name)` (`research/promotion.py:647-663`) counts
every `StrategySealedTest` joined `→ StrategyVersion → Strategy.name` — every version, every
snapshot. Its docstring states the design intent: "a v0.2.0 does not reset the multiple-testing
budget its v0.1.0 already spent."

**FACT.** `evaluate_promotion` captures `k_prior = count_sealed_looks(session, spec.name)` at
`promotion.py:924`, **before** gate 9 can seal anything.
`sealed_look_ledger` (`promotion.py:666-733`) enumerates the full history, and computes
`this_look` at `:717-725` — `prior + 1` for a run that seals, the replayed row's own index for a
run that replays. It is attached as gate-9 evidence under `sealed_look_ledger`
(`promotion.py:1373`), carried on `PromotionResult.sealed_look_prior`, and printed by
`cli.py:1386-1398` — which derives the line from the gate-9 ledger precisely "so the CLI can never
state a different count from the stored evidence" (`cli.py:1386-1388`).

**FACT.** It is derived from `strategy_sealed_test` on every read, so it cannot drift.

**Consequence for options: the family starts at k = 0 by construction, with no new code.**
`count_sealed_looks` keys on `Strategy.name`; a strategy named e.g.
`options_short_vertical.position` has no prior rows, so `k_prior = 0` automatically. The join
makes conflation with the equity ledger impossible in either direction.

### 8.2 The live ledger, re-verified read-only today

```sql
select s.name, count(*) from strategy_sealed_test t
  join strategy_version v on v.id = t.strategy_version_id
  join strategy s on s.id = v.strategy_id
 group by s.name;
```

| Family | `count_sealed_looks` | |
|---|---|---|
| `mean_reversion.short_swing` | **5** | |
| `relative_strength.medium_swing` | **4** | ← LIVE (PAPER_APPROVED) |
| `trend_continuation.medium_swing` | **5** | |
| `trend_continuation.short_swing` | **4** | ← LIVE (PAPER_APPROVED) |
| `volatility_breakout.short_swing` | **4** | |

Totals: `select count(*) from strategy_sealed_test` → **22**;
`select count(distinct dataset_snapshot_id)` → **5**.
**There is no global k.** Any multiplicity statement must name the family and cite
`count_sealed_looks` for it.

### 8.3 A live ±1 convention divergence — already settled by R2, and therefore a documentation error

**FACT.** For the 2026-09-11 powered runs, the stored gate-9 evidence records:

```sql
select json_extract(g.value,'$.evidence.sealed_look_ledger.k_prior'),
       json_extract(g.value,'$.evidence.sealed_look_ledger.this_look')
  from strategy_promotion_evaluation e, json_each(e.gates_json) g
 where json_extract(g.value,'$.number') = 9 and e.id in (45, 46);
```

→ **`k_prior = 4, this_look = 5`** for evaluation **45** (`trend_continuation.medium_swing`,
version 3, snapshot 11, `passed = 1`) and evaluation **46** (`mean_reversion.short_swing`,
version 4, snapshot 11, `passed = 0`).

**FACT.** The narrative documents for those same two runs call them **look 6**:
`docs/research/PREREGISTRATION_2026-09-11_snapshot11.md` ("Prior sealed looks (family) 5 … | look
6") and `docs/research/dispositions/mean_reversion_short_swing.md` ("family look 6"), which itself
flags the convention as unsettled and says "the operator should settle it once, before any counter
ships."

**So the code and the documents differ by exactly one, and both are currently in use.** The
divergence is harmless on equities only because both numbers are disclosed side by side. It is
**not** harmless on a new family, where the whole disclosure rests on "k started at 0".

**CORRECTION TO REVISION 1/2 — this is already settled in binding text, and D4 was wrong to
present it as an open convention choice.** FACT: `STRATEGY_COMPLETION_MAP.md` §1 **R2** states the
rule verbatim: *"k is the count of existing `StrategySealedTest` rows for the strategy family (all
versions, all snapshots); the next sealed evaluation is look k+1."* That is the code's convention
**exactly** — `k_prior = count_sealed_looks(...)` (`promotion.py:924`), `this_look = prior + 1`
(`promotion.py:725`). R1–R10 are the binding rules of engagement for this program. **There is
therefore no convention to choose.** The two narrative documents that say "look 6" for evaluations
45 and 46 are a **disclosed documentation error against R2**, not a competing convention — and
correcting a narrative document is not an operator decision. OQ-4 is downgraded accordingly (§12),
and **nothing about the options k = 0 baseline waits on it.**

**The rule for the options family, restated as what R2 already requires:**

1. **The code's convention is authoritative.** `k_prior = count_sealed_looks(...)` before the run;
   `this_look = k_prior + 1` for a run that seals; `this_look` = the replayed row's own index for a
   run that replays (`promotion.py:717-725` already implements exactly this, and a replay
   "takes no new look and must never be reported as though it did").
2. **Every options document quotes `sealed_look_ledger`'s `k_prior` and `this_look` verbatim**
   from the stored gate-9 evidence. No document recomputes, restates, or re-bases them.
3. **D5 records, before the first options evaluation, the read-only assertion**
   `count_sealed_looks(session, "<options family name>") == 0`, with the query and its output
   pasted in. That is the k = 0 baseline, established from the table rather than asserted.
4. After every options evaluation, the same query is re-run and the delta recorded. A pre-sealed
   diagnostic (including gate 4b's pre-sealed 2× run, §4.5 step 1) must leave the count
   **unchanged**; if it moved, a sealed look was taken by accident and that is a reportable
   incident.

### 8.4 Family naming, and the multiplicity leak it can create

Gate 0.5 makes each structure type its own version. If each structure type also gets its own
`Strategy.name`, then `count_sealed_looks` restarts at 0 for each — and the options program's
*total* multiplicity becomes invisible while every individual number stays technically correct.

**HYPOTHESIS — the rule.** Pre-register, in D5 and before the first sealed look, the **complete
enumerated list of `Strategy.name` values the options program will ever use**, and report in every
options record **both**:

- `count_sealed_looks(family)` — the code's number, for the family being evaluated; and
- `options_program_looks` = the arithmetic **sum** of `count_sealed_looks` over that
  pre-registered list.

This needs no new code (it is arithmetic over an existing read-only function, which is what map
§5.4 already concluded), and it makes the multiplicity cost of a second structure visible at the
moment it is paid. A family name that appears later and was not on the pre-registered list is, by
definition, an undisclosed look.

**HYPOTHESIS — a pre-registered look budget.** Before the first options sealed look, D5 states the
maximum number of sealed looks the options program will take before it stops: **3** (O3 as one
version with its put-side and call-side mirror inside it per §3; one re-specification if the first
is falsified; then stop). Exceeding the budget is permitted only with a written amendment that
discloses the overrun in every subsequent record.

### 8.5 Where multiplicity will actually leak — and it is not the count

**FACT.** `count_sealed_looks` counts what was **sealed**. It cannot count what was evaluated
pre-sealed, looked wrong, and was quietly dropped. With an options parameter space of
structure × delta × DTE × width, the number of **unsealed** variants explored will dwarf anything
the equity program has seen. R5 requires every evaluated variant, including abandoned ones, to be
disclosed with its pre-sealed evidence — and R5 has **no code enforcement** at all
(`STRATEGY_COMPLETION_MAP.md` §1: "Enforcement: none in code").

**HYPOTHESIS — the only mechanism that makes "abandoned variant" definable.** D5's
pre-registration must enumerate the **complete** grid, cell by cell, so that

```
abandoned variant  ==  a pre-registered cell that was not reported
```

A variant that was never pre-registered *and* never reported is invisible to both mechanisms —
which is precisely what R5 exists to prevent, and precisely what a large options grid makes easy.
For O3's declared axes (map §4.3: `short_delta` [0.10, 0.16, 0.20, 0.30] × `width` [3, 5, 10] ×
`dte_target` [21, 35, 45] × `profit_target_pct` [0.25, 0.50, 0.75]) that is
**4 × 3 × 3 × 3 = 108 cells** to enumerate. Enumerating 108 cells is tedious; it is also the
entire defence.

---

## 9. Disposition record format for the options family

The format follows the existing records in `docs/research/dispositions/` — verified against
`mean_reversion_short_swing.md` (12,526 bytes) and `trend_continuation_medium_swing.md` — and adds
the sections options require. Existing records open with a bold verdict line carrying the sealed
looks consumed, cite their source design document, and are appended to (never rewritten) when a
later powered run confirms or overturns them; that append convention is kept.

**File:** `docs/research/dispositions/<strategy_family>.md`, one per family.

```markdown
# Disposition — `<family>` v<X.Y.Z> (version <id>)

**Verdict: <PAPER_APPROVED | DOES NOT PASS (documented) | SUSPENDED>.** Status stays/becomes
`<STATUS>`. No `src/` or `tests/` file is touched.
**Sealed looks consumed: <n>. count_sealed_looks(<family>) = <k_after> (was <k_prior>).**
**Options program looks (pre-registered family list): <sum>.**

Source: `docs/research/options_designs/D5_<strategy>.md` (pre-registration, read in full);
`docs/research/options_designs/D4_options_gate_spec.md` (this ladder).

## 0. Structure identity and R basis          <-- NEW, required by gate 0.5 / map §5.1
structure_type: <...>      legs: <n>      sign pattern: <...>
R basis: <formula>, M = <shares_per_contract>
**Incomparability notice:** this R stream may not be pooled, averaged, bootstrapped together,
or compared with any other structure's R stream, or with the equity R stream.

## 1. The verdict, precisely
<expectancy ± SE, n, sd, clustering convention, which gate bound>

## 2. The sealed ledger                        <-- quote sealed_look_ledger verbatim
| Snap | Window | Sealed n | Expectancy | passed | k_prior | this_look |

## 3. Gate-by-gate result
| Gate | label | pass | detail |
| 0 | 0.a–0.h | | window / underlyings / bracket matrix / continuity / iv_source / fill+cost model / q / M |
| 0 | 0.i | | max R per structure and max concurrent open R vs the pre-registered limits |
| 0 | 0.5 | | structure singularity **and R-scale (one declared width, one M)** |
| 1..4 | | | |
| 4 | 4b | | baseline vs stressed cost, gates 2/3/4/7/7b, both asset classes; realised round-trip cost at each setting |
| 5 | | | incl. n_evaluable and the corner cells |
| 6 | | | bull/bear/range, **with the regime-partition mismatch fraction (§5.1a)** |
| 6 | 6b | | vol marginals + 4 joint cells + range_bound (vol-unlabelled) |
| 7 | | | vs SPY buy-and-hold Sharpe, matched span |
| 7 | 7b | | vs the pre-registered mechanical structure |
| 8 | | | the twelve fields of D4 §6.3 |
| 9, 10 | | | |

## 4. Data-provenance and disclosure block     <-- NEW, required by gate 0.e/0.f/0.g
iv_source mix: ...        q by underlying: ...        fill_model: ...
NBBO unavailable for options AND equities (403, 7/7 entitlement batches).
Assignment approximated away by the force-close rule — **bias is in the strategy's favour**.
Early assignment on short calls is not modelled at all.
Stop is a **close-basis** stop, checked only against the session close.

## 5. The measured-artefact block              <-- NEW, required by map §2.6/§2.7/§5.2a
r_clamped: n (frac)   pnl_r min unclamped: ...
pinned: n (frac)      expectancy excluding pinned: ...  (sign survives? yes/no)
stop non-binding: n of N all trades (frac) AND n of m losing trades (frac)
                   <-- the 0.25 ceiling binds on the LOSING-trade fraction
non-entries: n        exit deferrals: <histogram>
synthetic mark fraction (trade-weighted): ...  (ceiling 0.10)

## 5a. Risk-limit fit block                    <-- NEW, required by gate 0.i (§2.8a)
declared width: __    R scale: width x M = $__    max R observed: $__
pre-registered per-structure max loss: $__   aggregate open max loss: $__
max concurrent open R over the span: $__     structures breaching the cap: __
limits are inside options_config_hash: yes/no

## 6. Variant ledger (R5)                      <-- complete pre-registered grid, cell by cell
| # | cell | reported? | pre-sealed result (SE) | status |
Total pre-registered cells: <N>. Reported: <n>. **Unreported = abandoned, and listed here.**

## 7. Falsification record (R10)
What was stated in advance would kill this, and whether it was observed.

## 8. What this closes, and what it does not
## 9. Operator decisions outstanding
---
*Read-only disposition. No strategy code, configuration, database row, or gate threshold was
changed in producing this record.*
```

**Append convention (kept from the existing records):** a later powered or confirming run appends
a `## CONFIRMED — <date> …` section stating the pre-registration document it ran under, the
evaluation id, the sealed test id, `this_look`, and the verbatim gate outcomes. Earlier sections
are **never** rewritten.

---

## 10. Consolidated evidence contract

What each gate writes into `strategy_promotion_evaluation.gates_json`
(`db/models/research.py:314`). Every field here is a **new key in an existing JSON column** — no
migration, no schema change to any existing table.

| Gate | `label` | Keys |
|---|---|---|
| 0 | `0.a` | `window`, `presealed_days`, `min_presealed_days` (350), `sealed_window_days` (365) |
| 0 | `0.b` | `underlyings`, `underlying_source`, `underlying_first_bar`, `underlying_last_bar`, `underlying_gap_sessions` |
| 0 | `0.c` | `cycles_eligible`, `cycles_bracketed`, `bracket_fraction` (aggregate), `bracket_fraction_matrix` (`{dte: {put, call}}`), `bracket_fraction_min` (0.90), `bracket_fraction_gated_cells`, `eligible_cycle_definition` (literal clause text), `bracket_failures_by_underlying`, `bracket_failures_by_side` |
| 0 | `0.d` | `bar_continuity_fraction`, `bar_continuity_min` (0.80), `non_entry_count`, `non_entry_reasons`, `exit_deferral_histogram`, `gap_sessions` |
| 0 | `0.e` | `iv_source_mix`, `iv_source_unnamed_count` (0), `surface_n_floor`, `surface_n_actual_min` |
| 0 | `0.f` | `nbbo_available_options` (false), `nbbo_available_equities` (false), `entitlement_batches_checked` (7), `fill_model`, `spread_pct_of_last_print`, `spread_abs_floor_cents`, `spread_multiple`, **`option_cost_model`** (every field of map §2.5: `commission_per_contract`, `commission_min_per_order`, `exchange_fee_per_contract`, `spread_pct_of_last_print`, `spread_abs_floor_cents`, `assignment_fee`, `exercise_fee` — no default elided), **`option_cost_model_frozen_at`** (D5 commit sha), **`cost_per_structure_roundtrip_usd`** at each spread setting |
| 0 | `0.g` | `q_by_underlying` (`{value, source, as_of}`), `q_defaulted_count` (0) |
| 0 | `0.h` | `deliverable_refusal_count`, `deliverable_refusals` |
| 0 | `0.i` | `options_per_structure_max_loss`, `options_total_open_max_loss`, `account_equity_basis` (25000), `r_max_observed_usd`, `r_max_by_width`, `concurrent_open_r_max_usd`, `structures_breaching_per_structure_cap`, `width_grid_declared`, `limits_source`, `limits_in_options_config_hash` (true) |
| 0 | `0.5` | `structure_type`, `r_basis_formula`, `structure_types_observed`, `legs_per_structure`, `leg_sign_pattern`, `width_declared`, `widths_observed` (single-element), `m_declared` (100), `r_scale_usd`, `r_scale_dispersion`, `width_selected_adaptively` (false) |
| 4 | `4b` | `spread_multiple_baseline` (1.0), `spread_multiple_stressed` (2.0), `equity_spread_bps_baseline` (5.0), `equity_spread_bps_stressed` (16.0), `cost_bps_roundtrip_baseline` (11.0), `cost_bps_roundtrip_stressed` (22.0), `cost_multiple_realised` (2.00), `baseline{...}`, `stressed{...}` (each carrying gates 2/3/4/7/7b), `spread_source`, `applied_to`, `touchpoints` |
| 6 | — | `regime_label_source` (`backtest/regime.py:label_regimes`), `signal_regime_label_source`, `regime_partition_mismatch_fraction`, `regime_partition_crosstab` (§5.1a) |
| 6 | `6b` | `joint_cells`, `range_bound_count`, `range_bound_vol_labelled` (false), `vol_marginals`, `min_joint_cell_trades` (5), `min_vol_marginal_trades` (10), `census_closes`, `unbucketed` |
| 7 | `7b` | `strategy_sharpe`, `benchmark_sharpe_market`, `benchmark_sharpe_mechanical`, `mechanical_spec`, `mechanical_n_trades`, `span`, `both_pass` |
| 8 | — | the twelve fields of §6.3 |
| 9 | — | `sealed_look_ledger` (existing, `promotion.py:1373`) + `options_program_looks` |

Plus, on every options evaluation: `options_config_hash` (§2.9b — covering the gate-0 fractions,
the fill model, the `OptionCostModel` constants **and** the §2.8a limit set), the resolved
`dataset_snapshot.key` (§2.9b, which must be the explicit options key), `full_config_hash`
(`config/research.py:417-420`), and `options_scope_json` (map §3.5, written by `research/` — never
by `data.options_backfill`, which S11 forbids from importing `research.scan`,
`research.candidates` or `paper.ledger`, per map §3.6's quotation of `pyproject.toml:210-220`).

---

## 11. What D4 hands to the other workstreams

| To | Item |
|---|---|
| D1 (data) | Gate 0.b/0.c/0.d/0.e/0.g field definitions the coverage summary must emit; `eligible_cycles` denominator definition (§2.3); `options_config_hash` and its place in `options_scope_json` (§2.9b). **BLOCKER on the whole ladder: expand `OptionsConfig.underlyings` from the six it ships with (`("SPY","QQQ","IWM","AAPL","MSFT","NVDA")`, `config/research.py:200`) to map §1.1's ten.** §7.4 shows the gate arithmetic closing at `U = 10` and states plainly that at `U = 6` "the arithmetic does not close at all". Expanding it is safe for scope because `options` is outside `SCOPE_HASH_FIELDS` (§2.9). |
| D2 (engine) | The `fill_model` string contents (§2.6); `non_entry` / `exit_deferred_sessions` / `r_clamped` / `pin_risk_flag` / `assignment_risk` as **required** trade fields, because gate 8 gates on them (§6.3). **Plus §5.1a option (a): gate the structure's regime filter on `backtest/regime.py:label_regimes` — the same labelling function `_regime_census` reads — so the partition the strategy trades on is the partition gate 6 counts. If D2 declines, §5.1a option (b)'s cross-tab and `regime_partition_mismatch_fraction` become mandatory gate-6 evidence.** Also: the stress parameter must not be reachable from `_get_or_create_sealed_test` (§4.3a). |
| D3 (risk/paper) | **Gate 0.i (§2.8a) gates on the risk limits after all**, and the previous "nothing gates on collateral" was wrong: D3 supplies the pre-registered `options_per_structure_max_loss` / `options_total_open_max_loss` values and the concurrent-open-R accounting gate 0.i asserts against. Gate 0.h's `M == 100` assertion and gate 0.5's `structure_type` remain preconditions of `assert_options_auto_simulate_allowed` (map §3.6). |
| D5 (pre-registration) | **Ten** pre-registered items: `0.c = 0.90`, `0.d = 0.80`, the §2.4b surface N floor, the pin band, the `pct_otm_proxy` ceiling, `synthetic_mark_fraction_trade_weighted ≤ 0.10` (§6.3 item 3, tightened), `r_clamped_fraction ≤ 0.05`, `stop_non_binding_fraction_of_losers ≤ 0.25`, the clustering unit `(underlying, expiry cycle)`, **and the frozen `OptionCostModel` constant set of §2.6 — every field of map §2.5, frozen at D5 commit, raisable but never lowerable**; **plus** the §2.8a risk-limit set and the width decision it forces, the single mechanical 7b configuration, the complete 108-cell variant grid, the enumerated family-name list, the look budget (3), the minimum admissible DTE at entry (§2.1), and the §7.6 arithmetic block **including its proxy bear-session census**. |
| D6 (execution) | **Not "nothing" — three fail-closed invariants, because gate 0.h's `M == 100` and gate 0.5's `structure_type` are read at automatic-entry time out of `strategy_promotion_evaluation.gates_json`, which is research JSON that may be months old.** (a) The options guard is a **separate** function; `assert_auto_simulate_allowed`'s `inst.instrument_type not in ("stock", "etf")` refusal (`paper/ledger.py:497-500`) is **never widened** to admit options. (b) A **missing, null or unparseable** `structure_type` / `deliverable_refusal_count` / `M` key raises `AutoSimulateForbidden` and **never** defaults permissive — the existing guard fails closed on all five of its conditions (`paper/ledger.py:492-514`) and the options guard matches it. (c) `shares_per_contract == 100` is **re-asserted at entry against the live `OptionContract` row**, never read from a research evidence blob — a post-split deliverable is precisely the case gate 0.h exists for, and it changes *after* the evaluation was written. |

---

## 12. Open questions

**OQ-1 — (NARROWED, revision 3) Gate 4b's scope: should gates 1, 5 and 6 also be gated at the
stressed setting?** §4.1 now gates **2, 3, 4, 7 and 7b** and *reports* 1, 5 and 6 — gate 7 because
its benchmark pays no cost at all (`promotion.py:346-365`), 7b because both its sides move
together and it is the like-for-like cost question. What remains open is only gates 1/5/6, whose
binding constraints are fold coverage, grid-point trade counts and regime coverage. D5 may tighten
to the full ladder; it may not loosen. **Owner: orchestrator.** *Not blocking D5.*

**OQ-2 — Does gate 4b's equity application require a v0.2.0 of the two live strategies?** §4.5
step 4 argues the ladder change makes it an R3 version-bump event, and offers two clean forms:
leave v0.1.0's approval standing with the 4b diagnostic attached as a disclosure, or ship a
v0.2.0 evaluated under the 4b ladder from gate 0. **Owner: operator.** *Blocks: whether the 4b
diagnostic is a disclosure or a re-approval.*

**OQ-3 — Does `_NOMINAL_SPREAD_BPS` (`paper/ledger.py:50`) enter `SCOPE_HASH_FIELDS` when it is
lifted into config?** In: the live paper fill price is inside the approved-scope hash, but every
live scope must be re-approved (incident `0cc4cf4` in reverse). Out: no disruption, but the price
of a live paper fill can change without re-approval. **Owner: operator.** *Blocks touchpoint 4 of
§4.3; does not block the backtest side of 4b.*

**OQ-4 — (DOWNGRADED, revision 3) Correct the two narrative documents that number the
2026-09-11 runs "look 6".** This was carried as an unsettled convention question for the operator.
It is not one: `STRATEGY_COMPLETION_MAP.md` §1 **R2** already states in binding text that "k is the
count of existing `StrategySealedTest` rows for the strategy family … the next sealed evaluation is
look k+1", which is the code's convention exactly (`promotion.py:924`, `:725`). The stored gate-9
evidence for evaluations 45 and 46 (`k_prior = 4, this_look = 5`) is therefore correct and
`PREREGISTRATION_2026-09-11_snapshot11.md:13-14` and
`docs/research/dispositions/mean_reversion_short_swing.md` are a documentation error against R2.
**Owner: whoever next touches those two documents** — a documentation correction, not a decision.
*Does NOT block D5 or the options k = 0 baseline.* What **is** required of every options record is
unchanged and stands on its own: quote `sealed_look_ledger`'s `k_prior` and `this_look`
**verbatim** from the stored gate-9 evidence, and recompute nothing (§8.3 items 2–4).

**OQ-5 — One `Strategy.name` for the whole options program, or one per structure type?** §8.4
recommends one per structure type (so R streams are never pooled) **plus** a pre-registered
family list whose `count_sealed_looks` are summed and reported. The alternative — a single family
name — makes the program total automatic but invites pooling. **Owner: orchestrator + operator.**
*Blocks D5's family naming.*

**OQ-6 — Are the gate-8 ceilings of §6.3 (`r_clamped ≤ 0.05`, `stop_non_binding ≤ 0.25` of losing
trades, `pct_otm_proxy` ceiling) the right centres?** All three are design judgements with no
empirical basis, offered now so they are on the record before any coverage or outcome is observed.
They may be **tightened** at any time; loosening one after seeing data is exactly the move R1 and
R4 forbid. **Owner: operator, at D5 commit time.** *Blocks D5.*

**OQ-7 — Should `regime.py:59-62` ever be changed to emit `range_highvol` / `range_lowvol`?**
§5.1 recommends **no** for Phase 1: it would change gate-6 bucketing for every equity strategy, an
R3/R4 event, to gain one bucket the options design does not need. Recorded so the choice is
visible rather than defaulted. **Owner: orchestrator.** *Not blocking.*

**OQ-8 — Which clustering unit for the gate-8 clustered bootstrap?** §6.3 item 12 proposes
`(underlying, expiry cycle)`. The equity side has never computed a clustered CI at all
(`STRATEGY_COMPLETION_MAP.md` §4.3), so there is no precedent to inherit and the choice must be
pre-registered. **Owner: D5 author.** *Blocks D5.*

**OQ-9 — Does gate 5's grid corner check need a mechanical assertion, or is `n_evaluable`
(`promotion.py:1190`) enough?** §7.3/§7.4 flags the corner cells (e.g. `short_delta` 0.10 ×
`dte_target` 21) as the thin ones, and map §5.3 says they "must be checked rather than assumed".
`n_evaluable` reports how many points cleared `min_trades = 15` but does not say **which**.
**Owner: orchestrator.** *Not blocking D5; blocks a clean gate-5 reading at I-O4.*

---

## Appendix — Judge responses (revision 3)

Two adversarial reviews were run against revision 1 of this document: a **legitimacy/evidence**
lens (12 defects) and a **safety/feasibility** lens (10 defects), both verified against the repo at
`68b533c`. Revision 2 applied some and announced others it did not apply. Revision 3 works every
remaining item. Each is recorded below as **applied**, **applied with a correction to the
judgement itself**, or **rejected, with the reason**. Line numbers below are this document's own,
re-resolved against `5b41a61`; where a judge's cited line differs it is because the judges read
`68b533c`.

### A. Applied as stated

| Defect | Where it is now worked |
|---|---|
| L1 / S1 — §2.9's replacement protection does not exist; `DataSnapshot` identity is symbol-only | §2.9a (the refutation, with `promotion.py:567-570`, `:624-630`, `:632`) and §2.9b (the explicit mandatory snapshot key, and the guard's stated limit) — applied in revision 2, unchanged |
| L2 / S2 — §4.5 step 1 detected a stolen sealed look instead of preventing one | §4.5 step 1, rewritten as a mechanism; §4.3a pins the sealed call site to baseline cost and requires a raise rather than a seal |
| L3 — "spread_multiple = 2.0" is 1.45× on equities | §4.2's cost table and the `cost_bps_roundtrip_*` / `cost_multiple_realised` evidence keys (§10) |
| L4 / S8 — gate 7 exempted from the cost stress despite a cost-free benchmark | §4.1 gates 2/3/4 **and 7 and 7b** at the stressed setting; §6.1 records the `_benchmark_metrics` asymmetry as a standing caveat; OQ-1 narrowed to gates 1/5/6 |
| L5 — gate 0.c's denominator moved with a grid axis | §2.3, strategy-independent `eligible_cycles` + `bracket_fraction_matrix` — applied in revision 2, with §10 brought into line in revision 3 |
| L6 — the structure-identity test is purely formal and re-admits 3.3× incomparability via `width` | §3 clause (d) and the R-scale correction; `width_declared` / `widths_observed` / `r_scale_usd` / `width_selected_adaptively` evidence keys |
| L7 — gate 6b measures a different partition from the one the strategy filters on, and gate-6 reachability rests on the gap | §5.1a (the two options, and the mismatch cross-tab), §7.4 (reachability restated as UNKNOWN until counted), §7.6 (the proxy bear-session census, pre-registered) |
| L8 — the `OptionCostModel` constants were missing from the pre-registration handoff | §2.6 (applied in revision 2), §10's 0.f row and §11's D5 row (revision 3) |
| L9 — gate 8 item 3 was non-binding by construction | §6.3's item-3 correction: trade-weighted, ceiling tightened to 0.10 |
| L10 — OQ-4 is already settled by R2 | §8.3's R2 correction and the downgraded OQ-4 in §12 |
| L11 / S6 — systematic line-number drift | Every `promotion.py`, `cli.py`, `config/research.py`, `paper/ledger.py` and `db/models/research.py` citation in §3–§12 re-resolved by hand against `5b41a61` |
| L12 — §6.3 item 9 silently changed map §5.2a's denominator | §6.3's item-9 correction: all four fields recorded, and the ceiling's denominator named |
| S3 — the gate-identity design breaks two test assertions | §1's touchpoints 4 and 5 — applied in revision 2; the one stale `cli.py:1286` in the rejected-alternatives bullet fixed in revision 3 |
| S4 — the ladder certifies a population the arming limits refuse | **New §2.8a, gate 0.i**, plus the limit set folded into `options_config_hash` (§2.9b) and a new row in §2.10 and §10 |
| S5 — the byte-identical-hash claim has an unstated `schema_version` precondition | §2.9c — applied in revision 2 |
| S7 — the SPY price in the gate-0.5 argument is stale | §3, restated at the live close |
| S9 — §11's "D6: nothing" is not true, and the fail-closed rule is missing | §11's D6 row: three invariants (separate guard, never-permissive defaults, `M` re-asserted at entry against the live contract row) |
| S10 — the arithmetic closes only at a universe the config does not ship | §11's D1 row, as an explicit blocker on the whole ladder |

### B. Applied, but with a correction to the judgement itself

1. **L3's proposed `spread_bps = 19.0` for "a genuine 2×" is arithmetically wrong.** Per-side cost
   is `slippage_bps + spread_bps / 2` (`backtest/engine.py:94`), so the baseline is
   `3.0 + 2.5 = 5.5` bps/side. A genuine 2× is `11.0` bps/side, which needs
   `spread_bps = (11.0 − 3.0) × 2 = **16.0**`, giving 22.0 bps round trip. `19.0` would give
   `3.0 + 9.5 = 12.5` bps/side = 25.0 bps = **2.27×**, an unannounced over-stress. §4.2 specifies
   **16.0**. The judgement's *direction* — specify the equity stress on total round-trip cost — is
   correct and is adopted.
2. **S4's "EVERY width in the 108-cell grid breaches the $250 per-structure cap" is slightly too
   strong.** At `width = 3` and a credit of 0.40 × width, R ≈ $180 and the structure fits. §2.8a
   states it as the arithmetic actually gives it: **two of the three declared widths breach
   unconditionally; the third fits only when the credit is rich.** The conclusion — that the grid
   and the limits are inconsistent and the choice must be made before any outcome — is unchanged
   and is the reason gate 0.i exists.
3. **S4's "the $1,000 aggregate cap admits about two concurrent structures" is width-dependent.**
   It admits one at `width = 10` and four to five at `width = 3`. §2.8a states the range. The
   contrast with §7.4's `U = 10, s = 1` (up to ten concurrent) stands either way.
4. **L10's framing needs one qualification.** R2's *rule* is dispositive and matches the code
   exactly. R2's own worked example ("today k = 5") was written against an earlier ledger state and
   is not the authority here; the authority is the rule plus the live
   `count_sealed_looks` query of §8.2. §8.3 is written that way.
5. **L2's fallback ("if `evaluate_promotion` is used, pass the explicit snapshot and assert the row
   exists first") is recorded as a fallback, not as an option.** §4.5 step 1's primary rule is that
   the 4b pre-sealed run **must not call `evaluate_promotion` at all** — `evaluate_promotion` is the
   only function that can reach `_get_or_create_sealed_test` (`promotion.py:1316-1330`). The
   fallback is documented so that a reader who takes it anyway takes it correctly.

### C. Rejected, with reasons

1. **L1's option (b) — "drop the invariant and rely on disclosure plus the pre-registration
   document".** Rejected. The explicit-key mechanism of §2.9b exists in code today
   (`get_or_create_dataset_snapshot(key=…)`, `promotion.py:573-581`; `evaluate-promotion
   --snapshot-key`, `cli.py:1425-1436`), so a real structural protection is available and a
   documentary one is not the best available. Disclosure is kept as the *third* line (§2.9b item 4),
   not as the only one.
2. **L4's alternative — "or state in §4.1 the specific reason gate 7 is exempt".** Rejected. There
   is no good reason; the judgement's own evidence (`promotion.py:346-365`) refutes every candidate
   one. Gate 7 is gated.
3. **L4's "gate 7b may stay reported-only, since both its sides move together".** Rejected in
   favour of S8. 7b is new and additive, so gating it at the stressed setting removes no threshold
   and is R4-clean, and it is the *only* like-for-like cost question in the ladder — exactly the
   one worth gating. Both are gated; §4.1 says why each, separately.
4. **L9's alternative — "or reclassify item 3 as recorded-only".** Rejected. Reclassifying loses a
   check that can be made to bind for the cost of one pre-registered number. Tightening to a
   trade-weighted 0.10 is strictly more searching, which R4 permits and R1 does not touch (it is
   pre-registered before any outcome).
5. **L5's fallback — "if clause (iii) is kept, D5 must pre-register the DTE window first".** Moot
   and therefore rejected as an instruction: clause (iii) is **removed**, not kept (§2.3).
6. **Both lenses' line numbers were not copied.** Several judge-supplied citations resolve
   differently at `5b41a61` than at the `68b533c` they were verified against (for example the
   existing-row return is `:794-795` here, not `:788-796`). Every citation in this document was
   re-resolved independently against `5b41a61`; none was taken on the judges' authority. Where a
   judge's *content* claim was verified and its line differed, the content was kept and the line
   re-derived.

### D. Found during revision 3, in neither judge's list

1. **Revision 2's own change summary overstated its body.** It announced applied changes to §3,
   §4.1, §4.2, §4.3, §4.5, §6.3, §10 and §11, and a Judge responses appendix, none of which were
   present. A change summary that a reader cannot check against the body is a legitimacy defect of
   the same family as an unverifiable FACT citation. It is recorded at the head of this document
   rather than silently corrected, and revision 3's summary can be checked line by line against the
   sections it names.
2. **Gate 0.i is not measurable today but is already decidable.** §2.10's new row says so: there is
   no evaluated trade list, but the width/limit inconsistency follows from the declared grid and the
   decisions record alone, with no data at all. It is a D5 decision to take now, not a measurement
   to wait for — which is the whole point of pre-registration.

---

*Design document. No `src/` or `tests/` file, no configuration, no database row, no gate
threshold, and no baseline was changed in producing it. Every database figure came from a
read-only `SELECT`. No provider API was called.*
