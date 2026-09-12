# D3 — Options risk and paper-mechanics spec

Workstream D3 of `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` §7 Phase D.
Status: **DESIGN DOCUMENT ONLY.** No code, config, schema, contract, gate, or setting was
changed to produce it. Every DB fact behind it came from read-only `SELECT`s against the live
`data/signalforge.sqlite` while a paper probation and worker are running; every arithmetic
result came from the repo's own pure-math module (`signalforge.options.blackscholes`) on
**assumed** inputs, never from any price, IV, credit, return, or P&L series.

Written: 2026-09-11. Revised 2026-09-11 (rev 2) after an adversarial refutation pass; the
changes are itemised in **Appendix J — Judge responses**. Repo: `/Users/louisbrailey/signal-forge`.

**`git_sha` the FACTs were read at: `5b41a61` ("docs: state that operating mode alone produces no
intraday candidates").** Rev 1's `file:line` citations into `config/research.py`, `scheduler.py`
and `cli.py` were taken from a pre-commit read and did not resolve at HEAD; every citation in
this revision was re-resolved against `5b41a61`, and the sha is recorded here — as the program map
does — so the next reader can tell a stale pointer from a wrong claim. A `file:line` that does not
resolve is a correctness defect in this document, not a typo.

Labels: **FACT** = a `file:line` or a named read-only query stands behind it.
**HYPOTHESIS** = a design proposal nothing in the repo yet establishes.
**ARITHMETIC** = a computation from stated assumptions, reproducible from this document.

Binding inputs, not re-litigated here: `docs/research/DECISIONS_2026-09-12_options_execution.md`
(especially decisions **4** — capital limits — and **13** — a separate $25,000 SIMULATED options
paper account) and `docs/research/STRATEGY_COMPLETION_MAP.md` §1 R1–R10.

**R1 compliance statement.** Nothing in this document was informed by an outcome. The only
quantities computed are Black–Scholes values at hypothetical underlying prices and volatilities
chosen to illustrate limit arithmetic (S = 450, σ ∈ {0.12, 0.20, 0.30, 0.45, **0.60, 0.80**},
r = 0.04, q = 0, DTE ∈ {21, 30, 45, 60, **90**}, W ∈ {1, …, 5, 8, 10, 12, 20}; the box was widened
in rev 2 because rev 1's conclusions were artifacts of its narrowness). No `option_aggregate_daily`
row, no `option_quote_snapshot` row, and no underlying bar was read. The 110
`option_aggregate_daily` rows that exist were counted, never inspected.

---

## 0. What this document decides, and what it hands to someone else

| Decided here | Handed on |
|---|---|
| The account model, the collateral ledger, its reconciliation, the limit set and its arithmetic, the two marks, expiry processing, the second guard, the evidence-snapshot fields, the new tables, the migration plan, the auto-simulation extension | The fill model and spread constants (**D2**); `options_scope_json`'s composition (**D1**); gate wording and thresholds (**D4**); the pre-registered grid (**D5**); every capital number (**operator**, decision 4) |

| Decided here | Handed on (rev 2 additions) |
|---|---|
| The signal-to-fill session offset (§6.0); the transaction boundary and cash accounting (§8.0); the split of shaping parameters out of `OptionsRiskLimits` into `spec_json` (§4); the three-state `limits_evaluated` convention (§9); the reconcile-report table (§3.4, §13) | Whether `spec_json_hash` is the correct reading of map §3.2's "in `config_hash`" Rule (**D4**, §15 Q13a); the composition of the options `DataSnapshot` key (**D1**, **D4**); the frozen `OptionCostModel` constants that Findings 4 and 5 wait on (**D2**, §15 Q1) |

**Five** findings in §5 are load-bearing enough that they change what D4 and D5 can pre-register,
and two of them may change decision 4 itself. They are stated as findings, not as decisions.
**Rev 2 withdrew rev 1's Finding 3** (the "empty feasible set" that retired a gate the map states
as a Rule) and added **Finding 5** in its place.

---

## 1. Facts established by this pass

### 1.1 The live paper account is $30,000, not $100,000

**FACT** (read-only query, `data/signalforge.sqlite`, 2026-09-11):

```sql
select id, name, initial_cash, cash from paper_account;   -- (1, 'default', 30000, 30000)
select count(*) from paper_trade;      -- 0
select count(*) from paper_position;   -- 0
select count(*) from paper_order;      -- 0
select count(*) from paper_fill;       -- 0
select count(*) from strategy_health;  -- 0
select instrument_type, count(*) from instrument group by 1;  -- etf 684, stock 1974 (2658 total)
select name from sqlite_master where type='trigger';
  -- paper_trade_no_update, paper_trade_no_delete
select * from alembic_version;         -- e5a1b7c3d9f2
```

§3.1 of the program map reconciles the CSP collateral wall against "a $100k paper account" and
"a $250k account". **Neither exists.** The live equity paper account is $30,000
(`cli.py:1230` also ships `--cash` defaulting to `30_000.0`). The map's §3.1 arithmetic is
therefore softer than reality by 3.3×–8.3×, and every conclusion it draws against a $100k
account holds *a fortiori*. Decision 13's separate $25,000 options account is a **new, second**
account, not a resize of this one.

**FACT:** creating it needs no new code — `signalforge paper init --name <n> --cash 25000`
(`cli.py:1229`, `--cash` default `30_000.0` at `cli.py:1230`) creates a `PaperAccount` if absent
and is a no-op if present.

### 1.2 Every instrument in the live DB is a stock or an ETF

**FACT** (query above): 2,658 `instrument` rows, 1,974 `stock` + 684 `etf`, zero anything else.
`Instrument.instrument_type` carries the code comment `# stock | etf`
(`db/models/market.py:35`) and is `String(16)`.

Consequence, and it is the one that makes §3.3's demanded type assertion safe to add *today*:
an assertion in `mark_to_market` that raises on any non-`stock`/`etf` instrument is **provably a
no-op against current data** — there is no row it can fire on, and `paper_position` is empty
besides. It can and should be merged before any options code exists. See §7.

**Sizing trap (HYPOTHESIS):** `'option_structure'`, the type string §3.6 proposes, is **exactly
16 characters** — the full width of `String(16)`. SQLite does not enforce `VARCHAR` length, so it
would round-trip silently on SQLite and truncate or error on any other backend. Use
`'option_spread'` (13) **or** widen the column in the same migration. Do not ship a value that
sits exactly on the declared limit.

### 1.3 The live equity risk config is not the shipped default

**FACT** (read-only query on `app_setting`, key `research_overrides`):

```json
{"allow_short_candidates": true,
 "risk": {"per_trade_risk_pct": 10.0,
          "max_position_concentration_pct": 10.0,
          "max_portfolio_exposure_pct": 60.0},
 "watchlist": [...], "agents": {"enabled": true, "llm_narratives": true}}
```

**FACT:** `RiskLimits.per_trade_risk_pct` ships at `0.5` (`config/research.py:49`). The live
override is `10.0` — **20× the shipped default**.

**FACT (re-run read-only at `5b41a61`; rev 1 printed a filtered subset of this result and must be
corrected).** The stated query returns **seven** rows, not three:

```sql
select e.id, s.name, v.status, e.config_hash, e.dataset_snapshot_id
  from strategy_promotion_evaluation e
  join strategy_version v on e.strategy_version_id = v.id
  join strategy s on v.strategy_id = s.id
 where e.passed = 1;
-- 20 trend_continuation.short_swing   PAPER_APPROVED 11b54aee64dbc265... snapshot 3   SUPERSEDED
-- 23 relative_strength.medium_swing   PAPER_APPROVED 11b54aee64dbc265... snapshot 3   SUPERSEDED
-- 32 trend_continuation.short_swing   PAPER_APPROVED 11b54aee64dbc265... snapshot 3   SUPERSEDED
-- 35 relative_strength.medium_swing   PAPER_APPROVED 11b54aee64dbc265... snapshot 3   SUPERSEDED
-- 43 trend_continuation.short_swing   PAPER_APPROVED fe365720c0b61717... snapshot 3   CURRENT
-- 44 relative_strength.medium_swing   PAPER_APPROVED fe365720c0b61717... snapshot 3   CURRENT
-- 45 trend_continuation.medium_swing  PAPER_APPROVED fe365720c0b61717... snapshot 11  CURRENT
```

**What the two hashes mean.** `11b54aee64dbc265…` is the pre-`0cc4cf4` scope hash: before that
commit, `SCOPE_HASH_FIELDS` covered sections (including `agents`) that do not shape a signal, so
every approval carried a hash that a narrative-toggle change could move. `0cc4cf4` narrowed the
field list to the signal-shaping sections (`config/research.py:388-409` — the in-file comment
records exactly this incident), which re-hashed the *same* configuration to `fe365720…` and forced
evaluations 43–45. Rows 20/23/32/35 are superseded records of the same two strategies under the
old, wider scope definition; the table is append-only, so they remain `passed = 1` forever.

**FACT (verified by recomputation, no write):** `ResearchConfig(allow_short_candidates=True,
risk={"per_trade_risk_pct": 10.0, "max_position_concentration_pct": 10.0,
"max_portfolio_exposure_pct": 60.0}).config_hash` reproduces
`fe365720c0b61717649bba1b96e20a2d5c126ee6d4359f8c658510beda7c0a54` exactly. The live approval
scope therefore **is** the 10%-per-trade config.

**What the older hash implies for the options scope design (HYPOTHESIS).** Approved-scope evidence
exists under **two** config hashes for the same strategies, produced not by a strategy change but
by a change to the *definition of scope*. `scan_scope_matches` (`research/approval_scope.py:83-119`)
compares `config_hash` for equality, so a superseded row simply stops matching and the approval
narrows — fail-closed, correctly. But it means the blast-radius argument of §4 must be stated
precisely: the risk is not only "a new hash un-scopes an approval", it is "a change to what the
hash *covers* silently re-dates every approval in the table". The options design must therefore fix
the **composition** of `options_scope_hash` and `options_data_scope_hash` in the pre-registration
(D5), not only their values, so that a later widening of either is visible as a composition change
rather than as an unexplained re-evaluation.

Two consequences for D3:

1. §3.2's rationale for `options_per_structure_max_loss_pct = 0.5%` — "matches the equity
   per-trade figure so the two streams size comparably in *risk* terms" — is **not true of the
   running system**. The live equity per-trade risk budget is 10%. Options limits must be set on
   their own merits, in absolute dollars, exactly as decision 4 already states them. Delete the
   comparability argument; do not import an equity percentage.
2. **Three** strategies are PAPER_APPROVED, not the two §0.4 of the map records
   (`trend_continuation.medium_swing` v0.1.0 was added on snapshot 11 by commit `68b533c`).
   Any statement of the form "the two approved strategies" is now stale.

### 1.4 Adding a field to `SCOPE_HASH_FIELDS` un-scopes every live approval

**FACT** (`config/research.py:411-415`):

```python
@property
def config_hash(self) -> str:
    payload = self.model_dump(mode="json")
    return config_hash({k: payload[k] for k in self.SCOPE_HASH_FIELDS if k in payload})
```

Adding a key to `SCOPE_HASH_FIELDS` adds a dict entry and therefore changes the hash.
**Verified by recomputation** (pure, in-memory, no write): default scope hash
`7fb8213a…`; the same dict with one extra key `options_risk` hashes to `a19bce6c…`.

This is the exact failure mode recorded in `PAPER_PROBATION_ACTIVATION.md` and fixed by commit
`0cc4cf4` (the `agents` section incident) and in memory. **Hard rule for D3: no options risk
configuration may be added to `SCOPE_HASH_FIELDS`.** See §12 for where it goes instead.

### 1.5 Three functions besides `mark_to_market` would silently mis-handle an option position

§3.3 of the map names `mark_to_market`. It is not alone. Each of the following reads
`PaperPosition` with **no instrument-type filter and no account filter**:

| Function | `file:line` | What it would do to an options position |
|---|---|---|
| `mark_to_market` | `paper/ledger.py:266-321`, underlying lookup at `:290-292` | Prices the position from the **underlying's** daily bars and tests stop/target against the underlying's high/low (`:335-356`). Silently mis-prices. Filters by `account_id` (`:281-284`), so a separate options account does hide it from *this* one. |
| `portfolio_snapshot` | `paper/portfolio.py:22-97`, price lookup at `:51` via `_last_close` (`:17-19`) | Same underlying-bar pricing; feeds `equity_estimate`, `return_pct`, and the exposure report (`:81-82`). Filters by `account_id` (`:32-35`), so a separate account also hides it here. |
| `_paper_returns_r` (health monitor) | `research/health_monitor.py:57-80` | **No account filter.** Computes `R = realized_pnl / (abs(avg_price − stop_level) × qty)` — a per-share equity R. For a structure whose R is *max loss* this is simply a different number, and it feeds `downgrade_z`/`disable_z` (`config/research.py:277-278`). Worse: positions with `stop_level is None` are silently **skipped** (`:72-73`), so an options position that legitimately has no per-share stop would make the strategy permanently invisible to the health monitor. |
| `_paper_trade_summary` (probation) | `research/paper_probation.py:39-88`, query at `:48-67` | **No account filter.** Identical R formula and identical `stop_level is None` skip (`:61-62`); drives the probation equity curve and max-drawdown display. |
| `strategy_validation` agent | `agents/strategy_validation.py:228-230` | **No account filter.** Reads closed positions per strategy version. |

**Therefore (HYPOTHESIS, and this is the structural decision of D3): a separate account is
necessary but NOT sufficient.** Two of the five readers key on `strategy_version_id` alone and
would pick up options positions written into `paper_position` no matter which account they sit
on. Options structures get **their own tables** (§13), and the two R-computing readers get an
options-aware source (§7.3) rather than an accidental one.

### 1.6 Sealed-look accounting and R5 disclosure for the parameters D3 defines

Rev 1 defined `max_short_delta`, `time_stop_dte`, the DTE window, the width band and the profit/stop
multiples without saying anything about look counting. That is the wrong document to be silent in:
those are exactly the axes map §5.4 names as the place multiplicity will leak.

**FACT (map §5.4, re-verified):** `count_sealed_looks(session, strategy_name)`
(`research/promotion.py:615`) counts every `StrategySealedTest` joined through `StrategyVersion` to
`Strategy.name`; `evaluate_promotion` captures `k_prior` at `:888`; `sealed_look_ledger` (`:634`)
enumerates the history and is attached as gate-9 evidence (`:1293`). **FACT:** `StrategySealedTest`
is unique on `(strategy_version_id, dataset_snapshot_id)` (`db/models/research.py:252,263`) and is
reused, never recomputed, on replay.

**Therefore, stated here so D4 and D5 can rely on it:**

1. **The options family starts at k = 0 by construction, with no new code.** A strategy named
   e.g. `options_short_vertical.position` has no prior `strategy_sealed_test` rows, so
   `k_prior = 0` automatically and the equity families' counts (mean_reversion.short_swing 5,
   relative_strength.medium_swing 4, trend_continuation.medium_swing 5,
   trend_continuation.short_swing 4, volatility_breakout.short_swing 4) can never be conflated
   with it in either direction. Any multiplicity statement about options must name the family and
   cite `count_sealed_looks` for it.
2. **Every `OptionsRiskLimits` cell and every `spec_json` cell explored before the first sealed
   look is a disclosable R5 variant.** `count_sealed_looks` counts what was *sealed*; it cannot
   see a (delta, DTE, width, time-stop) cell that was evaluated pre-sealed, looked wrong, and was
   dropped. D5's pre-registration must enumerate the **complete** grid so that "abandoned variant"
   is definable as "a pre-registered cell that was not reported" — a cell that was never
   pre-registered and never reported is invisible to both mechanisms.
3. **`options_scope_hash` and `options_data_scope_hash` are recorded on every options promotion
   evaluation precisely so an undisclosed variant is detectable.** Two evaluations of the same
   `strategy_version` whose options hashes differ are, by construction, two variants; if only one
   appears in the disclosure list, the ledger says so.
4. **A change to any parameter in §4's *shaping* group forces a new sealed test** — see §4, which
   moves those parameters into the strategy's `spec_json` and makes the options snapshot key carry
   the options scope hashes. Without that, a shaping change leaves no artifact anywhere and the
   three mechanisms above have nothing to bite on. That coupling, not the counting, is the load
   bearing part.

---

## 2. The options paper account (decision 13)

**HYPOTHESIS — the shape.**

* Name: `options_paper`. Initial cash: `Decimal("25000")`. Created by
  `signalforge paper init --name options_paper --cash 25000` (**FACT**: `cli.py:1229-1240`
  already does exactly this and is idempotent).
* Every options code path takes `account_name` as a required keyword with **no default**.
  Rationale (**FACT**): `accept_candidate` (`ledger.py:129-137`), `mark_to_market` (`:266-270`),
  `portfolio_snapshot` (`portfolio.py:22-27`), `record_decision` (`ledger.py:92-98`) and the
  scheduler's `job_paper_mtm` (`scheduler.py:249`) all default to `"default"`. A defaulted options
  function would write into the equity account on the first forgotten argument. Making it
  required converts that from a silent bug into a `TypeError` at import-test time.
* **A required argument stops a *forgotten* account name; it does nothing about a *wrong* one.**
  `account_name="default"` is a perfectly valid string, and it resolves to the **live $30,000
  equity account** (**FACT**: `select id,name,initial_cash,cash from paper_account` →
  `(1, 'default', 30000, 30000)`), against which the options path would then write collateral
  reservations and a `collateral_reserved` balance. Rev 1's guard condition — "`account.name` ==
  the configured options account" — closed nothing, because rev 1 configured no options account
  anywhere: the guard resolved the account **by** the caller's string and then checked that the
  resolved account carried that string. It is a tautology.
* **Therefore the account is named in configuration, not by the caller (HYPOTHESIS).**
  `OptionsRiskLimits` (§4) carries `paper_account_name: str = "options_paper"` — it sits in the
  refusal-only group, outside every hash, so naming it costs nothing. §10.2 condition N compares
  the **resolved** account against *that configured value*, and additionally asserts
  `account.id != <the id of the account named 'default'>`, so the live equity account can never be
  the target even if the configured name is later edited to point at it.
* The account name is **recorded on every evidence snapshot** (§9) and asserted by the second
  guard (§10).

**Why $25,000 and what it collides with (ARITHMETIC).** $25,000 is also the PDT threshold
acknowledged in decision 4. Paper equity is not a broker balance, so PDT does not bind the
simulation; but sizing the *paper* account at exactly the PDT line means that when the operator
later mirrors these limits onto a real account, an account that dips below $25,000 through
drawdown crosses a regulatory threshold at the same moment the percent-of-equity limits tighten.
Record that as a known coupling; do not design around it in Phase 1.

**Reporting requirement (HYPOTHESIS).** The equity `portfolio_snapshot` must not silently exclude
options risk from the operator's view. `paper/portfolio.py` gains a sibling
`options_portfolio_snapshot(session, *, account_name)` and the dashboard/CLI display **both**,
side by side, with the combined net delta and net vega (§5.3) as a third block. Never a merged
equity figure — the two accounts are separate populations by decision 13 and must read that way.

---

## 3. Collateral and buying-power ledger

**FACT:** `PaperAccount` has exactly three business columns — `name`, `initial_cash`, `cash`
(`db/models/paper.py:37-44`). There is nowhere to hold collateral apart from spendable cash.

### 3.1 Fields and tables

**HYPOTHESIS:**

```
PaperAccount                                    (additive)
  + collateral_reserved : Numeric(20,6) NOT NULL DEFAULT 0

paper_collateral_entry                          (new, append-only, S9-style)
  id                    INTEGER PK
  account_id            FK paper_account ON DELETE CASCADE
  structure_id          FK paper_option_structure ON DELETE RESTRICT   # never orphaned
  event                 VARCHAR(16)   # 'reserve' | 'release'  (no 'adjust' — see below)
  amount                Numeric(20,6) # always POSITIVE; `event` carries the sign
  basis_json            JSON          # the full formula inputs, below
  balance_after         Numeric(20,6) # account collateral_reserved AFTER this entry
  as_of                 UTCDateTime   # session the entry belongs to
  created_at            UTCDateTime   (indexed)
```

`basis_json` records, per entry: `formula` (one of the four names in §3.2), `strike`,
`strike_width`, `shares_per_contract` **as read from `option_contract`** (`market.py:255`),
`contracts`, `net_credit`, `entry_costs`, and the resulting `amount`. A reservation whose
`basis_json` cannot be re-evaluated to `amount` is a bug the reconciler (§3.4) must catch.

**No `adjust` event, deliberately (HYPOTHESIS).** Phase 1 reserves once at entry and releases
once at exit. A mid-life adjustment would mean the reservation was wrong, and the honest record
of that is `release` + `reserve` (two rows, both auditable), never a mutation of the first.

**Immutability (HYPOTHESIS, mirroring **FACT** `20260906_1041-839214f66f31_initial_schema.py:1263-1286`):**
the migration adds `BEFORE UPDATE` / `BEFORE DELETE` triggers on `paper_collateral_entry` with
the same `RAISE(ABORT, …)` shape as `paper_trade_no_update` / `paper_trade_no_delete`, guarded by
the same `dialect.name in {"sqlite"}` check, and dropped symmetrically in `downgrade()`.

### 3.2 Reservation formulas

With `M = shares_per_contract` **read per leg from the contract row** and asserted `== 100` at
entry (§2.3 of the map; the assertion is what makes every `× 100` below provably correct):

| Structure | Reserved at entry |
|---|---|
| defined-risk vertical (credit) | `strike_width × M × contracts − net_credit + entry_costs` (**= R**, §2.6) |
| defined-risk vertical (debit) | `net_debit + entry_costs` (cash-settled at entry; reserve equals the debit so `spendable_cash` and max loss agree) |
| cash-secured put | `strike × M × contracts − net_credit + entry_costs` |
| covered call | the underlying shares, not cash — **out of Phase 1 scope** (decision 8 defers O2) |

**HYPOTHESIS:** `spendable_cash = cash − collateral_reserved`, exposed as a property, and every
options entry checks it **first** and refuses otherwise, raising the same
`OptionsAutoSimulateForbidden` used by the guard (§10) so the refusal is recorded rather than
logged.

**Invariant (HYPOTHESIS, asserted in code, not just documented):**

```
collateral_reserved == sum(+amount for reserve) − sum(+amount for release)
                    == sum(R over all open paper_option_structure rows)
```

Both equalities are checked by `reconcile_options_collateral` (§3.4). The first catches a lost
ledger write; the second catches a reservation that does not match the structure it is for.

### 3.3 Why the collateral ledger is not the binding constraint here

**ARITHMETIC.** Decision 4 sets the collateral cap at $5,000 = **20%** of the $25,000 account
(§3.2 of the map proposed 30%). Under decision 4's per-structure max loss of $250 and aggregate
of $1,000, the maximum collateral a defined-risk vertical book can ever reserve is the aggregate
max loss itself: **$1,000**, or 4% of equity. The $5,000 cap has 5× headroom and **never binds**
for verticals.

It binds only for the cash-secured put: one SPY-priced CSP at a ~$430 strike reserves
~$43,000 — **1.7× the entire options account** and 8.6× the collateral cap. This is the §3.1
collateral wall, and on a $25,000 account it is not a constraint to be managed, it is a
**structural impossibility**: the CSP cannot be paper-traded on this account at any strike above
$50. Combined with decision 12 (vertical ships first) this is settled; recorded here so that if
O1 is ever revived the wall is on the record with the right account size behind it.

### 3.4 Reconciliation

**HYPOTHESIS:** `reconcile_options_collateral(session, *, account_name, as_of) -> ReconcileReport`,
run by the worker **immediately after** the options mark and **before** expiry processing (§8),
and available as `signalforge paper options-reconcile`. It is **read-only except for its own
report row** — a reconciler that silently repairs is a reconciler that hides the bug it found.

Checks, each producing a named finding:

1. `account.collateral_reserved` equals the signed sum of `paper_collateral_entry` for that account.
2. `account.collateral_reserved` equals Σ R over open `paper_option_structure` rows.
3. Every open structure has exactly one unreleased `reserve` entry.
4. Every closed structure has exactly one matching `release`, with `release.amount == reserve.amount`.
5. **No closed structure has an unreleased `reserve`** — the reciprocal of check 3, and the one that
   catches the crash window §8 step 4 now orders against. Without it, a structure closed with its
   collateral still reserved is invisible until check 2 happens to disagree.
6. **No open structure has a `release`** — the reciprocal of check 4, and the one that catches the
   *other* crash ordering (collateral freed, structure still open). This is the fail-open case, so
   it is a finding at the highest severity: it inflates `spendable_cash` and re-opens capacity
   under §10.2 conditions O / P / R.
7. Every `basis_json` re-evaluates to its own `amount`.
8. `spendable_cash >= 0`.
9. `collateral_reserved <= collateral_cap_dollars`.
10. Every leg's `shares_per_contract` is still 100 (catches a post-entry OCC adjustment; **FACT**:
    `option_contract.shares_per_contract` is vendor-populated on every write path —
    `adapters/massive_options.py:183`, `data/options_ingest.py:97`, `data/options_backfill.py:151`).

**Where the result lives, and why a flag is not enough (HYPOTHESIS).** Rev 1 said "any finding sets
an `options_reconcile_failed` flag that the second guard reads". That flag had no home — it was not
a field of `OptionsRiskLimits`, not a table in §13, not a settings key in §12 — so the condition was
not buildable; and worse, it was **satisfiable by absence**: on the first session after the
migration, on any session the reconciler was skipped, and on any session it crashed before writing
anything, there is no failure flag and therefore no divergence, so an entry would open on a book
nothing had ever reconciled.

**The reconciler therefore writes a row, and the guard requires the row (HYPOTHESIS):**

```
paper_options_reconcile_report          (new, append-only — §13)
  id / account_id (FK) / as_of DATE / findings_json JSON / clean BOOLEAN
  collateral_reserved_observed / collateral_reserved_expected / open_structures / created_at
  UNIQUE (account_id, as_of)
```

§10.2 condition AA is then **positive and dated**: a `paper_options_reconcile_report` row exists
for **this** account with `as_of` equal to the current completed session **and** `clean` is true
(`findings_json` empty). A missing row refuses exactly as a divergent row refuses. Absence is never
evidence of health.

**Failure policy (HYPOTHESIS):** divergence blocks **opening** and never blocks **closing** — the
same asymmetry as the kill switch (**FACT**: `mark_to_market`'s docstring and body deliberately omit
`ensure_not_engaged`, `ledger.py:266-276`). A book that cannot be reconciled must still be able to
get flat.

### 3.5 The paper trade rate, and the gate-10 window

§3.1 of the map requires the expected paper trade rate to be stated **before** probation starts,
and the observation window derived from it.

**ARITHMETIC** (all inputs from decision 4 and §2.7's grid centres; no outcome data):

* Aggregate open max loss $1,000 ÷ per-structure max loss $250 ⇒ **4 concurrent structures**, not
  the 5 of §3.2's `options_max_open_structures` grid centre. The count limit is **not binding**;
  the aggregate max-loss limit is. `options_max_open_structures = 5` is dead configuration at
  decision 4's numbers — keep it (it binds if the per-structure cap falls) but report which limit
  actually bound on every refused entry.
* Entry at 21–45 DTE with a 7-DTE time stop ⇒ maximum hold 14–38 calendar days ≈ **10–27
  sessions**; profit-target exits shorten it. Take 10 sessions (fast) and 27 (slow) as bounds.
* Closed trades per month = 4 slots ÷ hold × 21 sessions ⇒ **8.4/month** (fast) to **3.1/month**
  (slow).
* **FACT:** `HealthMonitorConfig.min_paper_trades = 20` (`config/research.py:273`) and decision 10
  requires ≥ 20 closed paper trades with non-negative expectancy before arming.
* ⇒ **20 closed options paper trades takes 2.4 to 6.5 months**, and that is the *floor*: it assumes
  a qualifying signal every time a slot frees, which the regime filter of O3 will not deliver.

**Pre-registered statement for D5 (HYPOTHESIS):** state the probation window as **≥ 6 months or
20 closed structures, whichever is later**, and record the assumed rate above with it, so that a
window that ends early is visibly an override rather than a re-derivation. The backtest stream
(gates 1–9) and the paper stream (gate 10) are different populations by construction — decision
13 resizes the account, it does **not** make them the same population, and §3.1's alternative
reading ("size the paper account to the strategy" makes the streams comparable) is wrong at
$25,000: 4 concurrent structures is an order of magnitude thinner than any backtest that is
position-count-unconstrained.

---

## 4. Where the options risk config lives

See §1.4: it may **not** go into `SCOPE_HASH_FIELDS`.

**The rev-1 design put strategy-shaping parameters in a container it then declared hash-exempt, and
that is a pre-registration leak.** Rev 1 bundled `max_short_delta`, `min_credit_to_width` and
`time_stop_dte` into `OptionsRiskLimits` alongside the dollar caps, and made it a hard rule that the
**whole object** stays out of every hash. Those three do not limit capital — they decide **which**
structure opens and **when** it closes. The repo already distinguishes the two kinds and puts the
shaping kind inside the hash: **FACT** — `risk` **is** in `SCOPE_HASH_FIELDS`
(`config/research.py:392-409`), because `RiskLimits.min_reward_to_risk` filters which candidates
exist at all. `max_short_delta` filters entries and `time_stop_dte` forces exits by exactly the same
mechanism.

**What that leak buys an adversary, stated concretely.** **FACT:** `StrategySealedTest` is unique on
`(strategy_version_id, dataset_snapshot_id)` (`db/models/research.py:252,263`) and is reused, never
recomputed, so nothing forces a fresh look when a parameter outside the identity changes; and rev 1
compared `options_scope_hash` **only** inside the live guard (§10.2 condition I), never in snapshot
or sealed-test identity. Net: the entry delta ceiling or the time stop could be moved, the
pre-sealed backtest re-run, and **no trace would appear** in `config_hash`, in `spec_json_hash`, in
the five-part scope match, or in the sealed-look ledger. That is the whole of R1 defeated by a field
placement.

**HYPOTHESIS — split the object along the refusal / shaping line.**

```python
class OptionsRiskLimits(BaseModel):          # NEW, in config/research.py
    """REFUSAL-ONLY capital limits. Nothing here selects a structure or times an
    exit; every field can only ever REFUSE an open. Deliberately OUTSIDE every
    hash: an operator tightening a dollar cap must not un-scope an approval."""
    model_config = {"frozen": True, "extra": "forbid"}
    # decision-4 numbers, recorded as evaluation grid CENTRES.
    per_structure_max_loss_dollars:   PositiveFloat = 250.0
    total_open_max_loss_dollars:      PositiveFloat = 1_000.0
    collateral_cap_dollars:           PositiveFloat = 5_000.0
    max_net_delta_notional_dollars:   PositiveFloat = 10_000.0
    max_net_vega_dollars_per_vol_pt:  PositiveFloat = 50.0
    combined_max_net_delta_notional_dollars: PositiveFloat = 10_000.0   # §5.2 Finding 2
    per_order_notional_dollars:       PositiveFloat = 1_000.0
    daily_order_cap:                  PositiveInt   = 10
    account_exposure_cap_pct:         PositiveFloat = 40.0
    max_open_structures:              PositiveInt   = 5
    max_structures_per_underlying:    PositiveInt   = 1   # keyed on UNDERLYING (§10)
    paper_account_name:               str           = "options_paper"   # §2, §10.2 cond. N

class ResearchConfig(BaseModel):
    options_risk: OptionsRiskLimits = Field(default_factory=OptionsRiskLimits)
    # SCOPE_HASH_FIELDS: UNCHANGED. `options_risk` is deliberately absent.
```

**Every parameter that shapes selection or exit moves into the strategy's `spec_json`**, where the
existing machinery already hashes it:

```
strategy spec_json["options"] = {
    "structure_type":            "VERTICAL_CREDIT",   # gate 0.5: exactly one per version
    "max_short_delta":           0.20,   # SELECTION — entry delta ceiling
    "min_credit_to_width":       0.25,   # SELECTION — see §5.3, KEPT as a gate
    "min_net_credit_after_costs_to_max_loss": <theta>,  # SELECTION — §5.3 axis 2
    "dte_window":                [21, 45],
    "width_band_dollars":        [2, 3],
    "profit_target_pct_of_credit": 0.50,
    "stop_multiple_of_credit":   2.0,
    "time_stop_dte":             7,      # EXIT — forces a close
}
```

**FACT:** `StrategyPromotionEvaluation.spec_json_hash` (`db/models/research.py:309`) is "sha256 of
the strategy's own spec()/params at evaluation time", and `scan_scope_matches`
(`research/approval_scope.py:83-119`) compares it for equality as one of the five parts — with the
in-file comment stating that this is precisely what catches params drifting after approval without
the version string changing. Moving the shaping parameters there therefore costs no new machinery
and buys the exact protection the map's §3.2 **Rule** asks for ("both are pre-registered, both are
in `config_hash`, both are sensitivity axes") **without** the collateral damage of touching
`SCOPE_HASH_FIELDS` and re-hashing all three live equity approvals. Where the map says
`config_hash`, read `spec_json_hash`: same five-part match, correct blast radius. That reading is
flagged for D4's explicit agreement in §15.

**FACT:** `options` is already outside `SCOPE_HASH_FIELDS` (`config/research.py:392-409`) and the
in-file comment (`:380-391`) names exactly this reasoning. `options_risk` follows it.

**The options approval scope is pinned in three places, not one (HYPOTHESIS).** The equity scope
match is five-part (`research/approval_scope.py:83-119`). The options design adds a **sixth and
seventh** part, computed separately and never folded into `config_hash`:

```
options_scope_hash      = config_hash({"options": <OptionsConfig>, "options_risk": <OptionsRiskLimits>})
options_data_scope_hash = hash of D1/§3.5's options_scope_json
```

and — **this is the correction rev 1 missed** — both are components of the options
**`DataSnapshot` key**, not only of the live guard. **Requirement handed to D1 and D4:** the options
snapshot key must incorporate `options_scope_hash` and `options_data_scope_hash`, so that changing
either produces a **new** `DataSnapshot` and therefore, by the
`(strategy_version_id, dataset_snapshot_id)` uniqueness, a **new sealed test** that
`count_sealed_looks` counts. This is strictly more searching — it can only ever *increase* the
recorded look count — and is therefore permitted under R4. Map §2.7's equivalent rule for coverage
parameters ("changing any coverage parameter creates a new snapshot and therefore a new sealed
test") is the precedent; this extends it to the risk and shaping scope.

Both hashes are also stored on the options promotion evaluation and compared by
`assert_options_auto_simulate_allowed` (§10.2 conditions I and J). Changing a **refusal-only** limit
un-scopes the **options** strategy and nothing else — the correct blast radius, and the lesson of
`0cc4cf4` applied in the right direction. Changing a **shaping** parameter does more than un-scope
it: it moves `spec_json_hash`, forces a new snapshot, and costs a counted sealed look. That
asymmetry is the design.

---

## 5. Limits: decision 4 reconciled against §3.2, with the arithmetic shown

### 5.1 The percent/dollar reconciliation

Decision 4 states dollars; §3.2 states percents of equity. Against decision 13's $25,000:

| Limit | Decision 4 | As % of $25,000 | §3.2 grid centre | Decision 4 is |
|---|---|---|---|---|
| per-structure max loss | $250 | **1.00%** | 0.5% ($125) | **2× looser** |
| aggregate open max loss | $1,000 | **4.00%** | 2% ($500) | **2× looser** |
| collateral cap | $5,000 | **20.0%** | 30% ($7,500) | 1.5× tighter |
| net delta (beta-wtd notional) | ±$10,000 | ±40% of equity | *to be set* | — |
| net vega | $50/vol-pt | 0.20%/vol-pt | *to be set* | — |
| per-order notional | $1,000 | 4.0% | — | — |
| account exposure cap | 40% | — | — | — |

Decision 4 is binding and the looser cells are the operator's call. They are recorded here only
because §3.2's percentages are the numbers D4's sensitivity grid will be built around, and the
grid must be centred on the numbers that will actually be enforced. **D4 and D5 must use the
decision-4 dollar values as grid centres, not §3.2's percentages.**

**FACT correction to §3.2's stated rationale:** the 0.5% figure is justified in the map as
matching the equity per-trade risk. The live equity per-trade risk is **10%**
(§1.3). Drop the rationale; keep the number only if the operator wants it on its own merits.

### 5.2 Net delta and net vega — the units, and what actually binds

**FACT** (`options/blackscholes.py:24-39`): `Greeks.vega` is per **1.00** change in σ (i.e. per
100 vol points), and `Greeks.vega_per_vol_point` divides by 100 (`:36-38`). `Greeks.delta` is per
share. So, per structure:

```
position_delta_shares   = Σ_legs  qty_signed × delta_leg × M
net_delta_notional_$    = Σ_structures  position_delta_shares × underlying_price × beta_to_SPY
net_vega_$_per_vol_pt   = Σ_legs  qty_signed × (vega_leg / 100) × M
```

`beta_to_SPY` uses the same SPY proxy series `backtest/regime.py` already uses — **FACT**
(map §2.2): no new data is required.

**ARITHMETIC — one SPY short put vertical, 1 contract** (S = 450, σ = 20%, r = 4%, q = 0,
M = 100; all assumed, computed with `signalforge.options.blackscholes.greeks`):

| DTE | short \|Δ\| | width | net Δ (shares) | net Δ notional | net vega $/vol-pt |
|---|---|---|---|---|---|
| 30 | 0.16 | 2 | 1.90 | $854 | −2.55 |
| 30 | 0.20 | 3 | 3.24 | $1,459 | −3.76 |
| 30 | 0.30 | 3 | 4.04 | $1,817 | −3.00 |
| 30 | 0.20 | 10 | 9.49 | $4,269 | −12.59 |
| 45 | 0.20 | 3 | 2.70 | $1,216 | −3.78 |

For scale: one **ATM** SPY put at 30 DTE is $51.3/vol-pt and −$20,958 of delta notional per
contract — i.e. a single ATM contract would breach **both** decision-4 caps on its own. The caps
are correctly scaled for spreads and correctly hostile to naked ATM exposure.

**Finding 1 — at decision 4's numbers, neither greek cap binds.** Four 3-wide 0.20-delta
structures (the maximum the $1,000 aggregate max-loss cap permits, §3.5) total
**$5,836 of net delta notional** (58% of the ±$10,000 cap) and **−$15.0/vol-pt** (30% of the $50
cap). The delta cap would not bind until ~7 structures and the vega cap until ~13 — both beyond
what the max-loss caps allow. §3.2 argues the net-delta cap "is what stops the five-ticker beta
bet"; under decision 4 the **aggregate max-loss cap stops it first**, at $1,000 of simultaneous
realised loss.

The caps are still required, for three reasons that D3 asserts rather than assumes:
(a) they bind immediately if the per-structure cap is raised — and §5.4 argues it must be;
(b) they bind on a higher-priced underlying or a wider structure at the same max loss;
(c) they are the only limits that can express the **combined** options + equity book.

**Finding 2 — the combined cap must never block an equity entry.** §3.2 requires the delta and
vega caps to cover "all open options *plus* the open equity book". Decision 13 puts the two books
in separate accounts. The resolution (HYPOTHESIS):

* `max_net_delta_notional_dollars` / `max_net_vega_dollars_per_vol_pt` (§4) are computed over the
  **options account only** and are hard limits: exceeding one refuses the options entry.
* `combined_max_net_delta_notional_dollars` (§4) is computed over **both** accounts and is likewise hard —
  but it is evaluated **only inside `assert_options_auto_simulate_allowed`** and can therefore
  only ever refuse an **options open**. It is never consulted by `size_position`
  (`risk/engine.py:59`), by `accept_candidate`, or by `assert_auto_simulate_allowed`. The equity
  path is byte-identical whether or not this limit exists.
* Neither ever blocks a close. Both are reported on every cycle, bound or not, so the operator
  can see the headroom rather than infer it from an absence of refusals.

### 5.3 `min_credit_to_width` + `max_short_delta` — correlated, not degenerate, and the pair is KEPT

§3.2 requires `min_credit_to_width` to be paired with a maximum short-strike delta, both
pre-registered, both sensitivity axes, and states it as a **Rule**. Rev 1 proposed retiring the
credit hurdle on two grounds — that the two are the same axis "to within about ±0.02", and that the
pair has an empty feasible set. **Both grounds were measured on too small a box, and both are
withdrawn.** The Rule stands.

**ARITHMETIC** (`blackscholes.price`, S = 450, r = 4%, q = 0, integer strikes; credit/width for a
put vertical at the strike whose |Δ| is closest to the target; recomputed at `5b41a61`). The cell
now carries the **residual** `credit/width − |Δ|`:

| σ | DTE | W | Δ=0.10 | Δ=0.16 | Δ=0.20 | Δ=0.25 | Δ=0.30 | Δ=0.40 | residual range |
|---|---|---|---|---|---|---|---|---|---|
| 0.12 | 21 | 3 | 0.087 | 0.131 | 0.167 | 0.233 | 0.258 | 0.368 | −0.015 … **−0.034** |
| 0.20 | 30 | 3 | 0.098 | 0.157 | 0.199 | 0.248 | 0.301 | 0.403 | −0.001 … −0.002 |
| 0.20 | 45 | 2 | 0.104 | 0.170 | 0.206 | 0.257 | 0.312 | 0.408 | +0.006 … +0.013 |
| 0.30 | 45 | 3 | 0.111 | 0.180 | 0.218 | 0.275 | 0.322 | 0.428 | +0.012 … +0.026 |
| 0.45 | 60 | 2 | 0.133 | 0.202 | 0.249 | 0.303 | 0.361 | 0.465 | +0.032 … **+0.064** |

**Correction to rev 1: the residual is −0.034 to +0.064, not ±0.02 — roughly 3× the stated figure,
and it is not noise.** It is **monotone in σ√T**: strictly negative at σ = 0.12 / 21 DTE, ≈ 0 at
σ = 0.20 / 30 DTE, strictly positive and growing thereafter, reaching +0.064 at σ = 0.45 / 60 DTE /
Δ = 0.40. Credit/width approximates the risk-neutral probability that the short strike finishes ITM,
which is `N(−d₂)`, while |Δ| for a put is `N(−d₁)`; the two differ by exactly one `σ√T` term in the
d-argument, so the gap is a **systematic function of σ√T**, not measurement scatter.

Two things follow, and they point the opposite way from rev 1:

* **The systematic residual is an argument for keeping a credit axis, not for retiring it.** A
  quantity that differs from delta by a known, monotone function of σ√T carries information delta
  does not: at a fixed delta ceiling, the credit hurdle discriminates long-dated/high-σ entries from
  short-dated/low-σ ones. That is a real second dimension.
* **It is also exactly the quantity axis 4's ρ sets out to measure**, so ρ must not be presented as
  measuring a volatility risk premium: in this pure Black–Scholes computation there is **no premium
  at all**, and ρ is still ≠ 1 by up to 0.064/0.40 ≈ 16%. See the amended axis 4 below.

**Finding 3 (restated, and rev 1's version is withdrawn) — the feasible set is NOT empty; rev 1's
box was too small.** Rev 1 concluded that (`min_credit_to_width = 0.25`, `max_short_delta = 0.20`)
has an empty feasible set because the largest credit/width at Δ = 0.20 in the table above is 0.249
(σ = 0.45, 60 DTE, W = 2) — one thousandth under the hurdle. **RECOMPUTED over a wider box**
(σ ∈ {0.12, 0.20, 0.30, 0.45, 0.60, 0.80}, DTE ∈ {21, 30, 45, 60, 90}, W ∈ {1, 2, 3, 4, 5}, same
method), credit/width at |Δ| ≈ 0.20 reaches ≥ 0.25 in a substantial region:

| σ | DTE | W=1 | W=2 | W=3 | W=4 | W=5 |
|---|---|---|---|---|---|---|
| 0.45 | 60 | **0.2510** | 0.2488 | 0.2466 | 0.2444 | 0.2422 |
| 0.45 | 90 | **0.2635** | **0.2616** | **0.2597** | **0.2578** | **0.2560** |
| 0.60 | 45 | **0.2598** | **0.2578** | **0.2558** | **0.2538** | **0.2519** |
| 0.60 | 60 | **0.2705** | **0.2687** | **0.2670** | **0.2652** | **0.2634** |
| 0.60 | 90 | **0.2898** | **0.2882** | **0.2867** | **0.2851** | **0.2836** |
| 0.80 | 21 | **0.2556** | **0.2535** | **0.2513** | **0.2492** | **0.2471**\* |
| 0.80 | 45 | **0.2832** | **0.2816** | **0.2800** | **0.2784** | **0.2768** |
| 0.80 | 90 | **0.3238** | **0.3226** | **0.3213** | **0.3200** | **0.3187** |

(\* 0.2471 is below the hurdle; every other bolded cell clears 0.25. Every cell at σ ≤ 0.30 fails
the hurdle at any DTE or width tested, which is why rev 1's σ ≤ 0.45 / DTE ≤ 60 / W ∈ {2,3} box
looked empty.)

**What this does and does not show, stated carefully.** The feasible region is real but it is
narrow, it sits entirely at high σ and/or long DTE, and — critically — **it is produced by the same
σ√T residual documented above, in a model with no risk premium whatsoever.** It is therefore *not*
evidence that "the pair is feasible exactly where the volatility risk premium is present". It is
evidence only that the pair is arithmetically satisfiable outside rev 1's box. Whether the region is
*economically* reachable on real prints is an empirical question nobody may answer before the
pre-registration is sealed.

**HYPOTHESIS — the revised axis set. Both original axes are kept; a third is added.**

1. **`max_short_delta` is the risk axis** and stays a pre-registered sensitivity axis
   (grid centre 0.20; grid 0.10 / 0.16 / 0.20 / 0.25 / 0.30).
2. **`min_credit_to_width` is KEPT as a gate**, per map §3.2's Rule, paired with axis 1 and
   pre-registered as its own sensitivity axis. Before any cell may be declared infeasible, the
   feasibility scan above must be re-run over the **full pre-registered (σ, DTE, W) box** — including
   W = 1 and σ to at least 0.80 — on D2's frozen cost model. If, after that, D4 still wants the pair
   replaced, it must be recorded as an **explicit, D4-agreed override of the map's Rule**, with the
   override and its reason in the pre-registration — never as a derived finding of D3. Raising the
   delta ceiling to force feasibility remains forbidden: it drives the grid onto its highest-delta
   corner, which is precisely the failure §3.2 predicts.
3. **A third axis is added, economic rather than directional:**
   `min_net_credit_after_costs_to_max_loss = (net_credit − modelled_round_trip_costs) / R ≥ θ`,
   with θ pre-registered and evaluated at **both** the baseline and 2× spread settings (gate 4b).
   This is orthogonal to delta by construction — moving the short strike closer to the money
   raises both the credit and R, and raises the cost too — and it is the quantity that decides
   whether the structure can pay for itself. §5.4 shows it is also the constraint that currently
   fails.
4. **Optional fourth axis, disclosed as circular AND as model-contaminated if used:** a
   credit-quality ratio `ρ = (credit/width) ÷ |short delta| ≥ ρ_min`, which *intends* to ask whether
   the market pays more than the risk-neutral odds — i.e. whether the volatility risk premium is
   present. **Two independent reasons it does not cleanly measure that:**
   (a) **Circularity** — if the delta and the credit come from the same source, then under §2.4b's
   same-session surface an IV fitted to the prints reproduces ρ ≈ 1 by construction. It is
   informative only when the delta comes from the **cross-sectional surface fit** and the credit from
   the **two legs' own prints**, and even then the residual is a fit residual as much as a premium.
   (b) **Model contamination, new in rev 2 and measured above** — ρ ≠ 1 in a pure Black–Scholes
   world containing no premium at all, by up to 16% at σ√T at the top of the box, because
   credit/width tracks `N(−d₂)` and |Δ| tracks `N(−d₁)`. **Any ρ gate must therefore be stated
   relative to the model's own σ√T baseline**, i.e. against `ρ_BS(σ, T)` computed from the same
   inputs, not against 1.0. A ρ gate against 1.0 would systematically admit long-dated, high-σ
   structures and call the arithmetic an edge.
   If D5 uses ρ, it must disclose both. D3's recommendation is unchanged: report ρ, gate on θ, and
   keep axes 1 and 2.

### 5.4 Finding 4 — the per-structure max-loss cap, the cost model, and gate 4b are jointly infeasible

This is the most consequential result in D3 and it changes what D5 can pre-register.

**Setup (all assumed; D2 owns the real constants).** §2.4(1a) of the map specifies
*print-plus-full-spread*: a full modelled spread per leg per side, so a 2-leg vertical pays
**four** full crossings round trip. §2.5 specifies `spread_pct_of_last_print` and
`spread_abs_floor_cents`. For illustration take `spread = max(5¢, 5% × last_print)` per leg per
side and $0.70/contract of commission+fees, and compute the modelled Black–Scholes prints at
S = 450, σ = 20%, 30 DTE, |Δ| ≈ 0.20 (short strike 431, short print $2.98).

| width | credit | max loss (R) | R as % of $25k | cost @1× | cost/credit @1× | cost @2× | cost/credit @2× | credit − cost @2× |
|---|---|---|---|---|---|---|---|---|
| 2 | $41.01 | $158.99 | 0.6% | $58.26 | **142%** | $113.73 | **277%** | −$72.72 |
| 3 | $59.83 | $240.17 | 1.0% | $56.38 | **94%** | $109.96 | **184%** | −$50.14 |
| 5 | $94.26 | $405.74 | 1.6% | $52.94 | 56% | $103.08 | **109%** | −$8.82 |
| 8 | $138.49 | $661.51 | 2.6% | $48.52 | 35% | $94.23 | 68% | +$44.26 |
| 10 | $163.47 | $836.53 | 3.3% | $46.02 | 28% | $89.23 | 55% | +$74.23 |
| 12 | $185.21 | $1,014.79 | 4.1% | $43.84 | 24% | $84.89 | 46% | +$100.32 |
| 20 | $245.60 | $1,754.40 | 7.0% | $42.58 | 17% | $82.36 | 34% | +$163.24 |

The mechanism is arithmetic, not empirical: **credit scales with width, the crossing cost does
not.** The absolute spread floor dominates once the legs are cheap, so cost/credit falls roughly
as 1/W.

Consequences, stated plainly:

* Decision 4's **$250 per-structure max loss caps the width at 3** on a SPY-priced underlying
  (a 5-wide has max loss ~$406 > $250). Every structure that fits the cap pays **≥ 94% of its
  credit in modelled costs at the baseline spread and ≥ 184% at 2×.**
* **Gate 4b (pass at baseline *and* 2× spread, §2.4 and §5.2 of the map, made permanent by
  decision 5) is therefore unpassable at decision 4's limits**, for reasons that have nothing to
  do with whether the strategy has an edge. The structure has negative gross credit at 2× before
  any adverse move.
* Break-even at 2× needs width ≈ **8** (R ≈ $662, **2.6% of the $25,000 account**). Getting
  cost/credit at 2× under a third needs width ≈ **20** (R ≈ $1,754, **7.0% of equity**) — above
  decision 4's *aggregate* cap of $1,000, i.e. a single structure would exceed the whole book's
  loss budget.
* A cheaper underlying does **not** rescue it. The dominant term is the **absolute** spread floor
  (4 × 5¢ × 100 = $20 round trip regardless of price), and dollar width, not percentage width, is
  what generates credit. A $60 underlying with $1 strikes needs the same dollar widths.

**Finding 5 (NEW in rev 2) — `min_credit_to_width ≥ 0.25` and `θ@2× > 0` have a jointly EMPTY
feasible set, and the two constraints pull in opposite directions.** This is the result that
emerged from re-running §5.3's feasibility scan over the full box (the scan rev 1 did not do), and
it is the sharper form of Finding 4.

**ARITHMETIC** (same method and constants as the table above; σ ∈ {0.12, 0.20, 0.30, 0.45, 0.60,
0.80}, DTE ∈ {21, 30, 45, 60, 90}, W ∈ {1, 2, 3, 4, 5, 8, 10, 12, 20}, short strike at |Δ| ≈ 0.20):

> **Cells satisfying `credit/width ≥ 0.25` AND `θ@2× > 0` AND `|Δ| ≤ 0.20` AND `R ≤ $700`:
> ZERO.**
>
> Relaxing the R ceiling entirely, the best θ@2× anywhere subject to `credit/width ≥ 0.25` is
> **+0.116**, at σ = 0.80, DTE = 90, short K = 352, **W = 40** — R = **$2,902**, i.e. **11.6% of the
> $25,000 account** and 2.9× decision 4's *aggregate* cap.

**The mechanism, and it is arithmetic rather than empirical.** §5.3 shows `credit/width` clears 0.25
only at high σ√T. But the illustrative spread is `max(5¢, 5% × print)`, so at high σ the *proportional*
term dominates and the crossing cost scales **with** the credit rather than against it. Low σ/short
DTE is where costs are containable and the credit hurdle fails; high σ/long DTE is where the credit
hurdle passes and costs eat the credit. The two gates' feasible regions are, on these constants,
nearly disjoint.

**What this does NOT license.** It is not an argument for retiring `min_credit_to_width` — that would
be answering an infeasibility by deleting the constraint that reveals it, which is exactly the
gate-weakening R4 forbids, and §5.3 has already withdrawn rev 1's attempt at it. It is an argument
that the resolutions below are **required**, and that the first thing to move is D2's cost model, not
a gate and not a capital limit.

**What D3 does with this.** It does not resolve it — every candidate resolution is either an
operator capital decision or D2's fill model:

**Ordered deliberately: D2's constants move first, capital moves last, and the default disposition
if nothing closes the gap is to stop.** Rev 1 listed the capital raise first, with a number attached,
which reads as the recommendation — and a capital limit raised in order to make gate 4b passable is
gate weakening by another route, whatever it is labelled. The order below is the order of operations.

* **(1) Freeze D2's `OptionCostModel` first, and re-run this arithmetic against the frozen
  constants — before anything else moves.** Every number in §5.4 and Finding 5 rests on illustrative
  constants D3 does not own (`spread = max(5¢, 5% × print)`, $0.70/contract). **No capital limit may
  move until the feasible region has been recomputed against the frozen model.** — **D2 decision,
  blocking.**
* **(2)** Adopt §2.4(1b) *re-centred mid ± half-spread* instead of (1a), which cuts the crossings
  from four full spreads to two half-spreads — a 4× reduction — at the cost of inheriting every
  §2.4a/§2.4b input assumption — **D2 decision**.
* **(3)** Make `spread_abs_floor_cents` (and, per Finding 5, the *proportional* term) moneyness- and
  underlying-dependent rather than single constants, and justify each value — **D2 decision**. Note
  this is the direction that *weakens* the cost model, and R4 permits only strictly-more-searching
  changes, so it needs an explicit argument, not a tuning pass.
* **(4)** Only if (1)–(3) leave the region non-empty but the limits exclude it: raise
  `per_structure_max_loss_dollars` and `total_open_max_loss_dollars` to the smallest values that
  admit the region, stated as a consequence of the frozen cost model rather than as a target —
  **operator decision 4**. ~$700 (2.6% of equity) is what the *illustrative* constants imply; that
  figure is not carried forward until (1) is done.
* **(5) DEFAULT DISPOSITION if the region is still empty after (1)–(3): accept that O3 cannot be
  evidenced at this account size, and re-open decision 13.** This is what happens absent a positive
  decision, not the last resort. An unevidenceable strategy that is nonetheless traded is the outcome
  the whole R1–R10 discipline exists to prevent.

**And the pre-registration consequence (R1/R4):** the feasible (underlying, width, delta, DTE)
region must be computed from the **cost model and the limits alone** — as above, with no outcome
data — and recorded in D5's pre-registration **before** the first sealed look. Discovering after a
look that only the widest cells were economic would be indistinguishable from selecting them.

---

## 6. `mark_options_to_market`

**HYPOTHESIS — signature and placement.** New module `paper/options_ledger.py` (a sibling of
`paper/ledger.py`, never an extension of it):

```python
def mark_options_to_market(
    session: Session, *, account_name: str, as_of: date
) -> OptionsMarkResult
```

`account_name` and `as_of` are **required** (§2). It never calls `ensure_not_engaged` — closing
is protective and must work with the kill switch engaged (**FACT**: `ledger.py:266-276` sets this
precedent).

### 6.0 The signal-to-fill session offset — stated explicitly, because rev 1 did not state it at all

Rev 1 contained the strings "lookahead", "look-ahead", "next session" and "close-basis" **zero
times**, while specifying a mark taken from session *t*'s own `OptionAggregateDaily.close` (step 1
below) and a guard condition requiring "every leg has a print on the entry session" (§10.2 condition
M). Those two are only jointly satisfiable by looking forward.

**FACT** (`backtest/engine.py:1-13`, the module docstring stating the engine's honesty rules):
"A signal at bar `t` sees only `series.head(t)` — look-ahead is structurally impossible. Entries
fill at the **next** bar's open." The equity convention is therefore **signal at t, fill at t+1**.

Rev 1's options path implied one of two things, and both are lookahead:

* If signal and fill share session *t*, the options path fills a **full session earlier** than the
  equity path, on a close the signal itself was computed from.
* If the signal is at *t−1* and condition M filters on whether every leg prints at *t*, then the
  filter consults a fact not knowable at *t−1*. §6 step 6's deferral repairs only the **exit** side;
  the entry side was left open.

**HYPOTHESIS — the rule, and it is byte-identical in the backtest and the paper path:**

```
signal            computed on COMPLETED session t, from session t's prints and nothing later
entry fill        taken at session t+1's prints (the next completed session)
entry refusal     if ANY leg lacks a print on session t+1, the entry is a NON-ENTRY  (condition M)
exit signal       computed on completed session u, from session u's prints
exit fill         taken at session u+1's prints; if any leg lacks a print at u+1, the fill DEFERS
                  (exit_deferred_sessions increments) until every leg prints — never synthetic
```

Three consequences, all recorded rather than assumed away:

* **Condition M is evaluated at t+1, not at t.** It is a property of the *fill* session, which the
  guard is running on, so it consults nothing in the future. A leg that printed on the signal
  session and not on the fill session is a refusal, and refusals are recorded (§11).
* **The one-session gap is a cost that is borne.** The credit available at *t+1* is not the credit
  observed at *t*. The snapshot (§9) records both `signal_session` and `fill_session`, and the
  entry price is the *t+1* print, never the *t* one.
* **The same offset applies in the backtest.** If D2's options engine fills at *t* while the paper
  path fills at *t+1*, the two streams are not the same population and gate 10 compares different
  things. This is listed as a named test in §14 (item 11a).

**Per open structure, per session:**

1. **Mark each leg from its own print.** `OptionAggregateDaily.close` for that `option_ticker` on
   that `session_date` (**FACT**: unique on `(option_ticker, session_date, source)`,
   `market.py:300-303`). This is a *last-trade print*, not a mid — record it as `last_print`.
2. **No print ⇒ the §2.4b same-session surface**, with `iv_source = 'same_session_surface'`,
   `synthetic = True`, and the contract count the fit used. If fewer than N contracts printed on
   that (underlying, expiry), mark `iv_unavailable` and **do not extrapolate**.
3. **Never realised volatility as a fallback** (map §2.4b: it values short premium below its true
   worth and manufactures the very edge the strategy claims).
4. **Value the structure, never the underlying.** Net premium = Σ over legs of
   `qty_signed × leg_mark × M`. Unrealised P&L = entry net premium − current net premium for a
   credit structure (sign per structure type).
5. **Exits are evaluated against the structure's net premium**, never against the underlying's
   high/low: profit target as a fraction of the credit received, stop as a multiple of it, plus a
   **DTE time stop** at `time_stop_dte` (grid centre 7).
6. **A synthetic mark may trigger a signal; it may never set a fill price** (map §2.4(3)). When an
   exit is signalled on a session where any leg lacks a print, the structure is marked
   `exit_signalled_at` and `exit_deferred_sessions` increments each session until **every** leg
   prints; the fill is taken at that later session's prints. The deferral is a cost that is borne,
   recorded, and reported at gate 8 — never assumed away.
7. **Greeks are recomputed and stored on every mark** (net delta, net vega, short-leg delta) so the
   §5.2 caps are evaluated against a current book, not entry-time values, and so a breach is
   visible in the record even though the caps only gate *opening*.

**Return type (HYPOTHESIS):** `OptionsMarkResult(checked, closed, deferred, synthetic_marked,
iv_unavailable, realized_pnl, unrealized_pnl, net_delta_notional, net_vega_per_vol_pt)`.
Deliberately wider than `MarkToMarketResult` (`ledger.py:258-263`) — the four new counters are the
honesty of the model and must not be summarised away.

**Scheduling (HYPOTHESIS).** **FACT:** `job_paper_mtm` runs on a **12-hour interval**
(`scheduler.py:577`: `JobSpec("paper_mtm", job_paper_mtm, 12 * 60, …)`; the job itself is
`scheduler.py:249`) and is **not** part of the `daily_eod_update` chain
(`scheduler.py:381-402`). Options marking must run on **completed sessions only**, so it belongs in
the EOD chain, after `job_ingest()` and before the approved-scope scan, as a fourth sequential step
inside `job_daily_eod_update` with its own nested `guarded(...)` wrapper — the pattern
`scheduler.py:400` already uses for `approved_scope_scan`, which gives it its own `JobRun` row on
the Operational Status page. Ordering within the new step:

```
mark_options_to_market  →  reconcile_options_collateral  →  process_option_expiries
```

Expiry processing runs **last** so it acts on a reconciled book.

**Correction — there are TWO catch-up paths and rev 1 conflated them.** Rev 1 claimed the options
step "precedes the heartbeat, matching the existing startup-catch-up-before-first-heartbeat
discipline". That is not what the code does.

**FACT** (`scheduler.py:805-817`): `run_catch_up`, the **startup** path, does **not** call
`job_daily_eod_update`. It calls `guarded("catchup_ingest", job_ingest)()`,
`guarded("catchup_scan", job_scan_all)()`, then `guarded("catchup_approved_scope_scan",
job_approved_scope_scan)()` directly. **FACT** (`scheduler.py:770-782`): `job_catch_up`, the
**30-minute interval** path, *does* call `job_daily_eod_update()` at `:782`. The two differ.

Since §11 wires the options auto-simulation into `job_approved_scope_scan` (**FACT**:
`scheduler.py:282`, equity twin invoked at `:301`), the startup path as rev 1 left it would, on
**every worker restart**, run options opens against a book whose expiries for the missed session had
never been processed and whose reconcile report was up to a day stale — and rev 1's
satisfied-by-absence condition AA would have let it through.

**HYPOTHESIS — both halves, and they are belt and braces deliberately:**

1. **`run_catch_up` gains the options step as a fourth `guarded(...)` call, placed BEFORE
   `catchup_approved_scope_scan`:** `guarded("catchup_options_eod", options_eod_step)()` inserted
   between `catchup_scan` and `catchup_approved_scope_scan` at `scheduler.py:815-816`. This is an
   addition to the startup sequence, not a change to any existing call.
2. **And §3.4's dated condition AA is the enforcement.** Even with (1) in place, the guard refuses
   unless a `paper_options_reconcile_report` row exists for **this** account with `as_of` equal to
   the current completed session and `clean` true. If the options step is skipped, crashes, or is
   ever removed from either catch-up path, the scan simply refuses to open. (1) makes the normal
   path work; (2) makes the abnormal path safe.

---

## 7. The type assertion on the existing `mark_to_market` (and its three siblings)

### 7.1 The assertion, and why it is safe to merge now

**HYPOTHESIS (non-negotiable per §3.3 of the map):**

```python
# paper/ledger.py, inside mark_to_market's loop, immediately after `inst` is fetched
if inst.instrument_type not in ("stock", "etf"):
    raise NotAnEquityPosition(
        f"mark_to_market prices positions from the UNDERLYING's daily bars; "
        f"instrument {inst.symbol!r} is {inst.instrument_type!r}. "
        f"Use paper.options_ledger.mark_options_to_market."
    )
```

* It **narrows**, never widens. It is the same predicate `assert_auto_simulate_allowed` already
  applies (**FACT**: `ledger.py:497`), applied at the second place it matters.
* **FACT:** it cannot fire on current data — `paper_position` has 0 rows and all 2,658
  `instrument` rows are `stock` or `etf` (§1.1, §1.2). Merging it today is a provable no-op and it
  must be merged **before** any options position can exist, not after (map §3.3).
* A new exception type, not `ValueError`: `job_paper_mtm` (`scheduler.py:249`) must fail
  loudly and leave a named `JobRun` failure rather than be swallowed by a broad handler.

### 7.2 `portfolio_snapshot` gets the same assertion

**FACT:** `paper/portfolio.py:51` prices every open position via `_last_close(session, inst.symbol, on)`
— the underlying's bars, identically to `mark_to_market`. §3.3 of the map names only
`mark_to_market`; the same defect is here and the same assertion belongs here. It is equally a
no-op today.

### 7.3 The two R-computing readers must not see options positions at all

**FACT** (§1.5): `health_monitor._paper_returns_r` (`research/health_monitor.py:57-80`) and
`paper_probation._paper_trade_summary` (`research/paper_probation.py:39-88`) both compute
`R = realized_pnl / (abs(avg_price − stop_level) × qty)` with **no account filter** and both
silently `continue` when `stop_level is None`.

**HYPOTHESIS — the only safe shape:**

* Options structures **never** produce a `paper_position` row (§13). That alone makes both
  readers structurally blind to them, which is the correct default.
* Each reader gains an **explicit** options branch reading `paper_option_structure.pnl_r`
  (computed at close as `realized_pnl_dollars / R_at_entry`, §2.6 of the map), unioned with the
  equity R list **only** when the strategy version's family is an options family. It must be
  explicit, because the silent `stop_level is None` skip would otherwise mean an options strategy
  that underperforms is **never downgraded** — a fail-open in the health monitor, which is the
  one place the system is supposed to fail closed.
* `r_clamped` (map §2.6) is carried through: the health monitor uses the **clamped** series (so R
  means the same thing as in the backtest) and **reports** the clamp count and the unclamped
  minimum alongside it. A clamp rate above the pre-registered gate-8 ceiling is a finding, not a
  footnote.
* `agents/strategy_validation.py:228-230` is a read-only reporter; it gets the same explicit
  branch so its report does not silently omit the options book.

---

## 8. Expiry processing

**HYPOTHESIS:** `process_option_expiries(session, *, account_name, as_of) -> ExpiryReport` in
`paper/options_ledger.py`, run last in the EOD options step (§6).

### 8.0 Transaction boundary and cash accounting — neither was stated in rev 1

**The whole of an options open is ONE transaction, and the whole of a close is ONE transaction
(HYPOTHESIS).** An open writes roughly seven rows — order, fills, structure, legs, collateral entry,
account balance, `PaperTrade` — and rev 1 named no commit boundary for any of them, while arguing
about which *order* to write them in so that a crash would land on the conservative side. That
argument is unnecessary and, as rev 1 stated it, it was backwards (§8 step 4 below). With one commit
per open and one per close, a crash is all-or-nothing and there is no partial state to reason about.

**FACT** for contrast: the equity auto-simulation deliberately commits **per decision**
(`paper/auto_simulate.py:170, :178, :188, :213`) so that one candidate's failure cannot roll back
another's recorded rejection. The options path keeps that outer granularity — one commit per
candidate — but the *inside* of a single candidate's open or close is atomic.

**Cash accounting, stated explicitly (HYPOTHESIS).** §3.2's reservation for a credit vertical is
`strike_width × M × contracts − net_credit + entry_costs`, which is correct as **buying power only
if the net credit lands in `PaperAccount.cash` at entry**. It does: at entry, `cash += net_credit −
entry_costs` and `collateral_reserved += width × M × contracts − net_credit + entry_costs`, so
`spendable_cash = cash − collateral_reserved` falls by exactly the structure's maximum loss R. At
close, the reverse. (§9's `spendable_cash_before: 25000.0` is the value *before* the entry, which is
why it equals the account's initial cash; the snapshot records `spendable_cash_after` as well so the
arithmetic is checkable on the row.)

Behaviour, per open structure:

1. **Force-close at `expiry − 1`**, per map §2.7. Never hold through expiry in Phase 1.
2. **Per-leg force-close pricing with the intrinsic floor**: a long leg is never valued below its
   intrinsic value; a short leg is never bought back below its intrinsic value; the modelled
   spread is applied adversely to each. Record that the intrinsic floor bound, per leg — it is one
   of the two mechanisms that can push `pnl_r` below −1 (map §2.6(b)) and gate 8 must be able to
   attribute clamps to it.
3. **Entry eligibility is enforced at entry, not here.** A structure may be opened only if every
   leg can, in principle, be priced from prints on its own force-close session (map §2.7). In
   paper this cannot be known in advance, so the paper analogue is: if any leg lacks a print on
   the force-close session, the structure is closed at the **intrinsic floor with no print
   component**, flagged `forced_close_no_print = True`, and reported separately at gate 8. It is
   **not** excluded from the paper sample — a paper stream that drops its inconvenient trades is
   not a confirming test.
4. **Collateral is released** via a `release` entry whose `amount` equals the original `reserve`
   `amount` exactly (§3.1). **Ordering: the structure close and the immutable `PaperTrade` are
   written FIRST, the `release` entry LAST**, and the whole close is one transaction (§8.0).

   **Rev 1 had this backwards and its stated rationale produced the opposite of its stated
   guarantee.** Rev 1 read: "Release before the `PaperTrade` write, so a crash between the two
   leaves reserved collateral (conservative) rather than a freed reservation with no close."
   Release-then-write means a crash *after the release* leaves the collateral **freed with no close
   record** — exactly the outcome the sentence claimed to avoid, and a fail-open one: the next entry
   sees inflated `spendable_cash` and can breach `collateral_cap_dollars` and
   `total_open_max_loss_dollars` through §10.2 conditions O / P / R, before the reconciler next runs.
   Write-then-release leaves, in the same crash window, a **closed structure with its collateral
   still reserved** — conservative, capacity-*blocking*, and caught by §3.4 check 5 ("no closed
   structure has an unreleased reserve"). With §8.0's single transaction the window does not exist
   at all; the ordering is the second line of defence for a backend or a bug that breaks atomicity.
5. **An immutable `PaperTrade`** is written with `exit_reason = 'forced_pre_expiry'`, plus
   `pin_risk_flag` (underlying closed inside the pre-registered pin band around a short strike on
   the force-close session) and `assignment_risk_flag` (short leg ITM beyond the stated threshold
   on any close before force-close).
6. **Reaching expiry raises and halts.** Phase 1 has no assignment path; if a structure is ever
   found open on or past its expiration date, `process_option_expiries` raises
   `OptionExpiryUnhandled` and does not guess. **FACT:** `OptionContract.exercise_style` defaults
   to `'american'` (`market.py:254`) — early assignment is real, force-close approximates it away,
   and that approximation is biased **in the strategy's favour**. It is disclosed on every
   evaluation record (§9), never buried.
7. **Idempotence.** Keyed on `(structure_id, as_of)`; a re-run on the same session is a no-op.
   **FACT:** `job_catch_up` (`scheduler.py:770-782`, 30-minute interval) re-invokes
   `job_daily_eod_update()` at `:782` after a missed session, and `run_catch_up`
   (`scheduler.py:805-817`) runs its own sequence at startup, so every step in either must be safely
   re-runnable. See §6's correction: the two paths are **not** the same chain.

---

## 9. Evidence snapshot fields

**FACT:** `_candidate_snapshot` (`paper/ledger.py:369-464`) already freezes the complete evidence
record onto every `PaperTrade`, including the approval-scope match, the spec hash, the config
hash, and `git_sha()`. `paper_trade` is immutable (**FACT**: triggers
`paper_trade_no_update` / `paper_trade_no_delete`, `initial_schema.py:1263-1279`, present in the
live DB).

**HYPOTHESIS — `_options_candidate_snapshot` is a separate function** in `paper/options_ledger.py`
returning the equity snapshot's keys **plus** the block below. Separate, not an extension, so the
equity snapshot's shape is unchanged and the three live approvals' records stay comparable.

**Rev 1's worked example was a trade the guard must REFUSE, and it is the artifact D4, D5 and I-O6
will copy.** It carried `short_leg_delta: -0.201` against `max_short_delta = 0.20`, i.e. §10.2
condition S fails. **VERIFIED** with the repo's own Black–Scholes at S = 450, σ = 0.20, r = 0.04,
q = 0, 30 DTE, K = 431: put delta **−0.2009**, print $2.9782, W = 3 credit $59.83, credit/width
**0.1994**, R $240.17. The numbers were right; the example was non-compliant.

**Three further defects in the rev-1 block, all fixed below:**

* `"bound": true` on `max_short_delta` conflated **binding** (the limit was the tightest active
  constraint) with **breached** (the value exceeds the limit). A refused entry and a tight-but-legal
  entry rendered identically.
* `total_open_max_loss.value` was a **post-entry** figure while `max_structures_per_underlying.value:
  0` was **pre-entry**, in the same object, with no convention stated.
* The example did not disclose that at decision-4's numbers **no** compliant example exists that also
  passes condition T — which is Finding 4 (§5.4), and which an example silently sidestepping it hides.

**HYPOTHESIS — `limits_evaluated` gains an explicit three-state `state` field and a declared
convention.** Every entry is `{"limit", "value", "state"}` with `state ∈ {"ok", "binding",
"breached"}`: `breached` = the value violates the limit (the entry is refused, and the first such
condition is named); `binding` = within the limit but with less than 10% headroom; `ok` otherwise.
**Convention: every `value` is the POST-entry figure** — what the book would look like if this entry
were taken — because that is the quantity the limit actually governs. Counts therefore read 1, not 0,
for a first structure.

**Two worked records, because one is not honest on its own: a REFUSAL (the design's current state)
and an ACCEPTANCE (the schema D4/D5/I-O6 copy).**

**(A) The canonical ACCEPTANCE record — a SCHEMA ILLUSTRATION, not a certified-feasible cell.**
**VERIFIED** with the repo's Black–Scholes (S = 450, σ = 0.20, r = 0.04, q = 0, 30 DTE, short
K = 430, long K = 422, W = 8): short delta −0.1897, credit $130.32, R $669.68, credit/width 0.1629,
net Δ 7.59 shares = $3,416 notional, net vega −$10.12/vol-pt, break-even 428.70, modelled cost @1×
$45.12 ⇒ θ@1× = +0.1272, θ@2× = +0.0640.

**Read the `limits_config_note` and the `feasibility_note` before copying it.** This cell satisfies
`max_short_delta`, θ at both spread settings, and every capital limit **only under a
per-structure cap of $700**, i.e. only after the operator's Finding-4 resolution; and it
**breaches `min_credit_to_width`**, which Finding 5 (§5.4) shows cannot be satisfied simultaneously
with θ > 0 anywhere in the tested box under the illustrative cost constants. The breach is shown
deliberately, with `state: "breached"`, so that the canonical artifact carries Finding 5 on its face
instead of hiding it behind a cell chosen to look clean. **No configuration currently exists in
which this record would be accepted**; what is canonical here is the *shape*, the field set, and the
three-state convention — not the numbers.

```json
"options": {
  "account_name": "options_paper",
  "structure_type": "VERTICAL_CREDIT",
  "underlying_symbol": "SPY",
  "signal_session": "2026-09-15",          // §6.0: signal on completed session t
  "fill_session":   "2026-09-16",          // §6.0: fill at t+1's prints
  "legs": [{"option_ticker": "...", "right": "PUT", "strike": 430.0,
            "expiration": "2026-10-16", "qty": -1,
            "shares_per_contract": 100,          // READ from option_contract, asserted == 100
            "exercise_style": "american"},
           {"option_ticker": "...", "right": "PUT", "strike": 422.0,
            "expiration": "2026-10-16", "qty": 1,
            "shares_per_contract": 100,
            "exercise_style": "american"}],
  "contracts": 1,
  "dte_at_entry": 30,
  "entry_net_premium": 130.32,
  "max_loss_dollars_R": 669.68,
  "max_gain_dollars": 130.32,
  "break_evens": [428.70],
  "credit_to_width": 0.1629,
  "short_leg_delta": -0.1897,
  "net_delta_shares": 7.59,
  "net_delta_notional": 3416.0,
  "net_vega_per_vol_pt": -10.12,
  "beta_to_spy": 1.0,
  "theta_credit_after_costs_to_R": {"at_1x": 0.1272, "at_2x": 0.0640},
  "collateral_reserved": 669.68,
  "spendable_cash_before": 25000.0,
  "spendable_cash_after": 24330.32,
  "limits_config_note": "per_structure_max_loss_dollars = 700.0 — REQUIRES the operator's
                         Finding-4 resolution (§5.4, §15 Q1). INVALID at decision 4's $250.",
  "feasibility_note":   "SCHEMA ILLUSTRATION. Breaches min_credit_to_width; see Finding 5 (§5.4) —
                         c/w >= 0.25 and theta@2x > 0 have a jointly EMPTY feasible set at
                         |delta| <= 0.20 and R <= $700 under the illustrative cost constants.",
  "limits_evaluated": {     // EVERY limit, POST-entry value, with ok | binding | breached
     "per_structure_max_loss": {"limit": 700.0, "value": 669.68, "state": "binding"},
     "total_open_max_loss":    {"limit": 2800.0, "value": 669.68, "state": "ok"},
     "collateral_cap":         {"limit": 5000.0, "value": 669.68, "state": "ok"},
     "options_net_delta":      {"limit": 10000.0, "value": 3416.0, "state": "ok"},
     "combined_net_delta":     {"limit": 10000.0, "value": 3416.0, "state": "ok"},
     "options_net_vega":       {"limit": 50.0, "value": -10.12, "state": "ok"},
     "max_structures_per_underlying": {"limit": 1, "value": 1, "state": "binding"},
     "max_open_structures":    {"limit": 5, "value": 1, "state": "ok"},
     "daily_order_cap":        {"limit": 10, "value": 1, "state": "ok"},
     "max_short_delta":        {"limit": 0.20, "value": 0.1897, "state": "binding"},
     "min_credit_to_width":    {"limit": 0.25, "value": 0.1629, "state": "breached"},
     "theta_at_2x":            {"limit": "<theta>", "value": 0.0640, "state": "ok"}
  },
  "fill_model": "print_plus_full_spread_v1",
  "iv_source": "same_session_surface",
  "iv_surface_contracts_used": 12,
  "q_source": "trailing_12m_yield:massive",
  "greeks_source": "local_bs_inversion",
  "cost_model": {"name": "OptionCostModel_v1", "hash": "...", "spread_multiplier": 1.0},
  "synthetic_marks_at_entry": 0,
  "options_scope_hash": "...",
  "options_data_scope_hash": "...",
  "options_scope_matched": true,
  "disclosures": [
    "NBBO unavailable under the active entitlement for options AND equities — spread is modelled, not observed.",
    "Force-close at expiry-1 approximates away early assignment; the bias is IN THE STRATEGY'S FAVOUR.",
    "Dividend-driven early assignment on short calls is not modelled in Phase 1.",
    "Exercise style is american; no assignment path exists in Phase 1."
  ],
  "notice": "SIMULATED options structure — no order was placed."
}
```

**(B) The canonical REFUSAL record — this is rev 1's own worked example, and it is what the guard
actually does with it today.** Same underlying and session, decision-4 limits unchanged, short
K = 431, W = 3. **VERIFIED**: short delta **−0.2009**, credit $59.83, credit/width 0.1994,
R $240.17, modelled cost @1× $56.38 ⇒ θ@1× = +0.0143, θ@2× = −0.2088.

```json
"options": {
  "account_name": "options_paper",
  "structure_type": "VERTICAL_CREDIT",
  "underlying_symbol": "SPY",
  "signal_session": "2026-09-15",
  "fill_session":   "2026-09-16",
  "legs": [{"option_ticker": "...", "right": "PUT", "strike": 431.0, "qty": -1,
            "shares_per_contract": 100, "exercise_style": "american"},
           {"option_ticker": "...", "right": "PUT", "strike": 428.0, "qty": 1,
            "shares_per_contract": 100, "exercise_style": "american"}],
  "contracts": 1, "dte_at_entry": 30,
  "entry_net_premium": 59.83, "max_loss_dollars_R": 240.17,
  "credit_to_width": 0.1994, "short_leg_delta": -0.2009,
  "theta_credit_after_costs_to_R": {"at_1x": 0.0143, "at_2x": -0.2088},
  "limits_evaluated": {
     "per_structure_max_loss": {"limit": 250.0, "value": 240.17, "state": "binding"},
     "max_short_delta":        {"limit": 0.20,  "value": 0.2009, "state": "breached"},
     "min_credit_to_width":    {"limit": 0.25,  "value": 0.1994, "state": "breached"},
     "theta_at_2x":            {"limit": "<theta>", "value": -0.2088, "state": "breached"}
     // … every other limit recorded identically, state "ok"
  },
  "refused": true,
  "refused_condition": "S",
  "refused_reason": "|short leg delta| 0.2009 > max_short_delta 0.20",
  "notice": "SIMULATED options structure — no order was placed; the entry was REFUSED."
}
```

The refusal names the **first** failed condition in the A–AB order (S), even though T and the credit
hurdle also fail — matching `assert_auto_simulate_allowed`'s existing behaviour of naming the first
failed condition (**FACT**: `ledger.py:474-514`). A REJECTED `PaperTrade` carries this snapshot
(§11), so refusals are evidence, not log lines.

Four properties this buys, each of which is a specific defence:

* **`limits_evaluated` records every limit and its margin, in all three states.** Finding 1 (§5.2) is
  that the greek caps do not bind at decision 4's numbers; the only way to *keep* knowing that is
  to record the headroom on every trade rather than infer it from an absence of refusals. The
  three-state field is what keeps "tight but legal" distinguishable from "refused" — rev 1's boolean
  `bound` rendered them identically, which is how rev 1's own example passed review as an acceptance.
* **`shares_per_contract` is recorded per leg** as read from the contract row, so the `× 100`
  arithmetic in R and in the collateral basis is auditable rather than assumed.
* **`signal_session` and `fill_session` are both recorded** (§6.0), so the one-session offset is on
  the row and a same-session fill is detectable after the fact rather than only in review.
* **The disclosures are stored, not printed.** `paper_trade` is immutable, so a disclosure that is
  in the row cannot be dropped from a later report.

---

## 10. `assert_options_auto_simulate_allowed`

**FACT:** the existing guard is `assert_auto_simulate_allowed` (`paper/ledger.py:474-514`),
raising `AutoSimulateForbidden` (`:467-471`) and naming the first failed condition. Its
instrument-type check is `ledger.py:496-500`. It is a clean fail-closed template and the map's
§3.6 is explicit that it must **never** be widened.

### 10.1 The hole that must be closed first, and it is not in §3.6

**FACT — the discriminator problem.** An options candidate has to point its `Candidate.instrument_id`
(`db/models/research.py:96`, non-nullable FK) at *something*. The natural choice is the
**underlying** — SPY — because regime bucketing, beta weighting, and the underlying's bars all key
on it. But SPY's `Instrument.instrument_type` is `'etf'`. So an options candidate whose
`instrument_id` is the SPY row would **pass** the equity guard's instrument-type check at
`ledger.py:497` and be accepted through the equity ledger as a stock trade — equity-shaped sizing,
equity-shaped cash, equity-shaped mark. That is exactly the outcome §3.6 quotes the reader pass as
warning about, reached by a different route than the one §3.6 defends against.

**HYPOTHESIS — the fix, which narrows the equity guard and therefore does not violate "never
widened":**

1. Add a **positive discriminator on the candidate itself**, not on the instrument:
   `Candidate.structure_kind: str | None` (NULL = single-leg equity; `'option_spread'` = an options
   structure), plus a `candidate_option_structure` child row carrying the legs.
2. `assert_auto_simulate_allowed` gains **one additional refusal**, before every existing check:

   ```python
   if cand.structure_kind is not None:
       raise AutoSimulateForbidden(
           "candidate carries an options structure; the equity auto-simulate path "
           "cannot size, fill, or mark it. Use assert_options_auto_simulate_allowed."
       )
   ```

   This is strictly more restrictive. It refuses a class of candidate the guard previously would
   have accepted, and refuses nothing it previously accepted (**FACT**: `structure_kind` is NULL for
   every existing candidate by the column default).
3. **`accept_candidate` gains the same refusal.** This is the important one. **FACT** (map §0.1's
   B2 correction, verified): `accept_candidate` (`ledger.py:129`) is reachable from `cli.py:1267`
   and from `app/routers/dashboard.py:243` with **no guard at all** — it checks only
   `ensure_not_engaged()` (`:139`), that the direction is not AVOID, and that the risk width is
   non-zero. Without the refusal at `accept_candidate`, a single CLI invocation puts an options
   structure through the equity ledger. The guard belongs on the *ledger function*, not only on the
   automatic path.
4. **FACT:** `tests/paper/test_activation_guards.py:149-173` enforces that only `ledger.py`,
   `cli.py`, `app/routers/`, and `paper/auto_simulate.py` may call `accept_candidate`, and that only
   `scheduler.py` may call `auto_simulate_scan_runs`. **But it enforces the first half by BASENAME,
   not by path, and that hole must not be inherited.** **FACT** (`test_activation_guards.py:158`):
   `manual_ok = {"ledger.py", "cli.py"}`, tested at `:161-165` as `p.name in manual_ok` — a
   `Path.name`, so **any** file anywhere under `src/signalforge` named `ledger.py` or `cli.py` may
   call `accept_candidate` and the test still passes; `signalforge/agents/cli.py` is the obvious
   example, and the agents layer is live (`app_setting`: `"agents": {"enabled": true,
   "llm_narratives": true}`). Only the `auto_simulate.py` arm uses path equality (`rel ==`).
   §14.6 specifies the options twin with **path equality only**, and §14 requires the existing equity
   test be repaired to path equality **in the same commit**, since it is the template. Repairing it
   is strictly more restrictive and therefore permitted under R4.

### 10.2 The second guard

**HYPOTHESIS** — new function in `paper/options_ledger.py`, new exception
`OptionsAutoSimulateForbidden` (a distinct type, so no existing `except AutoSimulateForbidden`
handler can swallow it):

```
assert_options_auto_simulate_allowed(session, cand, *, account_name, now) -> None

refuses, naming the FIRST failed condition, unless ALL of:
  A. setting `options_auto_simulate_enabled` is ON            (NEW setting, default FALSE)
  B. killswitch.ensure_not_engaged()                          (shared with the equity path)
  C. cand.structure_kind == 'option_spread'                   (positive, not "not stock")
  D. cand.quality_gate_status is QualityGate.PASSED
  E. cand.direction is not Direction.AVOID
  F. strategy_version.status is StrategyStatus.PAPER_APPROVED
  G. structure_type == the version's SINGLE approved structure type   (gate 0.5)
  H. the five-part equity scope match (approval_scope.scan_scope_matches) PASSES
  I. options_scope_hash matches the approved options scope           (6th part, §4)
  J. options_data_scope_hash matches the approved data scope         (7th part, D1/§3.5)
  K. every leg's option_contract.shares_per_contract == 100
  L. every leg's option_contract.exercise_style == 'american' AND settlement is physical
     (a SCOPE restriction, not a safety property — see below)
  M. every leg has a print on the FILL session t+1 (§6.0; §2.4(3): a missing bar is a NON-ENTRY)
  N. the resolved account is options_risk.paper_account_name AND its id != the id of the
     account named 'default'                                          (§2 — NOT a tautology)
  O. spendable_cash >= collateral required                            (§3.1)
  P. collateral_reserved + required <= collateral_cap_dollars
  Q. R <= per_structure_max_loss_dollars
  R. sum(R over open) + R <= total_open_max_loss_dollars
  S. |short leg delta| <= max_short_delta
  T. net credit after modelled round-trip costs / R >= theta          (§5.3 axis 2)
  U. |options net delta notional| after this entry <= options cap
  V. |combined net delta notional| after this entry <= combined cap   (options-only block, §5.2)
  W. |options net vega $/vol-pt| after this entry <= vega cap
  X. open structures on THIS UNDERLYING == 0                          (keyed on UNDERLYING)
  Y. count(open structures) < max_open_structures
  Z. options orders today < daily_order_cap  AND
     options auto-sim accepts today < options_auto_simulate_max_per_day  (NEW cap, separate
                                                                          from the equity cap of 2)
  AA. a paper_options_reconcile_report row EXISTS for this account with as_of == the current
      completed session AND clean == true                             (§3.4 — positive and dated;
      a MISSING row refuses exactly as a divergent row refuses)
  AB. the options calendar agrees the session is a completed trading session
```

**Two guards, two settings, two caps, one shared kill switch.** The equity guard is not touched
except by the narrowing refusal of §10.1(2).

**Condition N was a tautology in rev 1 and is now a real check.** Rev 1 read "`account.name` == the
configured options account, and `account_id` == that account" while configuring no options account
anywhere — the guard resolved the account *by* the caller's string and then verified that the
resolved account carried that string, which is always true. A caller passing
`account_name="default"` — a valid string, not a forgotten argument — would have passed N and
written options collateral and a `collateral_reserved` balance against the **live $30,000 equity
account** (**FACT**: `paper_account` row `(1, 'default', 30000, 30000)`). The name now comes from
`OptionsRiskLimits.paper_account_name` (§4), and the second clause is an id comparison against the
`'default'` account, so the equity account cannot be the target even if the configured name is
edited to point at it.

**Condition L is a SCOPE restriction, and rev 1 presented it as a safety condition.** It admits
only `exercise_style == 'american'` — which §8 step 6 simultaneously records as the case where
force-close-at-expiry−1 is biased **in the strategy's favour**. Taken as a safety condition it is
backwards: it *excludes* european/cash-settled contracts, which carry no early-assignment bias, and
*admits* only the biased case. **The actual reason is narrower and must be stated as such
(HYPOTHESIS):** §2.4b's surface fit, the `q` sourcing of decision 11, and D1's data path are built
for **american-style, physically-settled single-name and ETF options** and nothing else. **FACT:**
`OptionContract.exercise_style` defaults to `'american'` (`db/models/market.py:254`), so the
condition is also a guard against a vendor row arriving with an unmodelled style.

**Recorded as an explicit scope decision with its bias direction named:** cash-settled index options
(SPX, XSP, RUT and the like) are **out of Phase 1 scope**. Their exclusion removes a family whose
bias direction is *against* the strategy relative to the american case — no early assignment, no pin
risk of the physical kind, cash settlement at a determined open value — so the remaining scope is the
one in which the force-close approximation flatters the results. That is disclosed on every
evaluation record (§9), and D4 must treat "american-only" as a scope statement in the pre-registration,
not as evidence of caution.

**Condition X is keyed on the UNDERLYING, and that is the correction §3.6 demands.**
**FACT:** `auto_simulate._has_open_position` (`auto_simulate.py:108-120`, called at `:164-171`) keys
on `instrument_id`. A multi-leg structure spans several contract rows, so an `instrument_id` key
would not stop a second structure on the same underlying. The options check queries
`paper_option_structure.underlying_instrument_id` instead.

**Condition A's setting name.** **FACT** (live `app_setting` query): the keys in use are
`auto_simulate_qualified_signals` (currently `true`) and `auto_simulate_max_per_day` (currently
`2`). The new keys are `options_auto_simulate_enabled` and `options_auto_simulate_max_per_day`,
**defaulting to FALSE and 0** — a fresh install and the live DB both have options auto-simulation
**off**, and turning it on is a deliberate, audited operator action. Nothing is armed by default.

---

## 11. Extending auto-simulation without touching the equity path

**FACT:** `paper/auto_simulate.py:123` `auto_simulate_scan_runs` owns the kill switch check
(`:138`), the already-decided check (`:99, :161`), the one-open-position check (`:108, :164`),
the daily cap (`:74, :82`), the per-decision commit (`:170, :178, :188, :213`), the guard call
(`:181`) preceding the acceptance (`:191`), and the immutable rejection reasons
(`record_decision(..., PaperDecision.REJECTED, note=reason)`). It is invoked from exactly one place
— `scheduler.py:301`, inside `job_approved_scope_scan` (`:282`) — and
`tests/paper/test_activation_guards.py:166-169` enforces that.

**HYPOTHESIS — the shape, and why it is a sibling.**

```
paper/options_auto_simulate.py
    auto_simulate_options_scan_runs(session, scan_run_ids, *, account_name, now) -> OptionsAutoSimReport
```

* **`paper/auto_simulate.py` is not edited at all.** Byte-identical. That is the strongest possible
  guarantee that the live equity auto-simulation — running since 2026-09-10 with the setting ON and
  a cap of 2/day — is unaffected.
* The new module **copies** `auto_simulate.py`'s five structural guarantees rather than sharing
  code with it, with three substitutions: the underlying-keyed open check (§10.2 condition X), the
  options daily cap, and `assert_options_auto_simulate_allowed` in place of
  `assert_auto_simulate_allowed`. Duplication is the right trade here: a shared helper is a shared
  blast radius, and the equity path is live.
* **The guard is called before the acceptance**, and the test at
  `test_activation_guards.py:170-173` (which asserts the guard's call site precedes the acceptance's
  by source-text index) gets an options twin.
* **Wiring.** `job_approved_scope_scan` (`scheduler.py:282-312`) gains a second, separately-guarded
  block that runs **only** when `options_auto_simulate_enabled` is ON, over the options scan runs,
  and never over the equity scan runs. Both blocks must remain the **only** call sites, which the
  safety test enforces.
* **A refused candidate is recorded, not dropped.** Same as the equity path: a gate-PASSED options
  candidate the guard refuses becomes a REJECTED `PaperTrade` whose immutable snapshot carries the
  exact refusal reason; one held back only by the daily cap becomes WATCH.
* **`AuditLog`** gets `action = "paper.options_auto_simulated"` with the structure, the collateral
  reserved, the limits evaluated, and `"simulated": True` — mirroring `auto_simulate.py:193-212`.

**What the options path must NOT reuse (HYPOTHESIS):** `accept_candidate`. The options acceptance
writes its own order/fill/structure/collateral/trade set through `paper/options_ledger.py`. Reusing
`accept_candidate` would mean reusing `_slippage_frac` (`ledger.py:88`) and the hard-coded
`_NOMINAL_SPREAD_BPS = 5.0` (`ledger.py:50`, **FACT**: a module constant with no override path,
pricing every live paper fill at `ledger.py:163-166`) — a per-share basis-point spread applied to
an option premium is not an approximation, it is a category error.

---

## 12. Config, settings, and what must not move

| Thing | Where | Why |
|---|---|---|
| `OptionsRiskLimits` | `config/research.py`, as `ResearchConfig.options_risk` | Version-controlled, diffable, in `full_config_hash` for audit |
| `SCOPE_HASH_FIELDS` | **UNCHANGED** (`config/research.py:392-409`) | §1.4: adding a key un-scopes all three live approvals. Verified by recomputation. |
| Shaping params (`max_short_delta`, `min_credit_to_width`, θ, DTE window, width band, profit/stop multiples, `time_stop_dte`) | the strategy's **`spec_json`** | §4: they select and exit, so they must be inside `spec_json_hash` and the five-part scope match. NOT in `OptionsRiskLimits`. |
| `options_scope_hash` | computed separately, stored on the options promotion evaluation | Changing an options limit un-scopes the **options** strategy only — the correct blast radius |
| `OptionCostModel` | D2's object, frozen before the first evaluation | **FACT**: R4 freezes `CostModel`; `OptionCostModel` is new, so it is a one-time decision |
| `options_auto_simulate_enabled` | `app_setting`, default **FALSE** | Operator-toggled, audited; **FACT**: not present in the live DB today |
| `options_auto_simulate_max_per_day` | `app_setting`, default **0** | Separate from the equity cap of 2 (**FACT**: live value `auto_simulate_max_per_day = 2`) |
| `PromotionThresholds` | **UNCHANGED** (`config/research.py:81-128`) | R4: frozen for the program; options thresholds are D4's *additional* gates, never edits to these |

### 12.1 The sibling-blindness hole is in THREE contracts, not one — and two of them are what keep the LLM off the decision path

Rev 1 found this defect in S11 and then failed to generalise it. The same one-line mechanism
applies to S13 and S14, and those two are load-bearing for the standing constraint "no LLM decides
an order".

**FACT** — an import-linter *forbidden* contract matches a module **and its descendants**.
`signalforge.paper.options_ledger` and `signalforge.paper.options_auto_simulate` are **siblings** of
`signalforge.paper.ledger`, not descendants, so every contract naming `signalforge.paper.ledger`
leaves them uncovered. Three contracts name it:

| Contract | `pyproject.toml` | What the hole means |
|---|---|---|
| **S11** options are simulation-only | `:209-219`, forbidden list at `:213-219` | `options.*` → the options paper decision path becomes allowed |
| **S13** Signal Forge 1000 is research-only | `:242-253`, forbidden list at `:246-253` | `sf1000.*` → options paper acceptance becomes allowed |
| **S14** research agents are read-only reporters | `:255-278`, forbidden list at `:259-278` | **`signalforge.agents.*` may import `paper.options_ledger` and open an options structure with import-linter green** |

**Why S14's hole is the decisive one.** **FACT:** the agents layer is live right now (`app_setting`
id 3: `{"agents": {"enabled": true, "llm_narratives": true}}`). **FACT:** `signalforge.agents` is
**not** a source module of S3 (`pyproject.toml:180-186` — sources are `research`, `risk`, `backtest`,
`paper` only), so `agents → llm` is permitted **by design**; S14 is the contract that stops the
agents layer reaching the decision path, and S14's only paper target is `paper.ledger`. Under rev 1's
§12 as written, an `agents` module could import `paper.options_ledger`, open an options structure,
and every contract would pass.

**And the reverse direction is uncovered entirely.** **FACT:** `signalforge.llm` is **never** a
source module in any contract — grep shows it appears only as a *forbidden target*
(`pyproject.toml:186, 215, 239, 249`). Nothing forbids `llm → paper.options_*`. This is exactly the
reverse-direction gap the map §0.1 B3 says needs a **new** contract, and rev 1 did not add it for the
options modules.

**HYPOTHESIS — three changes, all strictly more restrictive and therefore permitted under R4, all in
the same commit as the new modules:**

1. **Rewrite S11's, S13's and S14's `signalforge.paper.ledger` entries to `signalforge.paper`
   wholesale** (or, if a narrower change is preferred, add `signalforge.paper.options_ledger` and
   `signalforge.paper.options_auto_simulate` to each of the three explicitly). Wholesale is
   preferred: it closes the hole for every future sibling, not just these two.
2. **Add a new contract in the reverse direction** (map §0.1 B3):

   ```toml
   [[tool.importlinter.contracts]]
   name = "S15: nothing in the LLM/agent/app/alert layers may reach the options paper decision path"
   type = "forbidden"
   source_modules = ["signalforge.llm", "signalforge.agents", "signalforge.app", "signalforge.alerts"]
   forbidden_modules = ["signalforge.paper.options_ledger", "signalforge.paper.options_auto_simulate"]
   ```

3. **Add a meta-test** (§14 item 15a) asserting that **every** contract naming
   `signalforge.paper.ledger` also names the options siblings — so the next sibling module cannot
   quietly reopen this, and so a future edit that reverts (1) fails CI rather than passing it.

---

## 13. New tables and the additive migration plan

**FACT:** the live migration head is `e5a1b7c3d9f2` (`select * from alembic_version`), i.e.
`20260910_0800-e5a1b7c3d9f2_agent_report.py`. The chain is linear with `839214f66f31` at the root.

**HYPOTHESIS — one migration, `down_revision = "e5a1b7c3d9f2"`, purely additive.**

```
paper_option_structure                    (new)
  id                         INTEGER PK
  account_id                 FK paper_account  ON DELETE CASCADE
  candidate_id               FK candidate      ON DELETE SET NULL
  strategy_version_id        FK strategy_version ON DELETE SET NULL
  underlying_instrument_id   FK instrument     ON DELETE CASCADE   # the UNDERLYING (§10 cond. X)
  structure_type             VARCHAR(24)       # VERTICAL_CREDIT | VERTICAL_DEBIT | CASH_SECURED_PUT
  contracts                  INTEGER
  entry_net_premium          Numeric(20,6)     # signed: credit > 0
  exit_net_premium           Numeric(20,6)  NULL
  r_dollars                  Numeric(20,6)     # R = max loss at entry, after entry costs
  collateral_reserved        Numeric(20,6)
  dte_at_entry               INTEGER
  dte_at_exit                INTEGER        NULL
  profit_target_pct_of_credit  FLOAT
  stop_multiple_of_credit      FLOAT
  time_stop_dte              INTEGER
  opened_at                  UTCDateTime
  closed_at                  UTCDateTime    NULL
  exit_reason                VARCHAR(32)    NULL   # target|stop|time_stop|forced_pre_expiry
  exit_signalled_at          UTCDateTime    NULL
  exit_deferred_sessions     INTEGER  DEFAULT 0
  realized_pnl               Numeric(20,6) DEFAULT 0
  pnl_r                      FLOAT          NULL
  r_clamped                  BOOLEAN DEFAULT 0
  pin_risk_flag              BOOLEAN DEFAULT 0
  assignment_risk_flag       BOOLEAN DEFAULT 0
  forced_close_no_print      BOOLEAN DEFAULT 0
  fill_model                 VARCHAR(48)
  iv_source                  VARCHAR(32)
  q_source                   VARCHAR(48)
  greeks_source              VARCHAR(32)
  created_at                 UTCDateTime (indexed)
  INDEX (account_id, closed_at)
  INDEX (underlying_instrument_id, closed_at)     # the per-underlying check (§10 cond. X)
  INDEX (strategy_version_id, closed_at)          # the health-monitor / probation reads (§7.3)

paper_option_leg                          (new)
  id                    INTEGER PK
  structure_id          FK paper_option_structure ON DELETE CASCADE
  option_contract_id    FK option_contract        ON DELETE RESTRICT
  option_ticker         VARCHAR(40) (indexed)      # denormalised for the mark's hot path
  right                 VARCHAR(4)                 # call | put
  strike                FLOAT
  expiration_date       DATE
  qty_signed            INTEGER                    # + long / − short
  shares_per_contract   INTEGER                    # COPIED from option_contract at entry
  entry_price           Numeric(20,6)
  exit_price            Numeric(20,6)  NULL
  entry_spread_cost     Numeric(20,6)
  entry_commission      Numeric(20,6)
  UNIQUE (structure_id, option_ticker)

paper_option_mark                         (new, append-only)
  id                 INTEGER PK
  structure_id       FK paper_option_structure ON DELETE CASCADE
  as_of              DATE (indexed)
  net_premium        Numeric(20,6)
  unrealized_pnl     Numeric(20,6)
  net_delta_shares   FLOAT
  net_vega_per_pt    FLOAT
  short_leg_delta    FLOAT
  synthetic          BOOLEAN DEFAULT 0      # any leg marked from the surface
  iv_unavailable     BOOLEAN DEFAULT 0
  legs_priced        INTEGER
  legs_total         INTEGER
  iv_source          VARCHAR(32)
  surface_contracts_used INTEGER NULL
  UNIQUE (structure_id, as_of)

paper_collateral_entry                    (new, append-only)   -- fields in §3.1

paper_options_reconcile_report            (new, append-only)   -- §3.4, §10.2 cond. AA
  id                            INTEGER PK
  account_id                    FK paper_account ON DELETE CASCADE
  as_of                         DATE
  clean                         BOOLEAN DEFAULT 0    # false unless findings_json is empty
  findings_json                 JSON                 # one entry per named check that failed
  collateral_reserved_observed  Numeric(20,6)
  collateral_reserved_expected  Numeric(20,6)
  open_structures               INTEGER
  created_at                    UTCDateTime (indexed)
  UNIQUE (account_id, as_of)    # the guard's dated lookup key

candidate                                 (ALTER, additive)
  + structure_kind  VARCHAR(16) NULL      # NULL = single-leg equity (§10.1)

candidate_option_structure                (new)
  id / candidate_id (FK, UNIQUE) / structure_type / underlying_symbol / legs_json /
  net_premium / max_loss_dollars / max_gain_dollars / break_evens_json /
  short_leg_delta / net_delta_shares / net_vega_per_pt / credit_to_width / dte_at_entry

paper_account                             (ALTER, additive)
  + collateral_reserved Numeric(20,6) NOT NULL DEFAULT 0
```

**`instrument.instrument_type` is NOT retyped. Rev 1's table listed
`~ instrument_type VARCHAR(16) -> VARCHAR(24)` directly beneath a rule forbidding retypes, and the
retype was unnecessary.** On SQLite `op.batch_alter_table` (rule 2) **rebuilds** the table — a
copy / drop / rename of `instrument`, which has **2,658 rows** and **14 FK children** (`ohlcv_daily`,
`ohlcv_intraday`, `candidate`, `paper_position`, `paper_order`, `backtest_trade`, `corporate_action`,
`data_quality_flag`, `earnings_event`, `fundamentals_snapshot`, `quote_snapshot`,
`reconciliation_check`, `short_interest`, `watchlist_member` — all verified by
`pragma foreign_key_list`), on a live database while a paper probation runs. It bought nothing:
§1.2 already recommends `'option_spread'` (13 chars), §10.1 uses exactly that as
`Candidate.structure_kind` in a `VARCHAR(16)`, and §13's `paper_option_structure` carries no
`instrument_type` column at all. **No new `Instrument.instrument_type` value is introduced by this
design.** The only ALTERs are the two additive ones above (`candidate.structure_kind`,
`paper_account.collateral_reserved`).

**Consequence for §7.1 and §14.1, stated rather than left implicit.** The `NotAnEquityPosition`
assertion is therefore **defence-in-depth against a row this design never creates** — its value is
that it fires if some *future* code path introduces an option-typed instrument, not that it guards
anything Phase 1 writes. Its test must construct an option-typed `Instrument` that production never
will, and the test should say so in its docstring. **`Candidate.structure_kind` is the load-bearing
discriminator** (§10.1); the type assertion is the backstop.

**Migration rules (HYPOTHESIS):**

1. **Purely additive.** No column is dropped, renamed, retyped, or made non-nullable on existing
   data. Every new column on an existing table is nullable or has a server default, so the live
   $30,000 equity account and the 0-row paper tables migrate to a byte-identical state plus
   defaults. **This rule has no exceptions in this migration** — see the note above.
2. **`op.batch_alter_table` for the two additive ALTERs**, matching the existing style
   (`initial_schema.py:1292`) — SQLite needs the table rebuild even to add a column, which is the
   second reason the `instrument` retype is not worth its blast radius.
3. **Immutability triggers** on `paper_collateral_entry`, `paper_option_mark` and
   `paper_options_reconcile_report`, copying the `RAISE(ABORT, …)` shape and the
   `dialect.name in {"sqlite"}` guard from `initial_schema.py:1262-1286`, dropped symmetrically in
   `downgrade()`.
4. **`downgrade()` drops only what `upgrade()` created** and is exercised in CI. It must be safe to
   run against the live DB shape.
5. **No data migration, and no `PaperAccount` insert.** The options account is created by the
   operator with `signalforge paper init --name options_paper --cash 25000` (**FACT**:
   `cli.py:1229`), deliberately, and its creation is therefore an operator action with a
   timestamp rather than a schema side effect.
6. **The migration must not be applied while the worker is running.** **FACT** (memory): one writer
   per DB, write-intent sessions are sticky. Stop the worker, migrate, restart — and the first
   post-restart action is the startup catch-up, which precedes the first heartbeat.
7. **`make secrets` runs after the migration is written.** **FACT** (memory): the secret-scan gate is
   a real check-only gate and Alembic revision IDs are auto-excluded; the baseline is never
   rewritten casually.

**Why not reuse `paper_position` (HYPOTHESIS, decisive).** §1.5: `health_monitor._paper_returns_r`
and `paper_probation._paper_trade_summary` read `paper_position` filtered on
`strategy_version_id` with **no account filter**, and both silently skip rows with
`stop_level is None`. An options structure stored as a `PaperPosition` would therefore be either
mis-measured (if `stop_level` is set to something) or invisible to the health monitor (if it is
NULL) — and invisible means **never downgraded**. A separate table makes both readers blind by
default and forces the options branch to be written explicitly (§7.3).

---

## 14. Tests the design requires (for I-O6, listed so D4/D5 can reference them)

Safety tests, in the shape of the existing ones:

1. `mark_to_market` raises `NotAnEquityPosition` on an option-typed instrument — and the equity
   path's behaviour on stock/etf is unchanged (golden-value test against the existing
   `tests/paper/test_ledger.py` fixtures). The test must **construct** an option-typed `Instrument`,
   because §13 introduces no new `instrument_type` value and production never writes one; the
   docstring says so, so the next reader does not mistake a backstop for a live guard.
2. `portfolio_snapshot` raises the same on the same input.
3. `accept_candidate` refuses a candidate with `structure_kind is not None`.
4. `assert_auto_simulate_allowed` refuses the same, **and** the existing suite
   (`tests/paper/test_activation_guards.py`) still passes unmodified — the narrowing must not
   change any existing verdict.
5. `assert_options_auto_simulate_allowed` refuses on **each** of conditions A–AB independently, one
   test per condition, each asserting the refusal *names* the condition.
6. The options twin of `test_automatic_acceptance_has_exactly_one_guarded_entry_point`
   (`test_activation_guards.py:149-173`), **specified by PATH EQUALITY, never by basename**: the
   allowed callers of the options acceptance are exactly
   `{"paper/options_ledger.py", "cli.py", "paper/options_auto_simulate.py"}` — compared as
   `rel == …`, the form the existing test already uses for its `auto_simulate.py` arm. **`app/routers/`
   is NOT an allowed options caller in Phase 1**: the equity precedent it would copy is
   `app/routers/dashboard.py:243 res = accept_candidate(db, candidate_id)`, an HTTP route with no
   guard at all, and an HTTP route that can open an options structure is not a Phase 1 surface.
   Only `scheduler.py` may call `auto_simulate_options_scan_runs`; and the guard's call site precedes
   the acceptance's in source order.
6a. **The existing equity test is repaired to path equality in the same commit.** **FACT**
   (`test_activation_guards.py:158, :161-165`): `manual_ok = {"ledger.py", "cli.py"}` is matched with
   `p.name in manual_ok`, so any file anywhere named `ledger.py` or `cli.py` — `agents/cli.py`, for
   instance — may call `accept_candidate` and the suite stays green. Change it to
   `rel in {"paper/ledger.py", "cli.py"}`. This is strictly more restrictive (R4-permitted) and it
   must land with the options twin, because the twin is copied from it.
7. Kill switch: with an open options structure and the switch engaged,
   `mark_options_to_market` and `process_option_expiries` still run and can close; the guard
   refuses every open.
8. Collateral: reserve/release round-trips to exactly zero; `spendable_cash` never goes negative;
   a forced divergence makes the reconciler report and the guard refuse, and **does not** repair.
9. Immutability: `UPDATE`/`DELETE` on `paper_collateral_entry` and `paper_option_mark` raise.
10. `shares_per_contract != 100` on any leg refuses the entry and records the refusal.
11. A missing bar on any leg on the **fill** session is a **non-entry**, and a missing bar on an exit
    fill session **defers** the fill and increments `exit_deferred_sessions` — never a synthetic fill.
11a. **The signal-to-fill offset (§6.0), as a named test.** A signal computed on completed session
    *t* fills at session *t+1*'s prints, never at *t*'s; condition M is evaluated against *t+1*; and
    the offset is **byte-identical** in D2's options backtest and in the paper path (assert the same
    helper, or assert equal fill sessions on a shared fixture). Sits beside the equity engine's own
    convention (**FACT**: `backtest/engine.py:4-7` — "a signal at bar `t` sees only `series.head(t)`
    … entries fill at the **next** bar's open").
11b. **The worked ACCEPTANCE example of §9(A) satisfies every condition A–AB under the configuration
    its own `limits_config_note` declares**, and the worked REFUSAL example of §9(B) is refused
    naming condition **S**. Parameterised on the declared config, so the test stays meaningful
    whichever Finding-4 / Finding-5 resolution the operator and D2 choose.
11c. **Collateral crash ordering (§8 step 4).** With the close transaction interrupted after the
    `PaperTrade` write and before the `release`, the reconciler reports check 5 ("no closed structure
    has an unreleased reserve") and the guard refuses to open; with the *opposite* ordering forced in
    a fixture, check 6 fires. Asserts the conservative direction, not just that a check exists.
12. A structure found open on or past its expiration date raises `OptionExpiryUnhandled`.
13. Health monitor and probation return the options R series from `paper_option_structure.pnl_r`
    and **do not** silently skip it.
14. Determinism (S4): the same inputs produce the same structure, the same R, the same collateral,
    and the same snapshot JSON.
15. Import-linter S11, **S13 and S14** (all three tightened per §12.1) and S3 pass, and the **new
    S15** reverse-direction contract passes; `signalforge.paper.options_ledger` imports
    `signalforge.options.blackscholes` and nothing in `signalforge.llm`.
15a. **Meta-test on the contracts themselves:** parse `pyproject.toml` and assert that **every**
    contract whose `forbidden_modules` names `signalforge.paper.ledger` also names
    `signalforge.paper.options_ledger` and `signalforge.paper.options_auto_simulate` (or names
    `signalforge.paper` wholesale). This is what stops the next sibling module reopening the hole
    §12.1 documents, and it fails loudly if someone reverts the tightening.
16. **The reconcile-report condition AA is satisfied only positively:** with **no**
    `paper_options_reconcile_report` row for the current session the guard refuses (not passes), and
    with a row whose `clean` is false it refuses naming AA. Explicitly tests the
    satisfied-by-absence case, which is how rev 1's version failed.
17. **Account targeting (§10.2 condition N):** an options acceptance called with
    `account_name="default"` is refused naming N, and no row is written to any table against
    `paper_account.id == 1`. A wrong account name, not just a missing one.

---

## 15. Open questions

**For the operator (each blocks the step named):**

1. **Findings 4 and 5 (§5.4) are a D2-then-operator question, in that order.** At $250 per-structure
   max loss, every feasible SPY-priced vertical pays ≥ 94% of its credit in modelled costs at the
   baseline spread and ≥ 184% at 2×, so **gate 4b cannot be passed**; and Finding 5 shows
   `min_credit_to_width ≥ 0.25` and `θ@2× > 0` have a **jointly empty** feasible set at |Δ| ≤ 0.20
   and R ≤ $700 under the illustrative cost constants.

   **Nothing is asked of you yet.** The order of operations is §5.4(1)–(5): **D2 freezes
   `OptionCostModel` first and this arithmetic is re-run against the frozen constants.** Only if the
   region is non-empty but the limits exclude it does a capital question reach you, and then the ask
   is the *smallest* pair of values that admits the region, not a target. **If the region is still
   empty after D2's options (1)–(3), the default disposition is §5.4(5): O3 cannot be evidenced at
   this account size and decision 13 re-opens.**

   *Rev 1 listed the capital raise first, with the figure ~$700 attached. That is withdrawn as a
   recommendation: it derives entirely from spread constants D3 states it does not own, and raising
   a capital limit in order to make a gate passable is gate weakening by another route. The figure
   survives only as an illustration of what the illustrative constants imply.*
   *Blocks D5's pre-registration and I-O5.*
2. Decision 4's dollar limits are **2× looser in percent terms** than §3.2's grid centres on a
   $25,000 account (§5.1). Confirm the dollar values are the intended ones, since D4/D5 will centre
   the sensitivity grid on them. *Blocks D4.*
3. Is `options_max_open_structures = 5` intended, given that the $1,000/$250 pair already caps the
   book at **4** structures (§3.5)? *Blocks nothing; affects reporting only.*
4. Confirm the options paper account name and that $25,000 is the intended figure now that the
   live equity account is known to be **$30,000**, not the $100,000 §3.1 assumed (§1.1). *Blocks
   the account creation, hence gate 10.*
5. The gate-10 window: **≥ 6 months or 20 closed structures, whichever is later** (§3.5), derived
   from 3.1–8.4 closes/month. Confirm, or state a different window **before** probation starts.
   *Blocks gate 10.*
6. Decision 3 (options approval level) still gates whether a defined-risk vertical is reachable at
   all. Unchanged; restated because D3's whole design assumes Level 2.

**For D2 (backtest architect):**

7. §2.4(1a) vs (1b) — the four-full-crossings choice is what makes Finding 4 bite. If (1b) is
   adopted the arithmetic of §5.4 must be re-run before D5 pre-registers.
8. The spread model's absolute floor dominates every narrow structure (§5.4). Is
   `spread_abs_floor_cents` a single constant or moneyness/underlying-dependent? Either way it
   must be justified, not fitted.
9. `OptionCostModel`'s exact fields and frozen values, so §10.2 condition T (`θ`) can be evaluated
   at both spread settings.

**For D1 (data architect):**

10. The composition of `options_scope_json`, and therefore of `options_data_scope_hash`
    (§10.2 condition J). D3 assumes it exists and is hashable.
11. The §2.4b surface's `N` floor, which decides how often a mark is `iv_unavailable` and hence how
    often an exit defers (§6 step 6).
12. The `q` decision (decision 11 chose "source and record `q` per underlying"). `q_source` is a
    required snapshot field (§9); confirm its shape.

**For D4 (evidence architect):**

13. **`min_credit_to_width` is KEPT as a gate** (§5.3, rev 2 — rev 1's proposal to retire it is
    withdrawn; the "empty feasible set" was an artifact of too small a (σ, DTE, W) box and the
    "±0.02 degeneracy" was really −0.034…+0.064, monotone in σ√T). θ is added as a **third** axis,
    not a replacement. What D4 must decide: (a) whether the σ√T-corrected ρ of §5.3 axis 4 is used
    at all; (b) whether, after D2 freezes the cost model, Finding 5's joint emptiness justifies an
    **explicit, recorded override** of map §3.2's Rule — which would be D4's call and must appear in
    the pre-registration as an override, never as a derived finding.
13a. **Where the shaping parameters live (§4).** D3 places `max_short_delta`, `min_credit_to_width`,
    θ, the DTE window, the width band, the profit/stop multiples and `time_stop_dte` in the
    strategy's `spec_json` (hence `spec_json_hash`, hence the five-part scope match), because
    `SCOPE_HASH_FIELDS` cannot be touched without un-scoping all three live equity approvals (§1.4).
    Map §3.2's Rule says "both are in `config_hash`". **D4 must explicitly agree that
    `spec_json_hash` is the correct reading of that Rule**, and that the options `DataSnapshot` key
    carries `options_scope_hash` and `options_data_scope_hash` so a shaping change costs a counted
    sealed look (§1.6, §4). *Blocks D5's pre-registration.*
14. The gate-8 ceiling for the clamp rate, the pinned fraction, the deferral count, and the
    `forced_close_no_print` count — all four are produced by §6–§8 and need pre-registered ceilings.

**Unresolved in D3 itself:**

15. **Beta-weighting the combined delta cap across two accounts.** §5.2 Finding 2 proposes that the
    combined cap can only ever block an options open. If the equity book (live: 10% per-trade risk,
    §1.3) already consumes the ±$10,000 of beta-weighted delta on its own, the options stream would
    be permanently blocked and the block would look like "no qualifying signals". The combined
    figure must be **reported every cycle whether or not it binds** (§9 `limits_evaluated`), but the
    right ceiling is not something D3 can set without the operator's view of how the two books
    relate.
16. **The `r_clamped` series and the health monitor.** §7.3 uses the clamped series so R means the
    same thing as in the backtest, and reports the unclamped minimum alongside. If the clamp rate
    turns out high — which §5.4's cost arithmetic makes likely, since a 3-wide structure closed at
    max loss pays $56 of exit costs on a $240 R — the health monitor is comparing a truncated live
    distribution against an untruncated backtest one. D4 should decide whether gate 8's clamp
    ceiling or the health monitor's comparison is the right place to catch that.
17. **Whether an options `Candidate` should point at the underlying's `Instrument` row at all.**
    §10.1 makes that safe via `structure_kind`, but an alternative — a nullable `instrument_id` with
    a separate `underlying_instrument_id` — avoids the ambiguity entirely at the cost of a
    non-additive column change on a live table. D3 chose the additive route; the trade-off is
    recorded.

---

## Appendix J — Judge responses (rev 2)

Two adversarial refutation passes were run against rev 1 — one on legitimacy/evidence, one on
safety/feasibility — raising 19 defects between them. **Every defect was independently re-verified
against HEAD `5b41a61` before any edit**, using read-only `SELECT`s and recomputation with the
repo's own `signalforge.options.blackscholes`. No write, no provider call, no package install.

**All 19 were accepted as real.** Two *remedies* were rejected in favour of better ones, and one
judge *rationale* was accepted with a correction; those three are itemised at the end. Verification
also produced one result neither judge had: **Finding 5** (§5.4).

### Accepted and fixed

| # | Defect | Verification | Where fixed |
|---|---|---|---|
| 1 | Shaping parameters (`max_short_delta`, `min_credit_to_width`, `time_stop_dte`) hidden outside every pre-registration hash | `risk` **is** in `SCOPE_HASH_FIELDS` (`config/research.py:392-409`) precisely because it filters candidates; `StrategySealedTest` unique on `(version, snapshot)` and reused, never recomputed (`db/models/research.py:252,263`) | §4 (split), §1.6, §12, §15 Q13a |
| 2 | "Empty feasible set" was an artifact of the grid; it retired a gate the map states as a **Rule** | Recomputed: c/w ≥ 0.25 at \|Δ\|≈0.20 is reached at σ=0.45/DTE≥60 (W=1), σ=0.45/DTE=90 (all W), σ=0.60/DTE≥45, σ=0.80/DTE≥21 | §5.3 (Finding 3 withdrawn; gate KEPT) |
| 3 | Degeneracy overstated ~3× ("±0.02") | Measured residual **−0.034 … +0.064**, monotone in σ√T; worst at σ=0.45/60DTE/W=2/Δ=0.40 | §5.3 (table now carries residuals) |
| 4 | §8 step 4's crash ordering produced the opposite of its stated guarantee | Logic: release-then-crash = collateral freed, no close — the fail-open case | §8 step 4 (inverted) + §8.0 |
| 5 | The canonical worked snapshot depicts a trade the guard must REFUSE | K=431, σ=0.20, 30 DTE ⇒ put delta **−0.2009** vs `max_short_delta` 0.20; c/w 0.1994 | §9 (two records: acceptance schema + refusal) |
| 6 | No signal-to-fill offset anywhere; condition M satisfiable only by looking forward | `backtest/engine.py:4-7` — equity engine fills at the **next** bar's open, deliberately | §6.0 (new), §10.2 cond. M, §14 item 11a |
| 7 | §1.3's quoted query returns 7 rows, not 3 | Re-run read-only: ids 20/23/32/35 carry `11b54aee64dbc265…` | §1.3 (full result, superseded rows marked) |
| 8 | Stale `file:line` in `config/research.py`, `scheduler.py`, `cli.py` | Every cite re-resolved; e.g. `min_paper_trades` :240→:273, `SCOPE_HASH_FIELDS` :345→:392, `JobSpec("paper_mtm")` :474→:577, `paper init` :1126→:1229 | throughout; `git_sha` now in the header |
| 9 | Sealed-look accounting and R5 disclosure absent | Map §5.4; `count_sealed_looks` (`promotion.py:615`), `k_prior` (`:888`) | §1.6 (new) |
| 10 | §15 Q1 ordered so the reader acts on the only option that raises dollar risk | — | §5.4 resolutions reordered (1)–(5); §15 Q1 rewritten |
| 11 | Condition L mandates the exercise style whose bias flatters the strategy | `OptionContract.exercise_style` defaults `'american'` (`market.py:254`) | §10.2 (restated as a scope restriction with the bias named) |
| 12 | S13 and S14 inherit S11's sibling blindness — the two contracts that keep the LLM layer off the decision path | S13 `pyproject.toml:246-253`, S14 `:259-278` both name `signalforge.paper.ledger`; `signalforge.agents` is **not** a source of S3 (`:180-186`); `signalforge.llm` is never a source anywhere; agents live (`app_setting` id 3) | §12.1 (new), + new **S15** contract, + meta-test §14 item 15a |
| 13 | Caller-allowlist twin would inherit a **basename** match; `app/routers/` must not be an options caller | `test_activation_guards.py:158` `manual_ok = {"ledger.py","cli.py"}`, matched `p.name in manual_ok` at `:161-165` | §10.1(4), §14 items 6 and 6a |
| 14 | Condition AA satisfied by absence, and the flag had no home | — | §3.4 (report row), §13 (table), §10.2 cond. AA, §14 item 16 |
| 15 | Startup catch-up reaches the options auto-sim without the options mark/reconcile/expiry | `run_catch_up` (`scheduler.py:805-817`) does **not** call `job_daily_eod_update`; `job_catch_up` (`:770-782`) does | §6 (both halves), §8 step 7 |
| 16 | Condition N is a tautology; a wrong account name targets the live $30,000 equity book | `paper_account` → `(1,'default',30000,30000)`; rev 1 configured no options account anywhere | §2, §4 (`paper_account_name`), §10.2 cond. N, §14 item 17 |
| 17 | No transaction boundary anywhere; cash accounting unstated | `auto_simulate.py:170,178,188,213` commits per decision | §8.0 (new) |
| 18 | §13 retypes a live, heavily-referenced column and contradicts its own rule 1 | `instrument` has 2,658 rows and **14** FK children (`pragma foreign_key_list`); `batch_alter_table` rebuilds on SQLite; `'option_spread'` is 13 chars so no new value is ever written | §13 (retype deleted; §7.1/§14.1 reconciled) |
| 19 | §1.3's printed output did not match its printed query | see #7 | §1.3 |

### Remedies rejected, with the reason

1. **"Use a compliant strike Δ ≈ 0.16, K = 427.25" (§9).** Rejected: **VERIFIED** that at K = 427.25,
   W = 3, R = **$252.14**, which breaches `per_structure_max_loss_dollars` = $250 (condition Q). The
   suggested fix trades a condition-S breach for a condition-Q breach. More fundamentally, the
   verification pass found that **no** cell satisfies Q, S and T simultaneously at decision-4's
   numbers — that is Finding 5 — so a single clean "accepted" example cannot honestly exist yet.
   §9 therefore carries **two** records: a refusal (the design's actual current state) and an
   acceptance labelled as a **schema illustration** with its infeasibility stated on its face.
2. **"Amend §1.3's query to `… and e.config_hash = 'fe365720…'` so the output matches" (defect #19).**
   Rejected: narrowing the query would hide the four rows carrying the older hash, and the existence
   of approved-scope evidence under **two** config hashes bears directly on §4's blast-radius
   argument. §1.3 prints the **full** seven-row result, marks which rows are superseded, and states
   what the older hash implies — which is what the judge's own defect #7 asked for.

### Judge rationale accepted with a correction

3. **"The feasible set is non-empty exactly where implied vol is high, i.e. where the volatility risk
   premium is most likely present."** The *defect* is accepted — the set is non-empty and rev 1's
   Finding 3 is withdrawn — but this *rationale* is not. The computation is pure Black–Scholes with
   **no risk premium in it at all**; c/w exceeds |Δ| at high σ√T because credit/width tracks `N(−d₂)`
   while |Δ| tracks `N(−d₁)`, which is the same systematic residual as defect #3. Reading the
   non-empty region as evidence of a premium would be reading a model artifact as an edge. §5.3 says
   so explicitly, and §5.3 axis 4 now requires any ρ gate to be stated relative to `ρ_BS(σ, T)`
   rather than to 1.0 — without that correction, a ρ gate against 1.0 would systematically admit
   long-dated, high-σ structures and call the arithmetic an edge.

### Found during verification, in neither judge's list

**Finding 5 (§5.4): `min_credit_to_width ≥ 0.25` and `θ@2× > 0` have a jointly EMPTY feasible set**
at |Δ| ≤ 0.20 and R ≤ $700 over the full widened box — zero cells. The best θ@2× anywhere subject to
c/w ≥ 0.25 is +0.116, at W = 40, R = $2,902 (11.6% of the $25,000 account). Low σ√T is where costs
are containable and the credit hurdle fails; high σ√T is where the hurdle passes and the
proportional spread eats the credit. This sharpens Finding 4, is arithmetic rather than empirical,
and is on the record **before** any outcome is looked at — which is what R1 pre-registration is for.
It is explicitly **not** an argument for retiring the credit hurdle; see §5.4's ordered resolutions.
