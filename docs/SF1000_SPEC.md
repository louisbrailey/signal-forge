# Signal Forge 1000 (SF1000) — Provisional Specification

```
spec_version: 0.1.0-provisional
status:       DESIGN ONLY — Phase A. No code, no migration, nothing activated.
```

**SF1000 is a simulated model portfolio for paper-trading research. It is not
an ETF, not a fund, not an index license, not an investable product, and not
a solicitation.** Every artifact this spec produces must carry that statement
verbatim. It has no objective of "most profitable" and no claim of, or path
to, 100% profitability. It is Module B in `docs/PORTFOLIO_RESEARCH_ROADMAP.md`.

This document is versioned independently of the code (`spec_version` above).
A future revision that changes eligibility, weights, rebalance cadence, or
cost assumptions must bump this version and be diffable against the prior
one — the same "config is hashed and version-controlled" discipline already
used for `ResearchConfig` (`src/signalforge/config/research.py`,
`config_hash` property).

---

## 1. Eligible universe

**Target: ≤1,000 liquid U.S.-listed common stocks. ETFs excluded.**

Built directly on top of the existing universe pipeline — this spec does not
invent a second discovery/screening mechanism:

1. Take the latest `UniverseScreenRun` (`src/signalforge/universe/screen.py::run_screen`,
   `latest_screen`) and its `UniverseMember` rows.
2. Restrict to `UniverseMember.security_type == "CS"` — **ETFs are excluded
   from SF1000 entirely**, even though the same screen run includes them for
   other purposes.
3. Restrict to `UniverseMember.eligible == True` (survived every exclusion
   reason: `security_type_out_of_scope`, `inactive_listing`, `no_bulk_data`,
   `price_below_min`, `adv_dollar_volume_below_min`, `market_cap_below_min`,
   `insufficient_history`, `listing_too_recent`, `data_quality`,
   `corporate_action_continuity`, `sector_concentration`).
4. Rank the survivors by the composite score (§2) and take the top 1,000 (or
   fewer, if fewer than 1,000 pass step 3 — SF1000 is never padded with
   ineligible names to reach 1,000).

**Known bias risks in this universe construction, named explicitly:**
**survivorship** (active-only discovery, §7), **look-ahead** (using
information not actually knowable as of the historical date being
evaluated — see the point-in-time caveat immediately below, and §7's
point-in-time market-cap gap specifically), and **as-of adjustment**
(split/dividend factors applied as of the fetch date, not as they stood on
each historical date — `universe/normalize.py`'s `asof_adjusted_not_pit`
flag, inherited unchanged by this module).

**"Point-in-time" caveat — read before using this for anything historical.**
The underlying screen is explicitly labelled `asof_adjusted_not_pit` and
"active tickers only at discovery... NOT survivorship-free"
(`UniverseScreenRun.adjustment_basis` / `.survivorship_note`,
`src/signalforge/db/models/universe.py`). That is **acceptable for forward,
live construction** — building today's 1,000-name basket going forward never
needs historical point-in-time membership, only today's eligibility, which
the screen already provides honestly. It is **not acceptable for backtesting
SF1000's methodology over history** — reconstructing "what would SF1000 have
held on 2019-03-01" requires point-in-time membership and point-in-time
market cap that do not exist in this system today (§7). Every backtest output
under this spec must carry a **PROVISIONAL — survivorship/point-in-time
caveat applies** label until that gap is closed.

## 2. Ranking — composite score

**Target methodology (four factors):**

```
composite_z = w_liq · z(ADV$_20d) + w_cap · z(ln(market_cap))
            + w_qual · z(quality_score) + w_val · z(valuation_score)
```

| Factor | Target weight | Input | Status |
|---|---|---|---|
| Liquidity | 30% | 20-session average dollar volume (`ADV$ = mean(volume × vwap)`, same formula as `reports/UNIVERSE_CAPACITY_PLAN.md` §1 and `universe/screen.py::_metrics_from_archive`) | **available today** |
| Size | 30% | `ln(market_cap)` from `UniverseTicker.market_cap` (current value; §7 on why this can't be point-in-time yet) | **available today, current-value only** |
| Quality / profitability | 20% | e.g. ROE, gross margin stability, earnings-quality composite | **not licensed — no fundamentals adapter exists** (`docs/CAPABILITY_MATRIX.md`, `FundamentalsSnapshot` table is schema-only) |
| Valuation | 20% | e.g. trailing P/E, EV/EBITDA, relative-to-sector valuation | **not licensed — same gap** |

`z(·)` is the cross-sectional z-score within the eligible universe on the
scoring date (mean 0, std 1 across the ~1,000-2,600 eligible names measured
in `reports/UNIVERSE_CAPACITY_PLAN.md` §1) — a standard, deterministic,
auditable normalization; no machine-learned or LLM-scored component anywhere
in this formula, consistent with the project's standing rule that no
LLM ever decides an entry, exit, size, ranking, or probability
(`pyproject.toml` contracts S3/S11/S12).

### 2.1 How the score degrades today

Quality and valuation inputs do not exist in this system (§7). Rather than
silently dropping to a 2-factor score with the same weight labels — which
would misrepresent what the number means — the score **always publishes its
own coverage**:

```
available_weight = w_liq + w_cap                          # = 0.60 today
composite_z_provisional = (w_liq · z(ADV$) + w_cap · z(ln(cap))) / available_weight
data_coverage_pct = available_weight / (w_liq + w_cap + w_qual + w_val)   # = 60% today
```

- `composite_z_provisional` is liquidity+size only, renormalized so it stays
  a proper z-score-like statistic (not silently miscalibrated by carrying
  zero-weight terms).
- `data_coverage_pct` (60% today) is stored and displayed alongside every
  ranking output. It is not a footnote — it is a first-class field on every
  `sf1000_constituent_snapshot` row (§8).
- Every SF1000 ranking, chart, and report is labelled, verbatim:
  **"SF1000 (PROVISIONAL — ranked on liquidity + market cap only;
  quality/profitability and valuation inputs are not licensed; see
  docs/SF1000_SPEC.md §7)."**
- The label is mechanical, not manual: it is derived from `data_coverage_pct
  < 1.0`, so it cannot be forgotten when a report is generated, and it
  automatically stops applying only once real quality/valuation data is
  wired in and `data_coverage_pct` reaches 1.0.

### 2.2 Risk-control inputs (not part of the score)

Per-name risk controls are enforced at construction time, not folded into
the ranking (§4) — a name is either excluded/capped or it isn't; it does not
get a "risk-adjusted" score that could obscure why.

## 3. Rebalancing

**Cadence: monthly.**

Justification (quarterly and weekly/daily both considered and rejected):

- **Why not weekly/daily**: the inputs (ADV$, market cap) are themselves
  20-session trailing averages / current-value snapshots refreshed once per
  night by the universe pipeline (`universe/pipeline.py::run_universe_update`,
  which itself runs post-close). Rebalancing faster than the inputs
  meaningfully change would just be trading noise, not signal, and would
  blow through the turnover cap (§4) for no benefit.
- **Why not quarterly**: a full-quarter gap is long enough for a name to
  drift far out of eligibility (delisting, acquisition, a liquidity collapse)
  and sit in the model portfolio unaddressed for up to three months. Given
  this system's own conservative, disclosure-first posture (`ARCHITECTURE.md`
  style throughout the codebase — see e.g. `research/promotion.py`'s refusal
  to fabricate a pass), monthly is the more conservative choice between the
  two realistic options.
- Monthly also matches the natural cadence of the composite score's
  liquidity/size inputs settling out over roughly 20 trading sessions.

**Mechanism — rank-buffer hysteresis** (reduces churn from names oscillating
right at the cutoff, the same problem cap-weighted index providers solve with
buffer zones):

- An existing constituent is **removed** only if its rank falls below 1,200
  (a 20% buffer beyond the 1,000 target) or it fails a hard eligibility gate
  (delisted, `inactive_listing`, `corporate_action_continuity`, or any other
  screen exclusion reason from `universe/screen.py`) — hard-gate removals are
  never subject to the buffer.
- A non-constituent is **added** only if its rank is in the top 900 (a 10%
  buffer inside the 1,000 target).
- Names ranked between 901 and 1,199 that are already constituents are held;
  names in that band that are not yet constituents are not added. This is
  the entire mechanism — no discretionary override exists.

## 4. Turnover cap

**Hard cap: 10% of constituents (one-way) replaced per monthly rebalance**,
excluding forced hard-gate removals (delisting, eligibility loss, verified
corporate-action continuity break), which are never deferred — a name that
fails a hard gate leaves regardless of the cap, because holding a name known
to be ineligible is a worse outcome than exceeding a turnover budget.

If the buffer mechanism (§3) would otherwise replace more than 10% of
non-forced names in one rebalance, only the highest-priority replacements are
applied (largest rank improvement for adds, largest rank deterioration for
removals); the remainder are deferred to the next scheduled rebalance and the
deferral is logged on the `sf1000_rebalance` row (§8) — never silently
dropped and never silently exceeded.

## 5. Transaction-cost model

NBBO quotes are not licensed on this plan (`docs/CAPABILITY_MATRIX.md`,
`403 not_authorized` on `stocks_nbbo_quotes`). SF1000 reuses the project's
existing cost-model shape (`src/signalforge/backtest/costs.py::CostModel`:
commission + slippage_bps + half-spread) with an explicit spread **proxy**
in place of a real quote:

```
total_cost_bps(name) = commission_bps + slippage_bps + spread_proxy_bps(name) / 2
```

- `commission_bps` / `slippage_bps`: same conservative constants already used
  project-wide (`ResearchConfig.commission_per_share`, `.slippage_bps` —
  currently 0.0 and 3.0bps respectively, `config/research.py`).
- `spread_proxy_bps(name)`: **target** is the Corwin–Schultz high-low spread
  estimator, already identified as the documented option for exactly this
  gap in `reports/UNIVERSE_CAPACITY_PLAN.md` §4.5 — computed from the same
  daily bars the universe pipeline already archives, no new data entitlement
  needed. **Not implemented in Phase A.** Until it is built and back-tested
  against a known spread sample for calibration, every cost figure uses a
  conservative flat placeholder tiered by the liquidity bands already
  measured in `reports/UNIVERSE_CAPACITY_PLAN.md` §1 (ADV$≥$50M / $20-50M /
  $10-20M / below), wider than typical observed spreads at each tier, and
  every report using the placeholder is labelled **"cost model: PLACEHOLDER
  spread proxy — not yet calibrated against Corwin–Schultz or any observed
  spread sample."** Replacing the placeholder with the real estimator is a
  named Phase-B task (`docs/PORTFOLIO_RESEARCH_ROADMAP.md` Phase B), not
  silently absorbed into "done."
- Every reported return series must show gross (no cost) and net (with
  `total_cost_bps` applied at each simulated rebalance trade) side by side —
  never net-only, so the cost drag itself is auditable.

## 6. Concentration, sector, liquidity, and drawdown controls

| Control | Rule | Rationale / consistency |
|---|---|---|
| Single-name weight cap | max 2% of SF1000's simulated notional per name | Prevents one name from dominating a supposedly broad 1,000-name basket |
| Sector concentration cap | max 25% of the eligible/held set in one 2-digit SIC group | Reuses `UniversePipelineConfig.max_sector_share = 0.25` exactly (`config/research.py`) — same convention as the universe screen's own `R_SECTOR` exclusion, not a new number invented for SF1000 |
| Liquidity floor | ADV$ ≥ $20,000,000 (20-session average) | Reuses `UniversePipelineConfig.min_avg_dollar_volume` exactly — SF1000 never holds a name the universe screen itself would already exclude on liquidity grounds |
| Portfolio drawdown flag | if SF1000's simulated cumulative return draws down more than 2× the benchmark's peak-to-trough drawdown over any trailing 90 sessions, the paper ledger is flagged (not auto-liquidated) for operator review | Modeled on the existing health-monitor pattern of comparing live results against an expectation and flagging rather than acting unilaterally (`research/health_monitor.py`) — SF1000 has no automated exit/hedge mechanism in this spec |
| Weighting scheme | equal-weight within the 1,000-name basket at each rebalance (not cap-weighted) | Avoids compounding the point-in-time market-cap gap (§7) into the portfolio's actual weights, not just its ranking; cap-weighting is deferred to whenever point-in-time market cap is licensed |

None of these controls are risk limits on real capital — SF1000 never
touches the existing `paper_account`/`paper_position` tables or risk budget
(Module A); it is entirely its own, separately-isolated simulated ledger
(§8, and `docs/PORTFOLIO_RESEARCH_ROADMAP.md` Module B "paper-account
isolation").

## 7. Missing data before validation

**None of the following exist in this system today. SF1000 must not be
represented as validated, back-tested, or paper-probation-eligible until
each gap below is either closed or explicitly, permanently accepted as a
documented limitation by the owner.**

| Gap | Why it matters here | What category of data would be needed |
|---|---|---|
| **Point-in-time fundamentals** (quality/profitability, valuation) | §2's quality/valuation factors are 0-weighted today; any backtest of the *full* 4-factor design is impossible without this, and even a forward-only run can't be checked against history | A fundamentals data product with historical (not just current) financial-statement/ratio coverage — **ask the owner before purchase**, do not commit to one unilaterally |
| **Historical constituents / delisted-ticker history** | Without this, any backtest of SF1000's *membership* over time is survivorship-biased — a name that would have qualified in 2019 but delisted since is invisible (same caveat already disclosed for Module A's 25-symbol universe in `reports/FB_META_CONTINUITY_INVESTIGATION.md` §8) | A historical-reference/delisted-securities data product — **ask the owner before purchase** |
| **Point-in-time market cap** | §2's size factor and any future cap-weighting both need cap "as it was known then," not today's value re-applied to the past (which would leak the future) — `reports/UNIVERSE_CAPACITY_PLAN.md` §4.4 already flags this exact leak | Likely bundled with the fundamentals product above, but must be separately confirmed — **ask the owner before purchase**, do not assume bundling |
| **A calibrated spread proxy** (Corwin–Schultz or equivalent) | §5's cost model runs on an uncalibrated placeholder until this exists; net-of-cost figures are directional, not precise | No new entitlement needed — computable from already-archived daily bars; this is engineering work, not a purchase decision |

Until every data-only gap above is closed (the last row is not data-gated),
SF1000 backtests are **provisional by construction** and may not be used to
justify moving to paper-probation eligibility (§8) on their own.

## 8. Validation gate — what SF1000 must clear before ANY paper-probation eligibility

SF1000 is a portfolio-construction *methodology*, not a single strategy in
`research/registry.py`'s strategy list, so it cannot literally run through
`research/promotion.py`'s 10 gates unmodified — but it must clear an
equivalent bar, evaluated with the same rigor and the same refusal to
fabricate a pass that governs Module A:

1. **Rolling walk-forward reconstitution windows** over the backtest span
   (same concept as `backtest/walkforward.py`, applied to monthly
   rebalance events instead of individual trade entries).
2. **A sealed final out-of-sample window**, evaluated once and locked —
   same discipline as `StrategySealedTest` (`db/models/research.py`): never
   recomputed once sealed, never used to select the methodology after seeing
   the result.
3. **A bootstrap confidence interval** (reusing `backtest/montecarlo.py`'s
   seeded, reproducible resampling) on SF1000's turnover-and-cost-adjusted
   *excess* return over its benchmark (§9) — the lower bound must be
   materially above zero, not merely non-negative, mirroring
   `PromotionThresholds.min_bootstrap_ci_low_r` (`config/research.py`).
4. **Regime coverage** (reusing `backtest/regime.py`) across bull, bear, and
   range-bound periods with a minimum number of rebalance-period
   observations in each — a methodology validated only in one regime is not
   validated.
5. **No unresolved data-quality or survivorship finding** — every §7 gap
   still open at evaluation time must be disclosed *on the evaluation
   record itself*, the same way gate 8 in `research/promotion.py` refuses to
   let an unresolved finding hide inside a passing result.
6. **`data_coverage_pct` (§2.1) must be disclosed on every validation
   record.** A validation run at 60% coverage is not the same claim as one
   at 100%, and must never be presented as if it were.

Only after all six are met does SF1000 become eligible for its own,
separately-isolated live-paper probation ledger (Module B, Phase B in
`docs/PORTFOLIO_RESEARCH_ROADMAP.md`) — which itself starts with
`sf1000_paper_probation_enabled = False`, mirroring Module A's
`paper_probation_enabled` default (`src/signalforge/alerts/dispatch.py`).
**Phase A produces none of this evidence — it produces only this spec.**

## 9. Benchmark definition(s)

All benchmarks are computed **net of SF1000's own modeled transaction costs**
(§5) applied at the same simulated rebalance dates, so a comparison is
apples-to-apples on trading friction, not just raw price return:

| Benchmark | Definition | Purpose |
|---|---|---|
| SPY buy-and-hold | Same computation already used by `research/promotion.py::_benchmark_metrics` (Sharpe, CAGR, annualized vol, max drawdown) over the identical span | Consistency with Module A's existing benchmark convention — a reviewer who understands one understands both |
| SF1000 gross (no cost) | The equal-weight basket's raw return with monthly reconstitution, zero transaction costs | Isolates "did the ranking/construction methodology add anything" from cost drag |
| SF1000 net (modeled cost) | Same basket, §5's cost model applied at every simulated trade | The only figure that may ever be described as "what a paper account would have shown" |

No benchmark comparison here is permitted to be summarized as a claim of
outperformance without also showing the bootstrap CI (§8.3) on the excess
return — a positive point estimate alone is not evidence.

## 10. Provisional-labelling rules (summary)

Every SF1000 artifact — ranking table, rebalance record, chart, report, UI
page — must carry, verbatim and unconditionally in Phase A/B:

> "Signal Forge 1000 (SF1000) is a simulated model portfolio for paper-trading
> research. It is not an ETF, fund, index license, or investable product, and
> it makes no claim about future profitability."

And, mechanically, whenever `data_coverage_pct < 1.0` (true for the
foreseeable future per §7):

> "SF1000 (PROVISIONAL — ranked on liquidity + market cap only;
> quality/profitability and valuation inputs are not licensed; see
> docs/SF1000_SPEC.md §7)."

Neither label is a manual annotation an operator can forget to add — both
are derived fields computed from this spec's own thresholds and must be
generated by the same code path that produces the ranking/report, not typed
in separately.
