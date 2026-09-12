# D2 — Options engine spec

Workstream **D2** of `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` §7 Phase D
("backtest architect"). **Design document only. No code was written, no file under
`src/` or `tests/` was touched, no provider API was called, no package was installed,
no secret was read.** Every DB access behind this document was a read-only `SELECT`
against `data/signalforge.sqlite` (a LIVE paper-probation database).

Written: 2026-09-11. **Revised: 2026-09-11 (rev 2)**, after two adversarial audits
(legitimacy/evidence and safety/feasibility); see the *Judge responses* appendix for every
defect raised, what changed, and what was rejected. Repo: `/Users/louisbrailey/signal-forge`.

**Citation pin.** Every `file:line` reference below was (re-)verified against commit
**`5b41a61b709cd40e7d46413d7ed141a36e3d9eea`** (`5b41a61`), working tree clean under `src/`,
`tests/` and `pyproject.toml`. Rev 1's references to `research/promotion.py` and
`config/research.py` had drifted 30-75 lines low; every underlying claim survived, but a
reader auditing this document by its own coordinates would have landed on unrelated code.
A reference that does not resolve at that sha is **stale, not a refuted claim** — re-derive
it before treating the claim as wrong.

**Labelling.** **FACT** = verified against a named `file:line` or a named read-only
query in this pass. **HYPOTHESIS** = a design proposal that nothing in the repo yet
establishes. **MAP** = carried from the program map (which labels its own claims);
where this document re-verified a MAP claim it is re-labelled FACT with the line
reference, and where it *contradicts* a MAP claim it is flagged **CORRECTION**.

**Binding inputs, not re-litigated here:**
`docs/research/DECISIONS_2026-09-12_options_execution.md` (orchestrator decisions 1–13),
`docs/research/STRATEGY_COMPLETION_MAP.md` §1 R1–R10, and the program map's §0, §5.4, §7.
In particular: decision #7 (local Black-Scholes inversion + the §2.4b same-session
surface), decision #11 (source and record `q` per underlying — no allowlist),
decision #12 (O3 short vertical credit spread ships first), decision #5 (no NBBO
purchase; modelled spreads are a permanent disclosed assumption and gate 4b is
permanent), decision #6 (`backfill_max_total_bars` → 2,000,000).

---

## Contents

0. [Summary of what this spec changes relative to the map](#0)
1. [Placement, and how "byte-identical" is *proved* rather than promised](#1)
2. [Module inventory and the import contracts each new module inherits](#2)
3. [`OptionChainSeries` — the point-in-time data view the whole design rests on](#3)
4. [Leg and structure dataclasses](#4)
5. [The signal / strategy interface](#5)
6. [Fill model](#6)
7. [`OptionCostModel`](#7)
8. [The two-spread rule (gate 4b) — what it actually costs to wire](#8)
9. [R = max loss: the definition, its two variants, and the consequences](#9)
10. [Expiry, force-close pricing, intrinsic floor, pin band, assignment](#10)
11. [`options_calendar.py`, designed for the execution layer too](#11)
12. [Walk-forward / IS-OOS segmentation reuse](#12)
13. [Leakage checks for every new feature](#13)
14. [Config hashing, provenance, and the evaluation record](#14)
15. [Determinism and the test plan](#15)
16. [Out of scope for D2](#16)
17. [Open questions](#17)
18. Appendix — Judge responses (rev 2)

---

<a name="0"></a>
## 0. Summary of what this spec changes relative to the map

Nine items below are corrections or additions to the program map's §2. They are listed
first because each one changes what gets built.

| # | Item | Where |
|---|---|---|
| **C1** | **"Folded into `config_hash`" is not achievable as the map states it.** `ResearchConfig.SCOPE_HASH_FIELDS` deliberately **excludes** `options` and `promotion`. Adding options constants to it would change the scope hash of the two live PAPER_APPROVED strategies and un-scope them — the exact incident fixed in commit `0cc4cf4`. Options constants need a **separate** `options_config_hash`. | §14 |
| **C2** | **`spread_bps` is not reachable from the promotion path.** It is a `run_backtest` kwarg, but *none* of the three call sites between `evaluate_promotion` and `run_backtest` forwards it. Gate 4b on the equity side is a 3-call-site plumbing job, not zero. And under the current engine "2× spread" yields 2× *half*-spread. | §8 |
| **C3** | **The joint trend×vol bucket is not free, and `range_bound` carries no vol half.** `backtest/regime.py` emits `range_bound` as an `else`-branch override, so the label set is 4 joint cells **plus** an unsplittable range cell — not 3×2=6. Separately, **two different regime modules disagree**: the gate-6 census and the strategy's own regime filter use different functions with different definitions. | §12.3 |
| **C4** | **The existing leakage harness cannot express an options feature at all.** `FeatureFn = Callable[[PriceSeries, int], float]` takes a single underlying series; every options feature is a function of the *chain*. Gate 8's leakage self-check is structurally inapplicable until a chain-aware sibling exists. The equity side hit the same class of blindness during this pass (`base.py:62-63`). | §13 |
| **C5** | **Point-in-time *chain membership* is not reconstructible from the schema**, and the map's D2 fix (point-in-time reference price) does not close it. `OptionContract` has no listing date. The only data-grounded visibility rule is "a contract is visible at session *t* only if it has printed at some session ≤ *t*". | §3.3 |
| **C6** | **The `shares_per_contract == 100` assertion has a hole.** The adapter writes `int(r.get("shares_per_contract", 100))` — a vendor **omission** is silently recorded as 100 and passes the assertion. The mechanical guard is weaker than the map claims. | §4.3 |
| **C7** | **`r` (the risk-free rate) needs the same treatment as `q`, and the map never says so.** `OptionsConfig.risk_free_rate` is a single scalar constant with no date dimension, over a backfill window in which U.S. short rates moved by several hundred basis points. Gate 0.g must carry `r_source` alongside `q_source`. | §6.5 |
| **C8** | **R's treatment of entry costs interacts with gate 4b.** If entry costs sit inside R, the 2× spread run moves numerator *and* denominator and is no longer a clean stress. Resolution: a second, **fixed-denominator reporting basis `R_at_print`** computed from the *unadjusted* prints (rev 1 defined it from the credit *received*, which is spread-adjusted and therefore not cost-invariant at all — see §9.3); `R_incl` stays the gating basis; all four (basis × spread setting) are reported and **the gate binds on the worst of the four**, which by construction is `R_incl` at 2×. | §9.3 |
| **C9** | **`corporate_action` is empty (0 rows)**, so D7's "exclude cycles crossing an adjustment event" has no data source today other than the deliverable assertion of C6 — which C6 shows is itself incomplete. | §10.6 |

### What rev 2 changed in this document (self-corrections, not map corrections)

Twelve items — the ten below, plus two named under the table. Each is argued where it
lands and summarised in the *Judge responses* appendix.

| Item | Rev 1 said | Rev 2 says | Where |
|---|---|---|---|
| Pre-registration breach | published the vendor-IV **distribution** (cardinality, min, max) | coverage **counts only**; the look is disclosed for D5 to record; a query-whitelist rule added | §3.6, §16 |
| The −1R clamp | clamp, and report the clamp rate | **every gate statistic runs on the UNCLAMPED series**; the clamped series is a reported line only | §9.4 |
| `R_excl` | "invariant to the cost model" | false as defined; renamed `R_at_print`, defined on unadjusted prints, and labelled a reporting basis nobody can realise | §9.2, §9.3 |
| `OptionCostModel` | every field `= 0.0` | **no defaults at all**; both-zero spread refused; a vacuous 2× gate becomes impossible | §7.1, §7.4 |
| Gate 4b evidence run | cites the sealed-row reuse as protection | it is also a **replay**: gate 9 is omitted or labelled as baseline-locked, and an R3 bump costs sealed look k+1 | §8.3 |
| Exit fill timing | triggered exits filled at the triggering session's close | triggered exits fill at **t+1**; only calendar-knowable exits (time stop, force close) fill same-session | §10.1 |
| §10.2's exclusion bias | "not confidently signable" | **measurable** from the underlying close; gate 8 reports the excluded cycles' intrinsic-at-expiry distribution | §10.2 |
| Intrinsic floor | applied symmetrically | **buy side only**; a sold leg uses `last_print`, with the gap measured | §10.3 |
| Clock check | `disagrees_with(...) -> str \| None` | fail-open by signature and clock-reading; replaced by three-state `clock_agreement(now, ...)` | §11.1, §11.2 |
| Metrics reuse | "unchanged" | `compute_portfolio_metrics`'s `risk_fraction=0.005` is ~3× wrong for a fixed-dollar options R | §12.1 |

Two more: the spread floor is now bounded relative to the print (§6.3), and the contract
addition of §2.1 moves from I-E1 to I-O3.

---

<a name="1"></a>
## 1. Placement, and how "byte-identical" is *proved* rather than promised

### 1.1 The placement decision stands, and the reasons re-verify

**FACT.** `backtest/engine.py` never branches on asset class; `run_backtest`
(`src/signalforge/backtest/engine.py:85-151`) is pure arithmetic over `PriceSeries`
arrays with a `SignalFn` callback.

**FACT.** `EntrySignal.__post_init__` (`backtest/engine.py:37-41`) raises unless
`direction in (Direction.LONG, Direction.SHORT)` and `time_stop_bars >= 1`. A put credit
spread is simultaneously short one strike and long another; there is no honest value for
that field.

**FACT.** `SimTrade` (`backtest/engine.py:44-60`) is frozen with 14 fields including
`direction`, `entry_price`, `exit_price`, `mae_r`, `mfe_r`, `costs_bps` — several of
which have no meaning for a multi-leg structure priced as a net premium.

**FACT (and this is the strongest single reason).** `persistence.spec_json_hash`
(`src/signalforge/research/persistence.py:32-43`) hashes **every** `StrategySpec` field
except `{git_sha, status, notes}` (`persistence.py:29`). `StrategySpec`
(`research/registry.py:31-56`) has 25 fields. Adding one field would change the hash of
**every** existing strategy, including the two PAPER_APPROVED ones whose approvals are
scoped by their current hashes. `research/strategies/base.py:42-46` records exactly this
reasoning as the reason `sensitivity_axes()` was kept off the spec as a Protocol.

**Therefore (HYPOTHESIS, unchanged from MAP §2.1, now re-verified):** build
`src/signalforge/backtest/options_engine.py` as a **sibling**. Do not add fields to
`StrategySpec`, `EntrySignal`, `SimTrade`, or `CostModel`. Options structure parameters
live in a `params` dataclass and are surfaced into the existing free-text spec fields
(`rule_definition`, `entry_conditions`, `exit_logic`, `stop_logic`, `time_stop`,
`assumed_transaction_costs`, `slippage_model`) by string interpolation — which is how
`TrendParams` already works and which keeps them hash-detectable with no field-set change
(`persistence.py:25-28` states this design intent explicitly).

### 1.2 `params` is not optional — gate 5 requires it mechanically

**FACT.** `research/promotion.py:1171` calls `_asdict(strategy.params)` when building the
sensitivity baseline. A strategy object without a dataclass `params` attribute cannot
reach gate 5; it fails it with "no parameter-sensitivity grid is defined"
(`promotion.py:1151-1161`). So the `params`-dataclass pattern is a hard requirement of
the existing gate ladder, not a style preference.

### 1.3 Make "byte-identical" mechanical (HYPOTHESIS — new, not in the map)

The map asserts the equity path stays byte-identical "by construction". Construction is a
promise; a test is a guarantee. Propose `tests/safety/test_equity_core_frozen.py`:

```
FROZEN = {
  "src/signalforge/backtest/engine.py": "<sha256>",
  "src/signalforge/backtest/costs.py":  "<sha256>",
}
```

asserting each file's sha256. R4 freezes `CostModel` for the program's duration
(`STRATEGY_COMPLETION_MAP.md` §1 R4) and this makes that freeze observable rather than
attested. Trade-off, stated plainly: the test fires on whitespace and comment edits too.
That is the intended behaviour — any edit to these two files becomes a deliberate act
that must update the constant in the same commit, visible in the diff, rather than
something that can slip through under "just a comment".

---

<a name="2"></a>
## 2. Module inventory and the import contracts each new module inherits

**HYPOTHESIS (the module set).**

| New module | Contains | Imports it may make |
|---|---|---|
| `backtest/options_engine.py` | `run_options_backtest`, `OptionTrade`, exit resolution, force-close | `signalforge.options.blackscholes`, `backtest.options_costs`, `backtest.options_pricing`, `data.options_calendar`, `data.option_chain` |
| `backtest/options_costs.py` | `OptionCostModel` (sibling of `costs.py`, **not** a subclass) | stdlib only |
| `backtest/options_pricing.py` | print-based fill model, the modelled-spread function, the §2.4b same-session surface fit, intrinsic floor | `signalforge.options.blackscholes` |
| `data/option_chain.py` | `OptionChainSeries`, `ChainSession`, `ContractRef`, `ContractPrint`, loaders | `db.models.market`, `data.repository` |
| `data/options_calendar.py` | expiry resolution, DTE, early close, settlement style | `data.calendar` only |
| `backtest/options_leakage.py` | `assert_no_lookahead_chain`, `OPTIONS_LEAKAGE_FEATURE_CHECKS` | `data.option_chain`, `data.series` |
| `research/options_backtest_runner.py` | universe loop, IS/OOS split, per-regime segmentation (sibling of `backtest_runner.py`) | the above + `research.regime` |

### 2.1 What each placement buys, contractually

**FACT.** Import-linter contract **S3** (`pyproject.toml:177-186`) forbids
`signalforge.research`, `.risk`, `.backtest`, `.paper` from importing `signalforge.llm`.
Every module in the table above lives in `signalforge.backtest`,
`signalforge.research`, or `signalforge.data` — so **`options_engine.py` inherits the
"no LLM on the decision path" guarantee the moment it is created, with no new contract
needed.** (`signalforge.data.option_chain` and `data.options_calendar` are *not* covered
by S3; see the recommendation below.)

**FACT.** Contract **S11** (`pyproject.toml:209-219`) names
`source_modules = ["signalforge.options", "signalforge.data.options_backfill"]` and
forbids them from importing `signalforge.alerts`, `signalforge.llm`,
`signalforge.research.scan`, `signalforge.research.candidates`,
`signalforge.paper.ledger`. The direction matters: S11 constrains what the *options*
package may import, **not** what may import it. So `backtest/options_pricing.py`
importing `signalforge.options.blackscholes` is permitted today and creates no contract
violation.

**But that is a fact about the linter, not about the label, and rev 1 treated it as a
non-event.** That import turns an explicitly education-only module into the pricing core of
the decision path that decision #1 eventually connects to a live order — while S11's own
name, "options are education/simulation only — no alerts, no LLM, no decision path"
(`pyproject.toml:210`), keeps asserting the opposite **and keeps passing**, because S11
constrains only what `signalforge.options` may import. A safety label that silently stops
being true is worse than no label. Handed to the orchestrator in §16; D2 does not write it.

**FACT.** The **Layering** contract (`pyproject.toml:200-207`) forbids
`signalforge.data.adapters` from importing `signalforge.research`, `.risk`, `.backtest`,
`.paper`, `.app`, `.alerts`. `data/option_chain.py` and `data/options_calendar.py` sit in
`signalforge.data`, not `signalforge.data.adapters`, so they are unconstrained by it —
but they must not import `backtest` or `research` anyway, for the same reason the layering
contract exists. Keep them dependency-free of the research stack; this is also what makes
`options_calendar` usable by the execution layer (§11).

**HYPOTHESIS (recommended contract addition, for D6/I-E1 to carry — not for D2 to write):**
extend S3's `source_modules` to include `signalforge.data`, or add an S11a naming
`signalforge.backtest.options_engine`, `signalforge.backtest.options_pricing`,
`signalforge.data.option_chain`, `signalforge.data.options_calendar` as source modules
forbidden from importing `signalforge.llm`, `signalforge.alerts`, and (until the
execution ADR is approved) any future `signalforge.execution`. The point is that the
options engine's LLM-freedom should be *named*, not inherited by the accident of package
placement.

**Commit placement — a correction to rev 1.** Rev 1 put this in the I-E1 commit. That is
wrong on MAP §7's own terms, in a way that leaves an order-path gate unprotected. **FACT
(MAP §7 Phase I):** the two tracks are independent and "the execution track must **not**
wait on the options track", and I-E1 is specified as "safety-test rewrite + S1a/S15a/S15b
contracts + the S14 addition (**nothing else in the same commit**)". **FACT (MAP §7, same
section):** I-O3 — on the *other* track — is the commit that **creates**
`options_calendar.py`, and **FACT (MAP §6.4)** the OMS is required to cross-check
`adapter.clock()` against that module and block on disagreement. So under rev 1's ordering
there is no sequencing that guarantees the contract exists when the module does.

**Rule (HYPOTHESIS, corrected):** the contract addition naming
`signalforge.backtest.options_engine`, `signalforge.backtest.options_pricing`,
`signalforge.data.option_chain` and `signalforge.data.options_calendar` ships **inside
I-O3 itself**, and those modules may not merge without it. Only the execution-side
contracts (S1a / S15a / S15b / S14) stay in I-E1.

---

<a name="3"></a>
## 3. `OptionChainSeries` — the point-in-time data view the whole design rests on

The map's §2.3 specifies the *position* model and §2.4 the *fill* model, but never
specifies **how the engine sees the chain**, and every leakage property in this design is
a property of that view. This section is the load-bearing addition.

### 3.1 Why it must mirror `PriceSeries.head(t)`

**FACT.** `PriceSeries.head(t)` (`src/signalforge/data/series.py:39-50`) returns a view of
bars `0..t` inclusive, and the module docstring (`series.py:1-5`) states its purpose:
"makes look-ahead a structural impossibility in tests". **FACT.** `run_backtest` calls
`signal_fn(series.head(t), t)` (`backtest/engine.py:102`) — the strategy is *handed* the
truncated view; it cannot opt out. **FACT.** `assert_no_lookahead`
(`backtest/leakage.py:23-41`) works by calling the feature once on `series.head(t)` and
once on the full series and comparing.

The options engine gets the same three properties only if the chain has the same
`head(t)` contract.

### 3.2 The dataclasses (HYPOTHESIS)

```python
class Right(StrEnum):            CALL = "call";  PUT = "put"

@dataclass(frozen=True, slots=True)
class ContractRef:
    option_ticker: str            # OptionContract.option_ticker
    underlying_symbol: str
    right: Right                  # from OptionContract.contract_type
    strike: float                 # OptionContract.strike_price
    expiration: date              # OptionContract.expiration_date
    shares_per_contract: int      # READ from the row; never defaulted here
    exercise_style: str           # OptionContract.exercise_style
    first_print_session: date     # DERIVED: min(session_date) in OptionAggregateDaily

@dataclass(frozen=True, slots=True)
class ContractPrint:
    open: float; high: float; low: float; close: float
    volume: float; vwap: float | None; transactions: int | None

@dataclass(frozen=True, slots=True)
class ChainSession:
    session_date: date
    underlying_close: float              # from OHLCVDaily — see 3.4
    prints: Mapping[str, ContractPrint]  # option_ticker -> print. ABSENCE IS THE ANSWER.

@dataclass(frozen=True, slots=True)
class OptionChainSeries:
    underlying: str
    sessions: tuple[ChainSession, ...]        # ordered, one per underlying session
    contracts: Mapping[str, ContractRef]      # visible set — see 3.3
    def __len__(self) -> int: ...
    def head(self, t: int) -> OptionChainSeries: ...
    def print_at(self, t: int, ticker: str) -> ContractPrint | None: ...
    def printed_tickers(self, t: int) -> frozenset[str]: ...
    def visible_contracts(self, t: int) -> Mapping[str, ContractRef]: ...
```

**`print_at` returning `None` is a first-class liquidity fact and must never be coerced to
0.0, to the previous session's close, or to a model price.** That is MAP §2.4(3) expressed
as a type. A `Mapping` that raises `KeyError` is *better* here than one that returns a
default, because the default is the bug.

### 3.3 Visibility rule — CORRECTION C5

**FACT.** `OptionContract` (`src/signalforge/db/models/market.py:240-258`) has columns
`option_ticker, underlying_symbol, contract_type, strike_price, expiration_date,
exercise_style, shares_per_contract, source, ingested_at`. **There is no listing date and
no first-seen date.** `ingested_at` is *our retrieval time*, which for a backfill run in
2026 is 2026 for every contract regardless of when it listed.

**Consequence:** "which contracts existed on 2024-03-15" is **not** answerable from the
schema. The map's D2 blocker (point-in-time *reference price* for centring the strike
band, `options_backfill.py:77-88`) fixes which contracts get *fetched*; it does not make
chain **membership** point-in-time at evaluation time. A naive engine that iterates
`contracts` at session *t* is reading the future chain.

**Rule (HYPOTHESIS).** `OptionChainSeries.head(t)` restricts `contracts` to
`{c for c in contracts if c.first_print_session <= sessions[t].session_date}`. A contract
is visible at session *t* **only if it has printed at some session ≤ t**.

Why this rule and not a listing-date proxy:

- It is entirely data-grounded — derived from `OptionAggregateDaily`, no assumption about
  listing conventions.
- It is strictly conservative: the engine never assumes a contract was tradable before it
  demonstrably traded.
- It extends MAP §2.4(3)'s discipline from *fills* to *selection*: a strike that has never
  printed cannot be selected, which is the same reasoning that forbids synthetic fills.

**The cost, disclosed, not hidden.** The rule biases strike selection toward contracts that
have already traded — i.e. toward the more liquid strikes. That makes the *fills* more
realistic and the *strategy* potentially unrepresentative of its stated rule. **Gate 8
evidence field (new):** `target_strike_invisible_count` — the number of cycles in which
the strategy's stated strike-selection rule chose a strike that was not visible under this
rule, with the realised substitution (or the non-entry). A run in which that count is
large has not tested the strategy it pre-registered.

**Interaction with gate 0.c.** The map's gate 0.c ("the stored chain brackets the target
strike on the entry date") must be evaluated **under this same visibility rule**, not
against the full reference table. Otherwise gate 0.c passes on contracts the engine will
refuse to see. Flagging for D4.

### 3.4 `underlying_close` and the join

**FACT.** `OptionAggregateDaily` (`market.py:290-318`) has **no underlying-price column**.
The underlying's close must be joined from `OHLCVDaily` on `(instrument_id, session_date)`.
**FACT.** `OptionQuoteSnapshot.underlying_price` exists (`market.py:274`) but only at one
timestamp (see §3.6), so it is not a source for a historical series.

**Rule (HYPOTHESIS).** `ChainSession.underlying_close` comes from `OHLCVDaily.close` for
the same session, loaded through the **same `source` filter** the evaluation used, for the
same reason `_data_provenance` applies the source filter
(`research/backtest_runner.py:60-63`: otherwise the record can claim a source that never
contributed a bar). A session with an option print but no underlying bar is a data defect:
count it, exclude the session, and surface the count at gate 8 — do not interpolate.

### 3.5 Session alignment

**Rule (HYPOTHESIS).** `sessions` is indexed by the **underlying's** session list over the
evaluation window (from `data/calendar.py::sessions`, `calendar.py:38-41` — FACT: XNYS via
`pandas_market_calendars`), not by the union of option print dates. This keeps index *t*
meaning the same thing in `OptionChainSeries` and in the underlying `PriceSeries`, which is
what lets a single `t` address both in a feature function (§13) and what lets the existing
IS/OOS boundary arithmetic be reused unchanged (§12).

### 3.6 What the live DB says about all of this today

Read-only queries against `data/signalforge.sqlite`, 2026-09-11:

| Query | Result |
|---|---|
| `select count(*), count(distinct underlying_symbol), min(expiration_date), max(expiration_date) from option_contract` | **888, 1 (SPY), 2026-09-08 … 2026-10-16** |
| `select shares_per_contract, count(*) from option_contract group by 1` | **`[(100, 888)]`** — no adjusted deliverables present |
| `select exercise_style, count(*) from option_contract group by 1` | **`[('american', 888)]`** |
| `select count(*), count(distinct option_ticker), min(session_date), max(session_date) from option_aggregate_daily` | **110 rows, 10 contracts, 2026-07-31 … 2026-09-04** |
| per-contract bar counts | **26, 26, 9, 9, 8, 8, 7, 7, 5, 5** — all 10 contracts are struck at **$770**, i.e. one strike, five expiries, both rights |
| `select sum(case when volume=0 then 1 else 0 end), count(*) from option_aggregate_daily` | **0 of 110** zero-volume bars |
| `select count(*), count(distinct as_of) from option_quote_snapshot` | **878 rows, 1 distinct `as_of` = 2026-09-07 18:30:00** |
| `select count(*) from corporate_action` | **0** |

**Two consequences for D2.**

1. **Gate 0.c is unsatisfiable today and correctly so.** With one strike in the entire
   stored chain, nothing brackets anything. This is the expected outcome (MAP §1.5) and
   must not be worked around.
2. **CORRECTION — vendor IV/greeks/OI are *present*, not absent.** `market.py:260-264`
   documents `vendor_iv` / `vendor_greeks_json` as "usually absent on this entitlement
   (None)", and MAP §1.5 gate 0.e repeats it. The live data disagrees:
   `select count(*) from option_quote_snapshot where vendor_iv is not null` → **878 of
   878**; `vendor_greeks_json` is non-empty on **878 of 878**; `open_interest` is non-null
   on **878 of 878**. Those are **coverage** counts — presence, not value — and that is
   deliberately all this section reports. The
   entitlement *does* deliver IV/greeks/OI through `/v3/snapshot/options/{underlying}`.
   What it does not deliver is **history** — one timestamp is not a series. Decision #7
   (local inversion for history) is unaffected. But see §17 Q4: this one snapshot is a
   free, zero-API-call **validation set** for the local inversion, and using it is a
   judgement call under R1.

**Disclosed look (R1 / MAP §7) — a breach in rev 1 of this document, recorded here because
it cannot be undone.** Rev 1 of this row also reported the vendor-IV **distribution**: its
distinct-value count and its minimum and maximum. MAP §7's pre-registration ordering forbids
that verbatim — "**No price, IV, greek, return, credit, or P&L series may be inspected — by
a person or by a script — until D5 is committed. That includes summary statistics over
them.**" A non-null *count* is coverage and is permitted; a range is a summary statistic over
the series and is not. §17 Q4 below cites that exact rule to decline a *weaker* use of these
same 878 rows, so rev 1 contradicted itself inside one document.

The figures are removed. The inspection is not reversible — the numbers were seen — so it is
disclosed as a **look**: an IV range over 878 SPY rows at the single `as_of`
2026-09-07 18:30:00 was observed by this document's author, and it may have informed the
§6.6 surface-N floor and any IV sanity band proposed downstream. **D5's pre-registration
must record it as a disclosed look under R5**, and §16 adds the query-whitelist rule that
should have prevented it.

---

<a name="4"></a>
## 4. Leg and structure dataclasses

### 4.1 The types (HYPOTHESIS, refining MAP §2.3)

```python
class StructureType(StrEnum):
    VERTICAL_CREDIT = "vertical_credit"     # Phase 1 (decision #12: O3 first)
    VERTICAL_DEBIT  = "vertical_debit"
    CASH_SECURED_PUT = "cash_secured_put"
    COVERED_CALL = "covered_call"           # deferred (decision #8)

@dataclass(frozen=True, slots=True)
class OptionLeg:
    contract: ContractRef        # carries right/strike/expiration/shares_per_contract/style
    qty: int                     # signed: +long / -short. Never 0.

    @property
    def multiplier(self) -> int:
        return self.contract.shares_per_contract   # PER LEG. Never a module constant.

@dataclass(frozen=True, slots=True)
class OptionStructure:
    structure_type: StructureType
    underlying_symbol: str
    legs: tuple[OptionLeg, ...]
    contracts: int               # structure count; each leg's qty is per structure
```

### 4.2 Validation at construction (HYPOTHESIS)

`OptionStructure.__post_init__` raises unless **all** hold. These are not style checks;
each one is a specific way an options backtest manufactures edge:

1. `len(legs) >= 1` and no leg has `qty == 0`.
2. **Single underlying, single expiration** in Phase 1. A calendar/diagonal is a different
   R and a different risk model; forbid the type rather than leave a path that accepts one
   (MAP §2.3 Phase 1 restriction).
3. **Defined risk.** For `VERTICAL_CREDIT`: exactly 2 legs, same right, same expiration,
   opposite signs, equal absolute qty, and the long strike strictly **beyond** the short
   strike (further OTM). This is what makes the naked-short case unrepresentable in the
   type system rather than merely undesirable — the same discipline
   `options/simulators.py:1-9` already states for the education module ("naked/uncovered
   short options … NOT supported by design").
4. **`shares_per_contract == 100` on every leg**, else refuse and count (§4.3).
5. **`exercise_style == "american"` on every leg** in Phase 1, else refuse and count.
   FACT: 888 of 888 stored contracts are `'american'` (§3.6); an AM-settled cash-index
   contract appearing later must be refused mechanically, not filtered by an underlying
   allowlist comment (MAP §2.8 proposes the allowlist; the per-leg assertion is strictly
   stronger and costs nothing).
6. `contracts >= 1`.

Every refusal increments a named counter carried to gate 8. A refusal that is not counted
is a silent sample change.

### 4.3 CORRECTION C6 — the deliverable assertion has a hole

**FACT.** `OptionContract.shares_per_contract` is a real column
(`db/models/market.py:250`) with a **schema default of 100**, populated on every write
path: `data/options_ingest.py:97`, `data/options_backfill.py:151`, and at the adapter
boundary `data/adapters/massive_options.py:183`:

```python
shares_per_contract=int(r.get("shares_per_contract", 100)),
```

**Consequence.** A vendor payload that **omits** the field produces a stored `100` that is
indistinguishable from a vendor-confirmed `100`. The map's mechanical guard — "assert it
equals 100 at entry and refuse otherwise" (MAP §2.3) — therefore cannot distinguish
"the vendor said 100" from "the vendor said nothing". On an OCC-adjusted contract whose
payload is incomplete, the guard passes and the `× 100` arithmetic downstream is wrong on
exactly the contract D7 exists to exclude.

**Rule (HYPOTHESIS), one of — this is a D1 data-layer fix that D2 depends on:**

- **(a)** Make the column nullable and store `None` when the vendor omits it; the engine
  refuses `None` as it refuses `!= 100`. Requires a migration and an adapter change.
- **(b)** Add a sibling column `shares_per_contract_source ∈ {vendor, defaulted}` and
  refuse `defaulted` at entry. No semantic change to the existing column.
- **(c)** Weakest acceptable: leave the schema alone, and have the **backfill** record —
  in `IngestionRun.gaps_json` — the count of contracts whose payload lacked the field, so
  the evaluation can at least report the exposure.

**(b) is recommended**: it is additive, it makes the provenance explicit exactly as
`iv_source` / `q_source` / `fill_model` do elsewhere in this design, and it does not
change the meaning of an existing column. **Until one of (a)–(c) exists, gate 0.h's
assertion is weaker than the map claims and must be reported as such.** Flag for D1 and
D4.

**Also FACT (C9):** `corporate_action` has **0 rows**. `CorporateAction`
(`market.py:147-157`) supports `action_type ∈ {split, dividend, symbol_change}` with
`ex_date`, `ratio`, `amount` — so the schema *can* express D7's exclusion, but no data
populates it. Today the deliverable assertion is the **only** adjustment detector, and
C6 shows it is incomplete.

---

<a name="5"></a>
## 5. The signal / strategy interface

### 5.1 `OptionsEntrySignal` (HYPOTHESIS, refining MAP §2.3)

```python
@dataclass(frozen=True, slots=True)
class OptionsEntrySignal:
    structure: OptionStructure
    entry_session_index: int         # t; the fill is resolved at t+1 (see §6.1)
    # exit rule, all pre-registered constants interpolated into the spec text
    profit_target_pct_of_credit: float      # e.g. 0.50
    stop_multiple_of_credit: float          # e.g. 2.0
    time_stop_dte: int                      # e.g. 7
    # provenance, carried to the trade and to gate 0
    iv_source: IvSource                     # local_bs_inverted | same_session_surface | vendor | pct_otm_proxy
    q_source: str                           # per-underlying; gate 0.g
    r_source: str                           # per-session; gate 0.g extension (C7)
    reason: str = ""
```

Deliberately **absent**: `net_premium`, `max_loss_dollars`, `max_gain_dollars`,
`break_evens`. MAP §2.3 puts them on the signal. They must not be there: at signal time
(session *t*) no fill has occurred, and the map's own §6 fill rule prices the entry at
*t+1* prints. A signal carrying a premium is a signal carrying a price it cannot know
— the exact shape of a look-ahead bug. **These are computed by the engine at fill time
and live on `OptionTrade`.**

### 5.2 The strategy protocol (HYPOTHESIS)

```python
class OptionsStrategy(Protocol):
    key: str
    params: Any                               # a frozen dataclass — required by gate 5 (§1.2)
    def spec(self) -> StrategySpec: ...       # the EXISTING 25-field spec, unchanged
    def evaluate(
        self,
        chain: OptionChainSeries,             # already .head(t) — the engine truncates
        underlying: PriceSeries,              # already .head(t)
        t: int,
        ctx: StrategyContext,                 # reuse research.strategies.base:17-20
    ) -> OptionsEntrySignal | None: ...
```

`StrategyContext` (`research/strategies/base.py:17-20`, fields `regime: RegimeState`,
`allow_short: bool`) is reused unchanged — **FACT** it carries no equity-specific field.

**The engine truncates, the strategy does not.** Mirroring `engine.py:102`, the runner
calls `strategy.evaluate(chain.head(t), underlying.head(t), t, ctx)`. A strategy cannot
opt out of the truncation, and §13's leakage harness re-verifies it per feature.

### 5.3 Sensitivity axes and the grid cap

**FACT.** `_sensitivity_plan` (`research/promotion.py:255-340`) is a hard-coded
`if key.startswith(...)` chain over four equity families, returning `None` at
`promotion.py:340` for anything else — and `None` is a **gate 5 failure**, not a skip
(`promotion.py:1151-1161`). An options family needs a new branch in that chain. That is a
one-branch edit to `promotion.py` and it is unavoidable.

**FACT.** `sensitivity.MAX_GRID_POINTS = 120` (`research/sensitivity.py:29`), and
`run_parameter_sensitivity` **raises `ValueError`** above it
(`sensitivity.py:179-182`) — it does not fail the gate, it aborts the evaluation. A
pre-registered options grid must therefore be ≤ 120 points. `target_delta`(4) ×
`dte_window`(3) × `width`(3) = 36 is comfortable; adding a fourth 4-valued axis
(4×3×3×4 = 144) aborts. **D5 must check the product before pre-registering.**

**FACT.** `research/sensitivity.py:120-154` `_axis_movement` flags an axis as `inert` when
perturbing it alone changes neither OOS trade count nor expectancy at 4 d.p., and an inert
axis is a gate-5 **failure reason** (`sensitivity.py:231-235`). For options this is a real
trap: a `width` axis on a strategy whose stored chain offers only one width produces an
inert axis and fails gate 5 — correctly. That is gate 5 detecting the coverage problem of
§3.6, and it must not be worked around by removing the axis.

**FACT.** `DeclaresSensitivityAxes` (`research/strategies/base.py:31-48`) is an optional
Protocol picked up via `getattr` and merged by `_merge_declared_axes`. MAP §7 notes the
first options strategy would be the first anywhere to implement it. Nothing in D2 blocks
that; it is a strategy-class matter for D5/I-O5.

---

<a name="6"></a>
## 6. Fill model

### 6.1 Entry timing

**FACT (equity precedent).** `run_backtest` fills entries at `series.open[t+1]`
(`backtest/engine.py:108-110`) — the signal at *t* never transacts at *t*.

**Rule (HYPOTHESIS).** The options entry is resolved at session **t+1**, at that session's
**per-leg prints**. Not the option's open: **FACT** an option's daily open is a thin,
frequently-stale first print, and unlike the equity case there is no reason to prefer it
over the close. Use `OptionAggregateDaily.close` for every leg on the fill session, and
name it `last_print` everywhere.

### 6.2 Print, not mid — and a full spread per leg per side

**FACT.** `OptionAggregateDaily.close` (`market.py:290-318`) is a last-trade print. There
is no bid, no ask, and no mid anywhere in the schema. **FACT (entitlement, MAP §0.3 item 3,
re-stated here because the engine's disclosure depends on it):** `/v3/quotes/{O:contract}`
returns 403 in 7 of 7 `entitlement_check` batches, **and `/v3/quotes/{sym}` (equities NBBO)
returns 403 in 7 of 7 as well**.

**Rule (HYPOTHESIS — model 1a of MAP §2.4(1), adopted).** Per leg, per side:

```
adverse_fill(leg, session) =
    last_print + sign * full_modelled_spread(last_print, moneyness, dte)
    where sign = +1 when the engine is BUYING that leg (opening a long leg,
                    or buying back a short leg)
          sign = -1 when the engine is SELLING that leg
```

A **full** modelled spread, per leg, per side. Rationale, stated as the assumption it is:
the print's position within the true spread is unknown, so half-spreading it is arbitrary
**in sign** — a late-day print on a one-sided option market is already at a touch. The
conservative assumption is that it sat at the favourable touch and the fill must cross the
whole way. **A 2-leg vertical therefore pays a full modelled spread four times round
trip** (2 legs × 2 sides).

**Note the asymmetry with the equity engine, and do not paper over it.** FACT:
`run_backtest` applies `(slippage_bps + spread_bps/2) / 10_000` when
`half_spread_fill_penalty` is true (`engine.py:94`, `costs.py:16,25-28`). The equity path
is **half**-spread; the options path is **full**-spread per leg. These are different
conventions and every report must say which it used. They are not comparable, and §9.4's
cross-asset incomparability statement covers this too.

### 6.3 The modelled spread function

**Rule (HYPOTHESIS).**

```
full_modelled_spread(last_print, moneyness, dte) =
    max(spread_abs_floor_cents / 100.0,
        spread_pct_of_last_print * last_print)
```

Both constants live on `OptionCostModel` (§7), are pre-registered before the first
evaluation, and are recorded verbatim in the evaluation record (§14). Deliberately
pessimistic. Moneyness/DTE dependence is permitted as a **pre-registered, monotone**
multiplier (wider far-OTM, wider near expiry) — never a free-form table that can be tuned
after an outcome is seen (the same constraint MAP §2.4b puts on the surface fit).

**The spread is unbounded relative to the print, and one routine case is pathological.**
Nothing above relates the spread to the magnitude of the print it is applied to. Take the
routine case for a vertical — a long OTM wing printing at $0.05 against a 5-cent floor. The
1× modelled spread is then **100% of the print**, and gate 4b's 2× spread is **200%** of it,
so `last_print − spread` on the closing sale is **−$0.05**: the engine models being *paid*
to give a long option away. The sign is conservative, so it manufactures no edge — but it is
unbounded, it concentrates on exactly the wings §10.2 already excludes, and it inflates the
sub-−1R mass that §9.4's clamp would otherwise have hidden.

**Rules (HYPOTHESIS), bounding the fill:**

1. **A sale's modelled proceeds are floored at zero** — `proceeds = max(last_print − spread,
   0.0)` — and never go negative. A buy-side fill needs no upper bound: paying more is
   always the conservative direction.
2. **The modelled fill is rounded to a pre-registered tick grid**, carried on
   `OptionCostModel.tick_grid` and recorded verbatim in §14.3. Like `options_close_time` and
   `settlement_style` (§11.3), the grid is an asserted market-structure fact, not schedule
   data: it lives in a version-controlled constant table with its source named in a comment,
   never assumed. Rounding is **away from the engine** — up on a buy, down on a sale — so
   rounding can never improve a fill.
3. **Gate-8 counters (new):** `spread_ge_print_leg_sides` and `sale_proceeds_floored_at_zero`
   — count and fraction of leg-sides where the modelled spread met or exceeded the print, and
   where the zero floor bound, **reported at each spread setting**. That pair is the
   diagnostic that tells a reader whether the 2× run stressed the *strategy* or stressed the
   *arithmetic*: on a leg-side where the floor binds at both settings, 4b tested nothing.

**Named as a placeholder, always.** Precedent: `SF1000_SPEC.md` §5 already requires an
explicit "cost model: PLACEHOLDER spread proxy — not yet calibrated" label wherever a real
quote is unavailable (MAP §1.5 gate 0.f). The options `fill_model` string carries the same
label, plus the 403 disclosure for **both** asset classes.

### 6.4 A missing bar is a liquidity fact, never a fill

**Rule (HYPOTHESIS — MAP §2.4(3), adopted verbatim in substance, expressed as engine
states):**

| Situation | Engine behaviour | Counter for gate 8 |
|---|---|---|
| Any leg lacks a print on the intended **entry** session | **Non-entry.** The cycle is skipped. No synthetic fill. | `non_entry_missing_leg_bar` |
| A triggered exit's **fill** session (*t+1*, §10.1) has some leg without a print | The fill is **deferred** to the next session on which **every** leg prints, at that session's prints | `exit_deferred_sessions` (full distribution, not just a mean) |
| Any leg lacks a print on the `expiry − 1` **force-close** session | The trade is **excluded from the evaluation entirely** — see §10.2 | `force_close_unpriceable_exclusions` |
| A mark is needed for an unrealised value and a leg has no print | Mark from the §6.6 same-session surface **if that surface exists**; if it does not, the session is `iv_unavailable` and contributes **no mark at all** — see below | `synthetic_mark_fraction`, `unmarked_sessions` |

**`synthetic=True` on a fill must be unrepresentable in the type system.** The
`ContractPrint | None` return of `print_at` (§3.2) is what enforces this: a fill path that
takes `ContractPrint` cannot be handed a model price, because a model price is not a
`ContractPrint`. Make the mark a separate type (`Mark`) that the fill functions do not
accept. This is the difference between a rule and a comment.

**`iv_unavailable` is a terminal state, and rev 1 left it undefined.** Row 4 above routes an
unpriceable unrealised value to the §6.6 same-session surface — but §6.6(3) *hard-excludes*
that surface when fewer than **N** contracts on the (underlying, expiry) printed that
session. A position that can be neither printed nor marked therefore had no defined
behaviour, and an undefined state is precisely where a previous-close carry-forward or a
`0.0` gets added six months later by someone fixing a `None`.

**Rule (HYPOTHESIS).** On an `iv_unavailable` session the position contributes **nothing**:
no mark, no unrealised value, no MAE/MFE sample. MAE/MFE and every unrealised series are
computed **over marked sessions only**, and gate 8 carries `unmarked_sessions` as a count, a
fraction of held sessions, and the **maximum consecutive run** (a single scattered gap and a
two-week blackout are different facts). There is no previous-close carry-forward, no
last-good-mark, and no zero. Those three are named so that adding one is visibly a change to
this spec rather than a bug fix.

**The `Mark` firewall, in one sentence, because the type alone does not say it.** The
paragraph above makes a `Mark` unusable by a *fill* function. The invariant that actually
makes the type safe is larger: **a `Mark` participates in reported unrealised diagnostics
ONLY — never in an exit trigger, never in R, never in realised P&L, never in any gated
statistic.** §10.1's stop and profit target are evaluated on the structure's net premium
**from prints**; on a session where any leg lacks a print the trigger is not evaluable, and
the position is simply carried. §15.2 test 24 asserts that a `Mark`-only session cannot fire
either one.

### 6.5 CORRECTION C7 — `r` needs the same treatment as `q`

**FACT.** `OptionsConfig.risk_free_rate: NonNegativeFloat = 0.04` with the comment
"simulator assumption, not vendor data" (`config/research.py:205`). It is a **single
scalar with no date dimension**. **FACT.** A repo-wide grep for `risk_free|treasury` finds
exactly that one line and nothing else — **there is no rate series anywhere in the
schema**.

**FACT.** `r` enters `_d1_d2` (`options/blackscholes.py:42-45`) through
`(r - q + 0.5σ²)t` and the discount factors `exp(-r t)` (`blackscholes.py:56`), so it sets
the forward used by both the price and the IV inversion.

**Why this matters, HYPOTHESIS but directionally certain.** Over a 3–5 year backfill
window, U.S. short rates moved by several hundred basis points. Holding `r` at 4.00% across
the whole window mis-states the forward by roughly `(r_true − 0.04)·T`. At `T = 0.12 yr`
(≈45 DTE) and a 300 bp error, the forward is mis-stated by ≈0.36%, which for a near-ATM
contract translates into a non-trivial IV-inversion error — in a **direction that is
systematic across an entire sub-period of the sample**, not noise. A strategy whose
selection rule is "the strike nearest 0.20 delta" is then selecting different strikes in
2022 than the rule specifies.

**Rule (HYPOTHESIS).** The engine takes `r` **per session**, from a pre-registered source,
and records `r_source` per evaluation exactly as `q_source` is recorded. Gate 0.g is
extended: *a run that used a constant `r` across a multi-year window fails gate 0.g
outright*, for the same reason `q = 0.0` does. If no rate series can be sourced, the
honest fallback is a **pre-registered piecewise-constant schedule keyed to calendar
quarters, committed before the backfill is inspected** — worse than a real series, far
better than one number. **This is a D1 data item and a D4 gate item; D2's requirement is
only that the engine's signature is `r: float` *per session*, never a module constant.**

### 6.6 The IV the mark comes from (decision #7, MAP §2.4b)

The engine consumes IV; it does not choose the policy. Decision #7 is binding: local
Black-Scholes inversion from a print, plus the same-session surface where nothing printed.
D2's requirements on that machinery:

1. **Inversion.** `options/blackscholes.implied_vol` (`blackscholes.py:93-123`) — FACT:
   bisection on `[1e-6, 5.0]`, `tol=1e-6`, `max_iter=100`, returning `None` outside the
   no-arbitrage band (`blackscholes.py:107-112`). It is deterministic and needs no change.
   `None` must propagate as `iv_unavailable`, never as a default.
2. **Surface fit is cross-sectional and same-session only** — it reads session *t* and
   nothing else, so under `head(t)` it is trivially look-ahead-free. Per expiry, IV as a
   function of log-moneyness, a **pre-registered low-order or monotone fit**. No spline
   with free knots; no optimiser with random restarts; a fixed, documented ordering of the
   input points so the fit is bit-reproducible (S4 determinism).
3. **Hard exclusion, no extrapolation.** If fewer than **N** contracts on that
   (underlying, expiry) printed on that session, there is no surface: mark
   `iv_unavailable`. MAP's pre-registered hypothesis is **N = 5 per expiry with ≥3 distinct
   strikes on the relevant side**; D5 fixes the number before the backfill is inspected.
   For what `iv_unavailable` means *operationally* — the session contributes no mark, and the
   count, fraction and maximum consecutive run are reported — see §6.4.
4. **Realised volatility is forbidden as a fallback** (MAP §2.4b). For a premium-selling
   strategy, realised vol sits below implied on average — the volatility risk premium is
   the thing being harvested — so marking unsold short premium at realised vol inflates
   simulated credit capture on exactly the trades the strategy claims as its edge. If a run
   ever falls back to realised vol it is not evidence. **Make it unrepresentable:**
   `IvSource` is a `StrEnum` with no `realized_vol` member, and the mark function accepts
   only an `IvSource`.

---

<a name="7"></a>
## 7. `OptionCostModel`

### 7.1 The dataclass (HYPOTHESIS, refining MAP §2.5)

New file `backtest/options_costs.py`. **Not** a subclass of `CostModel` — shares and
contracts flow through different formulas, and R4 freezes `CostModel`
(`backtest/costs.py:11-35`) for the program's duration.

```python
@dataclass(frozen=True, slots=True)
class OptionCostModel:
    # NO DEFAULTS ON ANY FIELD. An omission is a TypeError at construction, not a
    # free backtest. See §7.4 — this is a correction to rev 1, not a style choice.
    commission_per_contract: float
    commission_min_per_order: float
    exchange_fee_per_contract: float            # ORF/OCC-style per-contract fees
    spread_pct_of_last_print: float             # §6.3
    spread_abs_floor_cents: float               # §6.3
    tick_grid: tuple[tuple[float, float], ...]  # §6.3 — (price_threshold, tick), pre-registered
    assignment_fee: float
    exercise_fee: float
    spread_multiplier: float                    # §8 — 1.0 baseline, 2.0 for the 4b run

    def __post_init__(self) -> None:
        if self.spread_pct_of_last_print == 0.0 and self.spread_abs_floor_cents == 0.0:
            raise ValueError("a zero-spread options cost model is not a cost model")
        if self.spread_multiplier not in (1.0, 2.0):
            raise ValueError("spread_multiplier is 1.0 (baseline) or 2.0 (gate 4b)")

    def commission(self, n_contract_sides: int) -> float: ...
    def fees(self, n_contract_sides: int) -> float: ...
    def spread(self, last_print: float, *, moneyness: float, dte: int) -> float: ...
```

### 7.2 Cost scales with legs × contracts × sides

A 2-leg vertical, 1 structure, round trip = **4 contract-sides**: commission ×4, exchange
fee ×4, and (under §6.2) **four full modelled spreads**. The engine must compute cost from
`sum over legs of abs(qty) × contracts`, never from a structure count.

### 7.3 Frozen before the first evaluation

R4 freezes `CostModel` for the program (`STRATEGY_COMPLETION_MAP.md` §1 R4).
`OptionCostModel` is a *new* object, so its values are a **one-time decision made before
the first options evaluation and then frozen identically for the program's duration** —
exactly as MAP §2.5 states. Because it cannot go into `SCOPE_HASH_FIELDS` (§14 / C1), the
freeze is enforced by (a) the values living in version-controlled config, (b) their verbatim
inclusion in `options_config_hash`, and (c) their verbatim inclusion in the per-evaluation
record. All three, not one.

### 7.4 No defaults at all — rev 1's zeros were the opposite of its stated intent

Rev 1 declared every field `= 0.0` and said D2 "deliberately proposes no default values …
beyond the zeros above". The zeros do not express that intent; they defeat it. A D5
pre-registration that omits a field, or **any** test or CLI path that constructs
`OptionCostModel()`, yields a **zero-commission, zero-fee, zero-spread** backtest. And
because gate 4b is a *multiplier* (§8.2), `2 × 0 = 0` — the dual-spread gate passes
**vacuously** on a cost model that charges nothing. That is the cheapest available way to
publish a stress test that stressed nothing, and decision #5 makes 4b permanent, so it would
be published on every options evaluation for the life of the program.

**Rules (HYPOTHESIS, corrected):**

1. **No field carries a default.** An omission is a `TypeError` at construction. MAP §3.2's
   standing caveat still holds — any number in a D-phase document is an evaluation grid
   centre for the operator to set, never a recommendation — so D2 still proposes no
   *values*. It now proposes that there be no way to avoid choosing them.
2. `__post_init__` **refuses** a model whose two spread parameters are both zero, and refuses
   a `spread_multiplier` outside `{1.0, 2.0}`.
3. `run_options_backtest` **refuses** a cost model whose `spread()` returns `0.0` for any leg
   it prices, counts the refusal, and surfaces the count at gate 8 as `zero_spread_refusals`.
   A model that is non-zero in the constructor but zero in practice — a percentage of a zero
   print, against a zero floor — is the same defect one layer down, and the constructor check
   cannot see it.
4. §7.3's R4 freeze governs the values **once chosen**. This section is only about there
   being no path on which they go unchosen.

---

<a name="8"></a>
## 8. The two-spread rule (gate 4b) — what it actually costs to wire

### 8.1 CORRECTION C2 — the equity half is a three-call-site plumbing job, not zero

MAP §5.2 and §0.4 state that gate 4b is "cheap on the backtest side (the parameter already
exists; it is a call-site/config plumbing job)" and that "only `paper/ledger.py:50
_NOMINAL_SPREAD_BPS` needs lifting into config". The first half understates the work.

**FACT — the full call chain from `evaluate_promotion` to `run_backtest`:**

| Step | `file:line` | Does it forward `spread_bps`? |
|---|---|---|
| `run_backtest(series, signal_fn, *, cost_model=None, spread_bps=5.0, warmup=50)` | `backtest/engine.py:85-92` | it **is** the parameter |
| `run_strategy_over_universe` → `run_backtest(series, fn, cost_model=cost_model, warmup=min_bars // 2)` | `research/backtest_runner.py:205-207` | **No.** `spread_bps` is not passed and is not a parameter of the function |
| `run_parameter_sensitivity` → `run_strategy_over_universe(...)` | `research/sensitivity.py:190-201` | **No.** Not a parameter |
| `evaluate_promotion` → `run_strategy_over_universe(...)` (gates 1–8 evidence) | `research/promotion.py:1042-1053` | **No** |
| `evaluate_promotion` → `run_parameter_sensitivity(...)` (gate 5) | `research/promotion.py:1166-1183` | **No** |

So `spread_bps=5.0` (`engine.py:90`) is the *effective* value on every promotion-path
backtest that has ever run, and it is unreachable without adding the parameter to
`run_strategy_over_universe` **and** `run_parameter_sensitivity` **and** threading it from
`evaluate_promotion`. Three signatures, four call sites.

### 8.2 CORRECTION C2 (second half) — "2× spread" is not 2× the spread paid

**FACT.** `run_backtest` computes
`slip = (cm.slippage_bps + (spread_bps / 2 if cm.half_spread_fill_penalty else 0.0)) / 10_000`
(`engine.py:94`), and `CostModel.half_spread_fill_penalty` defaults to `True`
(`costs.py:16`). So `spread_bps=10.0` yields a **5 bps** per-side penalty, not 10.

**Consequence.** Gate 4b's "2× modelled spread" on the equity side must be specified as
**"the spread *assumption* doubles from 5.0 bps to 10.0 bps"**, which doubles the
half-spread actually charged from 2.5 to 5.0 bps per side — i.e. round-trip cost goes from
11 bps to 16 bps, **not** from 11 to 22. The report must state the round-trip figure, not
the parameter, or the gate's stringency will be misread.

**Rule (HYPOTHESIS).** On the options side, doubling is unambiguous because §6.2 already
charges a full spread: `OptionCostModel.spread_multiplier ∈ {1.0, 2.0}` multiplies the
value returned by `spread()`. Use a single named field so the 4b run differs from the
baseline run in **exactly one recorded scalar** and nothing else.

### 8.3 The rule (binding — decision #5 makes 4b permanent)

Gates 2, 3, and 4 must clear at **both** the baseline and the 2× spread setting, on
**both** asset classes. Per MAP §5.2 and R4 this is strictly *more* searching, which R4
permits; and per R1/R3 the equity application takes a specific form:

- Run 4b on the **pre-sealed** span for both PAPER_APPROVED strategies and publish it as
  evidence. **FACT:** `StrategySealedTest` carries
  `UniqueConstraint("strategy_version_id", "dataset_snapshot_id")`
  (`db/models/research.py:263`), and `_get_or_create_sealed_test` returns
  `(existing, True)` — "locked — never recomputed, never overwritten" — the moment such a row
  exists (`promotion.py:763-793`), **even though it takes `cost_model` as a parameter**
  (`promotion.py:774`). The sealed window is pinned to the existing row's
  `window_start`/`window_end` too (`promotion.py:938-952`). So a 2× re-run **cannot** alter
  an existing sealed record even if someone tried.

- **The corollary rev 1 did not draw, and it is the one that matters.** "Cannot recompute"
  and "will replay" are the same mechanism read from two ends. A 2×-spread re-evaluation of
  either PAPER_APPROVED strategy on the same snapshot therefore emits a **gate-9 line that
  was computed at the BASELINE cost model**. A report headed "passes at 2× spread" that
  carries that gate-9 line is claiming stress-test evidence it does not have — and it is the
  single most authoritative-looking line in the report. **Rule (HYPOTHESIS):** the 4b
  evidence run is published as **gates 1-8 only**. Gate 9 is either omitted or labelled
  verbatim — *"replayed sealed result, locked under the BASELINE cost model; not re-measured
  at 2×"* — and that label travels with the number wherever it is quoted, including into a
  disposition document.

- A failure at 2× is a **disposition** input under R1 and a **version bump** under R3. It
  is never a silent re-seal. **And the version bump is not free.** A new `StrategyVersion`
  earns a fresh sealed look, and `count_sealed_looks` (`promotion.py:647`) counts it for the
  whole **family**, every version, every snapshot — so the family moves from *k* to *k+1*.
  MAP §5.4 records both live equity strategies at **k=4** today. That multiplicity cost must
  be named in the disposition **at the moment it is paid**, not discovered later from the
  ledger; `sealed_look_prior` and the family's *k* are in the §14.3 record for exactly this.

### 8.4 The paper-side constant

**FACT.** `paper/ledger.py:50` `_NOMINAL_SPREAD_BPS = 5.0` is a module constant with no
override path, used at `ledger.py:163` and `ledger.py:166` to price every live paper fill.
Lifting it into config is a D3/I-O6 item, listed here only so the 4b story is complete: an
options engine that runs at two spread settings while the paper ledger prices at one
hard-coded setting is internally inconsistent.

---

<a name="9"></a>
## 9. R = max loss: the definition, its two variants, and the consequences

### 9.1 Why the equity definition cannot carry over

**FACT.** `run_backtest` computes `risk_per_share = abs(entry_fill - sig.stop_price)`
(`engine.py:111`) and `pnl_r = d * (exit_fill - entry_fill) / risk_per_share`
(`engine.py:128`). For a 2-leg structure there is no "entry price", no single
"stop price", and no per-share unit.

### 9.2 The definition (HYPOTHESIS, per MAP §2.6)

With `M = leg.contract.shares_per_contract` read **per leg** (§4.1, asserted `== 100` in
Phase 1) and `C = structure.contracts`:

```
vertical credit spread : R_at_print = strike_width × M × C − net_credit_at_print
vertical debit spread  : R_at_print = net_debit_at_print
cash-secured put       : R_at_print = strike × M × C − net_credit_at_print
covered call           : no clean R — deferred behind O3 (decision #8); see MAP §4.2

R_incl = R_at_print + entry_costs     # the GATING basis (§9.3); the structural max loss
pnl_r  = realised_pnl_dollars / R
```

**`net_credit_at_print` / `net_debit_at_print` are computed from each leg's *unadjusted*
`last_print` on the fill session** — before any modelled spread, commission or fee is
applied. That is what makes `R_at_print` a fixed denominator across spread settings, and it
is also what makes it an accounting device rather than an economic quantity: **nobody ever
receives the print credit**, because §6.2 fills the entry across the whole modelled spread.
See §9.3.

`realised_pnl_dollars` is **net of all costs** (commission, fees, and the four modelled
spreads), matching the equity convention that costs are baked into `pnl_r`
(`backtest/metrics.py:1-6`: "All figures are net of modeled costs").

### 9.3 CORRECTION C8 — two R bases, and why gate 4b forces the issue

MAP §2.6 writes `R = (strike_width × M × C) − net_credit + entry_costs` — entry costs
**inside** the denominator. That choice has a consequence the map does not draw:

**Under gate 4b, doubling the modelled spread changes `entry_costs`, so it changes R.**
The 2× run then moves numerator *and* denominator, and a change in `pnl_r` cannot be
attributed to the cost stress. Gate 4b stops being an interpretable stress test.

**But excluding entry costs from R makes R smaller, which makes every winner's `pnl_r`
larger — i.e. it slightly *weakens* gates 3 and 4.** R4 forbids weakening a gate.

**A defect in rev 1 of this section, corrected here, because the whole four-way scheme rests
on it.** Rev 1 defined `R_excl = strike_width × M × C − net_credit_received` and asserted it
was "invariant to the cost model". It is not. §6.2 fills the entry at
`last_print ± full_modelled_spread`, so the credit *received* is **already spread-adjusted**,
and `spread_multiplier` moves it. On this section's own inputs: at 1× the received credit is
`(2.00 − 0.06) − (0.90 + 0.05) = 0.99`, so `R_excl` would be `500 − 99 = 401`; at 2× it is
`(2.00 − 0.12) − (0.90 + 0.10) = 0.88`, so `R_excl` would be `500 − 88 = 412`. The
denominator gate 4b was promised as fixed moves by 2.7%, and §15.2's test 13 ("`R_excl` is
invariant to `spread_multiplier`") would have **failed as written**. Rev 1's own arithmetic
below silently used the raw print credit ($1.10 / $110) instead — which is the definition
that actually has the invariance property. So the term is renamed and defined on the prints.

**Rule (HYPOTHESIS — resolves both, and binds on the strictest of the resulting cells):**
compute **both** bases.

```
R_at_print = structural max loss from the UNADJUSTED prints (the formulas in §9.2)
             # genuinely invariant to the cost model: no cost term appears in it
R_incl     = R_at_print + entry_costs        # the map's definition; the true max loss
```

- **`R_at_print` is a fixed-denominator *reporting* basis, not an economically realisable
  R.** No one receives the print credit. Its only job is to hold the denominator still so
  that a change in `pnl_r` between the 1× and 2× runs is attributable entirely to the
  numerator. **No gate ever binds on it.**
- **Gates 3 and 4 bind on `R_incl`** — the stricter basis for a positive-expectancy strategy,
  since a larger denominator shrinks expectancy.
- **All four numbers (basis × spread setting) are reported, and the gate binds on the worst
  of the four.** By construction that is **`R_incl` at 2×**: the largest denominator against
  the smallest numerator. Publishing the other three is disclosure, not slack — reporting an
  easier basis alongside a binding one is only honest if the document says which one binds,
  which is why this sentence exists.
- The evaluation record names which basis each reported figure used, **and which series**
  (clamped or unclamped, §9.4). A gate report that does not say which R it divided by is not
  a gate report.

**Worked arithmetic, so the size of the effect is on the record** (HYPOTHESIS for the cost
inputs; the arithmetic is deterministic given them). SPY 5-wide put credit spread, 1
structure, short leg print $2.00, long leg print $0.90, net credit $1.10 = $110;
`spread_pct_of_last_print = 3%`, `spread_abs_floor_cents = 5`;
`commission_per_contract = $0.65`; `exchange_fee_per_contract = $0.05`.

```
short-leg entry spread = max(0.05, 0.03 × 2.00) = 0.06   ->  $6.00
long-leg  entry spread = max(0.05, 0.03 × 0.90) = 0.05   ->  $5.00
entry costs = $6.00 + $5.00 + 2×$0.65 + 2×$0.05 = $12.40
```

**Rev 1 then set the exit costs equal to the entry costs. §6.3 forbids that**, and the error
understates the breach by roughly a factor of two. The modelled spread is
`max(floor, pct × last_print)` — a function of the *print* — and at max loss the legs are
nowhere near their entry prints: the structure is worth the full width, so the short put
prints around $8.00 and the long put around $3.00. Recomputing the exit on the section's own
inputs:

```
short-leg exit spread = max(0.05, 0.03 × 8.00) = 0.24   ->  $24.00
long-leg  exit spread = max(0.05, 0.03 × 3.00) = 0.09   ->  $9.00
exit costs at max loss = $24.00 + $9.00 + 2×$0.65 + 2×$0.05 = $34.40

R_at_print = 5 × 100 × 1 − 110                    = $390.00
R_incl     = 390.00 + 12.40                       = $402.40
max realised loss = −390.00 − 12.40 − 34.40       = −$436.80

pnl_r at max loss, R_incl basis:      −436.80 / 402.40 = −1.086
pnl_r at max loss, R_at_print basis:  −436.80 / 390.00 = −1.120

at 2× spread: entry costs $23.40, exit costs $67.40, max loss −$480.80
  R_incl(2×) = 390.00 + 23.40 = 413.40   ->  −480.80 / 413.40 = −1.163
  R_at_print (denominator unchanged)     ->  −480.80 / 390.00 = −1.233
```

So **the −1 bound is breached by roughly 9% to 23%**, not the 3–12% rev 1 reported. MAP §2.6
is right that the bound is not enforced; this is the size of the breach. Two consequences
carry forward: **D5's pre-registered clamp-rate ceiling (§9.4) is set against these figures,
not rev 1's**, and D5 must state the **max-loss leg prints it assumed**, because the exit
spread is a function of them and the whole number moves with that assumption.

### 9.4 The clamp, and what must be measured

**Rev 1 adopted MAP §2.6 Option 1 (clamp realised loss at −1R) and never said which series
the gates divide. Read plainly, that is a gate weakening, and R4 forbids it.** Clamping
truncates the **left** tail. Truncating the left tail mechanically **raises** mean
expectancy and **raises** the bootstrap lower bound — which are precisely the statistics
gate 3 tests (`min_net_expectancy_r`) and gate 4 stresses. §9.3's corrected numbers put the
suppressed mass at **8.6%–23.3% of R per max-loss trade**; at even a 10% max-loss rate that
is one to two points of expectancy handed back, the same order as the threshold itself.
`STRATEGY_COMPLETION_MAP.md` §1 R4 permits a change "when it makes a gate *runnable or more
faithful* without making it *easier to pass*". This one only makes it easier to pass.

**Rule (HYPOTHESIS, corrected — the clamp survives, but not on the gate path):**

1. **Every gate statistic is computed on the UNCLAMPED `pnl_r` series.** Gates 2, 3, 4, 4b,
   7 and 9, and every `compute_metrics` / `bootstrap_ci` / `compute_portfolio_metrics` call
   that feeds a gate, take the unclamped series. No exception, and no configuration flag that
   could introduce one.
2. The clamped series exists **only** as a supplementary reported line, labelled as such.
   `OptionTrade.r_clamped = True` marks the trades it would affect; the flag is a label on a
   diagnostic, not a transformation of the gated data.
3. Gate 8 reports the **clamp count and fraction**, the **unclamped `pnl_r` distribution**,
   and its **empirical minimum**. A clamp rate above a pre-registered ceiling is itself a
   gate-8 finding — the cost model and the exit rule are inconsistent with the structure.
4. The original motivation for clamping was real and is kept as an *option on the reporting*,
   not on the gate: **FACT** `bootstrap_ci` (`backtest/montecarlo.py:15-64`) resamples the
   raw R sequence with a fixed seed (`montecarlo.py:19` `seed=20240101`, `n_resamples=2000`)
   and computes percentiles, so unclamped tails below −1 widen the CI in a way that is real
   but cost-model-driven. If the orchestrator wants the clamped CI for readability,
   **publish both CIs and bind the gate on the worse of the two.** Publishing only the
   clamped one is not available.
5. Every reported figure names the series it used — `clamped` or `unclamped` — in the §14.3
   record. A figure that does not name its series is not evidence. §15.2 test 26 asserts the
   gate statistic actually moves when a sub-−1R trade is present, so the rule cannot rot into
   a comment.

### 9.5 The incomparability consequence (MAP §5.1, carried into the engine)

Because R is max loss and max loss is a property of the structure, R varies by ~100×
between a 5-wide vertical (R ≈ $390) and a cash-secured put on the same underlying
(R ≈ $44,500). **Engine-level enforcement (HYPOTHESIS):**

1. `OptionTrade` carries `structure_type` and `r_basis ∈ {at_print, incl}` as **required**
   fields.
2. The runner **raises** if a trade list handed to `compute_metrics`, `bootstrap_ci`, or
   `compute_portfolio_metrics` contains more than one `(structure_type, r_basis)` pair.
   MAP §5.1's "forbid pooling across structures" becomes a runtime precondition, not a
   convention. This is the cheapest possible implementation of gate 0.5
   (one structure type per strategy version) and it catches the mistake at the point where
   it would corrupt a statistic.
3. Every gate report prints the structure type and the R basis next to every R figure.
4. The equity ↔ options comparison is never made: an equity +0.30R, a vertical +0.30R, and
   a CSP +0.30R are three different claims, and §6.2's half-vs-full spread convention
   difference is a second, independent reason they are not comparable.

---

<a name="10"></a>
## 10. Expiry, force-close pricing, intrinsic floor, pin band, assignment

**FACT (the gap this fills).** `_resolve_exit` (`backtest/engine.py:154-184`) knows only
stop / target / time-stop / end-of-data. `paper/ledger.py::mark_to_market` prices positions
off the **underlying's** OHLCV bars with no expiry branch. Nothing anywhere models expiry,
assignment, exercise, or pin risk.

### 10.1 Exit precedence, and exit *timing* (HYPOTHESIS)

**Precedence.** Evaluated on each session's close, in this order — mirroring the equity
engine's "stop checked first" discipline (`engine.py:165-182`):

1. **Stop** — net premium ≥ `stop_multiple_of_credit × entry_credit` (for a credit
   structure). **Close-basis only** (§10.5).
2. **Profit target** — net premium ≤ `(1 − profit_target_pct_of_credit) × entry_credit`.
3. **Time stop** — `dte(session) <= time_stop_dte` (grid centre 7 DTE).
4. **Force close** — the `expiry − 1` session, unconditionally.

**Timing — a correction to rev 1, and it removes a free option the strategy never had.**
Rev 1 resolved an exit on a session's close and filled it at **that same session's** prints.
That is unattainable, and it is asymmetric with §6.1's entry rule, which exists precisely
because a signal at *t* cannot transact at *t* (`engine.py:102,108-110`) — §5.1 of this
document condemns the same thing on the signal side ("a signal carrying a price it cannot
know"). The equity engine's same-bar exit is legitimate only because a stop there is a
**resting order** touched intrabar and filled at `min(open, stop_price)`
(`engine.py:165-182`). §10.5 states flatly that there is **no live stop order** anywhere in
this design (`close_basis_stop`), so the close must first be **observed** and can only then
be acted on. Filling at the observed close books the profit target at exactly the target
price, with no overnight gap risk, on every winning trade.

**Rule (HYPOTHESIS, corrected), splitting the four exits by whether they are knowable
*before* the session:**

| Exit | Knowable before the session opens? | Trigger | Fill |
|---|---|---|---|
| 1 Stop | **No** — needs session *t*'s close | *t*'s close | **session *t+1*'s prints**, under §6.2's adverse-fill rule |
| 2 Profit target | **No** — same | *t*'s close | **session *t+1*'s prints** |
| 3 Time stop | **Yes** — pure calendar arithmetic | known at *t*'s open | session *t*'s prints (a scheduled, MOC-style exit) |
| 4 Force close (`expiry − 1`) | **Yes** — pure calendar arithmetic | known at *t*'s open | session *t*'s prints |

A triggered exit that cannot be priced (some leg has no print) is **deferred**, not
abandoned (§6.4) — and the deferral is measured from the **fill** session, not the trigger
session: if any leg lacks a print on *t+1*, the fill moves to the next session on which
every leg prints, and `exit_deferred_sessions` counts from *t+1*.

**Stated because it is the point:** a stop or target exit now carries **one session of gap
risk** that rev 1's rule removed. That is the honest direction, and it is the direction that
makes the gates harder, not easier.

### 10.2 Entry eligibility closes the force-close pricing hole

**Rule (HYPOTHESIS — MAP §2.7, adopted).** A structure may be entered only if its
force-close session can price **every** leg from prints. Operationally: if on the actual
`expiry − 1` session any leg lacks a bar, the trade is **excluded from the evaluation
entirely** and counted, rather than force-closed at a synthetic mark.

**State the awkward part plainly, because it is the whole point.** This condition is
evaluated with information from *after* the entry — it is a **sample-construction rule
applied with hindsight**, not a tradable rule. It is admissible only because it is
*exclusionary*: it can only ever remove trades from the sample, never add one. The honest
characterisation is: **a long OTM wing that stops trading near expiry — the routine case for
a vertical — is removed from the sample, not silently marked.** A wing that does not trade
cannot be sold.

**The bias is measurable, and rev 1 declared it unknowable — corrected.** Rev 1 said in one
sentence that the exclusion removes trades "for a reason … uncorrelated with the sign of the
outcome in no obvious direction" and in the next that "the bias direction is **not**
confidently signable". Those are two different claims, they contradict each other, and
neither was evidenced. In fact the direction is estimable from data that is **always**
present: **FACT** the underlying's close on the expiry session lives in `OHLCVDaily`
whether or not any option leg printed, the strikes are known, and the entry credit is known
(the entry session priced every leg, or §6.4 would have refused the entry). So the
**intrinsic-at-expiry** payoff of every excluded structure is computable from the underlying
alone.

**Rule (HYPOTHESIS), replacing the assertion with a measurement.** Gate 8 reports, alongside
`force_close_unpriceable_exclusions` (count **and** fraction of candidate cycles), the
**intrinsic-at-expiry `pnl_r` distribution of the EXCLUDED cycles** — computed on the same R
basis as the included ones, from the underlying's expiry-session close and the entry credit:
mean, median, and the fraction landing at full max loss. Compared against the included
sample's distribution, that *is* the measurement of the exclusion's bias, in direction and
in magnitude.

Two disclosures attach to it, and both must travel with the number. It is an **intrinsic-only**
payoff — no exit costs, no early-assignment path, and the underlying's daily close is not the
expiry settlement print — so it estimates the sign and order of magnitude, not a P&L. And it
is a **diagnostic**: an excluded cycle is never added back into any gated statistic, because
the reason it was excluded (no price existed) has not gone away.

The pre-registered ceiling stands: a fraction above it and the evaluation is not evidence at
all, regardless of what the excluded distribution looks like.

### 10.3 Per-leg force-close pricing with an intrinsic floor

Where all legs print on the force-close session:

```
short leg exit (BUY-BACK) = max(intrinsic, last_print) + spread    # paid, hence +
long  leg exit (SELL)     = max(last_print − spread, 0.0)          # NO intrinsic floor
    intrinsic = max(S − K, 0) for a call, max(K − S, 0) for a put,
                × M × C, with S = underlying close on that session
```

**The floor is asymmetric, and rev 1 applied it to both legs — corrected.** Rev 1's single
rationale is a statement about a leg being **bought**: "a short leg is never bought back for
less than its intrinsic value." On a leg being **sold** — the long wing of a vertical, at
every exit — the identical floor raises assumed **proceeds** above the last print, which is
favourable to the strategy, not conservative, and rev 1 presented the floor as a conservatism
mechanism without noting the sign flip. For a vertical the two partly offset; for the
cash-secured put and the covered call specified in §9.2 they do not offset at all.

So the intrinsic floor applies **only to the buy side**. A stale low print on a long leg
being sold understates proceeds, which is the conservative direction, and is therefore kept
as-is (floored at zero per §6.3, never below). **Gate-8 counter (new):**
`long_leg_intrinsic_gap_dollars` — the aggregate dollar difference between the long legs'
intrinsic value and their modelled sale proceeds, at each spread setting — so the size of the
conservatism this choice imposes is measured rather than assumed.

**Note the sign correction.** MAP §2.7 writes the short leg as
`min(−intrinsic, −last_print) − spread`. Written in *cost-to-close* terms rather than
signed-value terms, the rule is: **a short leg is never bought back for less than its
intrinsic value, and the spread is always paid.** `max(intrinsic, last_print) + spread`
says exactly that and is harder to get wrong. The economic content is identical to the
map's intent; the expression is not.

**Why the floor.** Without it, a stale print on a deep-ITM leg produces a fictional profit:
the engine closes a $5-intrinsic short for its last $0.40 print. **FACT (MAP §2.6(b)):**
the floor is one of the two mechanisms that can push realised loss past −1R, which is why
§9.4 measures the breach rather than asserting the bound.

**FACT.** `options/blackscholes.price` already returns `max(intrinsic, 0.0)` when `t <= 0`
or `sigma <= 0` (`blackscholes.py:52-54`), so the intrinsic convention is already encoded
in the shared math module and the engine should call it rather than re-deriving it.

### 10.4 Pin band

**Rule (HYPOTHESIS — MAP §2.7).** A pre-registered pin band around each short strike:
**±0.5% of the underlying, or ±1 strike increment, whichever is narrower**. If the
underlying closes inside the band on the force-close session, set
`OptionTrade.pin_risk_flag = True`. Gate 8 reports the pinned fraction **and their R
distribution separately**. Rationale, unchanged: a strategy whose edge concentrates in
pinned trades has demonstrated a modelling artefact, not an edge.

The band is a D5 pre-registration item, fixed before any outcome is inspected (R1).

### 10.5 CORRECTION-adjacent: the stop is explicitly a close-basis stop (MAP §5.2a)

**FACT.** The equity engine handles the analogue explicitly: a stop touched intrabar fills
at `min(open, stop_price)` for a long (`engine.py:166-171`) — a gap through the stop fills
at the **open**, not the stop. The options design cannot port that: there is no intrabar
option data at all, and `OptionAggregateDaily`'s `high`/`low` are the *option's* intraday
range, which for a thin contract is a range of a handful of prints, not a continuous path.

**Rule (HYPOTHESIS).**

1. The stop is checked **only** against the session close of the structure's net premium,
   and is never treated as an intraday trigger. `fill_model` records the string
   `close_basis_stop` so no reader can mistake it for a live stop order.
2. **Do not use the option's daily `high`/`low` to simulate an intraday stop touch.** A
   two-print day has a `high` and a `low` that are two prints, not a path; treating them as
   a touchable range manufactures fills that were never reachable.
3. Every evaluation reports the full distribution of `realised_loss / R` and specifically
   the **count and fraction of trades that closed worse than
   `stop_multiple × credit`** — those are the trades where the stop did not protect. Pair
   it with the `r_clamped` count (§9.4): both measure the same phenomenon from opposite
   ends.

### 10.6 Assignment and early exercise

**FACT.** `OptionContract.exercise_style` defaults to `'american'` (`market.py:250`) and is
`'american'` on **888 of 888** stored rows (§3.6). Early assignment is real.

**Phase 1 treatment (HYPOTHESIS — MAP §2.7, adopted with its disclosure requirement):**

- The force-close rule **approximates early assignment away**. It does not model it.
- That approximation is **biased in the strategy's favour** — it removes the tail in which
  a short leg is assigned at the worst moment — and that direction must be stated on every
  evaluation record, not buried.
- **`assignment_risk` flag, recorded not modelled.** If the short leg is ITM beyond a
  pre-registered threshold on any close before the force-close session, set
  `OptionTrade.assignment_risk = True`. Gate 8 reports the flagged fraction and their R
  distribution separately, exactly as for pinned trades.
- **Dividend-driven early assignment on short calls** — the main real-world case — is **not
  modelled at all** in Phase 1. Disclose; do not approximate. This is the second place `q`
  matters (§6.5 / MAP §2.4a): with `q = 0` the model cannot even *rank* which short calls
  were at risk, so even the flag would be uninformative.
- **C9 (FACT):** `corporate_action` has 0 rows, so D7's "exclude cycles crossing an
  adjustment event" has no data source beyond §4.3's deliverable assertion, which C6 shows
  is itself incomplete. The evaluation record must say so rather than implying the
  exclusion is enforced.

---

<a name="11"></a>
## 11. `options_calendar.py`, designed for the execution layer too

**FACT.** `data/calendar.py` (`calendar.py:1-101`, as of 2026-09-11) provides `sessions`, `is_session`,
`session_count`, `rth_bounds_utc`, `rth_bounds`, `session_of`, `is_rth`, `now_eastern` via
`pandas_market_calendars` XNYS, with `lru_cache` on the hot paths. It has **no expiration
logic of any kind**.

**FACT (MAP §6.4, §7 Phase V).** The OMS is required to cross-check `adapter.clock()`
against `data/options_calendar.py` and **block on disagreement**, and "clock/calendar
disagreement" is a named Phase-V drill. So this module has two consumers from day one.

### 11.1 Design rules that make it usable by both consumers (HYPOTHESIS)

1. **Pure functions of explicit arguments.** No DB session, no network, no reading of the
   wall clock **except** through a caller-supplied `now: datetime`. A backtest calls it at a
   2023 date; the OMS calls it at the present instant; both get the same code path. A module
   that reads `datetime.now()` internally cannot be used by a backtest and will be
   re-implemented by the execution layer — which is the failure MAP §2.8 names.
2. **Depends only on `data/calendar.py`.** No import of `backtest`, `research`, `paper`, or
   any future `execution`. That keeps it importable from the execution layer without
   dragging the research stack into the order path.
3. **Deterministic and cacheable**, following `calendar.py`'s `lru_cache` pattern.
4. **Every return is total, and totality is not limited to expiry resolution.** An
   unresolvable expiry raises rather than returning a plausible wrong date — **and so do
   `options_close_time` and `market_phase`** on any session the constant table cannot
   resolve (an early close not in the table, a session outside the calendar's range). Rev 1
   stated this rule for expiries only. A calendar function **on the order path** must never
   return a plausible time it cannot justify: the OMS would submit against it, and a wrong
   `options_close_time` on a half-day is exactly the input that turns a no-submit window
   into a submission.

### 11.2 Surface (HYPOTHESIS)

```python
# --- expiry resolution ---
def monthly_expiry(year: int, month: int) -> date
    """Third Friday; if that Friday is not an XNYS session, the preceding session."""
def weekly_expiries(start: date, end: date) -> tuple[date, ...]
def expiries_between(start: date, end: date, *, monthly_only: bool) -> tuple[date, ...]
def is_expiry(d: date, *, monthly_only: bool = False) -> bool
def cycle_of(d: date) -> date            # the monthly expiry whose cycle contains d

# --- DTE, both senses, named so they cannot be confused ---
def calendar_dte(as_of: date, expiry: date) -> int      # expiry - as_of, in days
def session_dte(as_of: date, expiry: date) -> int       # XNYS sessions in (as_of, expiry]
def last_trade_session(expiry: date) -> date            # the expiry session itself for PM-settled
def force_close_session(expiry: date) -> date           # the session before last_trade_session

# --- session shape (the OMS cross-check surface) ---
def is_early_close(d: date) -> bool
def options_close_time(d: date) -> time                 # regular vs early-close
def market_phase(dt: datetime) -> Phase                 # PRE | RTH | POST | CLOSED; RAISES if unresolvable
def clock_agreement(now: datetime, broker_clock: BrokerClockView) -> ClockAgreement
    """AGREE | DISAGREE | UNDETERMINED, plus the divergence text. The OMS treats
    UNDETERMINED exactly as DISAGREE: it BLOCKS."""

# --- settlement ---
def settlement_style(underlying: str) -> SettlementStyle   # PM_PHYSICAL | AM_CASH
```

**Why not rev 1's `disagrees_with(broker_clock) -> str | None`.** Two defects, both sitting
on the order path.

**(a) It is fail-open by signature.** Every case the function cannot resolve — an unknown
session, an early close the constant table cannot answer for, an exception swallowed by the
caller — degrades to `None`, and the OMS reads `None` as "agrees, submit". That inverts the
house discipline. **FACT (MAP §6.4):** `may_open` is specified fail-closed, and spells the
pattern out for exactly this shape of check — "execution-local kill state readable AND not
engaged (**unreadable ⇒ block**)". A clock check must inherit it, not quietly invert it.

**(b) It took no `now`**, which contradicts §11.1 rule 1 ("no reading of the wall clock
except through a caller-supplied `now`"). As written it would have to read the clock itself
— breaking determinism and the backtest reuse that is this module's entire justification —
or be unable to compare anything at all.

**Rule (HYPOTHESIS).** `ClockAgreement` is a frozen dataclass `(verdict: Verdict, detail:
str)` with `Verdict ∈ {AGREE, DISAGREE, UNDETERMINED}`. The OMS blocks on anything that is
not `AGREE`, and writes `detail` to `execution_event` in **every** non-`AGREE` case,
`UNDETERMINED` included — an unexplained block is a debugging dead end at precisely the
worst moment. §15.2 test 29 asserts the `UNDETERMINED` path.

### 11.3 The two rules that are FACT-derivable with no new data source

- **Third-Friday with the holiday rule.** Compute the third Friday arithmetically, then:
  `if not calendar.is_session(third_friday): take the preceding session`. **FACT:**
  `calendar.is_session` (`calendar.py:44-45`) answers this from XNYS. No expiry data feed
  is needed for monthlies.
- **Early close.** `is_early_close(d) = rth_bounds(d) is not None and rth_bounds(d)[1].time()
  < time(16, 0)`. **FACT:** `rth_bounds` (`calendar.py:62-71`) returns the Eastern-wall
  `(open, close)` from the XNYS schedule, which carries half-days. No hard-coded holiday
  list.

**Deliberately NOT derived from the calendar library:** the **13:00 ET options close on
early-close sessions** (MAP §6.7a states it as general information the operator must verify
with their own broker) and **settlement style**. Both are asserted market-structure facts,
not schedule data. `options_close_time` and `settlement_style` must read from a
**version-controlled, explicitly-sourced constant table** with the source named in a
comment, and `settlement_style` must **raise** for an underlying not in the table rather
than defaulting to `PM_PHYSICAL`. Phase 1 trades ETF and single-name options only — all
PM-settled, American-style, physically settled — so AM/cash settlement is out of scope, and
raising on an unknown underlying is how that scope boundary is *enforced* rather than
documented.

### 11.4 `dte` is a two-headed word and that has already caused a bug elsewhere

`time_stop_dte = 7` (grid centre): 7 **calendar** days is ~5 sessions; 7 **sessions** is
~9–11 calendar days. These produce materially different theta exposure at the short end.
The API above names both and never exposes a bare `dte()`. The strategy's spec text must
interpolate which one it used, so `spec_json_hash` (`persistence.py:32-43`) detects a
change of convention as a parameter change.

---

<a name="12"></a>
## 12. Walk-forward / IS-OOS segmentation reuse

### 12.1 What is reused with no code change, and what each consumer actually reads

This is narrower than MAP §2.2 implies, and the narrowness is good news — `OptionTrade`
needs **four** structurally-compatible fields, not `SimTrade`'s full 14.

**FACT, by reading each consumer:**

| Consumer | `file:line` | Fields it reads from a trade |
|---|---|---|
| `compute_metrics` | `backtest/metrics.py:62-110` | `.pnl_r` (71), `.bars_held` (81) |
| `compute_portfolio_metrics` | `research/portfolio_metrics.py:49-137` | `.entry_date` (59), `.exit_date` (81), `.pnl_r` (91), `getattr(t, "bars_held", 0)` (97) |
| `bootstrap_ci` | `backtest/montecarlo.py:15-64` | a bare `Sequence[float]` — no trade object at all |
| `_regime_census` | `research/promotion.py:406-441` | `.entry_date` (420) |
| `run_walkforward` fold assignment | `backtest/walkforward.py:112-116` | `.entry_date` |
| `_benchmark_metrics` | `research/promotion.py:346-382` | none — proxy closes only |

**Therefore (HYPOTHESIS):** `OptionTrade` reuses the whole metrics stack unchanged if and
only if it exposes `entry_date: date`, `exit_date: date`, `pnl_r: float`,
`bars_held: int`. Everything else on it is additive and invisible to those consumers.

**Note `portfolio_metrics.py:97` uses `getattr(t, "bars_held", 0)`** — defensive, so a
missing field degrades silently to zero exposure rather than raising. Provide the field;
do not rely on the default.

**But "the whole metrics stack unchanged" is false for `compute_portfolio_metrics`, and the
error is about 3× on numbers that gate.** Rev 1 named only the `bars_held` caveat. There is a
second one, and it is larger.

**FACT.** `compute_portfolio_metrics` models each trade as risking a fixed **fraction of
current equity**: `change = t.pnl_r * risk_fraction` with the signature default
`risk_fraction: float = 0.005` — "0.5% of equity risked per trade (matches RiskLimits
default)" (`research/portfolio_metrics.py:53,91`, docstring at `:57-58`). **FACT.** It is on
the gate path at three call sites, and **none of them passes `risk_fraction`**: the sealed
span (`promotion.py:812`), the gate-1 walk-forward folds (`promotion.py:1075`), and the
strategy/benchmark comparison (`promotion.py:1253`).

Options R is a **fixed structural dollar amount**, not a fraction of equity and not
equity-scaled at all. §9.3's worked vertical has R = **$390**; against decision #13's
**$25,000** options paper account that is **1.56% of equity — roughly 3× the 0.5% the model
assumes**. Max drawdown and the entire equity curve are understated by about that factor, on
gate-1 and gate-9 evidence.

**Rule (HYPOTHESIS).** `research/options_backtest_runner.py` passes an **explicit**
`risk_fraction = R_dollars / start_equity` on every `compute_portfolio_metrics` call, with
`start_equity` the decision-#13 options paper account, and records **both** numbers in the
§14.3 evaluation record. Two disclosures attach: the corrected fraction is still an
approximation — the function compounds a fraction of *current* equity while options R is
fixed in dollars, so it understates drawdown inside a drawdown and overstates it in a
run-up — and the faithful construction is a **fixed-dollar-R equity curve**, which is a
D3/D4 item, not D2's. Passing a corrected fraction makes the gate *more faithful and harder
to pass*, which is exactly R4's carve-out (`STRATEGY_COMPLETION_MAP.md` §1 R4: permitted when
it makes a gate "runnable or more faithful without making it easier to pass"). Escalated as
Q11.

### 12.2 The `bars_held` caveat is real and the fix is two fields

**FACT.** `compute_metrics` derives `span_days = max(1, sum(bars_held))` and
`trades_per_year = n / (span_days / 252)` (`metrics.py:82-83`), and
`risk_adjusted_ratio` is annualised by that figure (`metrics.py:84`). So `bars_held`
directly drives a reported risk-adjusted number.

Two options trades each held 14 sessions, one entered at 21 DTE and one at 60 DTE, have
entirely different theta profiles, gamma exposure, and assignment risk, and the metrics
stack cannot tell them apart. **Rule (MAP §2.2, adopted):** keep `bars_held` as sessions
held for structural compatibility, **add `dte_at_entry` and `dte_at_exit`**, and require
the gate 1 walk-forward report and the gate 5 sensitivity report to be **stratified by DTE
bucket** (21–30 / 31–45 / 46–60). An options result reported only in `bars_held` terms is
under-specified.

### 12.3 CORRECTION C3 — the IS/OOS split, and the two regime modules that disagree

**The split, FACT:** `_TRAIN_FRAC = 0.6` (`research/backtest_runner.py:29`);
`_is_boundary(series)` returns `series.dates[cut - 1]` where
`cut = max(1, min(int(len(series) * 0.6), len(series) - 2))`
(`backtest_runner.py:158-160`); trades are assigned by
`_as_date(tr.entry_date) <= boundary` (`backtest_runner.py:212`). So the boundary is a
**date derived from the 60th-percentile bar index of that symbol's own series**, and OOS is
the last 40% of *bars*, per symbol.

**Rule (HYPOTHESIS):** `research/options_backtest_runner.py` computes the boundary from the
**underlying's `PriceSeries`**, identically, so the options IS/OOS convention is the same
function of the same data as the equity one. Do not derive it from option-print dates
(which are sparse and chain-dependent) and do not derive it from cycle counts.

**FACT — gate 1's folds are a different construction again.** `evaluate_promotion` does
**not** call `backtest/walkforward.py`. It builds 4 folds inline by **calendar-day
arithmetic** over the pre-sealed span —
`lo = start + timedelta(days=span_days * k // n_folds)` (`promotion.py:1069-1075`) — and
assigns trades by `lo <= t.entry_date < hi`. `backtest/walkforward.py` exists and is used
elsewhere, but the promotion path does not use it. An options runner must satisfy
**promotion.py's** construction; matching `walkforward.py` would satisfy nothing that
gates.

**CORRECTION C3 — the regime story is worse than the map states, in two ways.**

**(i) `range_bound` has no volatility half.** FACT, `backtest/regime.py:59-62`:

```python
if abs(close[i] - sma_now) / sma_now <= RANGE_BAND:
    out[proxy.dates[i]] = "range_bound"
else:
    out[proxy.dates[i]] = f"{trend}_{vol}"
```

The `f"{trend}_{vol}"` compound label is the **else** branch. `segment_key`
(`regime.py:66-79`) confirms it: `"range_bound"` maps to `["all", "range"]` with no vol
segment appended. So the emitted non-warmup label set is exactly

```
{ range_bound, bull_highvol, bull_lowvol, bear_highvol, bear_lowvol }
```

— **five labels, of which four are joint and one is not splittable by vol at all.** MAP
§5.2 proposes "3 trend × 2 vol = 6 cells" as the "free" binary joint bucketing. That cell
set does not exist in the data. Any pre-registered joint-cell floor must be written against
the actual five, and the map's §5.3 arithmetic for the joint extension must be redone on
that basis (a D4 item; flagged here because the engine emits the labels).

**(ii) Two different regime functions are in play, and they disagree.** FACT:

| | `backtest/regime.py::label_regimes` | `research/regime.py::regime_from_proxy` |
|---|---|---|
| Consumed by | **gate 6's census** — `promotion.py` loads `proxy_full` then `regimes = label_regimes(proxy_full)` | **the strategy's own filter** — `backtest_runner.py:184-185` `regimes = regime_lookup(proxy)` → `signal_fn_for(..., regime_by_date=regimes)` |
| Trend | 200-session SMA slope: `sma_now >= sma_prev` → bull else bear (`regime.py:39-41`) | SMA-50 vs SMA-200 **and** the 200's slope, with a **NEUTRAL** third state (`research/regime.py:71-77`) |
| Vol | 20-session realised vol vs trailing median, `>` (`regime.py:43-57`) | 20-session realised vol vs trailing median × **1.15** (`research/regime.py:85`) |
| Range | `range_bound` when within ±3% of the SMA (`regime.py:22,59-60`) | **no range state at all** — `Trend.NEUTRAL` is not "range" |
| Labels | `warmup, range_bound, {bull,bear}_{highvol,lowvol}` | `RegimeState(trend ∈ {bull,bear,neutral}, vol ∈ {low,high})` |

**Consequence, and it is large for O3.** A regime-filtered short-vertical strategy gates
its entries on `research/regime.py`'s labels, while gate 6 counts its trades under
`backtest/regime.py`'s labels. **A strategy that "trades in bear" by the strategy module's
definition may book zero trades in the `bear` bucket the gate counts**, and vice versa.
MAP §5.3's finding that "O1 as specified is structurally unpassable at gate 6" is derived
from the gate's bucket set; the same reasoning applied to O3's mirror construction must be
redone against **both** definitions, because the design filter and the gate census are not
the same function.

**Rule (HYPOTHESIS).** The options engine and its strategy must (a) name which regime
function they gate on, in the spec text, (b) have the runner report the **cross-tabulation**
of the two labellings over the evaluation's trades as a gate-8 evidence field, and (c) not
"fix" the disagreement by changing either module — both are live and one of them prices
approved strategies. This is a disclosure requirement, not a refactor. **Flag to D4 and to
the orchestrator: this is an equity-side finding as much as an options-side one.**

### 12.4 One position per underlying at a time

**FACT.** The equity engine goes flat before re-entering: `t = exit_idx + 1` with the
comment "flat again; no overlapping positions" (`engine.py:149`).

**Rule (HYPOTHESIS).** The options runner enforces the same invariant per underlying, and
MAP §3.2's `options_max_structures_per_underlying = 1` is consistent with it. Note the
near-miss: a 30–45 DTE entry held to a 7-DTE time stop occupies ~4–5 weeks, so consecutive
**monthly** cycles barely fail to overlap. Any move to weekly cycles breaks the invariant
and would change what §5.3's trade-count arithmetic is counting. State the rule explicitly
in the spec text rather than letting the cycle spacing imply it.

---

<a name="13"></a>
## 13. Leakage checks for every new feature

### 13.1 CORRECTION C4 — the existing harness cannot express an options feature

**FACT.** `backtest/leakage.py:16`:

```python
FeatureFn = Callable[[PriceSeries, int], float]
```

and `assert_no_lookahead(feature_fn, series, ...)` (`leakage.py:23-41`) calls
`feature_fn(series.head(t), t)` against `feature_fn(series, t)` and compares.

**FACT.** `LEAKAGE_FEATURE_CHECKS` (`research/promotion.py:536-545`) is a list of eight
`(name, lambda s, t: ...)` pairs over `sma`, `rolling_return`, `atr`, `realized_vol`,
`atr_contraction`, `donchian_high`, `true_range` — all functions of a **single underlying
`PriceSeries`**. `_leakage_self_check` (`promotion.py:548-561`) runs them against the
**proxy symbol only** and returns an error string or `None`; gate 8 fails on a non-`None`
when `require_leakage_check_pass` is true (`promotion.py:1288-1291`,
`config/research.py:123`).

**Every options feature is a function of the chain**, not of a single price series:
ATM IV, IV rank, term-structure slope, surface-interpolated delta at a target strike,
credit-to-width at the selected strikes, the strike selector itself. None of them can be
typed as `Callable[[PriceSeries, int], float]`. **So gate 8's leakage self-check says
nothing whatsoever about an options strategy until a chain-aware sibling exists.** The map
does not name this; it is the single most important leakage item in D2.

**A live precedent landed in the repo during this pass, and it makes the point better than
this section can.** FACT: `research/strategies/base.py:50-70`
`declared_regime_lag_sessions` was added for the `intraday_orb` work, and its docstring
states the problem in the project's own words: `regime_lookup` labels a session from that
session's own daily bar, so an intraday entry inside session *D* would be gated on *D*'s
16:00 close — and "**`backtest.leakage.assert_no_lookahead` cannot see it, because it lives
in the `regime_by_date` plumbing and not in any feature function**"
(`base.py:62-63`). That is exactly the failure mode described here, already realised on the
equity side: a genuine look-ahead the existing harness is structurally blind to, because it
is not shaped like a `(PriceSeries, int) -> float`. The options case is the same class of
blindness, one layer larger — the chain is the plumbing. §13.2's sibling harness and
§3.3's visibility rule exist to make the options version *visible* rather than relying on
someone noticing it.

**Corollary for the options strategy (HYPOTHESIS):** an options strategy gated on a regime
label inherits the same lag question, and `declared_regime_lag_sessions` /
`lagged_regime` (`base.py:50-89`) are the existing, version-scoped mechanism for it. The
options runner should route its regime read through them rather than re-implementing the
lookup, so the lag is part of what the strategy *version* is and shows up in its
`StrategySpec`. For a daily-bar options strategy filling at *t+1* the correct lag is 0, the
same as the daily equity strategies — but it should be declared, not assumed.

### 13.2 The sibling harness (HYPOTHESIS)

New file `backtest/options_leakage.py`, mirroring `leakage.py:23-41` exactly in shape:

```python
ChainFeatureFn = Callable[[OptionChainSeries, PriceSeries, int], float]

def assert_no_lookahead_chain(
    feature_fn: ChainFeatureFn,
    chain: OptionChainSeries,
    underlying: PriceSeries,
    *, indices: list[int] | None = None, tol: float = 1e-9,
) -> None:
    """Calls the feature once on (chain.head(t), underlying.head(t), t) and once on
    (chain, underlying, t). A correct feature returns the same value both times."""
```

This works **only** because `OptionChainSeries.head(t)` truncates *both* the session list
and — per §3.3 — the **visible contract set**. A `head` that truncated sessions but left
`contracts` at its full extent would let a feature read a strike that did not yet exist and
the harness would not catch it. §3.3 and §13.2 are one design, not two.

### 13.3 The required check list (HYPOTHESIS)

`OPTIONS_LEAKAGE_FEATURE_CHECKS`, to be run by an options gate-8 extension. Each entry is
`(name, fn)` in the `promotion.py:536-545` style:

| # | Feature | Why it is on the list |
|---|---|---|
| 1 | `atm_iv(chain, und, t)` | the base of everything; must read session *t* only |
| 2 | `atm_iv(chain, und, t - 5)` | **FACT-motivated**: `promotion.py:542` already includes a lagged `@ t-5` variant because "a feature can be clean at t and still read the future when evaluated at an earlier index" |
| 3 | `iv_rank(chain, und, t, lookback)` | reads a trailing window — the classic leak site |
| 4 | `term_slope(chain, und, t)` | reads two expiries at *t* |
| 5 | `surface_delta_at_strike(chain, und, t, K, expiry)` | the surface fit (§6.6) under truncation |
| 6 | **`select_short_strike(chain, und, t, target_delta)` → strike** | **the most important one.** The strike selector is where a future-peeking chain bites hardest, and it is not a "feature" in the usual sense, so it is the one most likely to be omitted. Type it as a float-returning feature so the harness can check it. |
| 7 | `select_short_strike(..., t - 5, ...)` | same lag rationale as #2 |
| 8 | `credit_to_width(chain, und, t, short_K, long_K, expiry)` | reads two legs' prints at *t* |
| 9 | `visible_contract_count(chain, t, expiry)` | asserts §3.3's visibility rule is actually applied by `head` |

**FACT (R4 basis for adding these):** `promotion.py:525-535` records that adding leakage
checks "can only create new ways to FAIL gate 8, never make it easier to satisfy — the same
R4 carve-out that permits adding a missing sensitivity axis". Adding the options list is
the same carve-out.

### 13.4 Three leakage risks specific to options that the harness alone will not catch

`assert_no_lookahead_chain` catches *temporal* leakage. It does not catch these; each needs
its own named check:

1. **Chain-membership leakage** — covered by §3.3's visibility rule and check #9 above.
   Without the rule, `head(t)` is temporally clean and still wrong.
2. **Force-close eligibility leakage (§10.2)** — the entry-eligibility rule *deliberately*
   uses post-entry information. It is admissible only as an exclusion (never adds a trade)
   and only with the count disclosed. **It must be implemented as a post-hoc sample filter
   applied by the runner, never as a condition the strategy's `evaluate` can see** — if the
   strategy can read it, it becomes a selection rule with hindsight and the whole evaluation
   is void. Enforce structurally: `evaluate` receives `chain.head(t)`, which cannot answer
   a question about the expiry−1 session when `t` precedes it.
3. **Surface-fit leakage** — the §6.6 fit must be strictly same-session. A fit that
   smoothed across adjacent sessions (a natural-looking "stabilisation") reads session
   *t+1*. Check #5 catches it; also forbid it in the fit's own signature by giving the fit
   function access to **one** `ChainSession`, not to the series.

---

<a name="14"></a>
## 14. Config hashing, provenance, and the evaluation record

### 14.1 CORRECTION C1 — "folded into `config_hash`" cannot be done as the map says

The map says, in at least six places (§1.5, §2.4(1), §2.4(2), §2.4a, §2.5, §5.2), that an
options constant is "folded into `config_hash`" so it "cannot move silently". **That is not
available.**

**FACT.** `ResearchConfig.config_hash` hashes **only** the sections named in
`SCOPE_HASH_FIELDS` (`config/research.py:411-415`):

```
schema_version, watchlist, etf_universe, allow_short_candidates, enabled_horizons,
intraday_bar_size, liquidity, risk, events, data_quality, quality_gates,
universe_filters, commission_per_share, commission_min_per_order, slippage_bps,
half_spread_fill_penalty
```
(`config/research.py:392-409`)

**`options` is not in that list. Neither is `promotion`.** The comment immediately above
the tuple (`research.py:371-378`) states the reason explicitly: adding or changing an
unrelated section — "agents, news, **options**, the universe pipeline, the health monitor,
the alert cap, or promotion thresholds" — "can never silently un-scope a live
PAPER_APPROVED strategy", and "Adding a field that DOES change signals means adding it
here, and that is a deliberate re-approval event."

**FACT (the incident this encodes).** Commit `0cc4cf4` scoped the hash to signal-shaping
fields only after an `agents` section addition silently changed the hash used in the
five-part approved-scope match, causing live scans to match no approved scope — masked only
because those scans produced zero qualified candidates
(`docs/PAPER_PROBATION_ACTIVATION.md`, MAP §0.4).

**So: adding `OptionCostModel` constants, the pin band, the surface-N floor, or the gate
0.c/0.d fractions to `SCOPE_HASH_FIELDS` would change `config_hash` for the two live
PAPER_APPROVED strategies and knock them out of their own approval scope — re-running the
exact incident the project already had.** This must not happen.

### 14.2 The resolution (HYPOTHESIS)

Three mechanisms, all of them, not one:

1. **A separate `options_config_hash`.** Add an `OptionsResearchConfig` section (engine
   constants: cost model, spread function parameters, pin band, surface N, DTE/delta grid,
   `r`/`q` source identifiers, the R basis, the visibility rule version) with its **own**
   `ClassVar OPTIONS_SCOPE_HASH_FIELDS` and its own hash property. It is recorded on every
   options evaluation and on every options `IngestionRun`. It is **never** merged into
   `ResearchConfig.SCOPE_HASH_FIELDS`.
2. **`full_config_hash` already covers audit.** FACT:
   `ResearchConfig.full_config_hash` (`research.py:417-420`) hashes **every** section
   including `options`, and its docstring says "for audit trails, never for scope matching".
   Record it on every options evaluation. A change to any options constant therefore already
   shows up in an audit-grade hash today, with no schema change at all.
3. **Verbatim values in the evaluation record.** A hash proves change; it does not tell a
   reader what the value was. Every options evaluation record carries the constants
   themselves, in full, the way `StrategyBacktestResult.costs` already carries the four
   equity cost fields verbatim (`research/backtest_runner.py:234-239`) alongside
   `costs_label` (`backtest_runner.py:121-131`).

**Precedent for (3) being the load-bearing one, FACT:** `PromotionThresholds` is likewise
**not** in `SCOPE_HASH_FIELDS`, and the mechanism that keeps it honest is that "every
evaluation records [them] per gate in `gates_json`" (`research.py:374-375`). The options
constants get the same treatment. Note in passing that `promotion.py:12`'s module docstring
still says `PromotionThresholds` is "hashed into `config_hash`" — **that statement is stale
post-`0cc4cf4`**; it is accurate only of `full_config_hash`. Worth a one-line docstring fix
in some future commit; flagged, not fixed here (D2 writes no code).

### 14.3 The options evaluation record (HYPOTHESIS)

Every options evaluation carries, at minimum:

```
structure_type, r_basis, contracts_per_structure
fill_model                    # "print_not_mid; full_modelled_spread_per_leg_per_side;
                              #  close_basis_stop; NBBO unavailable under the active
                              #  entitlement for options AND equities — spread is
                              #  modelled, not observed; PLACEHOLDER spread proxy —
                              #  not yet calibrated"
spread_multiplier             # 1.0 | 2.0  (gate 4b)
option_cost_model             # every field, verbatim
iv_source_mix                 # per-trade fractions across IvSource members
q_source, r_source            # per underlying / per session (gate 0.g, incl. C7)
options_config_hash, full_config_hash, config_hash
sealed_look_family            # the Strategy.name count_sealed_looks keys on
sealed_look_prior             # k BEFORE this run (promotion.py:647, captured at :924)
sealed_look_index             # k+1 if this run seals; null if it does not
series_basis                  # per reported figure: clamped | unclamped  (§9.4)
r_basis_of_each_figure        # per reported figure: at_print | incl      (§9.3)
risk_fraction, start_equity   # what compute_portfolio_metrics was actually given (§12.1)
tick_grid                     # §6.3, verbatim, with its source
counts: non_entry_missing_leg_bar, exit_deferred_sessions (distribution),
        force_close_unpriceable_exclusions, synthetic_mark_fraction,
        unmarked_sessions (count, fraction, max consecutive run),
        target_strike_invisible_count, shares_per_contract_refusals,
        exercise_style_refusals, r_clamped, stop_did_not_bind,
        pin_risk_flag, assignment_risk, zero_spread_refusals,
        spread_ge_print_leg_sides, sale_proceeds_floored_at_zero,
        long_leg_intrinsic_gap_dollars            # all per spread setting
excluded-cycle intrinsic-at-expiry pnl_r distribution (§10.2)
dte_at_entry / dte_at_exit distributions, stratified metrics per DTE bucket
regime cross-tabulation (backtest/regime.py labels × research/regime.py labels)  # §12.3
disclosures: early-assignment approximation and its favourable-direction bias;
             corporate_action table is empty; deliverable assertion incompleteness (C6);
             gate 9 on a 4b run is a REPLAYED baseline-locked sealed result (§8.3)
```

**The sealed-look fields are not decoration.** MAP §5.4 is explicit that look *counting* is
already automatic and correct — `count_sealed_looks` is derived from the table on every read
and "cannot drift" — and that the options family starts at **k=0** by construction. What the
record must do is make the family's *k* visible **at the moment a look is consumed**, which
is also when an R3 version bump from a gate-4b failure consumes one (§8.3).

**The variant ledger — the thing MAP §5.4 says will actually leak, and rev 1 emitted nothing
for it.** MAP §5.4's headline finding is that "the number of **unsealed** variants explored
will dwarf anything the equity program has seen. **That, not the look count, is where
multiplicity will leak**" — i.e. R5 disclosure of abandoned variants across
structure × delta × DTE × width. The per-evaluation record above makes nothing about
abandoned variants mechanical.

**Rule (HYPOTHESIS).** `research/options_backtest_runner.py` writes an **append-only run
ledger** — one row per invocation, never updated, never deleted — carrying: UTC timestamp,
the **full `params` dataclass** as JSON, `options_config_hash`, `full_config_hash`, the
symbol set, the span, the spread setting, the R basis, and the invoking command. Every
variant ever run is then enumerable, and R5 disclosure becomes a **query** — "pre-registered
cells with no reported result, and run cells with no pre-registered entry" — rather than a
memory exercise. Two constraints on it: the ledger is written by the **runner**, never by the
pure `run_options_backtest` arithmetic core, so §15.1's S4 determinism and the engine's
no-side-effects property are preserved; and it is **append-only**, because a ledger a
disappointing variant can be deleted from is not a disclosure mechanism.

---

<a name="15"></a>
## 15. Determinism and the test plan

### 15.1 Determinism (invariant S4)

**FACT (the standard to match).** `backtest/engine.py:12` — "Deterministic: pure arithmetic
over the input arrays, no RNG, no wall-clock." `sensitivity.py:8` — "the same grid + data
always produce the same verdict (S4)." `montecarlo.py:15-19` — seeded at `20240101`.

**Rules (HYPOTHESIS):**

- No RNG anywhere in the options engine except `bootstrap_ci`'s existing seeded resampler.
- No wall-clock read. `options_calendar` takes `now` as an argument (§11.1).
- The surface fit uses a closed-form solve with a fixed input ordering (§6.6).
- `implied_vol`'s bisection is already deterministic (`blackscholes.py:113-123`).
- Dict iteration order must never affect a result: sort contract tickers before any
  reduction (sum, fit, selection tie-break). Strike selection ties break on
  `(abs(delta - target), strike, option_ticker)` — a total order.

### 15.2 Test plan (HYPOTHESIS — for I-O3, not written now)

**Structural / safety**

1. `test_equity_core_frozen` — sha256 of `engine.py` and `costs.py` (§1.3).
2. `OptionStructure` rejects: a naked short (single short leg), mixed expirations, mixed
   underlyings, `shares_per_contract != 100`, `exercise_style != "american"`,
   `qty == 0`, inverted vertical wings.
3. A fill function cannot be handed a `Mark` (type-level, checked by mypy strict —
   **FACT:** `signalforge.backtest.*` is under `disallow_any_generics`/`warn_return_any`/
   `strict_equality`, `pyproject.toml:131-135`).
4. `IvSource` has no `realized_vol` member.

**Point-in-time / leakage**

5. `head(t)` truncates sessions **and** the visible contract set; a contract whose
   `first_print_session > sessions[t]` is absent from `head(t).contracts`.
6. All nine `OPTIONS_LEAKAGE_FEATURE_CHECKS` pass on a synthetic chain (§13.3).
7. A deliberately-leaking feature (reads `chain.sessions[-1]`) is **caught** — the harness
   must be shown to fail, not merely to pass.
8. `evaluate` cannot observe the force-close session when `t` precedes it (§13.4 item 2).

**Fill model**

9. A missing leg bar on the entry session yields a **non-entry**, and the counter
   increments; no trade is produced.
10. A signalled exit with a missing leg defers and fills at the later session's prints,
    with `exit_deferred_sessions` recorded.
11. A full spread is charged **per leg per side**: a 2-leg vertical round trip charges four.
12. `spread_multiplier = 2.0` changes exactly one recorded scalar and doubles the spread
    charged (§8.2).

**R and expiry**

13. `R_at_print` is invariant to `spread_multiplier` — it is computed from the *unadjusted*
    prints (§9.2) — and `R_incl` is **not**. The rev-1 form of this test, written against a
    denominator built from the credit *received*, would have failed (§9.3).
14. Max-loss realisation produces `pnl_r ≈ −1.086` on `R_incl` and `≈ −1.120` on
    `R_at_print`, unclamped (§9.3's corrected worked numbers are the fixture, including the
    **state-dependent exit spread**); `r_clamped = True`; and the **gated** statistic uses the
    unclamped value.
15. Intrinsic floor: a stale deep-ITM short-leg print does **not** produce a profit
    (§10.3).
16. Pin band: underlying closing inside the band sets `pin_risk_flag`.
17. A structure whose force-close session cannot price every leg is **excluded and
    counted**, never force-closed at a mark.

**Calendar**

18. Third-Friday resolution across a holiday-Friday month falls back to the preceding
    session.
19. `is_early_close` is true on a known XNYS half-day and false on a regular session.
20. `settlement_style` **raises** for an underlying not in the constant table.
21. `calendar_dte` and `session_dte` disagree where they should, and neither is exposed as
    a bare `dte`.

**Metrics reuse**

22. An `OptionTrade` list flows through `compute_metrics`, `compute_portfolio_metrics`,
    `bootstrap_ci`, and `_regime_census` **unmodified** (§12.1).
23. A mixed-`structure_type` or mixed-`r_basis` trade list **raises** before reaching any
    statistic (§9.5 item 2).

**Added in rev 2 — each one pins a defect that rev 1 shipped**

24. A `Mark`-only session (no leg print) **cannot fire** the §10.1 stop or profit target,
    contributes no unrealised value, and increments `unmarked_sessions` (§6.4).
25. A triggered stop or profit target does **not** fill at the triggering session's print —
    the fill is taken at *t+1*'s prints; a time stop and a force close **do** fill at their
    own session's prints (§10.1).
26. The gate statistic **moves** when a sub-−1R trade is present: `compute_metrics` and
    `bootstrap_ci` over a fixture containing one −1.23R trade differ from the same fixture
    clamped at −1.0, and the figures the gates consume are the **unclamped** ones (§9.4).
27. `OptionCostModel(...)` with any field omitted raises `TypeError`; both spread parameters
    zero raises `ValueError`; a model whose `spread()` returns 0.0 for a priced leg is
    refused by `run_options_backtest` and counted as `zero_spread_refusals` (§7.1, §7.4).
28. A modelled sale's proceeds are never negative, and tick rounding is **away from the
    engine** on both sides (§6.3).
29. `clock_agreement` returns `UNDETERMINED` — never `AGREE` — for a session it cannot
    resolve, and the OMS-side harness blocks on it; `options_close_time` and `market_phase`
    **raise** on that same session (§11.1, §11.2).
30. The intrinsic floor applies to a leg being **bought back** and **not** to a leg being
    sold, and `long_leg_intrinsic_gap_dollars` accumulates the difference (§10.3).
31. The options runner never calls `compute_portfolio_metrics` without an explicit
    `risk_fraction`, and the value recorded in §14.3 equals `R_dollars / start_equity`
    (§12.1).
32. A 4b evidence report carries no unlabelled gate-9 line: either gate 9 is absent, or its
    label contains the verbatim baseline-locked wording of §8.3.

---

<a name="16"></a>
## 16. Out of scope for D2

Named so no one assumes D2 covered them:

- **The gate ladder itself** — gate 0.a–0.h, gate 0.5, gate 4b's threshold wiring, gate 6's
  joint buckets, gate 7b, the gate-8 additions. **D4.** D2 specifies what the engine
  *emits*; D4 specifies what the gates *require*. Items this document flags for D4:
  C3 (the real label set and the two-regime-module disagreement), C7 (`r_source` in gate
  0.g), C6 (gate 0.h is weaker than claimed), §3.3 (gate 0.c must use the visibility rule),
  §10.2's exclusion ceiling.
- **Data acquisition** — pacing, `--lookback-days`, per-cycle caps, point-in-time reference
  price, the `q` and `r` series, the `shares_per_contract_source` column. **D1.** This
  document depends on D1 for §4.3, §6.5, and §3.4.
- **Collateral, paper mechanics, `mark_options_to_market`,
  `assert_options_auto_simulate_allowed`, the options limits.** **D3.**
- **The strategy's actual parameters, the complete grid, the disposition rule, the pin
  band's number, the surface N, the 0.c/0.d fractions.** **D5**, pre-registered before any
  outcome is inspected (R1).
- **Everything in the execution layer** except the one constraint §11 imposes on
  `options_calendar`'s shape. **D6, orchestrator, not delegated.**
- **Any decision reserved to the operator** — the three open items in
  `DECISIONS_2026-09-12_options_execution.md`.

- **The S11 contract's own wording.** §2.1 shows that `backtest/options_pricing.py` importing
  `signalforge.options.blackscholes` violates no contract today. It also makes S11's **name**
  — "options are education/simulation only — no alerts, no LLM, no decision path"
  (`pyproject.toml:210`) — false, while the contract keeps **passing**, because S11 constrains
  only what `signalforge.options` may import. A safety label that silently stops being true is
  worse than no label, and this one will be read by whoever next audits the order path.
  **Handed to the orchestrator (Q12):** S11 must be renamed and re-scoped in the **same
  commit** that first imports `signalforge.options` from `signalforge.backtest.*`, with the
  before/after wording shown to the operator. D2 does not write contracts.

- **An options-specific equity curve.** §12.1 corrects the `risk_fraction` a gate-path
  `compute_portfolio_metrics` call must be given; building a *fixed-dollar-R* equity curve,
  which is the faithful construction, is **D3/D4**.

### A rule this document earned the hard way

It belongs here because it binds every D-phase document, not only D2. §3.6 of rev 1 published
an IV **distribution** — distinct-value count, minimum, maximum — from `option_quote_snapshot`.
MAP §7's pre-registration ordering says, verbatim: "**No price, IV, greek, return, credit, or
P&L series may be inspected — by a person or by a script — until D5 is committed. That includes
summary statistics over them.**" Non-null **counts** are coverage and are permitted; a range is
a summary statistic over the series and is not. The figures are struck and the look is disclosed
(§3.6), but the breach is **unrecoverable after the fact** — the numbers were seen, and no
amount of deletion unsees them. The only real remedy is upstream.

**Rule: every DB query a D-phase document intends to run is checked against MAP §7's
coverage-only whitelist BEFORE it is executed, and the check is recorded next to the query.**
The whitelist is: counts; distinct counts of *identifiers* (contracts, sessions, expiries,
symbols, snapshots); null / non-null coverage; date ranges of *sessions*; and completeness
fractions. Anything touching the **value** of a price, IV, greek, credit, return or P&L —
including its minimum, maximum, mean, cardinality, quantiles or range — waits for D5. When a
query is ambiguous, it waits for D5; the asymmetry is deliberate, because one side of the error
is a delay and the other side is unrecoverable.

---

<a name="17"></a>
## 17. Open questions

**Q1 — C1: where does `options_config_hash` live, and who owns the freeze?**
This document proposes a separate `OptionsResearchConfig` section with its own hash,
explicitly kept out of `SCOPE_HASH_FIELDS`. That is a config-schema change with an approval
-scope blast radius, and the project has already been burned once here (`0cc4cf4`).
**Orchestrator decision required before I-O3.** Sub-question: should the new section live
inside `ResearchConfig` at all, or as a standalone model, so that even an accidental
inclusion in `SCOPE_HASH_FIELDS` is impossible?

**Q2 — C8: is the four-way (R basis × spread setting) requirement accepted, with the gate
binding on the worst of the four?**
Rev 2 sharpens the question. The four-way surface is reported, but only one cell binds:
`R_incl` at 2×, by construction the largest denominator against the smallest numerator.
`R_at_print` is a fixed-denominator **reporting** basis on the unadjusted prints — nobody
receives that credit — and no gate ever binds on it (§9.3). The alternative is to pick one R
basis and accept that gate 4b's stress is not cleanly attributable. **Recommend the
four-way, binding on the worst.** Orchestrator call.

**Q3 — C6: which fix for the `shares_per_contract` default hole — (a) nullable, (b) a
source column, or (c) backfill-side counting only?**
(b) is recommended. It is a D1 schema item that D2's gate 0.h assertion depends on, so it
needs deciding before I-O1 completes, not before I-O3.

**Q4 — R1 boundary: may the single existing `option_quote_snapshot` be used to validate the
local IV inversion?**
878 rows, one `as_of`, all SPY, with `vendor_iv`, `vendor_greeks_json`, and
`open_interest` populated on 878/878 (§3.6). Inverting IV from those rows' own prices and
comparing to `vendor_iv` would validate the §6.6 inversion machinery at zero API cost.
**But it reads an option price series, which MAP §7's pre-registration rule forbids before
D5 is committed.** The conservative reading: it is a *mechanical* validation whose only
reported output is a pass/fail and an error distribution, reveals no strategy outcome, and
touches no return series — but it is a judgement call and D2 should not make it unilaterally.
**Recommend: pre-register the validation in D5 as a named, bounded check with its tolerance
fixed in advance, then run it.** Orchestrator call.

**Disclosure attached to this question, so it is judged on an accurate record.** §3.6 of rev 1
of this document **already published an IV range** over these same 878 rows, in breach of the
same rule this question invokes. That is recorded in §3.6 as a disclosed look and in §16 as
the query-whitelist rule. The rows are therefore **not** untouched, and the orchestrator
should weigh this question knowing that.

**Q5 — C7: what is the pre-registered source for the per-session `r`?**
No rate series exists anywhere in the schema and none of the probed endpoints is a rate
feed. If no series can be sourced, is a pre-registered piecewise-constant quarterly schedule
acceptable, and who commits it? **D1 + orchestrator.**

**Q6 — C3: how should the two-regime-module disagreement be handled?**
This document recommends disclosure (cross-tabulation at gate 8) and explicitly **not** a
refactor, because both modules are live and one of them gates the two approved equity
strategies. But it materially affects whether O3's mirror construction can populate the
gate's `bear` bucket — which is the exact structural failure MAP §5.3 found for O1.
**D4 must redo §5.3's gate-6 arithmetic against `backtest/regime.py`'s real five-label set,
and the answer may change the strategy design (an R1 pre-registration input).** Escalating
to the orchestrator because it is an equity-side finding too.

**Q7 — §3.3: is the "printed at some session ≤ t" visibility rule accepted, given the
liquidity-selection bias it introduces?**
It is the only data-grounded rule available, and it is conservative on fills. The bias it
introduces is toward already-traded strikes. The alternative — trusting the reference table
as a point-in-time chain — is a silent look-ahead. **Recommend the rule, with
`target_strike_invisible_count` disclosed at gate 8.** Orchestrator confirmation wanted
because it changes what "the strategy" means.

**Q8 — §10.2: what is the pre-registered ceiling on `force_close_unpriceable_exclusions`?**
Above some fraction, the surviving sample is not the pre-registered strategy. The number
must be fixed in D5 before the backfill's per-cycle completeness is inspected, exactly as
the 0.c/0.d fractions are.

**Q9 — §1.3: is the sha256-freeze test on `engine.py` / `costs.py` wanted?**
It converts a promise into a guarantee at the cost of firing on cosmetic edits. Cheap
either way; the orchestrator owns the safety-test surface.

**Q10 — §2.1: should the new contract naming the options modules' LLM-freedom be S3
extended, or a new S11a?**
Either works. Rev 2 moves its **commit placement** from I-E1 to **I-O3** — the commit that
creates `options_calendar.py` and `option_chain.py` — because I-E1 is on the execution track,
which MAP §7 says must not wait on the options track, and is specified as touching "nothing
else". So this must be decided before **I-O3** is cut, not I-E1.

**Q11 — §12.1: what `risk_fraction`, and whose equity curve, do the options gates run on?**
`compute_portfolio_metrics` defaults to `risk_fraction=0.005` and no gate-path call site
overrides it (`promotion.py:812,1075,1253`). Against decision #13's $25,000 options paper
account, §9.3's R = $390 is 1.56% — about 3×. D2's rule is to pass an explicit
`R_dollars / start_equity` and record both. The open questions are whether that approximation
is acceptable for gating at all, or whether D3/D4 must build a **fixed-dollar-R** equity
curve first, and whether the equity side's existing figures should be re-stated for
comparability (they should not, under R4's freeze, but it should be said out loud).
**D3 + D4 + orchestrator.**

**Q12 — §16: when and how is S11 renamed?**
S11's name asserts that options are "education/simulation only — no alerts, no LLM, no
decision path" while constraining only what `signalforge.options` may **import**. The first
`backtest.* -> signalforge.options` import makes the name false and leaves the contract
passing. D2's recommendation: rename and re-scope in that same commit, with the before/after
wording shown to the operator. **Orchestrator owns the contract surface**; D2 writes no
contracts.

---

---

## Appendix — Judge responses (rev 2)

Two adversarial audits reviewed rev 1: **J1**, a legitimacy/evidence refutation pass (20+
claims re-verified, 13 `file:line` checks, 12 read-only SELECTs), and **J2**, a
safety/feasibility pass (paths to an ungated order, clock races, fill holes, gate arithmetic,
buildability against HEAD). They raised **20 defects, 10 each, with substantial overlap.**

**Every defect was verified independently before it was acted on, against commit `5b41a61`,
read-only. All 20 were accepted** — 15 as stated and 5 with a refinement recorded below. **None
was rejected**, and the reasoning for each refinement is given rather than asserted, so that a
reader can disagree with it specifically.

### Accepted as stated (15)

| Defect | Raised by | Where fixed |
|---|---|---|
| §3.6 published an IV distribution — a MAP §7 pre-registration breach, self-contradicted by §17 Q4 | J1, J2 | §3.6 (figures struck, look disclosed), §16 (query whitelist), §17 Q4 |
| The −1R clamp never excluded from the gated series — a gate weakening under R4 | J1, J2 | §9.4 (rewritten), §15.2 test 26 |
| `R_excl` is not cost-invariant as defined; test 13 would have failed | J1 | §9.2, §9.3, §9.5, §15.2 test 13, §0 C8 |
| `OptionCostModel`'s `= 0.0` defaults make a vacuous gate 4b reachable | J1 | §7.1 (no defaults, `__post_init__`), §7.4 (rewritten) |
| §8.3's gate-4b run replays a baseline-locked gate 9; the R3 bump costs look k+1 | J1 | §8.3 |
| §14.3 carries no sealed-look fields and no variant ledger (MAP §5.4's headline finding) | J1 | §14.3 |
| `promotion.py` / `config/research.py` citations drifted 30-75 lines low | J1, J2 | every citation re-derived; commit sha pinned in the header |
| §10.2 declared a measurable bias unmeasurable, in two contradictory sentences | J1 | §10.2 (rewritten) |
| The mark path had no terminal behaviour and no stated `Mark` firewall | J1 | §6.4, §6.6(3), §15.2 test 24 |
| The modelled spread is unbounded relative to the print; the 2× run is pathological on wings | J1 | §6.3, §15.2 test 28 |
| Triggered exits filled at the very close that triggered them | J2 | §10.1 (rewritten), §6.4 row 2, §15.2 test 25 |
| `compute_portfolio_metrics`'s `risk_fraction=0.005` is ~3× wrong for a fixed-dollar options R | J2 | §12.1, §14.3, §15.2 test 31, Q11 |
| `disagrees_with` is fail-open by signature and reads no `now` | J2 | §11.1 rule 4, §11.2, §15.2 test 29 |
| The options modules' import contract was assigned to I-E1, on the other track | J2 | §2.1 (moved to I-O3), Q10 |
| §9.3 held the exit spread equal to the entry spread, understating the breach ~2× | J2 | §9.3 (recomputed) |

### Accepted with a refinement (5)

**1 — the long-leg intrinsic floor (J2).** Accepted: the floor is argued for a leg being
*bought* and rev 1 applied it to a leg being *sold*, where it raises assumed proceeds and is
favourable to the strategy. J2 offered two remedies — apply it buy-side only, or keep it
symmetric and report the aggregate dollar effect. **Refinement: both.** §10.3 applies the floor
to the buy side only *and* adds `long_leg_intrinsic_gap_dollars` at gate 8, because the
asymmetric rule silently makes some exits much worse and the size of that conservatism should
be a number in the record rather than an unexamined consequence of a sign convention.

**2 — the four-way R requirement (J1's fix to C8).** Accepted, with the gating rule made
explicit. J1's fix renames the basis and restates test 13; it does not say which of the four
cells binds. Since `R_at_print < R_incl` for any credit structure, requiring a positive-
expectancy strategy to "clear on all four" is satisfied trivially by the two easier cells, so
"all four" read as a stringency claim would have been decoration. §9.3 now states that the
**gate binds on the worst of the four — `R_incl` at 2×** — and that the other three are
disclosure.

**3 — the variant ledger's writer (J1).** Accepted, with one change of location. J1 asks that
the append-only run record be "written by `run_options_backtest` itself". That would put a
side effect inside the deterministic arithmetic core and break §15.1's S4 property (and make
the engine untestable without a DB). §14.3 puts the ledger in
`research/options_backtest_runner.py` — the layer that already owns the universe loop, the
IS/OOS split and persistence — which enumerates exactly the same set of invocations.

**4 — the S11 rename (J2).** Accepted as an **escalation**, not as a D2 decision. J2 is right
that a contract whose name stops being true while still passing is worse than no contract, and
right that the `backtest.* -> signalforge.options` import is what makes it stop being true.
But D2 writes no contracts and does not own the safety-test surface (§16). It is recorded in
§16 and escalated as Q12, with the specific requirement J2 asked for — same commit,
before/after wording shown to the operator.

**5 — the excluded-cycle bias measurement (J1).** Accepted, with two disclosures attached that
J1's fix did not name. The intrinsic-at-expiry payoff computed from `OHLCVDaily` carries no
exit costs, no early-assignment path, and uses the underlying's **daily close** rather than the
expiry settlement print. It measures the sign and order of magnitude of the exclusion's bias,
which is the point, but it is not a P&L — and §10.2 now says so, and says that an excluded
cycle is never added back into any gated statistic.

### What did not change, and why

Both audits' **strengths** sections agreed on the load-bearing content — C1 (the
`SCOPE_HASH_FIELDS` refusal), C2 (`spread_bps` is unreachable from the promotion path, and
"2× spread" is 2× the *assumption*), C3 (the five-label regime set and the two disagreeing
regime modules), C4 (the leakage harness cannot type a chain feature), C5/§3.3 (the
`first_print_session` visibility rule), the type-level conservatism of §3.2/§6.4/§6.6, and
§3.6's DB coverage claims, every one of which both passes reproduced exactly. **None of those
was altered.** J1 independently re-ran all eleven §3.6 coverage queries and reproduced them
without drift; those figures stand as written, minus the distributional statistics struck under
MAP §7.

---

*End of D2, rev 2. No code was written. No file under `src/` or `tests/` was modified. All
DB access in both revisions was read-only `SELECT`. No provider API was called, no package
installed, no secret or `.env` read. Rev 2's verification pass ran 13 `file:line` checks and
no DB query at all — the §3.6 figures were not re-read, because §16's whitelist rule applies
to this revision first.*
