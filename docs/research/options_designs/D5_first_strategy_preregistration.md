# D5 — Pre-registration of the first options strategy

**Family:** `options_short_vertical.medium_swing` (see OQ-1 on the horizon token)
**Structure:** O3 — short vertical (credit) spread, regime-filtered. Binding by
`docs/research/DECISIONS_2026-09-12_options_execution.md` decision 12.
**Version pre-registered here:** `v0.1.0`
**Written:** 2026-09-11. **Revised:** 2026-09-11 (rev 2, adversarial review — see §14).
**Status: DESIGN ONLY — nothing here is implemented.**
*Status note (2026-10-26): superseded as a status line. The strategy is implemented as
`v0.1.2` in `src/signalforge/research/options_strategies/short_vertical.py`, as amended by
D5a Amendments 1–3. No sealed look has been taken (k = 0). This document's design text is
unchanged; read the amendments for the binding parameters.*

---

## 0. What this document is, and the state it was written in

This is the R1 pre-registration for the first options strategy. It fixes the mechanism,
every parameter, the complete sensitivity grid, the disposition rule, the falsification
criteria, the gate-0 sub-thresholds, the §2.4b surface floor, the pin band, the variant
budget, and the null option — **before** any options price, IV, greek, credit, return, or
P&L series has been inspected.

**Attestation (FACT).** During the pass that produced this document the only database
access was read-only `SELECT` against `data/signalforge.sqlite`, and the only queries run
were row/coverage counts. The queries and their results are reproduced in §12. **No option
price, no option aggregate close, no implied volatility, no greek, no credit, no return and
no P&L was read, aggregated, or summarised** — by me or by any script. No provider API was
called, no package installed, no file under `src/` or `tests/` touched, and no file outside
`docs/research/options_designs/` written. Rev 2 re-verified every code citation and changed
no code, no config and no database row.

**Line numbers are pinned to commit `5b41a61` (2026-09-11).** FACT and a caution for the
reader: the tree moved *during* the original pass — `promotion.py` was rewritten between the
first and last read of that session (the INTRADAY gate-0 work, commits `907dcaf`…`5b41a61`),
shifting every line number in that file by 25-80. Every reference below was re-verified
against `5b41a61`. Rev 2 re-swept them a second time and **corrected three that were stale**
(§2.3's gate 2/3/4 triple — see §14 R7). Any reference that will not survive a later commit is
a reference to a *symbol*, and §13 names the symbol as well as the line for exactly that reason.

**FACT (why this can be written now at all).** There is nothing to look at. Options coverage
in the live DB is 888 `option_contract` rows on **one** underlying (SPY), expirations
2026-09-08 → 2026-10-16, and 110 `option_aggregate_daily` rows over 10 contracts, sessions
2026-07-31 → 2026-09-04 (§12). The backfill of I-O2 has not run. Pre-registration precedes
the data by construction here, which is the cheapest possible compliance with R1 and with
`OPTIONS_EXECUTION_PROGRAM_MAP.md` §7 Phase I ("the 0.c/0.d fractions are pre-registered
before I-O2 completes").

**FACT (sealed-look position of this family).** `strategy` holds six rows, none beginning
`options` (§12). `count_sealed_looks` keys on `Strategy.name`
(`src/signalforge/research/promotion.py:647`), so `k_prior = 0` for
`options_short_vertical.*` by construction, with no new code. The first sealed evaluation of
`v0.1.0` is **look 1** for this family. Equity families are unaffected and unpooled: current
per-family counts are `mean_reversion.short_swing` 5, `relative_strength.medium_swing` 4,
`trend_continuation.medium_swing` 5, `trend_continuation.short_swing` 4,
`volatility_breakout.short_swing` 4, total 22 rows (§12). **`count_sealed_looks` cannot see a
pre-sealed abandonment** — §10 pre-registers the `k_effective` accounting that closes that hole.

Every claim below is **FACT** (file:line, or a §12 query) or **HYPOTHESIS** (a design
proposal nothing in the repo establishes). Grid centres in the program map §3.2/§4.3 are
*evaluation* centres; where this document fixes a baseline it says so and gives the reason.
Nothing here is financial advice and nothing here is a recommended capital setting.

---

## 1. Mechanism, in market terms

**The claim being tested.** Index and large-cap equity options are, on average and across
most regimes, sold at an implied volatility above the volatility subsequently realised. The
seller is paid for bearing gap and crash risk and for the negative skew of equity index
returns. A *short vertical credit spread* harvests that premium while capping the tail: the
short leg sells the premium, the long wing a fixed distance further out-of-the-money buys
back the unbounded part of the payoff. What is given up is most of the premium's upside — max
gain is the net credit, which is by construction smaller than max loss. The trade is
therefore a high-hit-rate, low-payoff bet, and it is profitable only if the hit rate is high
enough to pay for the losses *and* for four crossings of a modelled spread.

**Why defined risk and not a cash-secured put.** Three independent reasons, all from the
map: max loss is finite so R is well-defined at entry and the whole metrics stack applies
unchanged (§2.6); one spread reserves roughly `width × 100 − credit` rather than
`strike × 100 − credit`, so the paper stream that feeds gate 10 is not collateral-starved
(§3.1); and the structure has a **call-side mirror**, so it can trade in bear regimes and
gate 6 is reachable at all (§5.3, defect 39). Decision 12 settles this and it is not
re-litigated here.

**Why a regime filter, and what it is for.** The filter is a *direction* control, not a
timing signal. The structure always leans with the prevailing trend of the broad-market
proxy: sell a **put** credit spread below the market when the lagged proxy trend is not
bear; sell the **call**-side mirror above the market when it is bear. The claim is narrow
and falsifiable: leaning with the lagged trend produces a higher hit rate than selling the
put side unconditionally. Gate 7b is the exact test of that claim (§7).

**Why there is no separate volatility filter.** A premium seller wants high implied
volatility, and the natural filter for it is already in the structure: `min_credit_to_width`.
A cycle whose options are too cheap cannot clear the credit floor and produces no entry. The
credit floor *is* the volatility filter, expressed in the units the trade actually pays in,
and it needs no new data. This is a deliberate design choice, pre-registered, and it is the
reason no `iv_rank`-style axis appears anywhere below.

**What would make this mechanism false, stated up front (R10).** If the premium collected
after four modelled spread crossings is smaller than the loss rate requires, the strategy
loses regardless of how well the regime filter works. §6.2 computes the break-even hit rate
in advance, on a **three-outcome** payoff (target win / stopped loss / max loss) rather than
the two-outcome payoff rev 1 used. At the central pre-registered max-loss frequency of **3%**:

> **break-even target-win rate = 80.4% at the baseline modelled spread, 88.6% at 2×.**
> (76.7% / 85.1% in the counterfactual where max loss never occurs; 82.9% / 90.9% if the
> max-loss frequency is 5%.)

Those are the numbers this design lives or dies on, and they are stated before any return
series exists. §6.3 goes further and states, in advance, the **only** corner of
(target-win rate × max-loss frequency × intra-cluster correlation) space in which the
deciding gate can close on any obtainable options history.

---

## 2. Declarations that fix the evaluation

### 2.1 Identity

| Item | Pre-registered value | Source / note |
|---|---|---|
| Strategy family name | `options_short_vertical` | new family; `count_sealed_looks` → k=0 (`promotion.py:647`) |
| Horizon token | `Horizon.MEDIUM_SWING` ("2-8 weeks", `src/signalforge/domain.py:17`) | the *holding* period, not the DTE, is what `Horizon` describes; a 35-DTE spread exited at 50% credit holds ~2-4 weeks. See **OQ-1** — map §1.1/§5.4 assumed `POSITION`. |
| Strategy key | `options_short_vertical.medium_swing` | |
| Version | `0.1.0` | R3: any behavioural change ships as `0.2.0` and costs a fresh sealed look |
| `structure_type` | `VERTICAL_CREDIT` — **exactly one per version** | map §5.2 gate 0.5; no structure allowlist exists anywhere |
| R basis | `R = strike_width × shares_per_contract × contracts − net_credit_received + entry_costs` | map §2.6. `net_credit_received` is the credit at the **adverse modelled fill** (§6.2a). **Not comparable** to any equity R or to any other structure's R (map §5.1). |

### 2.2 Underlying set — selection rule and count, both fixed now

Pre-registered rule (HYPOTHESIS). The underlying set is

> `{SPY, QQQ, IWM}` ∪ `{the 11 highest median-dollar-volume common stocks of DataSnapshot 11,
> measured over a PRE-SEALED liquidity window ending at the sealed-window start}`,
> minus any symbol excluded by the coverage rule below.

= **14 underlyings**. Rev 2 reduced this from 18. The reason is §6.3's corrected sizing: under
the clustered-variance accounting that rev 2 makes binding (§6.3b, F11), **adding underlyings
adds correlated trades and buys almost no independent information, whereas adding years adds
independent cycle-months one-for-one.** 14 × 8 years fits decision 6's 2,000,000-bar cap with
~9% headroom; 18 × 8 years does not fit at all (§6.3c). Years are therefore maximised first and
the underlying count is whatever the storage cap then allows, floored at 12 so that gate 5's
per-cell trade counts survive.

- Precedent (FACT): DataSnapshot 11's own 150 symbols were "selected on a PRE-SEALED
  liquidity window" (`docs/research/PREREGISTRATION_2026-09-11_snapshot11.md`). The same
  discipline is reused verbatim; no new kind of selection is introduced.
- Coverage exclusion, and the only data this document's author may see before the strategy
  runs: a symbol is dropped if its **chain coverage summary** (counts and completeness only —
  bracketing, contract counts per side, bar-continuity fractions, exclusion counts,
  `shares_per_contract != 100` counts, print-eligibility counts, `IngestionRun` gaps) fails
  gate 0.c or 0.d at the thresholds fixed in §5. This is explicitly permitted by map §7
  Phase I, which allows the coverage summary and nothing else to be visible before D5 is
  committed — and the 0.c/0.d numbers are fixed *here*, before the summary exists, so they
  cannot be reverse-engineered from it. The exclusion list is recorded in the evaluation and
  in `options_scope_json`.
- Equity-universe containment: every underlying is already in DataSnapshot 11, so regime
  labelling, liquidity screening and event filters reuse `OHLCVDaily` unchanged (map §1.1).

**The coverage-shortfall ladder, pre-registered in full (rev 2; was OQ-3's open "materially
below 55%").** §6.3 assumes a **55% net entry rate**. That assumption is checked once, against
the I-O2 coverage summary, *before* any outcome exists, and the entire response is fixed now so
that no post-hoc judgement enters:

1. **Trigger (exact).** The coverage summary's implied net entry rate `< 0.45`.
   ("Implied" = cycles clearing bracketing × the summary's own print-eligibility and
   `shares_per_contract` fractions. It uses counts only; no price is read.)
2. **Response (exact, and the only permitted one).** History depth rises from 8 to the maximum
   the entitlement and the 2,000,000-bar cap jointly allow; if that is already 8, the underlying
   set expands from top-11 to top-19 (i.e. 14 → 22 underlyings) **in strict median-dollar-volume
   rank order**, again subject to the bar cap, dropping history years last.
3. **It may fire at most once**, is recorded in `options_scope_json` with the summary that
   triggered it, and is disclosed at gate 8.
4. If the trigger does not fire, the set is exactly as declared above. No other change to the
   population is permitted at any point, for any reason.

### 2.3 Window

| Item | Pre-registered value | Reason |
|---|---|---|
| Total option history | **8 years** ending at the snapshot end; **floor 6 years** | rev 2. Independent cycle-months, not trades, are the unit gate 4 can actually spend (§6.3b). 8 × 12 = 96 cycles; the 2,000,000-bar cap binds at 14 underlyings (§6.3c). If the entitlement supports fewer than 6 years the shortfall is recorded and the expected consequence — stated here, in advance — is that F11's clustered CI does not close and the disposition is the §10 null option. |
| Sealed window | 365 days (`config/research.py:127` `sealed_window_days`) | frozen, R4 |
| Pre-sealed span | ~7 years, ≥ `MIN_PRESEALED_DAYS` = 350 calendar days (`promotion.py:106`) | gate 0.a |
| IS/OOS split | last 40% of each symbol's bars is OOS (`research/backtest_runner.py:29` `_TRAIN_FRAC = 0.6`) | frozen; gates 2/3/4 read `full.out_of_sample` — **`promotion.py:1110` (`oos = full.out_of_sample`), gate 2 at `:1111`, gate 3 at `:1124`, gate 4 at `:1137-1138`** |
| Proxy | SPY, source `massive` | R6; gate 6/7 both read the proxy |

**FACT, corrected in rev 2.** Rev 1 cited `promotion.py:1035,1048,1062` for the gate 2/3/4 OOS
reads. At the pinned commit `5b41a61` line 1035 is inside the `run_strategy_over_universe(...)`
call and 1048/1062 are inside the `data_provenance` dict — the citation was wrong. It was
inherited from `OPTIONS_EXECUTION_PROGRAM_MAP.md` §5.3, which carries the same stale triple
(`1034,1044,1061`) from a pre-`907dcaf` tree. The correct lines are in the table above and
match §6.4, which was already right. The map's §5.3 line triple should be corrected when the
map is next amended; it is recorded as **OQ-8**.

### 2.4 Pricing inputs, fixed before any price is read

| Input | Pre-registered value | Source |
|---|---|---|
| Risk-free rate `r` | **0.04, constant across the whole window** | `config/research.py:205` `risk_free_rate: NonNegativeFloat = 0.04`, which lives inside `OptionsConfig` (`:194`). A single constant over 8 years is a **disclosed approximation**; its effect on a 21-45 DTE delta is second-order but not zero, and it is reported as an assumption on every evaluation. Not a grid axis (§4.4). **It is strike-shaping and is therefore hashed — see §2.5.** |
| Dividend yield `q` | **Sourced and recorded per underlying per session** (trailing-12-month distribution yield), `q_source` recorded per evaluation | decision 11; map §2.4a, gate 0.g. A session with no `q` for an underlying produces **no entry** on that underlying, counted. `q = 0.0` by default is a gate-0 failure (`options/blackscholes.py:49,63,101` all default `q = 0.0`). |
| **Print eligibility (NEW, rev 2)** | A leg's `OptionAggregateDaily` bar is **print-eligible** on a session only if `volume ≥ 10` **and**, where `transactions` is non-null, `transactions ≥ 5` | FACT: both columns exist and rev 1 used neither (`db/models/market.py:312,313,314`). A bar that is not print-eligible may not set an IV, may not select a strike, and may not fill. See §3.3(1a) for the entry consequence and §8 for the ceilings. Fail-closed on `volume`; the `transactions` half is enforceable only where the provider populates it, and the null fraction is itself reported (§8). |
| IV / delta path | **`local_bs_inverted`** first (IV inverted from the contract's own **print-eligible** print on the signal session via `options/blackscholes.py:93 implied_vol`), **`same_session_surface`** (§5.3) as the only fallback, **`pct_otm_proxy` NEVER** | decision 7; map §1.5 gate 0.e. Realised volatility as a fallback is **forbidden** (map §2.4b) — it is below implied on average, which is the exact quantity being harvested. |
| **Asynchronicity disclosure (NEW, rev 2)** | The string `iv_print_stale_asynchronous_to_underlying_close` is carried in `fill_model` on every trade | FACT: `OptionAggregateDaily` is a settled daily bar with **no last-trade timestamp** (`db/models/market.py:290-318`). A wing that last traded at 10:03 is inverted against `s = U_t`, the underlying's *close*. The resulting σ absorbs the whole intraday move of the underlying and biases `delta`, and therefore the short strike, **in an unbounded direction** — it is not a spread error and bar-continuity (gate 0.d) cannot detect it, because a bar exists. Mitigated, never removed, by the print-eligibility floor above and measured by the `\|close − vwap\| / close` diagnostic in §8. |
| Fill model | **§2.4(1a) print-plus-**full**-spread**, adverse direction, per leg per crossing. 2 legs × 2 sides = **four full modelled spreads** per round trip | map §2.4(1). The reference is `OptionAggregateDaily.close`, a **last print**, never a mid (`db/models/market.py:290-318`; there is no bid/ask column and NBBO is 403 on both asset classes). |
| Modelled spread | `spread_per_leg = max(0.02, 0.03 × last_print)` dollars, **baseline**; `max(0.04, 0.06 × last_print)` at the **2× setting**. **The `max()` is not decorative: it binds on the cheap far-OTM long wing, which is the leg it was written for, and §6.2 applies it explicitly** | HYPOTHESIS. D2 owns the `OptionCostModel` definition; these are the constants this forecast assumes. If D2 sets different constants, §6's arithmetic is re-run and the difference disclosed — the **gate** never moves (R4). |
| Commissions / fees | `$0.65` per contract + `$0.15` exchange fee per contract → `$1.60` per 2-leg entry and `$3.20` per 2-leg structure round trip | HYPOTHESIS, D2's `OptionCostModel`. Cost scales with legs × contracts (map §2.5). |
| Missing bar | **a liquidity fact, never a fill** (map §2.4(3)) | entry with any leg lacking a print-eligible bar is a **non-entry**, counted; an exit signal defers to the next session on which every leg prints, `exit_deferred_sessions` recorded |
| `shares_per_contract` | read per leg from `OptionContract` (`db/models/market.py:255`); **asserted == 100 at entry, contract refused otherwise**, refusals counted | map §2.3, gate 0.h |

### 2.5 Where these constants are hashed — a correction to the map (FACT, load-bearing)

The map says repeatedly that the options constants are "folded into `config_hash`"
(§1.5, §2.4(2), §3.2 line 786). **Doing that literally would repeat the 2026-09-11 incident.**

FACT: `ResearchConfig.config_hash` hashes exactly the keys in `SCOPE_HASH_FIELDS`
(`src/signalforge/config/research.py:392-409`, applied at `:415`), and that tuple contains
`schema_version, watchlist, etf_universe, allow_short_candidates, enabled_horizons,
intraday_bar_size, liquidity, risk, events, data_quality, quality_gates, universe_filters,
commission_per_share, commission_min_per_order, slippage_bps, half_spread_fill_penalty` —
**no `options` entry**. Adding one adds a key to the hashed payload, changing the hash, which
is precisely what knocked live scans out of their approved scope on 2026-09-11 (map §0.4;
fixed by commit `0cc4cf4`).

**Two further FACTs rev 1 did not state, and they change the rule.**

1. `ResearchConfig.options: OptionsConfig` **already exists** (`config/research.py:353`) and is
   **already outside** `SCOPE_HASH_FIELDS`. `risk_free_rate` lives inside it (`:205`). §3.3(1)
   feeds `r` into `greeks(...)` to pick the short strike, so `r` is **strike-shaping**. Under
   rev 1's rule — which scoped `options_config_hash` to a *new* section only — an operator could
   move `r` from 0.04 to 0.06, change which strike every cycle sells, and **neither hash would
   move.** That is the same silent-scope-drift failure as the 2026-09-11 incident, in the
   opposite direction.
2. `ResearchConfig.promotion: PromotionThresholds` (`config/research.py:348`) is **also** outside
   `SCOPE_HASH_FIELDS`. The gate thresholds are therefore not covered by the equity scope hash
   either. That is pre-existing and out of D5's scope to change, but it means an options
   evaluation record must carry its own thresholds verbatim rather than rely on a hash.

**Pre-registered rule (HYPOTHESIS), rev 2.**

- The options evaluation constants live in a new `OptionsEvaluationConfig` section that is
  **not** added to `SCOPE_HASH_FIELDS`.
- `options_config_hash = config_hash({"options_evaluation": OptionsEvaluationConfig.model_dump(),
  "options": ResearchConfig.options.model_dump()})` — **explicitly over both sections**, so `r`
  and the `q_source` policy are inside it. (Equivalently, D1/D3 may *move* `risk_free_rate` and
  the `q_source` policy into `OptionsEvaluationConfig`; either shape is acceptable provided the
  hash covers both, and the choice is recorded.)
- Every options promotion evaluation additionally records the **verbatim** `PromotionThresholds`
  payload it ran under, because that payload is in neither hash.
- `options_config_hash` is recorded inside `options_scope_json` (map §3.5) and matched as the
  **sixth part** of the options approved scope (map §3.6).
- **Migration claim, stated so it can be checked mechanically:** no field is added to, removed
  from, or reordered within `SCOPE_HASH_FIELDS`, and no field *inside* a hashed section changes,
  so the equity `config_hash` is **byte-identical** before and after this work and both live
  PAPER_APPROVED strategies remain inside their own approved scope. A diff of the equity
  `config_hash` across the change is a required artefact of I-O1.

**Deterministic behaviour if the orchestrator rules the other way (rev 2; rev 1 left this
open and therefore left the evaluation undefined).** A pre-registration may not bind on a rule
it simultaneously flags as unresolved. Therefore: if the orchestrator confirms the map's
literal wording and directs that the options constants join `SCOPE_HASH_FIELDS`, then **v0.1.0
still runs exactly as specified above** — `options_config_hash` is computed and recorded
identically — and the `SCOPE_HASH_FIELDS` addition is made as a **separate, independently
recorded migration** that re-issues the approved scope of both live PAPER_APPROVED strategies
under the new equity `config_hash` before any options work lands. Nothing in §§3-8 changes
under either ruling; only the migration step differs. OQ-6 now decides *when* a migration
happens, not *what the evaluation does*.

---

## 3. The strategy, stated as a deterministic function

No LLM is consulted anywhere. Given the data and the params, entry, strike selection and exit
are a pure function (import-linter S3, `pyproject.toml:178-186`, already forbids
research/risk/backtest/paper → llm).

### 3.1 Cycle and entry timing

1. **Cycle.** One monthly (third-Friday) expiry per underlying. `options_calendar.py` (D2)
   resolves the Thursday rule for holiday weeks. No weeklies in v0.1.0.
2. **Signal session `t`.** The first NYSE session on which `DTE(expiry) ≤ dte_target`.
   Deterministic, exactly one per (underlying, cycle).
3. **Eligibility window.** `DTE(expiry) ∈ [dte_window_lo, dte_window_hi]` on session `t`.
   If `t` falls outside the window (a holiday run), the cycle is skipped and counted.
4. **Fill session.** Entry fills on session `t+1`'s prints, matching the equity engine's
   convention (`src/signalforge/backtest/engine.py:85-151` fills at `t+1`).
5. **Concurrency, with the tie-break stated (rev 2).** At most one open structure per
   **underlying** (map §3.2 `options_max_structures_per_underlying = 1`, keyed on the underlying
   not the `instrument_id` — map §3.6 records why the existing `auto_simulate.py:108-120,164-171`
   check would not catch this). **Pre-registered tie-break: exits scheduled on session `t` are
   settled *before* eligibility is tested on `t`.** If a structure is still open after that
   settlement, the cycle is skipped and counted as `skipped_concurrency`.

   **Why the tie-break is load-bearing and not a detail (rev 2, arithmetic).** Third-Friday
   expiries are 28 or 35 days apart. With `time_stop_dte = 7`, the prior cycle's time stop
   falls on `expiry_prev − 7`. At `dte_target = 35` the new signal session is
   `expiry − 35 = expiry_prev + gap − 35`, which for `gap = 28` is **exactly**
   `expiry_prev − 7` — the prior cycle's time-stop session. On the 2026 calendar that
   coincidence occurs on 7 of 11 consecutive expiry pairs. Without the tie-break the rule is
   ambiguous on ~58% of cycles; with it, the prior structure has closed and the new cycle is
   eligible. At `dte_target = 21` the new signal lands 7 days *after* the prior expiry and can
   never collide. **So without the tie-break, grid axis `dte_target` would have measured cycle
   availability rather than DTE**, and the 21-DTE cells would have carried systematically more
   trades — silently changing which cells clear `sensitivity_min_grid_trades = 15` and therefore
   §5.5's `n_evaluable ≥ 58` test. With the tie-break the only residual collisions come from
   §3.4 exit deferrals past the time-stop session, which are second-order and are **measured**:
   `skipped_concurrency` is a §8 census field and §4.2 reports it per grid cell so the residual
   confound is visible rather than assumed away.

   **The same arithmetic is why `dte_target = 45` is not a grid value** (map §4.3 lists it): at
   45 DTE the signal session is `expiry − 45 = expiry_prev + gap − 45`, which for every
   `gap ∈ {28, 35}` falls **before** `expiry_prev − 7`, so the prior structure is still open and
   **every cycle is skipped**. A 45-DTE cell under `options_max_structures_per_underlying = 1`
   produces approximately zero trades. This is a derived exclusion, not a preference, and it is
   recorded as a disclosed deviation from map §4.3 (§4.2).
6. **Size.** Exactly **1 contract per leg** in the backtest. The backtest is
   position-count-unconstrained by design (map §3.1); the paper stream is not (§9.2).

### 3.2 The regime filter — lagged by one session, and which module supplies it

Pre-registered: the label is `regime_from_proxy(proxy, t-1)` from
`src/signalforge/research/regime.py:62-96` — the proxy's state as of the session **before**
the signal session, i.e. lagged one session relative to the signal and two relative to the
fill. `regime_from_proxy` is already point-in-time for its own `t` (docstring: "uses only
`proxy` bars at indices <= `t`"), so the extra lag is strictly more conservative than the
engine's own convention and removes any dependence on a close that the signal session itself
produced.

```
label = regime_from_proxy(proxy, t-1)            # research/regime.py:61
side  = CALL  if label.trend is Trend.BEAR       # research/regime.py:20-23
        else PUT                                  # BULL or NEUTRAL
```

Trend only. `RegimeState.risk_off` (`research/regime.py:41-43`) is `BEAR or HIGH vol`; volume
of volatility does not tell direction, so it is deliberately not used to flip the side. There
is no "skip" branch: **every eligible cycle produces an attempted entry on one side or the
other**, which is what makes gate 6 reachable (map §5.3 defect 39).

**FACT, and it must be disclosed on every evaluation: the filter and the gate-6 census use
two different regime modules.** The filter uses `research/regime.py` (`Trend.BEAR` ⇔
`sma50 < sma200` **and** the 200-SMA not rising, `:67-78`). Gate 6's census uses
`backtest/regime.py::label_regimes` via `promotion.py:1205` (bear ⇔ the 200-session SMA
fell session-on-session, `backtest/regime.py:38-41`; `range_bound` ⇔ close within ±3% of that
SMA, `:22,59-62`). They can and will disagree on individual sessions. That disagreement is
harmless for this design — the mirror means trades exist on both sides regardless — but it is
**not** harmless to leave unstated, and it is recorded as **OQ-4**.

### 3.3 Strike selection

For side `S ∈ {PUT, CALL}`, underlying close `U_t` on session `t`, expiry `E`:

1. **Delta per candidate strike.** `greeks(s=U_t, k=K, t=(E−t)/365, r=0.04, sigma=σ_K,
   call=(S==CALL), q=q_t).delta` (`options/blackscholes.py:62`), where `σ_K` is inverted from
   that contract's own **print-eligible** print on `t` (`implied_vol`, `:93`) if it has one,
   else read off the §5.3 same-session surface. A strike with neither is **not selectable**.
1a. **Print eligibility at entry (NEW, rev 2).** A leg whose signal-session bar fails §2.4's
   print-eligibility floor (`volume ≥ 10`; `transactions ≥ 5` where non-null) may not set an IV
   and may not fill. If either selected leg is print-ineligible on `t`, the cycle is a
   **non-entry**, counted as `non_entry_thin_print`. Marking (never filling) may still fall
   through to the §5.3 surface for an *unselected* strike during the delta search. Rationale,
   pre-registered: a single-lot print struck hours before the underlying's close, inverted to an
   IV and then used to pick the short strike, size the width and measure the credit against the
   floor, is an asynchronous-pricing error of unbounded sign that no continuity fraction can
   detect. `volume ≥ 10` and `transactions ≥ 5` are **design judgements fixed now**, before the
   coverage summary exists, exactly as the gate-0 fractions are.
2. **Short strike.** Among OTM strikes with `|delta| ≤ max_short_delta`, pick the one whose
   `|delta|` is closest to `short_delta_target`; tie-break **further OTM** (the conservative
   side). If no strike is within `±0.05` of the target, **no entry**, counted.
3. **Long strike.** The listed strike closest to `K_short ∓ width_pct × U_t` (below for puts,
   above for calls), at least one listed increment away. If the realised width differs from
   `width_pct × U_t` by more than **50%**, **no entry**, counted. This is what stops a coarse
   strike ladder on a low-priced underlying from silently rewriting the width parameter.
4. **Credit floor.** Compute the net credit **at the §2.4(1a) adverse modelled fill**, not at
   the print. Require
   `net_credit / (|K_short − K_long| × shares_per_contract) ≥ min_credit_to_width`,
   else **no entry**, counted. Applying the floor to the realistic credit rather than the mid
   is a deliberate conservatism: it cannot be gamed by a generous spread constant. **Note the
   consequence for gate 4b, handled in §6.2c: doubling the spread constant changes which cycles
   clear this floor, so a naive 2× re-run evaluates a different, favourably re-selected
   population.**
5. **Deliverable integrity.** Both legs must have `shares_per_contract == 100`
   (`db/models/market.py:255`), else the contract is **refused** and counted (gate 0.h).
6. **Force-close priceability — no post-entry exclusion (REWRITTEN, rev 2).** Rev 1 excluded an
   entered structure from the evaluation entirely if a leg lacked a bar at force-close after
   deferral, following map §2.7 literally. **That is a survivorship channel and it is removed.**
   The condition is decidable only *after* the holding period and it correlates with the
   outcome: the wing that goes dark near expiry is the deep-ITM or far-OTM end, i.e.
   disproportionately the adverse cases. A ceiling on the *size* of the removed set says nothing
   about the *sign* of the bias, and on a design whose entire margin is ~0.02R a
   non-randomly-removed 10% is decisive.

   **Pre-registered rule.** Every entered structure stays in the evaluation. If a leg cannot be
   priced from a print on the realised force-close session after deferral has reached
   `expiry − 1`, that leg is marked at map §2.7's **conservative intrinsic floor** — the value
   that is worst for the seller: the short leg is bought back at no less than its intrinsic
   value and the long wing is valued at no more than `max(intrinsic, last_print)` with the
   adverse spread applied. The trade records `forced_intrinsic_mark = True`, and the fraction is
   a gate-8 evidence field with the ceiling in §8 (F6).

   **The map §2.7 exclusion is still computed — as a diagnostic, both ways.** The evaluation
   reports OOS expectancy on (a) all entered structures with the intrinsic floor (the
   **gating** figure) and (b) the map §2.7 subset with those structures excluded. **If the two
   disagree in sign, the result is dispositioned NO-SHIP** regardless of the gate verdicts,
   because the design's answer then depends on which of two defensible conventions was chosen.
   This is strictly more searching than either convention alone (R4), and it is a disclosed
   deviation from the map's operational wording, with the reason above.

   Exclusion from the evaluation is now reserved **strictly** for conditions decidable at or
   before entry: no bracketing, `shares_per_contract != 100`, no `q`, no delta match, width out
   of tolerance, credit floor, print-ineligible leg. Each is a **non-entry**, counted by reason.

### 3.4 Exits — all close-basis, and that is recorded in `fill_model`

Evaluated on each session close against the structure's **net buy-back premium** at the
adverse modelled fill, never against the underlying's price (map §3.3(b)):

| Rule | Trigger | Pre-registered value |
|---|---|---|
| Profit target | buy-back ≤ `(1 − profit_target_pct) × entry_credit` | `profit_target_pct = 0.50` |
| Stop | buy-back ≥ `stop_multiple × entry_credit` | `stop_multiple = 2.0` |
| Time stop | `DTE ≤ time_stop_dte` | `time_stop_dte = 7` |
| Force close | the `expiry − 1` session | hard boundary |

Whichever fires first. Execution defers to the next session on which **every** leg prints
(map §2.4(3)); `exit_deferred_sessions` is recorded per trade. A deferral that carries an exit
past the next cycle's signal session causes a `skipped_concurrency` (§3.1(5)).

**The stop is explicitly a close-basis stop (map §5.2a).** There is no intrabar option data
of any kind, so the equity engine's gap handling (`backtest/engine.py:154-184`, a stop gapped
through fills at the open) has no analogue and is **not** simulated. A spread that gaps
through both strikes realises max loss whatever `stop_multiple` said. **That branch is not a
footnote: it is the third outcome of §6.2's forecast and it dominates both the mean and the
variance that gate 4's CI consumes.** The string
`"close_basis_stop; no_intrabar_option_data; stop_not_a_live_order"` is carried in
`fill_model` on every trade so no reader can mistake it for a live stop order, and §8's
gate-8 fields measure how often it failed to bind.

**A structural note, pre-registered so it is not discovered later as a surprise.** The stop
is only a real stop while `stop_multiple × min_credit_to_width < 1`; at or above 1 the stop
level sits at or beyond max loss and can never bind first. At the baseline
`2.0 × 0.25 = 0.50` it binds at half the width, and at the grid's tight floor
`2.0 × 0.30 = 0.60`. The §4.4 OAT value `stop_multiple = 3.0` gives `3.0 × 0.30 = 0.90` and,
where a realised credit exceeds the floor and reaches `0.33 × width`, `3.0 × 0.33 ≈ 0.99` — an
**effectively inert stop**. This is expected, is reported as such, and is **not** a reason to
change the grid or the OAT table after the fact. It is also the reason `stop_multiple` is an
OAT parameter in rev 2 rather than a grid axis (§4.2).

### 3.5 P&L, R, and the clamp

```
R (dollars)  = |K_short − K_long| × shares_per_contract × contracts
               − net_credit_received + entry_costs          # known at entry
pnl_r        = realised_pnl_dollars / R
```

`net_credit_received` is the credit at the **adverse modelled fill** (§6.2a), so R is the
larger, conservative denominator.

Per map §2.6, the `−1` bound is **not** enforced by the fill model: four full modelled
spreads on a max-loss exit, and the §2.7 intrinsic floor, can each push realised loss past
`−1R`. §6.2's own arithmetic puts the baseline max-loss branch at **−1.046R** before clamping,
so the clamp is expected to engage on essentially every max-loss trade — that is a prediction,
made here, not a surprise. **Option 1 is pre-registered: clamp at `−1R`, set
`OptionTrade.r_clamped = True`, and report the clamp count and the unclamped `pnl_r` minimum
at gate 8.** Ceiling: a clamp rate above **10%** of trades is itself a finding (§8, F9) — it
means the cost model and the exit rule are inconsistent with the structure. Note the
interaction pre-registered in §6.2b: the clamp is why the max-loss branch enters the forecast
at exactly `−1.0000R` and not at the raw `−1.046R`.

`dte_at_entry` and `dte_at_exit` are recorded per trade, and the gate-1 walk-forward and
gate-5 sensitivity reports are **stratified by DTE bucket** (21-30 / 31-45), per map §2.2.

---

## 4. Parameters and the complete pre-registered sensitivity grid

### 4.1 Baseline parameters (the frozen `v0.1.0` spec)

FACT: these live in a frozen `params` dataclass interpolated into the spec's text fields,
exactly as `TrendParams` does (`src/signalforge/research/strategies/trend_continuation.py:21-30`).
They must **never** become `StrategySpec` fields: `persistence.spec_json_hash` hashes every
spec field except `{git_sha, status, notes}`, so adding one would change the hash of every
existing strategy and put both PAPER_APPROVED versions out of their own approval scope
(`src/signalforge/research/strategies/base.py:42-48` states exactly this).

FACT: `promotion.py:1171` passes `baseline_params=_asdict(strategy.params)` to the
sensitivity run, so **every grid axis must be a field of this dataclass**.

```python
@dataclass(frozen=True, slots=True)
class ShortVerticalParams:
    short_delta_target: float = 0.20    # AXIS 1
    max_short_delta:    float = 0.35    # AXIS 2  (rev 2: promoted from FIXED — map §3.2 Rule)
    width_pct:          float = 0.010   # AXIS 3 — fraction of the underlying close
    dte_target:         int   = 35      # AXIS 4
    profit_target_pct:  float = 0.50    # AXIS 5
    min_credit_to_width:float = 0.25    # AXIS 6
    stop_multiple:      float = 2.0     # FIXED — OAT only, see §4.2/§4.4
    time_stop_dte:      int   = 7       # FIXED — see §4.4
    dte_window_lo:      int   = 28      # FIXED — derived guard around dte_target
    dte_window_hi:      int   = 45      # FIXED
    delta_tolerance:    float = 0.05    # FIXED
    width_tolerance_pct:float = 0.50    # FIXED
    min_leg_volume:     int   = 10      # FIXED — print eligibility, §2.4
    min_leg_transactions: int = 5       # FIXED — print eligibility, §2.4
```

### 4.2 The grid — 96 points, and why it cannot have seven axes

**FACT that determines the shape of this grid:** `research/sensitivity.py:29`
`MAX_GRID_POINTS = 120`, enforced at `:178-181` by a `ValueError`
("grid has N points; cap is 120. Shrink the grid."), and `:178` builds the grid as the **full
Cartesian product** `itertools.product` of the axis value lists. The smallest full factorial
over seven axes is `2^7 = 128 > 120`. **Seven free axes are therefore arithmetically
impossible.** Six is the maximum, and only if at most one axis carries three values
(`3 × 2^5 = 96 ✓`; `3 × 3 × 2^4 = 144 ✗`). There are seven parameters that deserve an axis; the
cap forces exactly one of them into §4.4's OAT table, and rev 2 states below which one and why.

Pre-registered grid — **6 axes, 96 points**, complete and exhaustive:

| # | Axis | Values | Baseline | Why these values |
|---|---|---|---|---|
| 1 | `short_delta_target` | **0.12, 0.20, 0.30** | 0.20 — **centred**, two one-step neighbours | the parameter map §3.2 warns will be optimised along; it gets the only 3-value slot so both directions are probed |
| 2 | `max_short_delta` | **0.28, 0.35** | 0.35 | **rev 2: map §3.2's Rule honoured literally.** 0.28 binds on every `short_delta_target = 0.30` cell (truncating the delta search on the high side) and is inert elsewhere, so the axis measures the credit-floor/delta trade-off exactly as §3.2 asks. 0.25 was rejected: it would *empty* the 0.30-delta cells rather than bind on them (§4.3) |
| 3 | `width_pct` | 0.010, 0.020 | 0.010 | cost drag per R falls roughly as 1/width; 2% is the mechanism-motivated alternative and the §10 v0.2.0 lever |
| 4 | `dte_target` | 21, 35 | 35 | 21 is the thin-theta / high-gamma end. **45 is excluded by derivation, not preference** — §3.1(5) shows it produces ~zero trades under `options_max_structures_per_underlying = 1` |
| 5 | `profit_target_pct` | **0.50, 0.75** | 0.50 | **rev 2: the second value moved from 0.25 to 0.75.** 0.75 is the *tail-increasing* direction (later profit-take, more days of exposure per trade) and therefore the direction that makes gate 5's 60%-positive / 75%-neighbour thresholds **harder** to clear. 0.25 (fast recycle, less tail per trade) is the easier direction and moves to §4.4's OAT table |
| 6 | `min_credit_to_width` | **0.25, 0.30** | 0.25 | **rev 2: the second value moved from 0.20 to 0.30.** Rev 1 never tested the floor *above* baseline. 0.30 is the thinning direction — fewer, richer trades, more cells at risk of the 15-trade floor — and is therefore the harder side. 0.20 (loosening) is map §3.2's named failure mode and is reported one-at-a-time in §4.4 rather than offered as a grid cell a "best cell" reading could select |

`3 × 2 × 2 × 2 × 2 × 2 = 96 ≤ 120` ✓.
Baseline cell = `(0.20, 0.35, 0.010, 35, 0.50, 0.25)`.
One-step neighbours of the baseline (`sensitivity.py:105-118` `_is_neighbour`: differs on
exactly one axis by exactly one index): **7** — `short_delta ∈ {0.12, 0.30}` and one each on
axes 2-6. (Unchanged from rev 1's count; the axis membership changed, the count did not.)

**Which parameter the 120-cap forced out, and the direction of the error (rev 2).**
`stop_multiple` is the seventh parameter and it is the one moved to §4.4's OAT table
`{1.5, 2.0, 3.0}`. Reasons, in order: (i) §3.4 shows the high value is near-degenerate
(`3.0 × 0.30 = 0.90` of width, and effectively inert wherever a realised credit reaches
`0.33 × width`), so its grid cells carry least information per point; (ii) the stop's behaviour
is separately and directly measured at gate 8 — the count and fraction of trades closing worse
than `stop_multiple × credit` (map §5.2a) — and by F9, so removing it from the grid does not
remove it from the evidence; (iii) `max_short_delta` is a **Rule** in map §3.2, not a
preference, and a Rule outranks a discretionary axis. The OAT table reports 1.5 (a *tighter*
stop than baseline), which is the direction rev 1's grid never tested at all.

**Each cell additionally reports `skipped_concurrency`** (§3.1(5)), so that the residual
interaction between `dte_target` and cycle availability is visible per cell rather than folded
into the trade count.

**Every parameter that is not an axis is enumerated in §4.4.** Under R5, "abandoned variant"
is definable only as "a pre-registered cell that was not reported"; a parameter that is
neither an axis nor listed there would be invisible to both mechanisms, which is exactly what
R5 exists to prevent.

### 4.3 `max_short_delta` is now an axis — how rev 1's argument failed

Map §3.2 (`OPTIONS_EXECUTION_PROGRAM_MAP.md:785-787`) states as a **Rule**, verbatim:
"`min_credit_to_width` is always paired with a maximum short-strike delta … and **both are
sensitivity axes** so the ladder measures the trade-off rather than optimising along it."

Rev 1 held `max_short_delta` fixed at 0.35 and argued the axis would be inert. **The FACT half
of that argument is correct and is re-verified: `sensitivity.py:231-235` appends the reason
"axis … does not change OOS trade count or expectancy — the grid tested nothing on it",
`fragile = bool(reasons)` (`:266`), and gate 5 passes only on `not sens.fragile`
(`promotion.py:1188`); `_axis_movement` (`:120-153`) compares only points differing from the
baseline on that one axis. So an inert axis is a free gate-5 failure.** The *inference* was
wrong: 0.35 is inert only because rev 1 had itself capped `short_delta_target` at 0.30 with
`delta_tolerance = 0.05`, making `0.30 + 0.05 = 0.35` exactly. That shows an inert **value**
cannot be an axis endpoint; it does not show the **parameter** cannot be an axis.

Rev 2 therefore makes it axis 2 with a **binding** low value. The value is **0.28**, not 0.25:

- At `short_delta_target = 0.30` with `delta_tolerance = 0.05`, the selectable band is
  `|delta| ∈ [0.25, 0.35]`. A cap of **0.25** leaves only the exact boundary selectable and
  would **empty** all 16 of the `short_delta = 0.30` cells — 16 cells below
  `sensitivity_min_grid_trades = 15`, which pushes hard against §5.5's `n_evaluable ≥ 58` floor
  and converts an informative axis into a thin-cell generator.
- A cap of **0.28** truncates the band to `[0.25, 0.28]` — the search is genuinely constrained,
  a different strike is selected, the credit and the delta both move, and the cells stay
  populated. It is inert at `short_delta_target ∈ {0.12, 0.20}` (whose bands top out at 0.17 and
  0.25), which `_axis_movement` tolerates because it tests the axis globally, not per cell.

This is the trade-off ladder map §3.2 asks for: axis 1 moves the short delta, axis 6 moves the
credit floor, and axis 2 caps how far axis 1 may be pushed to satisfy axis 6. **No orchestrator
waiver against map §3.2 is now required**, and OQ-5 (rev 1) is withdrawn.

### 4.4 Parameters held fixed, and the disclosed one-at-a-time robustness table

These are **reported, non-gating** diagnostics run once at the baseline cell. They are listed
here so that every parameter of the design is either a gate-5 axis or a pre-registered
disclosed cell, and none is invisible.

| Parameter | Fixed at | OAT values reported | Reason it is not an axis |
|---|---|---|---|
| `stop_multiple` | 2.0 | **1.5, 2.0, 3.0** | the seventh axis is arithmetically impossible (§4.2); the high value is near-degenerate (§3.4) and the stop is measured directly at gate 8 and by F9. **1.5 is the tighter-stop direction rev 1 never tested** |
| `profit_target_pct` (second OAT value) | 0.50 (axis) | **0.25** | the *easier* direction (less tail exposure per trade); the grid carries the harder 0.75 |
| `min_credit_to_width` (second OAT value) | 0.25 (axis) | **0.20** | map §3.2's named failure mode (loosening the floor to reach for credit); reported, never offered as a selectable grid cell |
| `time_stop_dte` | 7 | 5, 7, 14 | binds only when neither target nor stop fires; also interacts with §3.1(5) concurrency, so it is reported with `skipped_concurrency` alongside |
| `dte_window_lo/hi` | 28 / 45 | (24,50), (28,45), (31,42) | a guard around `dte_target`, not an independent lever |
| `delta_tolerance` | 0.05 | 0.03, 0.05, 0.08 | a selection tolerance; widening it changes which strike is picked, not the design. **Reported jointly with axis 2**, since the two interact by construction |
| `width_tolerance_pct` | 0.50 | 0.35, 0.50 | a data-quality guard |
| `min_leg_volume` / `min_leg_transactions` | 10 / 5 | (5,3), (10,5), (25,10) | a data-eligibility floor (§2.4), not a strategy parameter; the OAT reports **entry-count sensitivity** and the change in the `\|close − vwap\|/close` distribution |
| `r` (risk-free) | 0.04 | 0.02, 0.04, 0.06 | an input assumption, not a strategy parameter; the OAT reports **delta-selection stability**, i.e. the fraction of cycles where the chosen short strike changes. **It is inside `options_config_hash` (§2.5) precisely because it is strike-shaping** |
| `contracts` | 1 | — | fixed by design in the backtest (map §3.1) |
| structure side rule | trend-mirror | (no alternative) | the alternative *is* gate 7b's mechanical benchmark (§7) |

**Interpretation rule, pre-registered.** If the best cell of the gate-5 grid is the
**highest-delta** cell (`short_delta_target = 0.30`), or the **loosest** cell on axis 2
(`max_short_delta = 0.35`), that is reported as the map §3.2 warning it is — the credit floor
being satisfied most easily where directional risk is highest — and it **does not move the
baseline**. Moving the baseline would be a behavioural change, i.e. a new version and a new
sealed look under R3, which the §10 budget does not fund.

---

## 5. Gate 0 sub-thresholds, fixed before the data exists

All the numbers below are pre-registered **now**, before I-O2 produces a coverage summary,
per map §1.5 and §7. Each derivation is a design judgement, explicitly not an empirical one.
Each is additive to gate 0 and therefore strictly *more* searching, which R4 permits.

### 5.1 Gate 0.c — cycle bracketing: **0.90**

**Threshold: ≥ 90% of (underlying, monthly cycle) pairs in the window must bracket the
structure on the relevant side on the signal session.** "Bracket" is defined precisely for a
vertical, which has no equity analogue:

1. listed strikes exist **both above and below** the `short_delta_target` strike on the traded
   side, so the delta search is not truncated by the edge of the stored chain; **and**
2. a listed strike exists at or beyond `K_short ∓ width_pct × U_t` within
   `width_tolerance_pct`, so the long wing can actually be placed; **and**
3. both selected contracts have `shares_per_contract == 100`; **and**
4. both selected contracts have a **print-eligible** bar on the signal session (§2.4).

**Derivation (design judgement, not empirical).** Below ~90% the strike-selection rule is
being silently rewritten by data availability in more than one cycle in ten — at which point
the reported `short_delta_target` is a label, not a parameter, and gate 5's delta axis is
measuring coverage rather than delta. Map §1.5 proposed 0.90; it is adopted with the
bracketing definition made structure-specific above. Clause 4 is a rev-2 addition and is
strictly more searching.

### 5.2 Gate 0.d — bar continuity: **0.80 evaluation-wide, and a 0.60 per-structure stratification**

**Threshold:** across the evaluation, ≥ **80%** of held `(structure, session)` pairs must have
a bar for **every** leg.

**Derivation.** Below 80% more than one session in five is marked by a model rather than a
print, which exceeds the synthetic-mark ceiling gate 8 enforces anyway.

**The 0.60 per-structure floor is a stratification and a disposition rule, not an exclusion
(REWRITTEN, rev 2).** Rev 1 excluded any individual structure below 60% continuity from the
evaluation. Realised held-session continuity is decidable only **after** the holding period and
correlates with the outcome, so excluding on it is the same survivorship channel §3.3(6)
removes, and a ceiling on the size of the removed set says nothing about the sign of its bias.

Pre-registered rule instead: every entered structure stays in. Structures whose realised
held-session continuity is below **0.60** are **flagged** (`thin_continuity = True`), counted,
and the evaluation reports OOS expectancy **with and without** them as a paired diagnostic.
**If the two disagree in sign, or if flagged structures exceed 15% of trades, the result is
dispositioned NO-SHIP** regardless of the gate verdicts — the same standing the pin-band rule
has in §5.4. Reporting both arms and binding on their disagreement is strictly more searching
than either the map's single evaluation-wide fraction or rev 1's exclusion (R4).

### 5.3 §2.4b same-session surface — N floor and the fit, both fixed

A non-printing leg may be **marked** (never filled — map §2.4(3)) from a same-session,
same-underlying surface. Pre-registered:

- **N floor: ≥ 5 contracts on that `(underlying, expiry, session)` printed with a
  print-eligible bar (§2.4), of which ≥ 3 are distinct strikes on the same side (put/call) as
  the contract being marked.** Below that there is no surface: the mark is `iv_unavailable`,
  no fill may occur from it, and at force close the §3.3(6) intrinsic floor applies. Map §2.4b
  proposed N = 5 with ≥3 distinct strikes; adopted, with "on the relevant side" made explicit
  because a put-side mark fitted entirely from calls is a different estimate, and with
  print-eligibility added (rev 2) so the surface is not fitted from single-lot prints.
- **The fit: ordinary least-squares quadratic in log-moneyness `ln(K/U_t)`, per expiry.** No
  spline, no free parameters chosen after the fact, no weighting scheme.
- **No extrapolation.** The mark is produced only if the target contract's log-moneyness lies
  **inside the convex hull** of the fitted contracts' log-moneyness. Outside it →
  `iv_unavailable`. This is the single rule that prevents the surface from inventing a price
  for the far OTM wing, which is the leg most likely to be dark and the one whose value most
  affects the spread's mark.
- **Term structure:** linear in total variance `σ²T` between the two bracketing expiries that
  each independently meet the N floor. No extrapolation beyond the nearest or farthest
  qualifying expiry.
- **Recorded per mark:** `iv_source = same_session_surface`, the contract count used, and the
  fit residual. Gate 8 reports the synthetic-**mark** fraction (there is no synthetic *fill*
  fraction; §2.4(3) forbids them).
- **Realised volatility is never a fallback** (map §2.4b). If a run ever falls back to it, the
  run is void.

### 5.4 Pin band: **±0.5% of the underlying, or ±1 listed strike increment, whichever is narrower**

Applied to the **short** strike on the force-close session. If the underlying's close on that
session lies inside the band, `pin_risk_flag = True`. Map §2.7's hypothesis, adopted; "whichever
is narrower" means the band never widens just because an underlying has a coarse strike ladder.

**Pre-registered consequence, and it is a hard disposition rule, not a report field.** Gate 8
reports the pinned fraction and its separate R distribution. **If pinned trades exceed 15% of
trades, or if excluding pinned trades drops OOS expectancy to or below the gate-3 threshold
(`min_net_expectancy_r = 0.0`, `config/research.py:102`), the result is dispositioned NO-SHIP
regardless of the gate verdicts.** A strategy whose edge concentrates in trades settled inside
the pin band has demonstrated a modelling artefact, not an edge.

### 5.5 A gate-5 evaluability floor — a pre-registered addition

FACT (`research/sensitivity.py:218-223`): `pos_frac = len(positive) / len(evaluable)`, where
`evaluable` is the subset of grid points with `n_trades ≥ min_trades` (15). The denominator is
**evaluable points, not all points**. The only evaluability guard is
`if len(evaluable) < 3` (`sensitivity.py:236`). So a grid where 92 of 96 points are too thin can still report
"100% positive" off four cells.

**Pre-registered addition: gate 5 is read as failing on evaluability unless
`n_evaluable ≥ 58` (= 60% of 96).** `n_evaluable` is already computed and surfaced
(`sensitivity.py:51`; `promotion.py:1190`), so this is a reporting rule this
pre-registration binds itself to, not a threshold change. It is strictly more searching (R4).

The cells most at risk of falling below 15 trades are enumerated **in advance**, so that a
thin corner is a prediction rather than an excuse. Under rev 2's grid that is
`short_delta_target = 0.12` combined with `min_credit_to_width = 0.30` — a 0.12-delta short
essentially never clears a 30%-of-width credit floor — across both values of axes 2, 3, 4 and 5:
**16 of the 96 cells**, leaving a predicted `n_evaluable ≈ 80`, comfortably above the floor.
(Rev 1 predicted 4 thin cells; rev 2 predicts more because axis 6's second value moved to the
thinning side. That is the intended direction: the grid is harder, and the prediction is stated
before the run.) The `max_short_delta = 0.28` cells are **not** in the at-risk list, which is
precisely why 0.28 and not 0.25 was chosen (§4.3).

---

## 6. Gate-by-gate forecast, with required n

Every number in this section is arithmetic on pre-registered parameters plus **assumed** win
rates, max-loss frequencies and intra-cluster correlations. Those assumptions are **stated in
advance to make the design falsifiable**, not measurements — nothing has been measured. Same
caveat the map's Appendix B attaches to its own §5.3 illustration.

### 6.1 The R arithmetic of this structure (exact, not assumed)

Write `W = |K_short − K_long| × 100` (dollars of width) and `c/W = min_credit_to_width`,
where **`c` is the net credit at the §2.4(1a) adverse modelled fill** (§3.3(4)). At the
baseline floor `c/W = 0.25`, ignoring commissions:

```
adverse entry credit C = 0.25 W
R                      = W − C            = 0.75 W
max gain               = +C/R             = +0.333 R
profit target 50%: P&L = +0.5C            = +0.125 W = +0.1667 R
stop at 2×C      : P&L = C − 2C           = −0.25 W  = −0.3333 R
max loss         : P&L = C − W            = −0.75 W  = −1.0000 R
```

So the **gross** payoff profile is a 1:2 reward-to-risk bet in R terms, and the break-even hit
rate before costs and before any max-loss branch is `0.3333 / (0.1667 + 0.3333) = 66.7%`.

### 6.2 Costs, the three-outcome payoff, and the break-even hit rate

#### 6.2a The representative structure, derived rather than asserted (REWRITTEN, rev 2)

Rev 1 used "short-leg print ~$1.50, long-wing print ~$0.60, `W = $500`, `C = $125`". That is
**internally inconsistent**: `$1.50 − $0.60 = $0.90/share = $90` of credit, not $125, so the
spread cost was computed off one structure and R off another. It also ignored §2.4's own
absolute spread floor — `0.03 × $0.60 = $0.018` is below the pre-registered `max(0.02, …)`
floor, and `0.06 × $0.60 = $0.036` is below `max(0.04, …)` — on exactly the leg the floor was
written for, the cheap far-OTM long wing. And it applied the floor to a print credit rather
than to §3.3(4)'s **adverse** credit, so the structure it described would have produced **no
entry**.

Rev 2 derives the representative structure from the design's own rules. Take the baseline
`width_pct = 0.010` on an underlying at `U = $500`, so the strike distance is $5.00 and
`W = $500`. Leg prints on the signal session:

| | short leg | long wing |
|---|---|---|
| print | **$1.95** | **$0.62** |
| baseline spread `max(0.02, 0.03 × print)` | $0.0585 | **$0.0200** ← floor binds |
| 2× spread `max(0.04, 0.06 × print)` | $0.1170 | **$0.0400** ← floor binds |

- **Adverse entry credit** `C = 100 × [(1.95 − 0.0585) − (0.62 + 0.0200)] = $125.15`
  → `C/W = 0.2503 ≥ min_credit_to_width = 0.25` ✓ **this structure actually enters.**
- **Entry commissions** `$1.60`; `R = W − C + entry_costs = 500 − 125.15 + 1.60 = $376.45`.
- **Round-trip friction** `F = 2 × 100 × (0.0585 + 0.0200) + $3.20 = $18.90 = 0.0502 R`
  (rev 1 stated 0.042 R — a ~20% understatement).
- **At 2×:** `F₂ = 2 × 100 × (0.1170 + 0.0400) + $3.20 = $34.60 = 0.0919 R`
  (rev 1 stated 0.076 R).

**Accounting convention, stated because it matters (rev 2).** §3.4's exit triggers are
evaluated on the *adverse* buy-back, so the two exit crossings are already embedded in the
trigger level. This forecast nevertheless charges the **full four crossings** against a credit
that is already net of the two entry crossings. That is a deliberate, disclosed over-charge of
about **0.042 R**; it is kept because R1/R10 require cost conservatism and because an
over-stated cost can only make the design look worse, never better. Any reader reconciling
§6.2 against a future engine output should expect the engine to be *kinder* by roughly that
amount, not harsher.

#### 6.2b The three-outcome payoff (NEW, rev 2)

Rev 1 modelled two outcomes — target win and stopped loss — and derived its standard deviation
from that binary assumption. **That is the exact hole map §5.2a (`:1128-1130`) names.** §3.4 of
this document concedes that a spread gapping through both strikes realises max loss whatever
`stop_multiple` said, and §3.5 concedes losses can exceed `−1R` before clamping; neither the
max-loss branch nor its variance appeared in the forecast. For a short-vol payoff the left tail
is precisely what drives both the mean and the sd that gate 4's CI consumes, so rev 1's
required-n table was **anti-conservative in both terms**.

Pre-registered three-outcome forecast. Under gate-4b **form (a)** (§6.2c), entry selection and
trigger levels are frozen at the baseline and only the friction is re-priced, so the two
columns are the same trades:

| Outcome | Baseline | 2× spread |
|---|---|---|
| Target win `w` (`+0.5C − F`) | **+0.1160 R** | **+0.0743 R** |
| Stopped loss `l` (`−C − F`) | **−0.3827 R** | **−0.4244 R** |
| Max loss `m` (`C − W − F`, raw) | −1.0460 R → **clamped −1.0000 R** | −1.0877 R → **clamped −1.0000 R** |

`w − l = 1.5 C / R = 0.4987` in both columns, by construction.

Break-even target-win rate given an assumed max-loss frequency `p_m`:

```
p_w*  =  [ −l + p_m ( l − m ) ] / ( w − l )
```

| assumed `p_m` | baseline break-even `p_w*` | 2× break-even `p_w*` |
|---|---|---|
| 0% (rev 1's implicit assumption) | 76.7% | 85.1% |
| 1% | 78.0% | 86.3% |
| **3% — the pre-registered central assumption** | **80.4%** | **88.6%** |
| 5% | 82.9% | 90.9% |
| 8% | 86.6% | 94.3% |

**Why 3% is the central assumption, fixed now.** Max loss on this structure requires the
underlying to close through *both* strikes — the short strike is ~2-4% OTM at
`short_delta_target = 0.20` and the wing is a further 1% of the underlying beyond it — with the
close-basis stop having failed to bind on any prior session. That is a gap of roughly 3-5% in a
single session, or a sustained move that the 2×-credit stop rode through. 1% and 5% bracket it;
8% is the stress row. **F8 is keyed to the 3% row** (§8).

**This is the single most important pre-registered number in the document**, and rev 2 moves it
materially: rev 1 said 75.1% / 81.8%; the corrected, three-outcome numbers are
**80.4% / 88.6%** at the central assumption. A 0.20-delta short put has roughly a 20% chance of
finishing ITM, but a 50% profit target closes most trades long before expiry, so target-win
rates in the 80-92% band are the plausible range. The strategy is therefore forecast to sit
**very close to, and quite possibly below, break-even at the 2× spread**, and the whole
question is which side of 88.6% the realised target-win rate lands on.

#### 6.2c Gate 4b is run in two forms, and only one of them gates (NEW, rev 2)

FACT about this design: §3.3(4) applies `min_credit_to_width` to the **adverse modelled
credit** and §3.4 evaluates the profit target and the stop against the **adverse modelled
buy-back**. Doubling the spread constant therefore changes *which* cycles are entered (only
credit-richer ones clear the floor) and *when* they exit (stops fire earlier, targets later).
The §6.2a structure demonstrates it exactly: at 2× its adverse credit falls to
`100 × [(1.95 − 0.117) − (0.62 + 0.040)] = $117.30 = 0.2346 W`, **below the 0.25 floor — it
does not enter at all.** A naive 2× re-run therefore measures a favourably re-selected
subsample, not the same trades under worse costs, which is weaker than map §5.2's
"gates 2/3/4 clear at 2×" (`:1079-1080`) intends.

**Pre-registered rule.** Gate 4b is run in two forms and both are reported:

- **(a) Re-priced, selection frozen — THE GATING FORM.** The baseline-selected trade set, with
  entry decisions, strike choices, R denominators and exit trigger levels all frozen at their
  baseline values, re-priced with the 2× friction. Same trades, worse costs. **Gate 4b passes
  only if form (a) passes.** §6.2b's 2× column and §6.3's 2× columns are form (a).
- **(b) Full re-selection at 2× — a reported diagnostic.** The strategy re-run end to end with
  the 2× constant, so the credit floor and the exit triggers re-select. Its entry count is
  reported next to the baseline's; a large drop is itself evidence about how much of the
  baseline population is marginal on credit.

If (a) and (b) disagree in sign, that is disclosed at gate 8 and is a NO-SHIP input.

### 6.3 Gate 4 — the deciding gate, under both iid and clustered variance

Gate 4 (`config/research.py:105` `min_bootstrap_ci_low_r = 0.02`, `ci_low` read at
`promotion.py:1137`, checked at `:1138`) is approximately `mean − 1.96·sd/√n > 0.02`, so
`n > (1.96·sd / (mean − 0.02))²`. Rev 2 computes `mean` and `sd` from the **three-outcome**
distribution of §6.2b rather than the two-outcome one, which raises both the required `n` and
the break-even.

#### 6.3a Required `n_OOS` under iid variance

Required out-of-sample trades to clear `min_bootstrap_ci_low_r = 0.02` at 95%:

| target-win rate `p_w` | baseline, `p_m` = 1% | baseline, **3%** | baseline, 5% | 2× (form a), `p_m` = 1% | 2× (form a), **3%** |
|---|---|---|---|---|---|
| 0.85 | ~691 | ~31,000 | mean < 0.02 — never | never | never |
| 0.88 | ~151 | ~661 | ~9,740 | never | never |
| 0.90 | ~76 | ~252 | ~1,120 | mean < 0.02 — never | never |
| 0.92 | ~43 | ~126 | ~390 | ~1,375 | mean < 0.02 — never |
| 0.94 | ~25 | ~72 | ~189 | ~251 | ~3,020 |
| 0.96 | ~15 | ~45 | ~108 | ~86 | ~470 |

Rev 1's equivalent table read 140 / 97 / 51 / 29 at `p` = 0.85 / 0.86 / 0.88 / 0.90 on the
baseline. Those figures were produced by a two-outcome sd and are **underestimates by roughly
an order of magnitude** at the plausible `p_m`.

#### 6.3b The clustered variant, and why it binds (NEW, rev 2)

FACT: gate 4 reads `full.oos_ci` (`promotion.py:1137`), which comes from `bootstrap_ci`
(`src/signalforge/backtest/montecarlo.py:15-33`) — an **iid** resample of the bare per-trade R
sequence (`rng.integers(0, arr.size, size=(n_resamples, arr.size))`). This design writes up to
14 short-vol structures on the **same monthly expiry**, all on correlated large-cap/index
underlyings, all short the same volatility. The independent unit is the **cycle-month**, not the
trade. §8 of rev 1 already conceded that "overlapping monthly cycles … are MORE correlated than
the equity trades whose iid violation the completion map already flags as unresolved" — and then
relegated the clustered bootstrap to an "alongside" disclosure while the iid CI did the gating.
**A document cannot name a method invalid for its population and then let that method decide.**

Rev 2 makes it bind. R4 forbids lowering a gate; **adding** a condition is strictly more
searching, which is what §5.2, §5.4 and §5.5 already do elsewhere. D5 cannot change frozen
config, so this is pre-registered as a **disposition rule of the same standing as gate 4**:

> **F11 (new, §8).** The clustered-bootstrap CI low must **also** exceed `0.02 R`. Clusters are
> pre-declared **now** as the **(cycle-month)**, pooled across underlyings — i.e. all structures
> entered on the same monthly expiry cycle resample together. The code's iid gate-4 verdict is
> reported unchanged; **if the clustered CI low is ≤ 0.02 R the disposition is NO-SHIP whatever
> gate 4 says.** The realised design effect is reported with it.

For planning, the design effect of a one-stage cluster sample is `DEFF = 1 + (m̄ − 1)ρ` with
`m̄ = 14` structures per cycle-month. Required **raw** `n_OOS` = iid requirement × `DEFF`:

| ρ (intra-cycle) | DEFF | baseline `p_w` = 0.92, `p_m` = 3% (126 iid) | baseline 0.94 / 3% (72) | 2× 0.94 / 1% (251) | 2× 0.96 / 1% (86) |
|---|---|---|---|---|---|
| 0.00 | 1.00 | 126 | 72 | 251 | 86 |
| 0.05 | 1.65 | 208 | 119 | 414 | 142 |
| 0.15 | 2.95 | 372 | 212 | 740 | 254 |
| 0.30 | 4.90 | 617 | 353 | 1,230 | 421 |

#### 6.3c What must be true for this design to pass — stated before any data exists

Available evidence at the pre-registered population (§2.2, §2.3): 14 underlyings × 84
pre-sealed cycle-months = **1,176 candidate cycles**; at the 55% net entry assumption
(§2.2's ladder governs it) **≈ 647 pre-sealed entries**; the frozen 40% OOS split
(`backtest_runner.py:29`) gives **≈ 259 OOS trades** over **≈ 34 OOS cycle-months**.

Reading 259 against the tables above, the pre-registered forecast is:

> **The design closes gate 4 and gate 4b only if all three of the following hold:
> a realised max-loss frequency `p_m ≲ 1%`, a realised target-win rate `p_w ≳ 0.96`, and a
> realised intra-cycle correlation `ρ ≲ 0.15`.** At `p_m = 3%` the 2× arm needs ~470 OOS trades
> even at `ρ = 0` and ~2,300 at `ρ = 0.30`; neither is obtainable. At `ρ = 0.30` no cell of the
> 2× column closes on any history this program can buy.

That is a hard, falsifiable statement made before any return series exists, and it is the
reason §10's null option is described there as the **expected** outcome rather than a courtesy.
It also fixes the planning rule: **maximise independent cycle-months (years) first; the
underlying count is set by the storage cap and by coverage, not by raw `n`.** Rev 1 had this
backwards — its ladder ("3 pre-sealed years → ≥18 underlyings; 5 years → ≥11") traded years for
underlyings, which under clustering buys almost nothing.

**Storage cross-check (FACT + arithmetic), corrected.** 14 underlyings × 96 cycles ×
~30 contracts × ~45 sessions ≈ **1,814,400 bars**, inside decision 6's raised
`backfill_max_total_bars` of 2,000,000 with **9.3% headroom**, and well outside the shipped
default of 200,000 (`config/research.py:216`). Two rev-1 errors are corrected here: rev 1's own
plan (18 × 5 years) was **1.46M bars, not the 1.17M printed** — it used 48 cycles (4 years)
where §2.3 pre-registered 5 — and 18 underlyings × 8 years would be 2.33M, which does **not**
fit, which is the arithmetic that sets the count at 14.

### 6.4 The other gates

| Gate | Threshold (frozen) | Forecast at 14 underlyings × 7 pre-sealed years (~647 entries, ~259 OOS, ~34 OOS cycle-months) |
|---|---|---|
| **0** (`promotion.py:954`) | pre-sealed ≥ 350 d + sealed 365 d | ✓ by construction at 8 years. Sub-checks 0.a-0.h per §5; run today it fails 0.b/0.c/0.d/0.e/0.g simultaneously and that is correct. |
| **1** `rolling_walkforward` (`:1075-1106`) | ≥15 trades **and** positive expectancy in ≥2 of 4 folds | counts clear with margin (~162/fold ≫ 15). The binding half is the **sign** in 2 of 4 folds — an edge question. A short-vol book losing a whole fold to one vol spike is the realistic failure mode, and over 7 years the window contains at least three such episodes. ⚠ |
| **2** `min_oos_trades` (`:1111`, threshold 30, `config/research.py:99`) | ≥30 OOS | ~259 ≥ 30, ~8.6× margin ✓ on raw trades. **In cluster units it is ~34 — a 1.1× margin**, which is the honest reading (§6.3b). ⚠ |
| **3** `net_expectancy` (`:1124`, `>0.0R`, `research.py:102`) | OOS expectancy > 0 net of costs | passes iff the target-win rate exceeds **80.4%** at `p_m` = 3% (§6.2b) ⚠ |
| **4** `bootstrap_ci` (`:1137-1138`, `>+0.02R`, `research.py:105`) | 95% CI low > 0.02R | §6.3a table ⚠⚠ **the deciding gate**, and **F11 adds the clustered CI as a binding disposition** |
| **4b** dual spread (map §5.2, new) | gates 2/3/4 clear at baseline **and** 2×, in **form (a)** (§6.2c) | passes iff the target-win rate exceeds ~**0.96** with `p_m ≲ 1%` ⚠⚠ |
| **5** `parameter_sensitivity` (`:1154-1197`) | ≥60% of evaluable points positive, ≥75% of one-step neighbours positive, ≥15 trades/point, no inert axis; plus §5.5's `n_evaluable ≥ 58` | 96 points; the 16 enumerated thin cells (§5.5) leave a predicted `n_evaluable ≈ 80`. Note the compute cost: 96 full pre-sealed re-runs over 14 underlyings × 8 years — an I-O4 engineering input. ⚠ |
| **6** `regime_coverage` (`:1203-1247`, 3 of 3 buckets × ≥10, `research.py:112-113`) | bull/bear/range each ≥10 | reachable **only because of the call-side mirror** (map §5.3 defect 39). The bear bucket is `backtest/regime.py`'s falling-200-SMA label (`:38-41`), rare in a rising market. An 8-year window ending 2026-09 starts ~2018-09 and therefore contains **2018Q4, 2020 and 2022** — a second, independent reason years beat underlyings. ✓ likelier than at rev 1's 5 years. |
| **6 + vol** (map §5.2 extension) | binary joint trend×vol: **≥10 in each marginal vol bucket, ≥5 in each of the 6 joint cells** | adopted in the binary form; `bear_lowvol` is rare by construction and is the cell that will bind. The tercile form is **not** adopted — map §5.3 shows it will not close and would be quietly abandoned the first time it bound. |
| **7** `benchmark_comparison` (`:1250-1280`, `require_beat_benchmark_sharpe`, `research.py:120`) | strategy Sharpe > SPY buy-and-hold Sharpe, **all pre-sealed trades** (`:1253`) | genuinely uncertain and a plausible failure. **Gate 7 is kept, not replaced** (map §5.2; replacing it would be an R4 violation). ⚠ |
| **7b** structure benchmark (map §5.2, new) | strategy Sharpe > a mechanical version of the **same** structure | see §7 ⚠ |
| **8** `data_quality_and_leakage` (`:1290-1318`) | `validate_daily` pass + leakage self-check, plus every options field of §8 | the disclosure surface, not a hurdle — except where §8's pre-registered ceilings bite |
| **9** `sealed_final_test` (`:1345-1380`, ≥10 trades, expectancy ≥0, `research.py:128-129`) | one-time, immutable per `(version, snapshot)` | **≈ 92 sealed-year entries** (14 underlyings × 12 cycles × 55%; the 40% OOS split does **not** apply to the sealed year); ≥10 ✓ on counts. In cluster units that is **12** cycle-months. Expectancy sign is the question. *(Rev 1 printed a stale "~48" here and then corrected itself to ~118 in the same sentence; both are superseded.)* |
| **10** `live_paper_probation` (`:1382-1392`) | health monitor enabled | see §9.2 — the paper stream is a **different population** from the backtest (decision 13), and §9.1 now states a hard precondition without which gate-10 evidence is **void** |

---

## 7. Gate 7b — the mechanical benchmark, specified now

Gate 7b asks whether the *signal* adds anything over mechanical premium harvest. It is
specified before any result exists so it cannot be chosen to flatter the outcome.

**The mechanical benchmark for this version:** the identical structure, identical underlyings,
identical window, identical `OptionCostModel`, identical fill, print-eligibility, marking and
non-entry rules, with

- `short_delta_target = 0.20`, `max_short_delta = 0.35`, `width_pct = 0.010`,
  `dte_target = 35`, `profit_target_pct = 0.50`, `stop_multiple = 2.0`, `time_stop_dte = 7`,
  `min_credit_to_width = 0.25` (the same baseline), **and**
- **no regime filter: always the put side**, every cycle.

So the benchmark differs from the strategy in exactly one thing — the regime filter — which is
the only thing the strategy claims. **Both gate 7 (vs SPY buy-and-hold) and gate 7b must
pass.** R4 permits adding 7b; it does not permit dropping 7.

---

## 8. Falsification criteria (R10), and the gate-8 evidence fields

Each criterion names a **pre-sealed** observation that kills the design. Sealed numbers may
inform disposition only, never design (R1).

| # | Killing observation | Consequence |
|---|---|---|
| **F1** | OOS expectancy ≤ 0 at the baseline spread | dead. No parameter change is attempted in response. |
| **F2** | OOS expectancy > 0 at baseline but ≤ 0 (or CI low ≤ 0.02R) at **2× spread, form (a)** (§6.2c) | dead as **COST-FRAGILE**. The response is the null option or more data — **never** a smaller spread constant. |
| **F3** | Expectancy positive overall but negative in the **bear** trend bucket **and** negative in the **highvol** bucket | dead. That is the short-vol failure signature: an edge that exists only in quiet rising markets is the regime the structure is least able to survive. |
| **F4** | Expectancy positive only with pinned trades included (§5.4), or pinned fraction > 15% | dead — modelling artefact, regardless of gate verdicts. |
| **F5** | Gate 7b fails: the regime-filtered version does not beat the always-put mechanical version on Sharpe | dead **as specified**. The mechanical version would be a different version costing a look, and §10's budget does not fund it. |
| **F6** | > 25% of eligible cycles are non-entries for a missing or print-ineligible leg bar, **or** > 10% of entered structures carry a `forced_intrinsic_mark` at force close (§3.3(6)), **or** the paired with/without-exclusion diagnostic of §3.3(6) disagrees in sign | dead as specified. The fix is a narrower, more liquid underlying set — a **data** decision for D1 — not a parameter change. *(Rev 2: the third clause replaces rev 1's exclusion ceiling, which bounded the size of a non-randomly-removed set without bounding the sign of its bias.)* |
| **F7** | `n_evaluable < 58` of 96 grid points (§5.5) | gate 5 fails on evaluability; reported as such, not as a pass on a thin grid. |
| **F8** | **Pre-sealed 2× (form a) mean R ≤ 0.02R** — equivalently, at the central `p_m` = 3%, a pre-sealed target-win rate **< 0.89** | **stop before the sealed look is spent.** §6.2b puts the 2× break-even at **88.6%** at `p_m` = 3%, so below 0.89 the arithmetic says gate 4b cannot clear at any `n`, and gate 4b is required. **The test is run on the *realised* three-outcome mix** — target-win rate, stop rate and max-loss rate — through §6.2b's break-even formula; 0.89 is the scalar value that formula returns at the central assumption, published so the tripwire is legible in advance. Abandoning here **saves** a look and is the cheapest possible R5 disclosure. *(Rev 1 set this at 0.78, which sat below its own — already understated — baseline break-even and would have let through a design that rev 1's own corrected arithmetic says cannot clear gate 3.)* |
| **F9** | `r_clamped` rate > 10% of trades, **or** > 20% of losing trades close worse than `stop_multiple × credit` | the cost model and the exit rule are inconsistent with the structure (map §2.6, §5.2a). Reported at gate 8 and treated as NO-SHIP. Note §3.5/§6.2b predict in advance that the max-loss branch clamps at −1.046R, so the clamp rate is expected to track `p_m` closely; a clamp rate far above the realised max-loss rate means something *else* is breaching the bound. |
| **F10** | Any evaluation in which a synthetic mark set a **fill** price, or realised volatility was used as an IV fallback | the run is **void**, not a failure — re-run after the defect is fixed. |
| **F11** (new, rev 2) | **Clustered-bootstrap CI low ≤ 0.02 R**, clusters pre-declared as the **(cycle-month)** pooled across underlyings | **NO-SHIP regardless of the iid gate-4 verdict** (§6.3b). Adding a condition is strictly more searching and does not touch a frozen threshold (R4). The realised design effect `DEFF` and the realised intra-cycle ρ are reported with it. |
| **F12** (new, rev 2) | The §5.2 paired diagnostic disagrees in sign (expectancy with vs without `thin_continuity` structures), or `thin_continuity` structures exceed 15% of trades | NO-SHIP. Same standing as F4. |
| **F13** (new, rev 2) | The §8 staleness diagnostic breaches its ceiling: **median `\|close − vwap\| / close` above 0.10 across entered legs, or more than 20% of entered legs above 0.25** | the evaluation is declared **non-representative** — the prints driving IV, strike selection and the credit are too far from the session's volume-weighted trade to support a delta-targeted design. Reported, not repaired by a parameter change. |

**Gate 8 evidence fields, pre-registered (map §5.2, §5.2a, §2.6, §2.7).** Every options
evaluation records: options corporate-action exclusions (D7); the
`shares_per_contract != 100` refusal count (gate 0.h); the synthetic-**mark** fraction and its
ceiling; the **non-entry count by reason** — no bracket / no delta match / width out of
tolerance / credit floor / missing leg bar / **print-ineligible leg** / no `q` / **skipped
concurrency** (§3.1(5)) / cycle outside the DTE window; the exit-deferral distribution; the
`r_clamped` count and the **unclamped** `pnl_r` minimum; the **`forced_intrinsic_mark`
fraction** and the paired with/without-exclusion expectancy of §3.3(6); the
**`thin_continuity` fraction** and the paired expectancy of §5.2; the pinned-trade fraction and
its separate R distribution; the count and fraction of trades closing worse than
`stop_multiple × credit`; the **realised three-outcome mix** (target win / stopped loss / max
loss) that §6.2b's forecast is scored against; the **`|close − vwap| / close` distribution per
entered leg** and the **`transactions`-null fraction** (§2.4, F13); the `iv_source` /
`q_source` / `greeks_source` mix; the `fill_model` string including `close_basis_stop` **and
`iv_print_stale_asynchronous_to_underlying_close`**; the verbatim `PromotionThresholds` payload
and `options_config_hash` (§2.5); the American-exercise/early-assignment approximation disclosed
**with its direction of bias** (in the strategy's favour — it removes the tail where a short leg
is assigned at the worst moment); "NBBO unavailable under the active entitlement for options
**and** equities — spread is modelled, not observed"; the gate-4b form (a) and form (b) results
side by side (§6.2c); and the **clustered bootstrap** CI with its `DEFF` and ρ, which under F11
is a **binding disposition input**, not a footnote.

---

## 9. What a pass does and does not authorise

### 9.1 Nothing is armed — and one hard precondition on gate-10 evidence

FACT: `StrategyStatus` has exactly three values — EXPERIMENTAL, PAPER_APPROVED, DISABLED — and
there is no ARMED state anywhere (map §0.1 B2). A gate-ladder pass writes PAPER_APPROVED and
an approved scope. It authorises **no order**. Decision 10 additionally requires ≥20 closed
paper trades with non-negative expectancy under the health monitor before any arming, and
operator decisions 2 (broker), 3 (approval level) and 4 (capital limits) are unresolved. The
kill switch blocks opening and never blocks closing; nothing is armed by default; no LLM ever
decides an order.

FACT and a standing hazard this design inherits — **re-verified and quantified in rev 2**:
`accept_candidate` (`src/signalforge/paper/ledger.py:129-141`) calls only `ensure_not_engaged()`.
There is **no quality-gate, status, approved-scope or instrument-type check**. It then sizes with
equity share arithmetic — `per_share_risk = abs(entry_ref − stop)`,
`shares = risk_dollars / per_share_risk`, `_NOMINAL_SPREAD_BPS = 5.0` (`ledger.py:50,149-166`) —
and `mark_to_market` (`ledger.py:266`) values the position off the **underlying** instrument.
The fail-closed instrument-type guard exists **only** inside `assert_auto_simulate_allowed`
(`ledger.py:474`, the `("stock", "etf")` check at `:496-500`), which the manual CLI path does
not traverse. The moment D1/D3 creates `option_structure` Instruments and options Candidates, a
single manual CLI accept writes a `PaperTrade` with provably wrong sizing, spread and marks —
and `PaperTrade` rows feed gate 10 (`promotion.py:1382-1392`).

Rev 1 answered this with a posture ("nothing in this pre-registration may be read as treating
[an ACCEPTED PaperTrade] as authorisation"). A posture is not a control. **Pre-registered hard
precondition, rev 2:**

> **No options `PaperTrade` may be created, and any gate-10 evidence derived from one is VOID,
> until `accept_candidate` itself refuses every instrument whose type is not `stock`/`etf` —
> fail-closed at the shared entry point, not only in the auto path.** The refusal is a named
> counter in the paper ledger's evidence. This is a precondition on gate 10 only; it blocks
> nothing in Phase D or in I-O1…I-O5.

Two further guards §9.2 and §3.1(5) assume exist are hereby **assigned to D3 by name**, with the
counters they must emit, because neither exists today:

1. **Per-structure R cap.** A paper guard that refuses any structure whose entry-time R exceeds
   `options_per_structure_max_loss` (decision 4: $250), emitting `refused_r_cap`. **Owner: D3.**
   No code implements this; rev 1 named no owner.
2. **Underlying-keyed concurrency.** A paper guard enforcing
   `options_max_structures_per_underlying = 1` keyed on the **underlying**, emitting
   `refused_concurrency`. FACT: the existing `auto_simulate.py:108-120,164-171` check is keyed
   on `instrument_id` and would not catch a multi-leg structure (map §3.6). **Owner: D3.**

**An ACCEPTED `PaperTrade` is not evidence that anything was gated**, and nothing in this
pre-registration may be read as treating one as authorisation.

### 9.2 The paper stream is a different population — and the operator limit does not fit the baseline

Decision 13: a **separate options paper account, initial $25,000 SIMULATED**. Decision 4:
per-structure max loss **$250**.

Pre-registered arithmetic, purely parametric (no price is asserted):
`R = width_pct × U × 100 − credit ≈ 0.75 × width_pct × U × 100`, so at the baseline
`width_pct = 0.010` the structure's max loss is **`R ≈ 0.75 × U` dollars**, where `U` is the
underlying's price. Therefore:

| Underlying price `U` | R at `width_pct = 0.010` | fits the $250 cap? |
|---|---|---|
| $100 | ~$75 | yes |
| $250 | ~$188 | yes |
| $333 | ~$250 | at the limit |
| $500 | ~$375 | **no** |
| $700 | ~$525 | **no** |

**Any underlying priced above ~$333 fails the $250 per-structure cap at the baseline width**,
and the set of §2.2 is chosen for liquidity, which correlates with exactly that end of the
price range. **The gate-10 paper stream would therefore trade a materially different, and
possibly empty, subset of the structure that gates 1-9 certify.** (Note §6.2a's representative
structure is at `U = $500`, R = $376 — it is one of the refusals.)

This is the §3.1 collateral reconciliation the map demanded be made explicitly rather than
discovered later. Pre-registered handling:

1. Gates 1-9 are fed by the **backtest** and are position-count- and capital-unconstrained
   (map §3.1). The baseline is not changed to fit a capital limit — that would be sizing
   driving design.
2. The **paper** guard of §9.1(1) refuses any structure whose entry-time R exceeds
   `options_per_structure_max_loss`, and the **refusal fraction is reported**.
3. Pre-registered ceiling: if more than **50%** of backtest-eligible cycles are refused in
   paper, the gate-10 stream is declared **non-representative** and probation does not count
   as confirmation of this version.
4. The resolution is an **operator item**, listed in §11 as OP-1: either raise the
   per-structure max loss for the options paper account to at least `0.75 × U_max` for the
   highest-priced underlying in the set (on the table above, **~$700** covers `U` up to
   ~$930), or accept that gate 10 confirms only the cheap tail of the underlying set —
   recorded either way, and the affected underlyings named.

This blocks **gate 10 only**. It blocks nothing in Phase D or in I-O1…I-O5.

---

## 10. Variant budget, stopping rule, and the null option

**Budget: 1 variant. Hard cap 2.** The multiplicity cost is paid per family. It is visible
automatically for *sealed* looks — `count_sealed_looks(session, "options_short_vertical")`
(`promotion.py:647`), captured as `k_prior` at `:924`, surfaced as gate-9 evidence at `:1373`
and printed at `cli.py:1384-1397,1570`. It is derived from `strategy_sealed_test` on every read,
so it cannot drift.

**But `count_sealed_looks` cannot see a pre-sealed abandonment, and this program's stopping
rules are full of them (REWRITTEN, rev 2).** §10 makes `v0.2.0` conditional on `v0.1.0` failing
F2 or a gate-3 failure with measured cost/R > 0.06 — both **pre-sealed OOS observations** — and
`v0.2.0` is then evaluated on that same pre-sealed set. If `v0.1.0` stops at F8 or F2 before its
sealed look, `count_sealed_looks` still reads 0 and `v0.2.0`'s gate-9 evidence would print
`k_prior = 0`, **understating the multiplicity by exactly one full pre-sealed evaluation.**

**Pre-registered accounting rule.** Any pre-sealed abandonment of a version in this family is
written as a **numbered disposition record under `docs/research/dispositions/` BEFORE the next
version is run**, naming the version, the falsification criterion that fired, and the pre-sealed
figures that fired it. Every subsequent version's gate-9 evidence must cite

```
k_effective = count_sealed_looks(family) + n_presealed_abandonments(family)
```

with both components shown separately, and `v0.2.0`'s gate-3/4/4b results must be **labelled as
conditioned on a `v0.1.0` pre-sealed outcome**. `k_effective`, not `k_prior`, is the number the
stopping rule below is read against.

- **Variant 1 = `v0.1.0`**, exactly as specified above. Sealed look **k = 1** if it reaches one.
- **Variant 2 = `v0.2.0`, pre-specified now so it is not invisible under R5:** identical in
  every respect except `width_pct` baseline moved from 0.010 to **0.020**. It is chosen in
  advance because §6.2's arithmetic shows cost drag per R falls roughly as `1/width` — a
  mechanism-motivated change, not a result-chasing one.
  **It may be taken only if** `v0.1.0` fails at the **pre-sealed** stage for a cost-drag
  reason specifically (F2, or a gate-3 failure with measured cost/R > 0.06), **and never in
  response to any sealed number** (R1). If `v0.1.0` fails for any other reason — F1, F3, F4,
  F5, F6, F7, F8, F9, F11, F12, F13 — the program stops at the null option and variant 2 is not
  taken.
- **Stopping rule.** After at most 2 looks for this family — counted as `k_effective`, i.e.
  sealed looks **plus** recorded pre-sealed abandonments — the program stops. A third requires
  an explicit operator decision recorded in `docs/research/dispositions/`, naming
  `k_effective = 2`, its two components, and the structure type and R basis (map §5.1(2)).
- **Every abandoned cell is disclosed.** A cell of §4.2's 96-point grid or of §4.4's OAT table
  that was run and not reported is an R5 violation. A parameter combination that is in neither
  list may not be run at all — that is what makes "abandoned variant" definable here.

**The null option, pre-registered as a legitimate and expected outcome.** If `v0.1.0` (and at
most `v0.2.0`) fail, the disposition is **NO OPTIONS STRATEGY SHIPS**. The options data,
engine, calendar, cost model and gate wiring remain as infrastructure and as a recorded
negative result. The program does **not** reach for a different structure to rescue the
outcome: a different structure is a different family starting at k=0, which is permitted in
principle but is explicitly **outside this pre-registration's budget** and would require a
fresh pre-registration document and an operator decision. Nothing is armed; the default-
disabled posture, the kill-switch semantics and the credential rules are unchanged.
**§6.3c states in advance the narrow corner of parameter space in which this design can pass at
all; on the strength of that arithmetic the null option is the *expected* outcome, not a
courtesy**, and saying so before the data exists is the point of writing it down.

---

## 11. Open questions

Numbered for the orchestrator. None blocks Phase D; the ones that block a later step say so.

**OQ-1 — Horizon token: `MEDIUM_SWING` or `POSITION`?** This document declares
`Horizon.MEDIUM_SWING` because `Horizon` describes the *holding* period
(`domain.py:16-18`: SHORT_SWING 2-10 trading days, MEDIUM_SWING 2-8 weeks, POSITION 2-6
months) and a 35-DTE spread exited at 50% credit holds ~2-4 weeks. Map §1.1 and §5.4 assumed
`POSITION` (with the stated reason that POSITION has no registered strategy). The only
mechanical consequence of either choice is gate 0's INTRADAY branch — **which is no longer an
unconditional fail**: as of commit `5b41a61` it is a real `intraday_rth_coverage` query
(`promotion.py:981-1010`), the R4 carve-out the completion map flagged as permitted-in-principle.
Neither `MEDIUM_SWING` nor `POSITION` enters that branch, so the choice is mechanically inert.
Needs ratification before I-O5, because the family name is baked into `count_sealed_looks`.

**OQ-2 — Does `_sensitivity_plan` get an options branch, or does the strategy declare its
axes?** FACT: `promotion.py:255-316` hard-codes a per-family grid by key prefix and returns
`None` for anything unknown, which is an honest gate-5 failure (`:1076-1086`). FACT: the
`DeclaresSensitivityAxes` Protocol exists (`strategies/base.py:32-48`) and **zero** of the six
shipped strategies implements it, so this would be the first. Either path works; the grid of
§4.2 must end up identical. D4/I-O4 decides.

**OQ-3 — *(closed in rev 2)*.** Rev 1 left the response to a shortfall in the 55% net entry
assumption as a post-hoc judgement ("if the realised rate is materially below 55%, the
underlying count or the history depth must rise"). That is a data-conditioned change to a
pre-registered population, taken after the I-O2 coverage summary is seen, with "materially"
undefined. §2.2 now pre-registers the exact trigger (implied net entry rate < 0.45), the exact
response, the fire-once rule and the `options_scope_json` record. Nothing is left to judgement.

**OQ-4 — The two regime modules disagree, and both are load-bearing.** The filter uses
`research/regime.py` (`Trend.BEAR` ⇔ sma50 < sma200 and the 200-SMA not rising, `:67-78`);
gate 6's census uses `backtest/regime.py::label_regimes` (bear ⇔ the 200-session SMA fell,
`:38-41`; `range_bound` ⇔ within ±3% of it, `:22,59-62`). Harmless for this design because the
mirror produces trades on both sides, but it must be disclosed on every evaluation, and it
would **not** be harmless for any future options strategy that skips a regime.

**OQ-5 — *(closed in rev 2)*.** Rev 1's OQ-5 asked whether the modelled spread constant of §2.4
is the one D2 will set; it remains a real dependency and is retained below as **OQ-5b**. Rev 1's
separate deviation from map §3.2 on `max_short_delta` is closed: §4.3 now makes it a grid axis
with a binding value, so no waiver is needed.

**OQ-5b — Is the modelled spread of §2.4 (3% of print with a $0.02 floor, full spread per
crossing) the constant D2 will set?** §6's entire forecast is conditional on it, and §6.2a shows
the `max()` floor is not cosmetic — it binds on the long wing at both settings. If D2 sets a
different constant the forecast is re-run and the difference disclosed; the gate never moves.

**OQ-6 — `options_config_hash` vs `SCOPE_HASH_FIELDS` (§2.5).** This document asserts the
options constants must **not** join `ResearchConfig.SCOPE_HASH_FIELDS`
(`config/research.py:392-409`) because doing so changes the equity `config_hash` and repeats
the 2026-09-11 scope incident, and it hashes `ResearchConfig.options` (which already exists at
`:353` and is already unhashed, and which contains the strike-shaping `risk_free_rate` at
`:205`) inside `options_config_hash` instead. **Rev 2 makes the evaluation deterministic under
either ruling** — §2.5's closing paragraph states exactly what `v0.1.0` does if the orchestrator
confirms the map's literal wording — so OQ-6 now decides *when a migration happens*, not what
the evaluation does. It still contradicts the map's wording in §1.5, §2.4(2) and §3.2 (`:786`),
and it still blocks D1/D3's schema work.

**OQ-7 — Does gate 4's bootstrap seed and iteration count need restating for options?** FACT:
`montecarlo.bootstrap_ci` (`backtest/montecarlo.py:15-33`) operates on a bare `Sequence[float]`,
is asset-class-agnostic, and resamples iid. Assumed unchanged **for the gate**; F11's clustered
CI is a second, separately-computed statistic on the same sequence with a pre-declared cluster
key, and the two must never be confused in the report. The clustered implementation itself is a
D4 deliverable.

**OQ-8 (new, rev 2) — The map's own gate 2/3/4 line citations are stale.**
`OPTIONS_EXECUTION_PROGRAM_MAP.md` §5.3 cites `promotion.py:1034,1044,1061`; at the pinned
commit `5b41a61` the correct anchors are `:1110` (`oos = full.out_of_sample`), `:1111` (gate 2),
`:1124` (gate 3), `:1137-1138` (gate 4). Rev 1 of this document inherited the stale triple into
§2.3 and it is corrected there. Should be fixed when the map is next amended. Blocks nothing.

**Operator items (not mine to decide):**

- **OP-1 (§9.2)** — per-structure max loss for the options paper account: raise to
  `0.75 × U_max` (~$700 covers underlyings up to ~$930), or accept that gate 10 confirms only
  the cheap tail of the underlying set. Blocks gate 10 only. Decision 4 says the operator may
  change any capital limit before arming.
- **OP-2** — decisions 2 (broker + paper keys via env-var or keychain item names only) and 3
  (options approval level) remain open and block arming, not evaluation.
- **OP-3 (new, rev 2, §2.3)** — options history depth is pre-registered at **8 years, floor 6**,
  which is a vendor-entitlement question the orchestrator/operator must confirm before I-O2.
  §6.3c states the consequence of a shorter window in advance: F11's clustered CI does not
  close and the disposition is the null option. Blocks I-O2 sizing, not Phase D.

---

## 12. Read-only queries run to produce this document

All against `data/signalforge.sqlite` with `sqlite3 -readonly`, while the live paper-probation
worker was running. Counts and coverage only; **no price, IV, greek, return or P&L column was
selected**. Rev 2 did **not** re-run them and did not touch the database; the block below is the
rev-1 record, reproduced verbatim. It was independently re-executed during adversarial review
and every result matched.

```sql
select name from strategy;
-- intraday_orb.intraday | mean_reversion.short_swing | relative_strength.medium_swing
-- | trend_continuation.medium_swing | trend_continuation.short_swing
-- | volatility_breakout.short_swing            -> 6 rows, none 'options%'

select count(*) from strategy_sealed_test;                                  -- 22
select s.name, count(*) from strategy_sealed_test t
  join strategy_version v on v.id = t.strategy_version_id
  join strategy s on s.id = v.strategy_id group by s.name;
-- mean_reversion.short_swing 5 | relative_strength.medium_swing 4
-- | trend_continuation.medium_swing 5 | trend_continuation.short_swing 4
-- | volatility_breakout.short_swing 4

select count(*), count(distinct underlying_symbol),
       min(expiration_date), max(expiration_date) from option_contract;
-- 888 | 1 | 2026-09-08 | 2026-10-16

select count(*), count(distinct option_ticker),
       min(session_date), max(session_date) from option_aggregate_daily;
-- 110 | 10 | 2026-07-31 | 2026-09-04

select count(*) from paper_trade;      -- 0
select count(*) from paper_position;   -- 0
select count(*) from strategy_health;  -- 0
```

---

## 13. Code touchpoints referenced

Reading only; nothing was modified. Symbols are named alongside line numbers because line
numbers do not survive commits and symbols do.

| Touchpoint | What it fixes here |
|---|---|
| `src/signalforge/research/sensitivity.py:29,178-181` | `MAX_GRID_POINTS = 120`, full Cartesian product + `ValueError` → §4.2's six-axis arithmetic |
| `src/signalforge/research/sensitivity.py:105-118` | `_is_neighbour` one-step definition → the 7 neighbours of the baseline |
| `src/signalforge/research/sensitivity.py:120-153` | `_axis_movement` — tests an axis **globally**, over points differing from the baseline on that axis alone → why `max_short_delta = 0.28` is not inert (§4.3) |
| `src/signalforge/research/sensitivity.py:218-223,231-241,266` | `pos_frac` denominator is **evaluable**; `fragile = bool(reasons)`; inert-axis reason → §4.3, §5.5 |
| `src/signalforge/research/promotion.py:106` | `MIN_PRESEALED_DAYS` → gate 0.a |
| `src/signalforge/research/promotion.py:255-316` | `_sensitivity_plan` per-family grids → OQ-2 |
| `src/signalforge/research/promotion.py:406-430` | `_regime_census` buckets `{bull, bear, range}` only → gate 6 |
| `src/signalforge/research/promotion.py:647,666,924,1373` | `count_sealed_looks` / `sealed_look_ledger` / `k_prior` capture / gate-9 evidence → k=0 for this family, and the hole §10's `k_effective` closes |
| `src/signalforge/research/promotion.py:1110,1111,1124,1137-1138` | `oos = full.out_of_sample`; gates 2, 3, 4 as they actually run — **corrected in rev 2** (§2.3, OQ-8) |
| `src/signalforge/research/promotion.py:1075-1106,1154-1197,1203-1247,1250-1280,1290-1318,1345-1380,1382-1392` | gates 1, 5, 6, 7, 8, 9, 10 as they actually run |
| `src/signalforge/research/promotion.py:1171` | `baseline_params=_asdict(strategy.params)` → every axis must be a dataclass field |
| `src/signalforge/research/promotion.py:1188,1190` | gate 5 passes on `not sens.fragile`; `n_evaluable` is already surfaced → §5.5 |
| `src/signalforge/backtest/montecarlo.py:15-33` | `bootstrap_ci` resamples the bare per-trade R sequence **iid** (`rng.integers(0, arr.size, …)`) → §6.3b, F11, OQ-7 |
| `src/signalforge/research/backtest_runner.py:29` | `_TRAIN_FRAC = 0.6` → the OOS arithmetic of §6.3c |
| `src/signalforge/research/regime.py:20-23,41-43,62-96` | `Trend`, `risk_off`, `regime_from_proxy` → §3.2's filter |
| `src/signalforge/backtest/regime.py:21,37-40,56-79` | `label_regimes`, compound `trend_vol` label, `segment_key` → gate 6 and OQ-4 |
| `src/signalforge/backtest/engine.py:85-151,154-184` | `t+1` fill convention; the intrabar gap handling that has **no** options analogue (§3.4) |
| `src/signalforge/backtest/engine.py:90` | `spread_bps` is a kwarg default → gate 4b is cheap on the backtest side |
| `src/signalforge/backtest/costs.py:12-17` | `CostModel` shape that `OptionCostModel` parallels (frozen by R4) |
| `src/signalforge/research/strategies/base.py:32-48` | `DeclaresSensitivityAxes`, and why axes must never be `StrategySpec` fields |
| `src/signalforge/research/strategies/trend_continuation.py:21-30` | `TrendParams` — the params-dataclass pattern §4.1 copies |
| `src/signalforge/config/research.py:97,99,102,105,107,108,109,112,113,120,127,128` | every frozen gate threshold cited in §6 |
| `src/signalforge/config/research.py:194,205,216` | `OptionsConfig`; `risk_free_rate = 0.04` **inside it**; `backfill_max_total_bars = 200_000` → §2.5, §6.3c |
| `src/signalforge/config/research.py:348,353` | `promotion: PromotionThresholds` and `options: OptionsConfig` — **both already outside** `SCOPE_HASH_FIELDS` → §2.5 |
| `src/signalforge/config/research.py:392-409,413-415` | `SCOPE_HASH_FIELDS` and the `config_hash` property → §2.5's correction |
| `src/signalforge/options/blackscholes.py:48,62,93` (+ `q = 0.0` defaults at `:49,63,101`) | price / greeks / `implied_vol`; the `q` default that gate 0.g forbids |
| `src/signalforge/db/models/market.py:254-255,290-318` | `shares_per_contract`, `exercise_style='american'`; `OptionAggregateDaily` has no IV/greeks/OI/bid/ask **and no last-trade timestamp** |
| `src/signalforge/db/models/market.py:312,313,314` | `volume`, `vwap`, `transactions` — the three columns rev 1 did not use → §2.4 print eligibility, F13 |
| `src/signalforge/paper/ledger.py:50,129-141,149-166,266,474,496-500` | `_NOMINAL_SPREAD_BPS`; `accept_candidate` calling only `ensure_not_engaged()`; its equity share sizing; `mark_to_market` priced off the **underlying**; `assert_auto_simulate_allowed` and the `("stock","etf")` check the manual path never reaches → §9.1 |
| `src/signalforge/domain.py:16-18,27-30` | `Horizon` bands → OQ-1; `StrategyStatus` has exactly three values and no ARMED state → §9.1 |
| `pyproject.toml:178-186,210-219` | S3 forbids research/risk/backtest/paper → llm; S11 over `signalforge.options` **and** `signalforge.data.options_backfill` |

---

## 14. Judge responses (rev 2)

Two adversarial reviews were run against rev 1 — a LEGITIMACY/EVIDENCE lens (13 defects) and a
SAFETY/FEASIBILITY lens (7 defects). Every defect was re-verified against the pinned commit
before acting. **All 20 are accepted in substance.** Five carry a rejected *remedy*, where the
defect is real but the proposed fix was worse or unavailable; those are argued below rather than
silently altered. No finding was dismissed.

### 14.1 Accepted in full

| Finding | Where it is fixed |
|---|---|
| L1 / S1 — §6.2's representative structure was internally inconsistent (`$1.50 − $0.60 = $90 ≠ $125`), understated cost by ~20-25%, and described a structure that would not have entered under §3.3(4)'s adverse-fill credit floor | §6.2a — structure re-derived ($1.95 / $0.62, adverse credit $125.15 = 0.2503 W, R = $376.45, cost 0.0502 R baseline / 0.0919 R at 2×); §6.2b, §6.3, §6.4, §1 and F8 all republished from it |
| L2 — the `max(0.02, …)` / `max(0.04, …)` spread floor was ignored on the leg it was written for | §6.2a's table shows the floor **binding** on the long wing at both settings. The representative wing was priced at $0.62 rather than a judge's $0.72 specifically so the floor binds and the arithmetic is demonstrated, not merely asserted |
| L3 — no max-loss branch in the break-even or required-`n` model | §6.2b — three-outcome forecast (target win / stopped loss / max loss at the clamped −1.0000 R), break-evens published at `p_m` ∈ {0, 1, 3, 5, 8}%, **3% pre-registered as central**, and §6.3a's required-`n` recomputed from the three-outcome variance |
| L6 — two exclusion rules selected on post-entry information (force-close priceability; realised continuity) | §3.3(6) and §5.2 — both rewritten. Every entered structure stays in; the unpriceable force-close leg is marked at map §2.7's conservative intrinsic floor and flagged `forced_intrinsic_mark`; thin continuity becomes a flag and a paired diagnostic. Exclusion is now reserved strictly for entry-decidable conditions |
| L7 — gate 4b's 2× arm re-selected the population instead of stressing costs | §6.2c — form (a) re-priced with selection frozen is the **gating** form; form (b) full re-selection is a reported diagnostic. §6.2a demonstrates the problem concretely: the representative structure's adverse credit falls to 0.2346 W at 2× and would not enter at all |
| L9 / S6 — no staleness or liquidity guard on the print that drives IV, strike selection and the credit; asynchronicity undisclosed | §2.4 (print-eligibility floor `volume ≥ 10`, `transactions ≥ 5` where non-null; `iv_print_stale_asynchronous_to_underlying_close` in `fill_model`), §3.3(1a) (`non_entry_thin_print`), §5.3 (surface fitted only from print-eligible bars), §8 + **F13** (the `\|close − vwap\|/close` ceiling), §4.4 (OAT row) |
| L10 — sealed-look accounting could not see a pre-sealed abandonment, and v0.2.0's trigger is data-conditioned | §10 — `k_effective = count_sealed_looks + n_presealed_abandonments`, a numbered disposition record required **before** the next version runs, and v0.2.0's results labelled as conditioned on a v0.1.0 pre-sealed outcome |
| L11 — OQ-3's remedy was an uncontrolled post-hoc universe change | §2.2's four-clause ladder: exact trigger (implied net entry rate < 0.45), exact response, fire-once, recorded in `options_scope_json`. OQ-3 is closed |
| L12 — two numeric/consistency errors (storage used 48 cycles where §2.3 pre-registered 60; a stale "~48 sealed-year entries") | Both confirmed. The storage arithmetic is fully restated in §6.3c for the new population (1,814,400 bars, 9.3% headroom) and the rev-1 error is acknowledged there; §6.4's gate-9 row now reads ~92 with the stale figure removed and its history noted |
| L13 / S5 — §2.5 bound the evaluation to an unratified rule, and left `risk_free_rate` outside **both** hashes | §2.5 rewritten: `ResearchConfig.options` (`:353`) is named as already-existing and already-unhashed, `risk_free_rate` (`:205`) is brought inside `options_config_hash`, `PromotionThresholds` (`:348`) is recorded verbatim, the byte-identical-equity-hash migration claim is stated as a checkable artefact, and a **deterministic behaviour under the opposite ruling** is pre-registered so the evaluation is defined either way |
| S2 — dataset sizing inverted by the clustering the document itself flagged | §2.2, §2.3, §6.3b, §6.3c — sizing preference reversed to maximise independent cycle-months (8 years, floor 6) with the underlying count falling out of the storage cap (18 → 14); required `n` restated in cluster units with a `DEFF` ladder; §6.3c states the exact corner in which the design can pass |
| S3 — concurrency × `dte_target` undisclosed, ambiguous on ~58% of cycles, and confounding grid axis 3 | §3.1(5) — the tie-break is pre-registered ("exits on session `t` settle before eligibility is tested"), `skipped_concurrency` joins the §8 census and is reported per grid cell, and the same arithmetic **derives** why `dte_target = 45` cannot be a grid value at all |
| S4 — §9 named the ungated `accept_candidate` hazard but pre-registered no control | §9.1 — a hard precondition: no options `PaperTrade` may be created and gate-10 evidence is **VOID** until `accept_candidate` itself refuses non-`stock`/`etf` instruments fail-closed at the shared entry point; the R-cap and underlying-keyed concurrency guards are assigned to **D3 by name** with the counters they must emit |
| S7 — stale citation `promotion.py:1035,1048,1062` in §2.3, contradicting §6.4 | §2.3 corrected to `:1110/:1111/:1124/:1137-1138`; the map's own stale triple (`§5.3`, `:1034,1044,1061`) is recorded as **OQ-8** |

### 14.2 Defect accepted, remedy rejected — with the argument

1. **L4 — "make `profit_target_pct` {0.25, 0.50, 0.75} and restore `dte_target = 45`."**
   *The defect is accepted:* rev 1's grid was one-sided in the tail-*reducing* direction on five
   of six axes, which makes gate 5's 60%-positive / 75%-neighbour thresholds easier, not harder.
   *The remedy is rejected in two parts.*
   (a) **Two 3-value axes do not fit.** `MAX_GRID_POINTS = 120` is a hard `ValueError`
   (`sensitivity.py:29,178-181`). The review's own arithmetic offers `3×3×2×2×2 = 72` — which is
   **five** axes, i.e. it buys the second 3-value slot by deleting a whole parameter — and
   `2×3×2×2×2×2 = 96`, which is six axes with **one** 3-value slot, exactly rev 1's shape. So the
   choice is *which single parameter* gets three values. It stays with `short_delta_target`,
   because map §3.2 names that one specifically as the parameter gate 5 "will reliably prefer
   the highest-delta cell" on. Instead, rev 2 flips the *second value* of axes 5 and 6 to the
   harder side — `profit_target_pct` 0.25 → **0.75** (later profit-take, more tail exposure) and
   `min_credit_to_width` 0.20 → **0.30** (thinner, richer trades) — which fixes the one-sidedness
   the defect actually identifies, and moves 0.25 and 0.20 to §4.4's OAT table so nothing
   disappears under R5.
   (b) **`dte_target = 45` is excluded by derivation, not preference.** §3.1(5) shows that with
   `time_stop_dte = 7` and 28-35-day third-Friday spacing, a 45-DTE signal session always falls
   *before* the prior cycle's exit, so under `options_max_structures_per_underlying = 1` every
   45-DTE cycle is skipped and those 32 cells would carry ~zero trades — pushing hard against
   §5.5's `n_evaluable ≥ 58` floor. That arithmetic came from the *other* review (S3); the two
   findings interlock, and the derivation is now in the document so the deviation from map §4.3
   is justified rather than merely disclosed. Neighbour count re-stated as required: **7**,
   unchanged under the new grid.
   *One arithmetic note recorded for the record:* the review states F8's 0.78 "sits BELOW the
   corrected baseline break-even" of 77.2%. `0.78 > 0.772`, so it sat marginally *above* that
   particular figure. F8 is nonetheless raised — to **0.89** — because it must be keyed to the
   **2×** break-even (88.6% at the central `p_m`), since gate 4b is required and a design that
   cannot clear 2× break-even cannot clear 4b at any `n`.

2. **L5 — "make `max_short_delta` an axis with a binding low value, e.g. {0.25, 0.35}."**
   *The defect is accepted in full* — map §3.2's Rule is honoured and rev 1's "it would be
   inert" argument confused an inert *value* with an inert *parameter*. *The specific value 0.25
   is rejected.* At `short_delta_target = 0.30` with `delta_tolerance = 0.05` the selectable band
   is `|delta| ∈ [0.25, 0.35]`; a cap of 0.25 leaves only the exact boundary and **empties** all
   16 of those cells rather than binding on them, trading one gate-5 problem for another.
   **0.28** truncates the band to `[0.25, 0.28]`, genuinely constrains the search, moves the
   selected strike and the credit, and leaves the cells populated. `_axis_movement`
   (`sensitivity.py:120-153`) tests an axis globally, so inertness at
   `short_delta_target ∈ {0.12, 0.20}` is not a gate-5 failure. §4.3 carries the argument.

3. **L8 — "pre-register that gate 4 passes only if the clustered CI low also exceeds 0.02R."**
   *The defect is accepted in full and is arguably the most important in either review.* *The
   mechanism is rejected.* A gate's pass condition is computed by frozen code against frozen
   config (`promotion.py:1138`, `config/research.py:105`); D5 has no standing to redefine what
   "gate 4 passes" means, and claiming to would make the document's own verdicts unreconcilable
   with the ladder's output. Rev 2 therefore binds the same requirement as **F11, a disposition
   rule of the same standing as gate 4** (§6.3b, §8): the code's iid verdict is reported
   unchanged, and a clustered CI low ≤ 0.02 R is NO-SHIP regardless of it. Clusters are
   pre-declared as the (cycle-month) pooled across underlyings. This is the same standing §5.4's
   pin-band rule and §5.2's continuity rule already have, it adds a condition rather than moving
   a threshold (R4), and §6.3a/b/c restate every required-`n` figure under both variances.

4. **L6 — "reserve exclusion strictly for entry-decidable conditions."**
   *Accepted, with one addition the review did not ask for.* Simply dropping the map §2.7
   exclusion would replace one defensible convention with another and leave the reader unable to
   tell whether the answer depended on the choice. §3.3(6) and §5.2 therefore report **both**
   arms — intrinsic-floor-retained (gating) and map-§2.7-excluded (diagnostic) — and make a
   **sign disagreement between them a NO-SHIP disposition**. That is strictly more searching than
   either convention alone, and it keeps the document honest about deviating from the map's
   operational wording.

5. **S2 — "set the underlying count by coverage rather than by `n`."**
   *The principle is accepted and implemented* (years first, F11 binding, required `n` in cluster
   units). *The instruction as literally phrased is rejected as under-specified for a
   pre-registration*: "by coverage" is a judgement taken after the I-O2 summary exists, which is
   the same R1 problem L11 raises about OQ-3. §2.2/§2.3 instead fix the number **now** — 8 years
   (floor 6) and **14** underlyings — with the arithmetic that produces it (14 × 96 × 30 × 45 =
   1,814,400 bars vs decision 6's 2,000,000 cap; 18 × 96 does not fit), a floor of 12 so gate 5's
   per-cell counts survive, and §2.2's fire-once ladder as the only permitted adjustment.

### 14.3 What rev 2 does not change

The five strengths both reviews identified are untouched: the §12 attestation and its queries;
the §2.5 config-hash correction (extended, not weakened); the additions that are strictly more
searching (§5.1's clause 4, §5.2, §5.3's convex-hull rule, §5.4's pin-band disposition, §5.5's
`n_evaluable ≥ 58`); the falsification set and the null option (extended to F13 and made
sharper by §6.3c); and §9.2's collateral reconciliation. **No frozen threshold is moved anywhere
in this document, in either revision.** Every change in rev 2 either corrects an arithmetic
error, closes a selection channel, adds a condition, or converts a post-hoc judgement into a
pre-registered rule.

---

## Appendix P — Pointer: amended in part by D5a (2026-09-12, append-only)

**This block is a pointer. It moves no threshold, asserts nothing new, and changes no sentence
above it — §14.3's claim holds verbatim for every section of this document.**

Four arithmetic defects in the sections above were found during wave-2 implementation, recorded
in `docs/research/DECISIONS_2026-09-12_wave2_findings.md`, and resolved at **k = 0** in

> **`docs/research/options_designs/D5a_amendment_1_reachable_credit_floor_and_fixed_R.md`**
> — D5 Amendment 1, applying to `options_short_vertical.medium_swing` **v0.1.1**.

Do not act on the following numbers from this document without reading D5a first:

| Superseded here | See |
|---|---|
| §4.1 / §4.2 `min_credit_to_width` = 0.25, axis (0.25, 0.30); §4.4's OAT 0.20 — **unreachable** | D5a §2 |
| §4.1 `width_pct = 0.010` as a fraction of `U`; §4.2's `width_pct` axis — **fails gate 0.5** | D5a §3, §6.2 |
| §9.2's `R ≈ 0.75 × U` table vs decision 4's $250 per-structure cap | D5a §3.3 |
| §4.2 / §4.4's exclusion of `stop_multiple` from the grid | D5a §6.2 |
| §3.3(3)'s 50 % width tolerance | D5a §3.4 |
| §6.1 / §6.2 / §6.3's cost and required-`n` forecasts | D5a §4, §6.5 (OQ-9) |
| **OQ-1** (MEDIUM_SWING vs POSITION) — **ratified MEDIUM_SWING**, OQ-1 closed | D5a §5 |

Everything not listed above is unchanged and still binding.

**Addendum (2026-09-23).** D5a is itself amended by
`docs/research/options_designs/D5a_amendment_2_raised_cap_and_viable_width.md` (v0.1.2: OP-1
raised the per-structure cap to $900 and the aggregate to $3,600, `width_usd` $8.00, band 0.140 /
0.150 / 0.155). Read it before acting on any D5a number.

**Addendum (2026-10-04).** §2.2's underlying set is restricted, for the first evaluation, to
**SPY, QQQ, IWM** by
`docs/research/options_designs/D5a_amendment_3_index_underlyings.md`: the 21 Stage B underlyings
fail gate 0.c / 0.d's coverage floors (0.420 / 0.644 against 0.90 / 0.80) and are dropped, the
runbook's permitted response, on coverage alone at k = 0. No threshold in this document is moved.
Read it before acting on §2.2, §2.3 or §6.3's sizing.
