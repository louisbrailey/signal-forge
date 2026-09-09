# Portfolio Research Roadmap — Four Isolated Paper-Research Modules

Status: **Phase A design pack. No code, no migration, no activation step, no
alert enabled by this document.** Companion documents: `docs/CAPABILITY_MATRIX.md`
(capability-by-capability evidence) and `docs/SF1000_SPEC.md` (the full
Module B specification).

## Purpose

Signal Forge is a paper-trading-only, research-only U.S. equities (and,
eventually, options-education and forex-design) platform
(`pyproject.toml`: `description = "... local-first, paper-trading-only
market research & trade-recommendation platform (research/education
only)."`). This roadmap defines four **isolated** research modules — each
with its own scope, its own data-quality caveats, its own risk/position
caps, its own test bar, and its own paper ledger where one exists — so that
adding new research surfaces never widens what any existing module is
allowed to do.

"Isolated" is load-bearing: no module in this roadmap may read another
module's approved scope, paper ledger, or alert eligibility as if it were
its own. Module A's `ex_meta` `PAPER_APPROVED` scope
(`src/signalforge/research/approval_scope.py`) stays exactly what it is
today; nothing in Modules B/C/D broadens it, reuses it, or is approved by
extension of it.

## Non-negotiable boundaries

These hold across every module in this document, with no exception planned
at any phase:

- **No brokerage, no order placement, no trade mirroring, anywhere.**
  Enforced structurally by import-linter contract **S1**
  (`pyproject.toml`) and by `ruff`'s `flake8-tidy-imports` banned-api list
  (`ib_insync`, `ibapi`, `alpaca_trade_api`, `selenium`, `ccxt` are
  unimportable project-wide).
- **No LLM on any decision path.** Contract **S3** forbids
  `signalforge.research`, `.risk`, `.backtest`, `.paper` from importing
  `signalforge.llm`. Every module in this roadmap inherits that boundary;
  none of the new modules (B, D) introduce an exception, and Module C's
  existing exclusion (**S11**, below) is not relaxed.
- **No news-driven decisions.** Contract **S12** forbids
  `research.scan`/`.candidates`/`.strategies`/`risk` from importing the news
  modules. News (generic or Benzinga) is context only, everywhere.
- **Options stay education/simulation-only.** Contract **S11** forbids
  `signalforge.options` from importing `alerts`, `llm`, `research.scan`,
  `research.candidates`, or `paper.ledger`. No options-trade alert exists as
  code, not merely as a disabled setting.
- **Alerts and paper probation ship OFF and stay OFF until an operator
  turns them on by hand**, per the exact sequence in
  `docs/RUNBOOK_ALWAYS_ON.md` ("Manual enable steps"). Nothing in this
  roadmap changes that default or that sequence for Module A, and every new
  module (B/C/D) adopts the identical "ships OFF" posture for anything it
  eventually adds.
- **Every candidate/alert/simulated-portfolio artifact carries "Research
  signal only — no order was placed"** (Module A convention, e.g.
  `alerts/dispatch.py` module docstring) — Module B's SF1000 outputs carry
  the equivalent "simulated model portfolio... not an investable product"
  statement (`docs/SF1000_SPEC.md` §10).
- **No "most profitable" objective, no claim or implication of 100%
  profitability, anywhere in this system.** Every test-methodology section
  below reports risk-adjusted, cost-inclusive, out-of-sample evidence or it
  reports nothing.
- **No brokerage/Webull/order-placement integration is in scope for any
  module, at any phase.** This roadmap does not create one and does not
  plan to.

## Module A — Existing U.S. Equity Paper Probation

### Purpose & permitted scope

The already-built and already-running research pipeline: scan → candidate →
manual paper-acceptance → mark-to-market, gated by a 10-gate promotion
pipeline before any strategy may alert. **This roadmap does not broaden
Module A's approved scope, gates, universe, or alert eligibility in any
way.** Its only role here is to be the reference pattern the newer modules
are held to, and to state explicitly what must stay frozen.

**Exact current scope, preserved as-is:**

- Universe: the `ex_meta` `DataSnapshot` — 24 symbols (the 25-symbol
  watchlist+ETF set minus `META`, whose raw pre-2022-06-09 history was found
  to blend an unrelated micro-cap entity's prices —
  `reports/FB_META_CONTINUITY_INVESTIGATION.md` §1). `ResearchConfig.universe`
  (`src/signalforge/config/research.py`) is the de-duplicated union of
  `watchlist` (10 names) and `etf_universe` (15 ETFs) = 25; `ex_meta` is 24.
- Currently `PAPER_APPROVED`, on that exact scope, per
  `reports/FB_META_CONTINUITY_INVESTIGATION.md` §5: `trend_continuation.short_swing`
  v0.1.0 and `relative_strength.medium_swing` v0.1.0. Every other default
  strategy remains `experimental` (`mean_reversion.short_swing`,
  `trend_continuation.medium_swing`, `volatility_breakout.short_swing`,
  `intraday_orb.intraday`).
- `Strategy.status == PAPER_APPROVED` is necessary but **not** sufficient
  for a candidate to alert — the live scan must match the exact approved
  dataset snapshot, config hash, live parameter hash, and source
  (`research/approval_scope.py::scan_scope_matches`). This is the mechanism
  that keeps "approved" from silently drifting to mean "approved on
  whatever data happens to be current."

### Deterministic strategy specification

Six strategies, each a versioned, hashed spec
(`src/signalforge/research/strategies/{base,breakout,intraday_orb,
mean_reversion,relative_strength,trend_continuation}.py`), each producing a
long/short/avoid candidate with an explicit entry zone, invalidation level,
target, time stop, and reward:risk estimate (`Candidate` model,
`db/models/research.py`) — no probability, ranking, or sizing decision in
this module is LLM-produced (S3) or news-influenced (S12).

### Data providers & latency categories

Per-symbol daily bars from Massive (`data/adapters/massive.py`), `source=
"massive"`, `LatencyCategory.END_OF_DAY`. Intraday (`Horizon.INTRADAY`) is
entitled at `DELAYED` 15-minute granularity but **not ingested** for this
module — `intraday_orb.intraday` fails promotion gate 0 for exactly that
reason (`reports/STRATEGY_PROMOTION_STATUS.md`). See
`docs/CAPABILITY_MATRIX.md` for the full evidence table.

### Point-in-time requirements & known bias risks

- **Survivorship bias, disclosed and unresolved**: the 25/24-symbol universe
  is a fixed, hand-picked large-cap/ETF list with no delisted names and no
  point-in-time membership reconstruction (`research/promotion.py` gate 8
  evidence payload, `known_caveats`). This roadmap does not resolve it for
  Module A — resolving it would require the same historical-constituents
  data gap identified for Module B (`docs/SF1000_SPEC.md` §7).
  Retroactively applying today's universe across the whole 10-year backtest
  window, as if it had always been "the" universe, is a known, disclosed
  look-ahead-adjacent simplification (`reports/FB_META_CONTINUITY_INVESTIGATION.md`
  §8).
- **As-of adjustment, not point-in-time**: research/promotion bars are
  split/dividend-adjusted as fetched, from `OHLCVDaily.adj_close`
  (`db/models/market.py`) — adequate for this module's existing 10-year
  single-universe backtest, but the same underlying limitation the universe
  pipeline discloses explicitly for its own bulk path
  (`universe/normalize.py`, `ASOF_FLAG = "asof_adjusted_not_pit"`).
- **Ticker-continuity risk**: the FB→META investigation is the template for
  how a corporate action can silently corrupt a symbol's history
  (`db/models/market.py::SymbolContinuityMapping`); no other symbol in the
  universe has been audited for a similar collision
  (`reports/FB_META_CONTINUITY_INVESTIGATION.md` §8, "Corporate-action
  coverage is FB→META only").

### Paper-account / risk-budget isolation

`PaperAccount` (`db/models/paper.py`) — one ledger, `cash`/`initial_cash` as
`Numeric(20,6)`. `PaperPosition`/`PaperOrder`/`PaperFill`/`PaperTrade` are
immutable after creation (invariant S9 — DB triggers, per
`paper/ledger.py` module docstring). Sizing is `risk_dollars` /
per-share-risk, capped by `RiskLimits.per_trade_risk_pct` (0.5% of account)
— never a fixed share count.

### Position / sector / correlation / liquidity / exposure caps

All from `RiskLimits` (`config/research.py`), applied project-wide today —
Module A does not get its own separate cap set:

| Cap | Value | Field |
|---|---|---|
| Per-trade risk | 0.5% of paper account | `per_trade_risk_pct` |
| Max daily portfolio risk | 1.5% | `max_daily_portfolio_risk_pct` |
| Max single-position concentration | 10% | `max_position_concentration_pct` |
| Max portfolio exposure | 60% | `max_portfolio_exposure_pct` |
| Max correlated (sector/theme) exposure | 25% | `max_correlated_exposure_pct` |
| Min reward:risk | 1.5 | `min_reward_to_risk` |

Liquidity: `LiquidityFilters` — min price $5, min ADV$ $20M, max spread proxy
15bps (spread itself unlicensed, see `docs/CAPABILITY_MATRIX.md`), min
market cap $1B.

### Test methodology

The 10-gate promotion pipeline (`research/promotion.py`) is the bar every
strategy version must clear before `PAPER_APPROVED`:

1. Rolling walk-forward folds (≥4, at least half clearing a trade-count +
   expectancy floor) over the pre-sealed span.
2. Minimum OOS trade count (≥30).
3. Positive net expectancy after costs.
4. Bootstrap CI lower bound materially above zero (>+0.02R, not merely
   non-negative) — `backtest/montecarlo.py::bootstrap_ci`, seeded, 2,000
   resamples.
5. Parameter-sensitivity robustness grid (`research/sensitivity.py`).
6. Bull/bear/range-bound coverage, all three regimes, minimum trades each
   (`backtest/regime.py::label_regimes`).
7. Risk-adjusted benchmark comparison (Sharpe vs. SPY buy-and-hold, same
   actual-data span).
8. No unresolved data-quality/leakage finding (`data/validate.py`,
   `backtest/leakage.py`).
9. A sealed final OOS window, evaluated once, locked forever
   (`StrategySealedTest`, unique per `(strategy_version_id,
   dataset_snapshot_id)`).
10. Live-paper probation mechanism (`health_monitor.py`) confirmed active.

### Approval / downgrade / kill-switch criteria

- **Approval**: only `research.promotion.evaluate_promotion` may set
  `PAPER_APPROVED` — a human/manual action may only downgrade or disable
  (`promotion.py` module docstring).
- **Downgrade/disable**: `health_monitor.py::_decide` — `z =
  (paper_expectancy - oos_expectancy) / stderr(paper)`; downgrade to
  `experimental` at `z<=-2.0`, disable at `z<=-3.5` on an already-
  experimental strategy, **both** additionally requiring outright-negative
  paper expectancy (a strategy merely trailing a rich backtest while still
  profitable is left alone).
- **Kill switch**: `signalforge killswitch on/off/status`
  (`docs/RUNBOOK_ALWAYS_ON.md` "Incident basics") — every scheduled job and
  every position-opening path checks it; closing an existing position is
  allowed while engaged (protective), opening a new one is not.

### Dashboard / chart / journal / reporting requirements

Already built: Strategy Promotion page (`/strategies/promotion`), Paper
Probation dashboard (`research/paper_probation.py::paper_probation_context`
— approved scopes, sealed-test summary, realized-vs-expected shortfall,
health status per strategy), `/ops` Operational Status page
(`app/templates/ops_status.html`, `ops_status_context()` in
`app/views.py`), journal (`paper/journal.py`'s `JournalEntry` —
why-qualified/why-might-fail/rule-adherence/lessons).

---

## Module B — "Signal Forge 1000" Paper Index Research

### Purpose & permitted scope

A simulated, ≤1,000-name model portfolio for research into a systematic,
liquidity/size-first (and, once licensed, quality/valuation-aware) approach
to constructing a broad U.S. common-stock basket. **Not an ETF, fund, index
license, or investable product.** Full specification, ranking formulas,
weights, and rebalance mechanism: `docs/SF1000_SPEC.md`. This section covers
only what the spec references from the rest of the platform.

### Deterministic ranking specification

See `docs/SF1000_SPEC.md` §2 in full. Summary: a four-factor composite
z-score (liquidity 30%, market cap 30%, quality 20%, valuation 20% target
weights), currently degrading to a liquidity+cap-only 60%-coverage score
because quality/valuation inputs are not licensed (§7 of that spec) — the
degradation is mechanical and disclosed on every output, never silent.

### Data providers & latency categories

Built entirely on the **existing, in-progress** `universe/` module
(`src/signalforge/universe/{bulk,discovery,normalize,pipeline,screen}.py`):
grouped-daily bulk archive (`source="massive_grouped"`, `END_OF_DAY`),
reference-ticker discovery (active-only), current market cap enrichment.
SF1000 introduces **no new provider or adapter** — see
`docs/CAPABILITY_MATRIX.md` for every entitlement it depends on and every
gap it inherits.

### Point-in-time requirements & known bias risks

Covered in full in `docs/SF1000_SPEC.md` §1 (universe) and §7 (missing
data). Summary of the two distinct failure modes, kept explicitly separate
because they have different remedies:

- **Forward/live construction** (build today's basket going forward) is
  legitimate on today's data — no point-in-time gap bites here.
- **Historical backtesting of the methodology** cannot be done honestly
  without point-in-time market cap and historical constituent/delisting
  data, neither of which exists in this system (`docs/SF1000_SPEC.md` §7).
  Substituting today's values into a past date is a **look-ahead bias** —
  the ranking would "know" something (eventual size, or that a name was
  still listed at all) that was not actually knowable on the historical
  date being scored. SF1000 backtests are provisional by construction until
  that gap closes or is explicitly, permanently accepted as a disclosed
  limitation.

### Paper-account / risk-budget isolation

**A separate, dedicated SF1000 paper ledger — never the Module-A
`PaperAccount`/`PaperPosition` tables.** Built in Phase B (§ "Schema &
migration plan" below proposes the tables; none exist yet). SF1000 tracking
never writes to, reads from as if authoritative, or shares a risk budget
with Module A's existing paper account. A future `sf1000_ledger_entry` table
is its own immutable, append-only record — mirroring the `paper_trade`
immutability invariant (S9) by construction, not by convention.

### Position / sector / correlation / liquidity / exposure caps

`docs/SF1000_SPEC.md` §6: 2% single-name cap, 25% sector cap (reusing
`UniversePipelineConfig.max_sector_share` exactly), $20M ADV$ liquidity floor
(reusing `UniversePipelineConfig.min_avg_dollar_volume` exactly), equal-weight
construction (deferring cap-weighting until point-in-time cap is licensed),
and a drawdown-flag-not-auto-liquidate control modeled on
`health_monitor.py`'s flag-don't-act pattern.

### Test methodology

`docs/SF1000_SPEC.md` §8: an SF1000-specific analog of Module A's 10 gates —
rolling walk-forward over monthly reconstitution windows, a sealed final OOS
window evaluated once and locked, bootstrap CI on cost-adjusted excess
return over benchmark, full regime coverage, no unresolved data-quality
finding, and mandatory disclosure of `data_coverage_pct` on every
validation record. **None of this evidence exists yet — Phase A produces
only the spec, not a single validation run.**

### Approval / downgrade / kill-switch criteria

SF1000 has no "promotion" in the Module-A sense (it is not a strategy in
`research/registry.py`). Its equivalent gate is the six-point validation
checklist in `docs/SF1000_SPEC.md` §8, all of which must pass before
`sf1000_paper_probation_enabled` may even be set `True` — mirroring Module
A's `paper_probation_enabled` default-off/manual-enable-only pattern
(`docs/RUNBOOK_ALWAYS_ON.md`). The kill switch
(`signalforge killswitch`) applies to every scheduled job project-wide,
including any future SF1000 rebalance job, by the same mechanism Module A
already uses (`killswitch.ensure_not_engaged()`, called project-wide).

### Dashboard / chart / journal / reporting requirements

Phase B builds: an SF1000 dashboard page (current constituents, rank
history, `data_coverage_pct`, rebalance history with turnover and any
deferred replacements), a chart of gross vs. net-of-cost vs. SPY benchmark
(`docs/SF1000_SPEC.md` §9), and a journal-equivalent audit trail (every
rebalance decision, every buffer-hysteresis add/remove, every cap
breach/adjustment) in the same spirit as Module A's `JournalEntry`
(`paper/journal.py`) — none of it built in Phase A.

---

## Module C — Options Education & Simulation

### Purpose & permitted scope

Education and simulation only. Long call, long put, covered call, cash-
secured put — nothing else. **Deliberately excluded by design, not merely
by configuration**: naked/uncovered short options, margin-dependent
structures, spreads, 0DTE alerts, any options recommendation, any options
alert (`options/simulators.py` module docstring; import-linter contract
**S11**, `pyproject.toml`, structurally forbids `signalforge.options` from
importing `alerts`, `llm`, `research.scan`, `research.candidates`, or
`paper.ledger`).

### Deterministic specification

Not a ranking or strategy-selection module — no candidate is ever produced.
Two deterministic components:

- **Pricing/Greeks**: closed-form Black-Scholes-Merton
  (`options/blackscholes.py::price`, `greeks`, `implied_vol`) — European
  exercise, constant vol/rate, explicitly "computed locally... never
  presented as vendor Greeks or vendor implied volatility" (module
  docstring).
- **Payoff simulation**: `options/simulators.py` — `long_call`, `long_put`,
  `covered_call`, `cash_secured_put`, each returning an explicit,
  always-finite `max_loss`, a `max_gain` (may be `inf` for a long call), and
  the standard disclaimer (`options.DISCLAIMER`).

### Data providers & latency categories

Options Developer entitlement, fully measured (`reports/SUBSCRIPTION_STATUS.md`
§2, `docs/CAPABILITY_MATRIX.md`): contracts/chain snapshot/contract
snapshot/historical aggregates/delayed trades/last trade/greeks/IV/OI all
`OK` — trades/last-trade/greeks/IV `DELAYED`, open interest `END_OF_DAY`,
contract reference + historical aggregates `HISTORICAL`. NBBO bid/ask
quotes `403` — spread is estimated in the UI, never presented as observed.

### Point-in-time requirements & known bias risks

Historical option-aggregate backfill (`data/options_backfill.py`,
`OptionAggregateDaily`) is hard-capped before any fetch (`OptionsConfig`:
365-day lookback, 4 expirations/underlying, 40 contracts/underlying, 15%
strike band, 200,000-bar global ceiling — `config/research.py`) — bounded by
design, not by a discovered limit. No point-in-time bias risk analogous to
Modules A/B exists here because this module never backtests a strategy
against history; it only prices/simulates hypothetical positions at
a point in time the user chooses.

### Paper-account / risk-budget isolation

None — Module C has no paper ledger and never touches
`paper.ledger`/`PaperAccount` (enforced by contract S11). Every simulated
payoff is a standalone computation, not a booked position.

### Position / sector / correlation / liquidity / exposure caps

Not applicable in the position-sizing sense (nothing is booked). The only
"cap" is structural: `OptionsConfig.underlyings` is a small, fixed set
(`SPY, QQQ, IWM, AAPL, MSFT, NVDA`) — deliberately narrow, per the module's
own docstring ("a small liquid ETF + large-cap set").

### Test methodology

`tests/options/test_options_math.py` (8 tests, pricing/Greeks correctness),
`tests/data/test_options_backfill.py` (6, cap enforcement/idempotency/
resumability), `tests/data/test_validate_option_aggregates.py` (6, data
quality). No walk-forward/OOS/bootstrap/regime methodology applies — there
is no strategy or ranking to validate.

### Approval / downgrade / kill-switch criteria

Not applicable — nothing here is ever promoted, downgraded, or alert-
eligible; the kill switch still guards the backfill job like every other
scheduled network call (`data/options_backfill.py` uses the same
`ensure_not_engaged()` pattern as `universe/bulk.py`).

### Dashboard / chart / journal / reporting requirements

Already built: `/options` chain explorer, contract detail (explicit
"not entitled (spread estimated)" caveat), paper simulator with payoff SVG,
max-loss/gain/break-even, Black-Scholes time-decay curve, and a red
risk-warning panel (`reports/SUBSCRIPTION_STATUS.md` §2). Phase E (below)
proposes incremental improvements only — a historical-bars panel for a
selected contract is "available next step, not yet wired"
(`reports/SUBSCRIPTION_STATUS.md` §2) — no expansion of scope.

---

## Module D — Future Forex Module (design only, Phase 3)

**Nothing in this module exists today. No adapter, no table, no entitlement
check has ever been run against a forex endpoint.** This section is a design
placeholder, explicitly gated on a licensed currency-data subscription being
confirmed first — it commits to no schema, no code, and no timeline beyond
"Phase 3."

### Purpose & permitted scope

Research/education into currency-pair price behavior, on the same
paper-only, no-brokerage, no-LLM-decision, no-alert-by-default posture as
every other module. Scope is **not yet defined** beyond that — which pairs,
which sessions, which horizons are all open questions pending the
entitlement check below. `(unverified — no forex design decision has been
made; this section exists to reserve the module's place in the roadmap, not
to specify it)`.

### Deterministic strategy/ranking specification

Not defined. Would follow the same pattern as Module A (versioned,
hashed strategy specs, no LLM/news on the decision path) once pairs and
horizons are chosen — `(unverified, Phase 3 work)`.

### Data providers & latency categories

**Unknown and unverified.** The lead's brief states explicitly "no forex
entitlement checked." `data/entitlements.py::verify_entitlements` has no
forex probe today. Before any further Module D design work: run the
equivalent of `signalforge providers verify` against whatever forex
endpoints the current Massive plan exposes (if any), and record the result
the same way every other feed in `docs/CAPABILITY_MATRIX.md` is recorded.
Massive/Polygon-style APIs commonly gate FX behind a separate product tier
from the Stocks Developer plan already licensed — `(unverified)`.

### Point-in-time requirements & known bias risks

Not assessable without knowing what data is actually available. FX markets
have their own distinct data-quality issues (24-hour sessions, no single
authoritative "close," interbank vs. retail quote conventions) that have no
analog anywhere else in this codebase and would need dedicated design work
— `(unverified, Phase 3 work)`.

### Paper-account / risk-budget isolation

Would be its own, separately-isolated paper ledger, following the same
pattern proposed for Module B (never sharing Module A's `PaperAccount`) —
`(unverified, Phase 3 work)`.

### Position / sector / correlation / liquidity / exposure caps

Not defined. FX has no "sector" in the equity sense; correlation/exposure
caps would need a currency-specific design (e.g. per-currency net exposure
rather than per-sector) — `(unverified, Phase 3 work)`.

### Test methodology

Would reuse the existing `backtest/{walkforward,montecarlo,regime}.py`
machinery in principle (all three are already asset-agnostic on a
`PriceSeries`), but this has not been designed or attempted —
`(unverified, Phase 3 work)`.

### Approval / downgrade / kill-switch criteria

Would mirror Module A's promotion/health-monitor pattern in principle; not
designed — `(unverified, Phase 3 work)`.

### Dashboard / chart / journal / reporting requirements

Not defined — `(unverified, Phase 3 work)`.

**Gate for even starting Module D's real design work**: a licensed currency
subscription must be confirmed first (Phase D below) — this roadmap does
not authorize evaluating, selecting, or purchasing one; that decision is the
owner's.

---

## Phased rollout

### Phase A — this document (current phase)

- `docs/PORTFOLIO_RESEARCH_ROADMAP.md` (this file), `docs/CAPABILITY_MATRIX.md`,
  `docs/SF1000_SPEC.md`.
- Schema + migration **plan** only (below) — no Alembic revision file is
  created in Phase A. **No migration is created in Phase A.**
- Safety-boundary scaffolding already present in the working tree at the
  time of writing (uncommitted — verify with `git status` before relying on
  it as merged): an import-linter contract **S13** ("Signal Forge 1000 is
  simulated research only — no alerts, no paper acceptance, no LLM, no
  brokerage", `pyproject.toml`) with `source_modules =
  ["signalforge.sf1000"]` forbidding that package from importing
  `signalforge.alerts`, `signalforge.paper.ledger`, `signalforge.llm`,
  `signalforge.research.promotion`, `httpx`, and `requests` — the same
  forbidden-import pattern **S11** already uses for `signalforge.options`.
  A placeholder `src/signalforge/sf1000/__init__.py` exists carrying only
  `SPEC_VERSION = "0.1.0-provisional"`, `STATUS = "design_only"`, the
  `PROVISIONAL_LABEL`, and `RESEARCH_ONLY_NOTICE` constants — no `def`, no
  `class`, no behavior, verified by `tests/sf1000/test_phase_a_boundaries.py`
  (also present), which additionally asserts every activation switch
  (`alerts_enabled`, `paper_probation_enabled`,
  `auto_simulate_qualified_signals`, every per-type alert switch, and
  `universe_pipeline.enabled`) still defaults off, and that this roadmap,
  the capability matrix, and the SF1000 spec exist and carry the "not an
  ETF" / "provisional" / "survivorship" / "look-ahead" language this
  document uses throughout.
- **Nothing is activated.** No table is created, no job is scheduled, no
  alert type is added, no setting defaults to on.

### Phase B — SF1000 build-out

- A separate SF1000 simulated ledger (schema below), its own audit trail,
  its own dashboard, and a backtest framework operating **only** on data
  explicitly labelled provisional per `docs/SF1000_SPEC.md` §10.
- Implement the Corwin–Schultz spread proxy (`docs/SF1000_SPEC.md` §5) to
  replace the placeholder cost model — engineering work, no new data
  entitlement required.
- Run the six-point validation checklist (`docs/SF1000_SPEC.md` §8) for the
  first time; publish results with full disclosure regardless of outcome,
  matching Module A's own precedent of publishing a `NO TRADE` result
  honestly (`reports/STRATEGY_PROMOTION_STATUS.md`).
- Keep the Phase-A safety-boundary contract (S13) and boundary tests green as the package gains behaviour.

### Phase C — licensed point-in-time fundamentals

- **Only after identifying the exact gap and asking the owner before
  purchase.** This roadmap does not select a vendor or authorize spend.
  The exact gaps to resolve are enumerated in `docs/SF1000_SPEC.md` §7:
  point-in-time fundamentals, historical constituents/delisted-ticker
  history, point-in-time market cap.
- Once (and only once) licensed, wire the quality/valuation factors into
  SF1000's composite score (`docs/SF1000_SPEC.md` §2) and re-run the full
  validation checklist — a coverage change from 60% to 100% is itself a
  new methodology version (`spec_version` bump), not a silent upgrade to
  the existing one.

### Phase D — forex design, after a licensed currency subscription is confirmed

- No forex design work proceeds past what's in Module D above until a
  currency-data subscription is confirmed active on the account (mirroring
  Phase C's "ask before purchase" discipline — this roadmap does not
  authorize evaluating or purchasing one).
- Once confirmed: run the forex-equivalent of `signalforge providers verify`,
  populate `docs/CAPABILITY_MATRIX.md`'s forex row with real evidence, and
  only then draft a forex-specific spec analogous to `docs/SF1000_SPEC.md`.

### Phase E — options education improvements

- Wire the already-identified "historical-bars panel for a selected
  contract" (`reports/SUBSCRIPTION_STATUS.md` §2 — "available next step, not
  yet wired") using the existing `OptionAggregateDaily` data that already
  exists from the bounded backfill.
- No scope expansion: still no options alerts, no naked/margin/spread/0DTE
  structures, no options recommendation — contract S11 stays exactly as it
  is.

---

## Schema & migration plan (Phase A — plan only; no migration created)

Proposed tables for Module B, following the exact conventions already used
throughout `db/models/` (typed `Mapped[...]` columns, `IntPK`/`CreatedAt`
mixins from `db/base.py`, `UTCDateTime` from `db/types.py`, JSON columns for
structured/variable evidence payloads, explicit `UniqueConstraint`s). **No
Alembic revision file exists for any of this yet** — the most recent real
migration in this repo is `20260909_0143-6d1e552c9a20_universe_pipeline_tables.py`
(`src/signalforge/db/migrations/versions/`), and a real SF1000 migration
would be the next one in that sequence, written only in Phase B.

### `sf1000_constituent_snapshot`

One row per (rebalance date, held symbol) — the actual as-of-then basket.

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `rebalance_id` | FK → `sf1000_rebalance.id` | |
| `symbol` | `String(16)`, indexed | |
| `rank` | `Integer` | Position in the composite-score ordering that rebalance |
| `composite_z_provisional` | `Float` | §2.1 formula's output |
| `data_coverage_pct` | `Float` | e.g. `0.60` while quality/valuation are unlicensed |
| `liquidity_z` / `market_cap_z` | `Float` | Individual factor z-scores, for auditability |
| `quality_z` / `valuation_z` | `Float`, nullable | `NULL` until licensed (§7), never `0.0` (which would silently claim "neutral" rather than "absent") |
| `weight_pct` | `Float` | Equal-weight target (§6) |
| `sector_group` | `String(4)` | 2-digit SIC, mirrors `UniverseMember.sic_group` |
| `entered_this_rebalance` | `Boolean` | For turnover accounting |

### `sf1000_rebalance`

One row per monthly rebalance event.

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `rebalance_date` | `Date`, indexed | |
| `universe_screen_run_id` | FK → `universe_screen_run.id` | Ties the basket to the exact eligibility screen it was built from |
| `n_constituents` | `Integer` | ≤1,000 |
| `n_added` / `n_removed` | `Integer` | For turnover-cap reporting |
| `n_deferred_by_turnover_cap` | `Integer` | §4's explicit deferral logging |
| `turnover_pct` | `Float` | One-way, excluding forced hard-gate removals |
| `data_coverage_pct` | `Float` | Snapshot of §2.1 at this rebalance |
| `spec_version` | `String(24)` | e.g. `"0.1.0-provisional"` — ties every rebalance to the exact spec version that produced it |
| `notes` | `Text` | Deferred-replacement detail, any hard-gate forced removals |

### `sf1000_ledger_entry`

**Immutable, append-only** — mirrors the `paper_trade` invariant (S9)
exactly, not a weaker version of it. No `UPDATE`/`DELETE` path in the
repository layer, and (once built) the same BEFORE UPDATE/DELETE trigger
pattern the `paper_trade` migration already uses.

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `rebalance_id` | FK → `sf1000_rebalance.id` | |
| `symbol` | `String(16)`, indexed | |
| `action` | `String(12)` | `add` \| `remove` \| `hold` \| `reweight` |
| `simulated_price` | `Numeric(20,6)` | The as-of close used for the simulated fill |
| `simulated_shares_or_weight` | `Float` | Depends on whether the ledger tracks notional weight or share count |
| `cost_bps_applied` | `Float` | §5's `total_cost_bps` at this entry, always stored even when it's the placeholder |
| `cost_model_version` | `String(24)` | Distinguishes placeholder-spread entries from later Corwin–Schultz-calibrated ones |
| `created_at` | `UTCDateTime` | |

### `sf1000_performance`

Periodic (e.g. daily) mark of the simulated portfolio's value — gross and
net, alongside the benchmark(s).

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `as_of_date` | `Date`, indexed | |
| `gross_value` | `Numeric(20,6)` | §9's "SF1000 gross (no cost)" |
| `net_value` | `Numeric(20,6)` | §9's "SF1000 net (modeled cost)" |
| `benchmark_symbol` | `String(16)` | e.g. `"SPY"` |
| `benchmark_value` | `Numeric(20,6)` | |
| `data_coverage_pct` | `Float` | So every performance point is traceable to the ranking coverage that produced its basket |

### `sf1000_benchmark_definition`

A small reference table so "the benchmark" is itself versioned and never
silently redefined mid-history.

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `key` | `String(40)`, unique | e.g. `"spy_buy_and_hold"`, `"sf1000_gross"`, `"sf1000_net"` |
| `description` | `Text` | |
| `cost_model_version` | `String(24)`, nullable | `NULL` for the no-cost/raw-price benchmarks |

**Explicitly, per the task boundary for this phase: no migration is created
in Phase A.** The tables above are a plan for Phase B's implementation, not
a schema that exists in this database today.
