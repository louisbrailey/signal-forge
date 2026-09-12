# Pre-registration — the `execution_limits` row, v1

**Document id: `PREREGISTRATION_execution_limits_v1`** (this file's stem; that is the exact
string an `execution_limits.preregistration_doc_id` column must carry, and the exact string
`signalforge execution arm --preregistration ...` must be given).

**Date: 2026-09-12. Status: pre-registered, NOTHING ARMED.** Writing this document arms nothing,
enables nothing, and creates no database row. It is the artefact D6 §7b rule 1 requires to exist
*before* the first armed session, and it is the thing the arming ceremony's S3 check looks for.

---

## 0. Why this document exists, in the ADR's own terms

D6 §7b names the hazard precisely, and it is not a bureaucratic one:

> Several of them materially change realized fills, and realized fills change the live expectancy
> that §12 step 2 / decision 10 uses as the **arming gate**. Choosing a no-submit window after
> observing which windows produced bad fills is a parameter selected after seeing the outcome.

Seven of the columns below are parameters **this ADR invented** (`no_submit_after_open_minutes`,
`no_submit_before_close_minutes`, `max_intent_age_minutes`, `execution_stale_after_s`,
`max_reconciliation_age_s`, `drain_timeout_s`, and the §10 buying-power tolerance). Rev 1 of the
ADR described them only as "operator-set" and stored them in a row that is mutable by supersession
and re-read every cycle. That is the exact shape of an outcome-tuned gate (R1/R4), and §7b makes
fixing the complete row in a document a hard precondition of arming.

The other columns are decision 4's capital limits and map §3.2's percent-of-equity forms. Map §3.2
states its own framing in the strongest available words — "every number below is an **evaluation
grid centre, not a recommendation**" — and decision 4 says "**Operator may change any of these
before arming.**" Both are carried forward verbatim in §5 below.

### What the code actually checks, and what it does not

`execution/arming.py::_preregistration_exists` resolves `docs/` from the package root and matches
the given id against the **stem of any `*.md` file anywhere under `docs/`**. So the check this
document satisfies is: *the operator named a real, reviewable file rather than typing a
placeholder.* It deliberately cannot prove that the file enumerated the grid — that is a review
fact — so the id is written onto the `armed_strategy` row and into the `ARMED` `execution_event`,
where a reviewer follows it here. `execution/limits.py::LimitSet.__post_init__` separately refuses
any row whose `preregistration_doc_id` is empty, and `load_active_limits` turns such a row into
`None`, which **blocks opening** — "no limits row" is not "no limits".

---

## 1. The complete row, pre-registered

One `execution_limits` row, every column, its unit, its value, and its declared grid. Nothing is
defaulted, nothing is omitted, and a column absent from this table would be a column nobody chose.

Reference equity for every percent figure below: **$25,000 SIMULATED** (decision 13 — "a separate
options paper account sized to the strategy (initial $25,000 SIMULATED)"). Percent limits are
evaluated against the broker's **live** equity every cycle, never against this number; it appears
here only so the arithmetic of "which form binds" is checkable by a reader.

### 1.1 Capital limits (decision 4 + map §3.2) — both forms stored, the tighter binds

| Column | Unit | Value | Declared grid | Provenance |
|---|---|---|---|---|
| `max_orders_per_day` | count | **10** | 5 / 10 / 20 | Decision 4 ("daily order cap 10") |
| `max_order_notional_usd` | USD | **1000.0** | 500 / 1000 / 2000 | Decision 4 ("per-order notional $1,000") |
| `max_account_exposure_pct` | % of live equity | **40.0** | 20 / 40 / 60 | Decision 4 ("account exposure cap 40%") |
| `per_structure_max_loss_usd` | USD | **250.0** | 125 / 250 / 500 | Decision 4 ("per-structure max loss $250") |
| `per_structure_max_loss_pct` | % of live equity | **0.5** | 0.25 / 0.5 / 1.0 | Map §3.2 `options_per_structure_max_loss_pct` |
| `aggregate_open_max_loss_usd` | USD | **1000.0** | 500 / 1000 / 2000 | Decision 4 ("aggregate open max loss $1,000") |
| `aggregate_open_max_loss_pct` | % of live equity | **2.0** | 1.0 / 2.0 / 4.0 | Map §3.2 `options_total_open_max_loss_pct` |
| `collateral_cap_usd` | USD | **5000.0** | 2500 / 5000 / 10000 | Decision 4 ("collateral cap $5,000") |
| `collateral_cap_pct` | % of live equity | **30.0** | 15 / 30 / 50 | Map §3.2 `options_collateral_pct_of_equity_max` |
| `max_net_delta_notional_usd` | USD of beta-weighted underlying-equivalent notional, absolute | **10000.0** | 5000 / 10000 / 20000 | Decision 4 ("net delta ±$10,000 notional") |
| `max_net_vega_per_volpt_usd` | USD per volatility point | **50.0** | 25 / 50 / 100 | Decision 4 ("net vega cap $50/vol-pt") |

**Which form binds, worked at the reference equity.** `limits.binding_cap` is
`min(dollars, pct × live equity)` and is recomputed each cycle from the broker's own equity figure.
`None` in, `None` out: an uncomputable cap is not a cap and the caller treats it as a block.

| Pair | Dollar form | Percent form at $25,000 | Binds |
|---|---|---|---|
| per-order notional (L2) | $1,000 | 0.5% → **$125** | the **percent** form |
| per-structure max loss | $250 | 0.5% → **$125** | the **percent** form |
| aggregate open max loss | $1,000 | 2% → **$500** | the **percent** form |
| collateral cap | **$5,000** | 30% → $7,500 | the **dollar** form |

This asymmetry is intended and is the reason both forms are stored rather than one being discarded
at write time: on a larger account the dollar forms bind instead, and neither number has to be
re-chosen for the limit to stay the tighter of the operator's two recorded intents (§4.1).

**Note on L2's percent side.** `may_open`'s L2 check pairs `max_order_notional_usd` with
`per_structure_max_loss_pct`, not with a separate "order notional pct" column. That is §4.1's own
worked arithmetic: for a defined-risk structure the notional *is* the max loss, so one percentage
governs both and a second column would be a second thing to drift.

### 1.2 Timing parameters (§7b rule 2) — the seven this ADR invented

| Column | Unit | Value | Declared grid | Rationale |
|---|---|---|---|---|
| `cycle_interval_s` | seconds | **30** | 15 / 30 / 60 | The kill switch is a file read with no watcher, signal or callback anywhere in the repo — the OMS cannot be told, it can only look, so this is the poll interval and therefore the first term in the worst-case engage→`cancel_all()` latency. |
| `execution_stale_after_s` | seconds | **90** | 60 / 90 / 180, constrained to ≥ 3 × `cycle_interval_s` | The dead man must tolerate **two** missed cycles before it lapses; one missed cycle is noise, and a lapse disarms the whole book. `LimitSet.__post_init__` refuses a row that violates the 3× constraint, so the two numbers cannot be set into contradiction. |
| `max_reconciliation_age_s` | seconds | **120** | 60 / 120 / 300 | Four cycles. Long enough that one failed reconciliation round trip does not block opening; short enough that "clean as of some point in the last two minutes" is still a statement about now. Past this, opening blocks exactly as a dead-man lapse does (§10). |
| `max_intent_age_minutes` | minutes | **15** | 5 / 15 / 60 | An intent priced on information from 15+ minutes ago is a different order from the one the gates evaluated. The effective expiry is `min(session end, created_at + this)`. |
| `no_submit_after_open_minutes` | minutes | **15** | 5 / 15 / 30 | The post-open auction and the first minutes after it have the widest spreads of the session. **This parameter and the next are the two most obviously outcome-tunable numbers in the row** — see §3. |
| `no_submit_before_close_minutes` | minutes | **15** | 5 / 15 / 30 | Measured against the calendar's own session end, with the **options** close substituted on a half-day (13:00 ET), not the equity close. |
| `drain_timeout_s` | seconds | **30** | 10 / 30 / 60 | D6 Q7, answered here rather than after seeing which drains were slow. Too short manufactures `UNKNOWN`s (an undrained order is promoted to `UNKNOWN`, never assumed failed); too long delays the kill switch. |

**Worst case from a kill-switch engage to `cancel_all()`, at these centres:**
`cycle_interval_s` (30s) + `drain_timeout_s` (30s) + one reconciliation round trip ≈ **60–70
seconds**, *with the worker running*. With the worker **down** it is unbounded, because nothing
runs — which is arming acknowledgement (iv), and why it is an acknowledgement rather than a
footnote.

### 1.3 Reconciliation tolerance and the regulatory counters

| Column | Unit | Value | Declared grid | Rationale |
|---|---|---|---|---|
| `buying_power_tolerance_usd` | USD | **1.0** | 0.50 / 1.00 / 5.00 | D6 Q9. The broker's own buying-power figure is authoritative; the local collateral model is a model. Divergence beyond the binding tolerance halts. **Zero is not an option — it halts on rounding**, which is the whole reason a tolerance exists. |
| `buying_power_tolerance_pct` | % of buying power | **0.1** | 0.05 / 0.1 / 0.5 | The percent form, so the tolerance does not become absurdly tight on a large account. Binding tolerance is `min(usd, pct × buying power)`; at $25,000 that is `min($1.00, $25.00)` = **$1.00**. |
| `round_trips_per_5_sessions_max` | count, rolling 5 business days | **3** | 2 / 3 / 4 | §20.2. The counter and the refusal are the system's job; the threshold is the operator's input. **3 is deliberately one below the 4 at which a PDT designation can attach** — see §2. |
| `pdt_equity_threshold_usd` | USD | **25000.0** | not a grid — a regulatory figure, not a tunable | §20.1 / decision 4 ("PDT threshold acknowledged at $25,000"). Compared against `adapter.account()` equity **each cycle**, never against a constant in code. |

### 1.4 Traceability

| Column | Value |
|---|---|
| `preregistration_doc_id` | **`PREREGISTRATION_execution_limits_v1`** |

---

## 2. The PDT acknowledgement

**This is general information, restated from D6 §20.1. It is not advice, and nothing in this
repository advises on an account type, an approval level, or a position size.** The operator must
verify all of it with their own broker.

- In a U.S. **margin** account, a **pattern-day-trader** designation attaches at **4 or more day
  trades in 5 business days** where those trades are a significant share of activity, and carries
  a **$25,000 minimum equity** requirement. Falling below that minimum restricts day trading.
- A **cash** account avoids PDT but is bound by **settlement** instead; U.S. equities and options
  settle **T+1**, and using unsettled proceeds in a cash account can cause a good-faith violation.

**What the operator is acknowledging by arming under this row, in these words:**

1. `round_trips_per_5_sessions_max = 3` is set **one below** the 4-day-trade line on purpose. The
   OMS counts round trips over a rolling 5 business days and **refuses** (may_open check L3) the
   order that would cross the threshold. It refuses rather than warns.
2. `pdt_equity_threshold_usd = 25000.0` is an **acknowledged figure, not a protection**. Nothing
   in this system prevents equity falling below $25,000, and nothing here can prevent a broker
   applying a designation. The figure is read against live equity each cycle so that a breach is
   *visible in the record*; that is the whole of what the software does about it.
3. The counter is the OMS's own, derived from `execution_event` rows this OMS wrote. **It cannot
   see a trade the operator places by hand in the same account** — which is the same fact that
   makes acknowledgement (iii) (no shared account) machine-checked at arm time (§10 rule 2).
4. `paper_reference` is a **local simulator**. Round trips it "executes" are drill artifacts and
   have no regulatory character whatsoever. This acknowledgement is pre-registered now so it is
   not written for the first time in the commit that points the OMS at a real broker.

---

## 3. The arming-expiry rule

**`ARMING_EXPIRY_DAYS = 7` (decision 4). There is no indefinite arming and no way to ask for
one.** This is not an `execution_limits` column — it lives on `armed_strategy.expires_at` and in
`execution/arming.py` — and it is pre-registered here because it is the parameter that bounds how
long every number above can go unreviewed.

- The ceremony's S7 check refuses an expiry in the past **and** an expiry beyond `now + 7 days`.
  An operator who asks for 30 days is refused; the maximum is not silently clamped.
- Expiry is enforced twice, in both directions of the fail-closed split: `may_open`'s A1 blocks on
  an expired arming, and the per-cycle auto-disarm sweep writes a real `DISARMED` row with trigger
  `expires_at_passed`. Neither is sufficient alone — the gate blocks while the worker runs, the
  sweep is what makes the expiry a matter of record.
- **There is no "resume".** Re-arming is the full ceremony again: the live evidence, the `is_paper`
  proof, the flat-account check, the acknowledgements and the typed confirmation phrase, all of it.
- An expiry does **not** close a position and does **not** cancel anything at the broker. It ends
  the authority to **open**. `build_close_intent` requires no armed row, and the protective close
  lane stays constructible for a strategy that expired, was disarmed, or never existed.

**Why the expiry belongs in a pre-registration document at all.** Seven days is the interval at
which every number in §1 is forced back in front of the operator. Change it and you change how
long an outcome-tuned parameter could sit in force unreviewed, which is the same hazard §7b names
— so it moves under the same rule as everything else in §4.

---

## 4. Changing any of this — the rule, without exceptions

**Every value in §1, plus the expiry rule in §3, is frozen under this document id. Changing any
one of them requires a NEW pre-registration document with a NEW id** (`..._v2`, then `_v3`), and
the new `execution_limits` row must carry that new id in `preregistration_doc_id`.

The mechanics, so this is a procedure rather than an intention:

1. **Rows are never edited.** `execution_limits` is versioned by supersession: the old row gets a
   `superseded_at`, a new row is inserted. The model and §7 both say so, and the table has no
   update path.
2. **A new row RESETS the decision-10 evidence counter** for every strategy armed under it (§7b
   rule 3). The ≥ 20 closed paper trades must be accumulated **under the limits row actually in
   force**; `arming.evaluate_evidence` counts only from `active_limits_created_at`. Without this
   rule a parameter tuned mid-window inherits evidence generated under the old parameter — the
   precise shape of an outcome-tuned gate. **This is the expensive consequence of a change, and it
   is meant to be.**
3. **A v2 document must state, for every changed value: the old value, the new value, whether the
   new value is inside the grid declared here, and — if it is not — why the grid itself was wrong.
   A move within a declared grid is a different act from a fresh choice, and only the document can
   tell them apart.**
4. **A change made after seeing fills is disclosed as such, in the v2 document, in those words.**
   The honest record of an outcome-tuned parameter is a disclosed one; an undisclosed one is the
   finding this whole section exists to prevent.
5. The old document is never edited or deleted. Superseded documents stay, because an
   `armed_strategy` row pointing at `..._v1` must remain followable forever.

### The operator's own three items (decision 4, decisions §"Remaining operator items")

Decision 4 ends: "**Operator may change any of these before arming.**" That is carried here
without qualification:

> **The operator may change any capital limit in §1.1 — and any timing parameter in §1.2 or
> tolerance in §1.3 — before the first arming. Doing so does not violate this pre-registration;
> it supersedes it. The changed row is written with `preregistration_doc_id` set to
> `PREREGISTRATION_execution_limits_v2`, and this document is superseded by that one, which states
> what changed and why. There is no path in which a changed value is arming under `_v1`.**

Still outstanding, and blocking exactly the steps named (they are the operator's, not this
document's):

| # | Operator item | Blocks |
|---|---|---|
| 1 | Confirm the broker (Alpaca paper assumed) and place its paper API keys in the environment or Keychain **yourself** | the vendor paper adapter (I-E5) only — **not** `paper_reference`, which needs no credential |
| 2 | State the options approval level (design assumes Level 2; the actual level is operator-only) | arming any **options** structure. Equity arming at `--approval-level 0` is unaffected |
| 3 | Confirm or change the capital limits in §1.1 | **arming** |

---

## 5. Framing carried forward verbatim

Two sentences from the sources this document is assembled from, quoted rather than paraphrased,
because paraphrasing them is how a grid centre turns into a recommendation:

- Map §3.2: "every number below is an **evaluation grid centre, not a recommendation**", and
  "**Every capital limit in this section is an operator decision** … and this document does not
  make it."
- Decision 4: "**Operator may change any of these before arming.**"

Nothing in this file recommends a position size, an account type, an approval level, or a broker.
It records which numbers were fixed, in advance, so that a later change is visibly a change.

---

## 6. Provenance

| Source | What was taken from it |
|---|---|
| `docs/research/DECISIONS_2026-09-12_options_execution.md` row 4 | the capital limits, the arming expiry, the PDT threshold |
| `docs/research/DECISIONS_2026-09-12_options_execution.md` rows 10, 13 | the ≥ 20-closed-trade evidence gate; the $25,000 SIMULATED reference account |
| `docs/research/options_designs/D6_execution_adr.md` §7b | rules 1–5, and the seven timing grids |
| `docs/research/options_designs/D6_execution_adr.md` §10 | the buying-power tolerance pair and its grid centres ($1.00, 0.1%) |
| `docs/research/options_designs/D6_execution_adr.md` §12, §20 | the expiry rule, the acknowledgements, the PDT facts |
| `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` §3.2 | the percent-of-equity forms, and the grid-centre framing quoted in §5 |
| `tests/execution/conftest.py::LIMIT_GRID_CENTRES` | the values as the test suite already asserts them — this document and that constant must agree, and `tests/execution/test_preregistration_doc.py` fails if they do not |

**This document is machine-checked against the code in two places**: the file must exist under
`docs/` with this stem (`arming._preregistration_exists`, ceremony check S3), and every value in
§1 must equal the corresponding entry in `LIMIT_GRID_CENTRES`
(`tests/execution/test_preregistration_doc.py`). A value edited here and not there — or there and
not here — fails the suite.
