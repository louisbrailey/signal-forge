# Risk & Paper Mechanics — Options Readiness Map (read-only, 2026-09-10)

Scope: `risk/engine.py`, `risk/portfolio.py`, `paper/ledger.py`, `paper/portfolio.py`,
`paper/journal.py`, `db/models/paper.py`, `alerts/render.py`, `paper/auto_simulate.py`
(+ `paper.ledger.assert_auto_simulate_allowed`). All paths below are repo-relative
under `src/signalforge/` unless stated otherwise. No repo file was modified except
this one; no writes/network calls were made — this is a static read of the files
above plus `risk/portfolio.py`, `domain.py`, `config/research.py`,
`db/models/market.py`, `db/models/research.py`, `options/__init__.py`,
`options/simulators.py`, and one Alembic migration, all via `Read`/`grep`.

## 1. What exists today (FACT, file:line)

The paper/risk stack is built for a **single-instrument, single-leg, long-or-short
equity position** end to end:

- **Sizing** (`risk/engine.py:59-131`, `size_position`): risk is `|entry_price -
  stop_price|` per share (`engine.py:70`), shares = risk budget / per-share risk
  (`engine.py:74-77`), notional = `shares * entry_price` (`engine.py:79`).
  `SizingRequest` (`engine.py:26-31`) has only `symbol, sector, entry_price,
  stop_price, account_equity` — no strike, expiry, right, multiplier, or leg list.
- **Exposure/concentration** (`risk/portfolio.py:9-70`): `Holding.market_value`
  (`portfolio.py:10-13`) is "signed: negative for shorts" — a stock-style notional.
  Caps in `size_position` (concentration `engine.py:83-95`, portfolio exposure
  `engine.py:96-103`, correlated/sector exposure `engine.py:105-114`, daily risk
  `engine.py:116-123`) are all expressed in **notional dollars**, never in max-loss
  dollars or collateral dollars.
- **Accept flow** (`paper/ledger.py:129-255`, `accept_candidate`): one `entry_ref`
  price (`ledger.py:150`), one `per_share_risk` (`ledger.py:152`), `shares` derived
  from `risk_dollars / per_share_risk` (`ledger.py:156`), one `PositionSide`
  (`LONG`/`SHORT` only — `domain.py:82-85`), one `PaperOrder`/`PaperFill`/
  `PaperPosition` row per trade, each tied to exactly one `instrument_id`
  (`ledger.py:175-217`; FK sites at `db/models/paper.py:54,82`). Spread/slippage
  cost is a flat basis-points-of-notional model (`_NOMINAL_SPREAD_BPS = 5.0`,
  `ledger.py:50,163-167`) — an equity-liquidity convention.
- **Cash accounting** (`ledger.py:220-221`, `304-308`): "longs tie up notional,
  shorts tie up costs only (proceeds held as credit)" — comment at `ledger.py:220`
  and mirrored on close at `ledger.py:303-304`. `PaperAccount` (`db/models/
  paper.py:37-44`) has exactly two money columns, `initial_cash` and `cash`; there
  is **no** collateral/buying-power/margin-reserved column anywhere in the schema.
- **Mark-to-market / exit** (`ledger.py:266-319`): pulls the *underlying's* daily
  OHLCV bars only (`get_daily_bars(session, inst.symbol, ...)`, `ledger.py:292`);
  `_exit_reason` (`ledger.py:335-348`) checks `bar.low <= stop_level` /
  `bar.high >= target_level` against the underlying's bar, plus a `time_stop_date`
  cutoff (`ledger.py:346-347`). There is no expiry-date branch, no
  option-mark source, no assignment/exercise logic anywhere in this function or
  file.
- **`PaperPosition`** (`db/models/paper.py:78-97`): `side` (long/short enum),
  `qty` (int), `avg_price`, `stop_level`, `target_level` (both plain floats),
  `time_stop_date`. No `strike`, `expiry`, `option_right`, `multiplier`, or any
  foreign key grouping several rows into one spread/combo position.
- **`PaperOrder`/`PaperFill`** (`db/models/paper.py:47-76`): one `instrument_id`
  per order, one `qty`, one `price` per fill. No leg index, no parent
  order-group id, no per-leg fill semantics.
- **Evidence snapshot** (`_candidate_snapshot`, `ledger.py:369-464`): exhaustive
  for a single-leg equity candidate (entry zone, invalidation, target, R:R,
  liquidity/event/slippage/portfolio-context JSON blobs, scan scope match,
  strategy version, code sha) but has no field shaped for legs, strikes,
  expiries, IV assumption, mark source, collateral reserved, or a payoff/
  max-loss/max-gain/breakeven object.
- **Alerts** (`alerts/render.py:16-52`, `render_candidate_alert`): renders one
  `entry_low`/`entry_high`/`stop`/`target`/`reward_risk`/`risk_dollars`/`risk_pct`
  per candidate (`render.py:31-39`) — no rendering path for multiple legs,
  strikes/expiries, net debit/credit, or max-loss/max-gain/breakeven.
- **Auto-simulation guard** (`ledger.py:474-514`, `assert_auto_simulate_allowed`):
  explicitly checks `inst.instrument_type not in ("stock", "etf")` and raises
  `AutoSimulateForbidden` if so (`ledger.py:496-500`) — **this is the existing,
  working equity-only gate**, already doing exactly the kind of explicit,
  fail-closed check the operator wants for options. `paper/auto_simulate.py`
  adds no instrument-type logic of its own (confirmed by full read of
  `auto_simulate.py:1-241`) — it relies entirely on this one guard plus its own
  kill-switch check (`auto_simulate.py:138`), already-decided check
  (`auto_simulate.py:99-105,161-163`), one-open-position-per-**instrument**
  check (`auto_simulate.py:108-120,164-171`), and the daily cap
  (`auto_simulate.py:74-96,172-179`, setting key `auto_simulate_max_per_day`,
  default 2).
- **`Instrument`** (`db/models/market.py:30-43`): `instrument_type` column
  comment reads `# stock | etf` (`market.py:35`) — the two-value assumption is
  baked into the core reference table itself, not just the ledger guard.
- **Options data already exists, decoupled from all of the above** (FACT): a
  full options market-data pipeline is already in the repo —
  `data/options_ingest.py`, `data/options_backfill.py`,
  `data/adapters/massive_options.py`, and the `option_aggregate_daily` table
  (migration `20260907_1654-c0b787616343`, columns `option_ticker`,
  `underlying_symbol`, OHLCV, no structured strike/expiry/right columns — those
  are presumably packed into the OCC-style `option_ticker` string). None of
  `risk/`, `paper/`, or `db/models/paper.py` reference this table or module —
  confirmed by `grep` across those paths finding zero hits for `collateral`,
  `multi_leg`, `assignment`, `exercise`, `option_leg`, `OptionLeg`,
  `buying_power`, or `margin`.
- **Options payoff math already exists, also decoupled** (FACT):
  `options/__init__.py:1-20` and `options/simulators.py:1-168` implement
  Black-Scholes pricing/Greeks and payoff simulators for `long_call`, `long_put`,
  `covered_call`, `cash_secured_put` — each returning a `SimResult` with
  `entry_cost`, `max_loss`, `max_gain`, `break_evens`, `payoff_at_expiry`
  (`simulators.py:28-37`). The module's own docstring is explicit and load-
  bearing: "no order placement, no broker contact... Naked short options,
  uncovered calls, margin-dependent strategies, 0DTE alerting, and spreads are
  intentionally absent." (`options/__init__.py:3-6`). This is research/education
  code only; nothing in `paper/ledger.py` calls into `options/simulators.py` or
  serializes a `SimResult` into a `PaperTrade` snapshot.

## 2. Every equity-only assumption, by file:line (FACT)

| File:line | Assumption |
|---|---|
| `risk/engine.py:26-31` (`SizingRequest`) | One `entry_price`/`stop_price` pair; no legs/strike/expiry/right/multiplier |
| `risk/engine.py:70` | Risk = linear `|entry - stop|` per unit; no defined-risk-spread or naked-premium risk model |
| `risk/engine.py:74-95` | Sizing/concentration in shares × price notional, not contracts × max-loss |
| `risk/portfolio.py:10-13` | `Holding.market_value` is stock-style signed notional, not option max-loss/collateral |
| `paper/ledger.py:150-164` | One `entry_ref`, one `PositionSide` (long/short only), no leg list |
| `paper/ledger.py:156` | `shares = risk_dollars / per_share_risk`, no ×100 contract multiplier anywhere |
| `paper/ledger.py:163-167` | Flat bps-of-notional spread/slippage model (equity liquidity convention) |
| `paper/ledger.py:175-217` | One `PaperOrder`/`PaperFill`/`PaperPosition` row per trade, one `instrument_id` each |
| `paper/ledger.py:220-221,303-308` | Cash model = "notional for longs, cost-only for shorts"; no collateral/margin reserve concept |
| `paper/ledger.py:292` | `mark_to_market` prices positions off the **underlying's** OHLCV bars only |
| `paper/ledger.py:297,335-348` | Exit check compares underlying bar high/low to a flat `stop_level`/`target_level`; no expiry-date branch, no assignment/exercise |
| `paper/ledger.py:313` | Unrealized P&L = `(underlying close - avg_price) * qty`, i.e. delta-1 pricing |
| `paper/ledger.py:369-464` | Evidence snapshot has no leg/strike/expiry/IV/mark-source/collateral/payoff fields |
| `paper/ledger.py:496-500` | `assert_auto_simulate_allowed` hard-blocks any `instrument_type` other than `stock`/`etf` |
| `paper/portfolio.py:51-81` | `portfolio_snapshot` equity/exposure math assumes delta-1 mark-to-market and the same two-branch (long/short) cash logic |
| `paper/auto_simulate.py:108-120` | One-open-position check keyed on a single `instrument_id`, not "one structure per underlying" |
| `db/models/paper.py:78-97` (`PaperPosition`) | No `strike`/`expiry`/`option_right`/`multiplier`/leg-group columns |
| `db/models/paper.py:47-76` (`PaperOrder`/`PaperFill`) | One instrument per order/fill; no multi-leg grouping |
| `db/models/paper.py:37-44` (`PaperAccount`) | Only `cash`/`initial_cash`; no `collateral_reserved`/`buying_power` column |
| `db/models/market.py:35` | `Instrument.instrument_type` comment: `# stock | etf` — the schema itself only documents two values |
| `alerts/render.py:31-39` | Single entry/stop/target/R:R block; no multi-leg/payoff rendering |

## 3. What an options paper trade needs

### 3.1 Multi-leg orders and fills
Today one `PaperOrder`/`PaperFill` = one instrument, one price, one side
(`db/models/paper.py:47-76`). An options structure (vertical spread, iron
condor, covered call = stock + short call, CSP) needs an atomic group of 1-4
legs, each with its own right (call/put), strike, expiry, side (buy/sell), and
ratio, priced individually but accepted/rejected as one unit. HYPOTHESIS:
lowest-risk shape is a new `option_right`/`strike`/`expiry_date`/`multiplier`
set of columns on `PaperPosition`/`PaperOrder` plus a nullable
`leg_group_id` (self-referencing or a new `paper_spread` parent table) so a
2-4-leg structure is N position rows sharing one group id, and
`accept_candidate`'s single-row insert (`ledger.py:175-217`) becomes a loop
over legs inside one DB transaction (all-or-nothing, matching the existing
per-decision-commit discipline in `auto_simulate.py:170,178,188,213`, which
already commits once per candidate — extend that unit-of-work to "once per
leg-group", not "once per leg").

### 3.2 Collateral / buying-power model
`PaperAccount` (`db/models/paper.py:37-44`) has no reserved/collateral column;
`accept_candidate`'s cash debit (`ledger.py:220-221`) only handles "pay full
notional" or "pay costs only." Needs, at minimum: a **cash-secured put**
reserves `strike * 100 * qty` (matching `options/simulators.py:118-139`'s own
`collateral = strike * mult` line 121); a **defined-risk spread** (e.g. a
vertical) reserves `(strike_width * 100 * qty) - net_credit` as margin, not
full notional; a **covered call** reserves nothing beyond the long-stock cost
already modeled for equities plus the short-call premium credit. HYPOTHESIS:
add `PaperAccount.collateral_reserved` (or a separate append-only
`PaperCollateralHold` table mirroring the immutability discipline of
`PaperTrade`, S9) so `cash` stays "spendable" and buying-power checks in
`risk/engine.py` can test `cash - collateral_reserved >= required` without
conflating the two.

### 3.3 Mark-to-market of legs
`mark_to_market` (`ledger.py:266-319`) only ever calls `get_daily_bars` on the
underlying (`ledger.py:292`) and prices at `last.close` (`ledger.py:313`) —
correct for delta-1 equities, wrong for options (theta/vega/strike/expiry all
matter). The repo already has both halves of the fix decoupled:
`option_aggregate_daily` (vendor EOD option marks, keyed by `option_ticker`)
and `options/blackscholes.py` (local BS fallback, already used by
`options/simulators.py:149-167`'s `time_decay_curve`). HYPOTHESIS: an options
`mark_to_market` path should (a) look up each leg's own `option_ticker` bar for
the `as_of` date, netted per leg by side (long adds value, short subtracts),
falling back to (b) a local Black-Scholes mark (`options/blackscholes.py`,
already IV-input-driven, i.e. `COMPUTED_NOTE` at `options/__init__.py:17`)
when the vendor bar is missing/stale — and the resulting position-level
unrealized P&L must be the sum across all legs in the group, not a
single-instrument delta as at `ledger.py:313`.

### 3.4 Expiry processing (expire worthless / assignment / auto-exercise)
No expiry-date-driven branch exists anywhere in `_exit_reason`
(`ledger.py:335-348`) — only stop/target/time-stop against the *underlying's*
bar. Needed, per leg, on/after its `expiry_date`: (a) **expire worthless** — OTM
legs simply zero out, no cash impact beyond premium already
collected/paid; (b) **assignment** — an ITM short leg at expiry (or American-style
early assignment, which HYPOTHESIS says should be explicitly out-of-scope for
a paper simulator absent a real assignment feed, deferred to expiry-only
"European-style" simulation as a documented approximation) converts into a
synthetic long/short 100-share equity `PaperPosition` at the strike,
consuming/releasing the reserved collateral from §3.2; (c) **auto-exercise** —
an ITM long leg at expiry converts the same way. Each of these must still
respect S9 (`ledger.py:1-8`, `ARCHITECTURE.md:72`): the option `PaperPosition`
closes immutably, and the resulting equity position is a **new**, audit-linked
row (new `PaperTrade` with a `decision` value that records "assignment" or
"auto_exercise" as the cause, mirroring how `note`/`actor` are already frozen
into `signal_snapshot_json.decision` at `ledger.py:117,229`), never a mutation
of the option row.

### 3.5 Position limits by max loss and by concentration
`size_position` (`risk/engine.py:59-131`) sizes and caps everything in
notional dollars (`engine.py:79,84-95,97-103,106-114`). For options, "notional"
is frequently meaningless or misleading: a CSP's premium notional is small
relative to its `strike*100` collateral/max-loss; a debit spread's max-loss is
capped and much smaller than its "notional" would suggest. HYPOTHESIS: an
options sizing path should size and cap on **max_loss dollars** (already
computed per-strategy shape by `options/simulators.py`'s `SimResult.max_loss`,
e.g. `cash_secured_put(...).max_loss` at `simulators.py:125,130`) instead of
`per_share_risk`/`notional`, and the portfolio-level caps
(`max_portfolio_exposure_pct`, `max_correlated_exposure_pct`,
`max_daily_portfolio_risk_pct` — all defined generically in
`config/research.py:48-53`, `RiskLimits`) should be extended with an
options-specific accumulator (sum of `max_loss` and/or `collateral_reserved`
across open option positions, by underlying/sector) rather than reusing
`OpenExposure.gross_dollars`/`by_sector_dollars` (`risk/engine.py:35-41`) which
are computed from equity notional today.

### 3.6 Evidence snapshot fields
`_candidate_snapshot` (`ledger.py:369-464`) is the S9-immutable audit record
and is exhaustive for one equity leg but carries nothing option-shaped.
HYPOTHESIS: extend it (new version, not a mutation of the existing schema — the
function already merges a `decision` key on top per call site,
`ledger.py:116-117,228-229`, so precedent exists for additive keys) with an
`option_legs` list (per leg: `right`, `strike`, `expiry_date`, `side`, `ratio`,
`quoted_mark`, `mark_source` [vendor `option_aggregate_daily` vs. local
Black-Scholes], `iv_assumption`) and a `payoff` object that is essentially
`options/simulators.SimResult` serialized (`entry_cost`, `max_loss`,
`max_gain`, `break_evens` — `simulators.py:28-37`), plus
`collateral_reserved` and an explicit `assignment_policy` string (e.g.
"European-style, expiry-only simulation") so every immutable trade record
states its own settlement assumptions.

### 3.7 Auto-simulation guard extension
`assert_auto_simulate_allowed` (`ledger.py:474-514`) today hard-fails any
non-stock/etf instrument at `ledger.py:496-500`. Per the operator's directive
that the options scope must be **explicit, never implicit**, the correct
extension is *not* to add `"option"` to that tuple and fall through the
existing equity checks — it is a parallel, independently-gated path:
(a) a new setting distinct from `auto_simulate_qualified_signals`
(`ledger.py:74-78`) — e.g. `auto_simulate_options_enabled` — defaulting OFF,
checked before anything else, mirroring `auto_simulate_enabled`'s own
fail-closed shape; (b) the strategy version's approved scope
(`approved_scopes`/`scan_scope_matches`, imported at `ledger.py:377-381` and
`484-490` from `signalforge.research.approval_scope`) must be extended to
carry and check an explicit `instrument_type` field so an options strategy's
scope can never be satisfied by an equity strategy's approval, and vice
versa; (c) `paper/auto_simulate.py`'s daily cap
(`AUTO_SIM_CAP_KEY`/`DEFAULT_MAX_PER_DAY`, `auto_simulate.py:55-56,74-96`)
should get an options-specific counterpart, since option structures carry very
different risk-per-trade economics than the equity per-trade-risk-% model; and
(d) the one-open-position guard (`auto_simulate.py:108-120,164-171`), which
keys on a single `instrument_id`, needs an options-specific version keyed on
**underlying + strategy structure**, since a multi-leg options position spans
several `instrument_id`s (one per contract) and the existing per-instrument
check would not stop a second, different structure from being opened on the
same underlying.

## 4. Net read

Nothing in `risk/`, `paper/`, or `db/models/paper.py` currently represents an
option contract, a multi-leg structure, collateral, or expiry. The one
existing options-aware control in this scope — `assert_auto_simulate_allowed`'s
stock/etf-only check (`ledger.py:496-500`) — is a hard block, not a partial
implementation, and is exactly the fail-closed pattern the operator wants
extended (never loosened) for the options approval scope. The market-data
(`option_aggregate_daily`) and payoff-math (`options/blackscholes.py`,
`options/simulators.py`) pieces needed to compute options marks, max-loss, and
collateral already exist in the repo but are completely unwired from the paper
ledger, risk engine, alert renderer, and auto-simulation guard — this is
additive work (new columns/tables/branches alongside the existing equity path)
rather than a rewrite of the equity path, which the immutability (S9) and
kill-switch (S6) invariants apply to unchanged.
