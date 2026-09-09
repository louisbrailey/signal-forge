# SF1000 Data Requirements — Vendor-Neutral

**Status: requirements only. No vendor named, evaluated, or recommended
below, and no vendor is recommended by omission either. No price appears
anywhere in this document — every cost line reads "to be filled by owner —
ask before purchase."** This document does not run the app, does not read
`.env`, and prints no secret. It is a companion to
`docs/SF1000_SPEC.md` §7 (which already names these four gaps) and
`docs/CAPABILITY_MATRIX.md` (which already records what is and isn't
entitled today) — this document goes one level deeper into *what a
replacement data source would need to provide* for each gap, and how we'd
test it before trusting it, without naming or ranking any provider.

SF1000 itself: a simulated, non-investable model-portfolio research module
(`docs/SF1000_SPEC.md` §0/§10 — "not an ETF, not a fund, not an index
license, not an investable product"). Nothing below changes that framing;
these are data inputs to a research methodology, not to a real portfolio.

---

## Gap 1 — Point-in-time fundamentals (quality / profitability, valuation)

| | |
|---|---|
| **Purpose in SF1000** | Two of the composite score's four factors — Quality/Profitability (20% target weight) and Valuation (20% target weight) — are currently 0-weighted (`docs/SF1000_SPEC.md` §2, §2.1: `available_weight = w_liq + w_cap` = 60% today). Without this data the 4-factor design cannot be run at all, forward or historical. |
| **Required fields** | Enough to compute at minimum: ROE, gross margin (or margin stability over several periods), an earnings-quality proxy; trailing P/E, EV/EBITDA, or an equivalent relative-valuation metric — the exact metric set is a methodology decision for whenever this is licensed, not fixed here. |
| **Point-in-time semantics** | Each fact must carry (a) the **as-reported** value as originally filed, (b) the **first-available timestamp** — when that value actually became knowable to a market participant (filing/press-release date, not period-end date), and (c) restated/corrected values as **separate, dated records**, never silent overwrites of the original. A backtest run as-of date D may only see facts whose first-available timestamp is ≤ D. |
| **History depth** | ≥10 years preferred (matches the existing per-symbol research history depth already ingested for the current 25-symbol watchlist — measured 2016-09-12 → 2026-09-04 in `data/signalforge.sqlite`, `ohlcv_daily` source `massive`). **Minimum for the validation gate**: enough to run `docs/SF1000_SPEC.md` §8's rolling walk-forward windows *and* a sealed OOS window over a span that includes bull, bear, and range-bound periods — by the same reasoning as `docs/POSITION_HORIZON_HISTORY_PLAN.md` §c, that is on the order of several years at an absolute floor, and closer to a full decade to get credit for more than one kind of downturn. |
| **Coverage** | All U.S.-listed common stocks currently eligible under the universe screen (`universe/screen.py::run_screen`; 1,730 CS eligible in the latest run per `data/signalforge.sqlite`), not a large-cap-only subset — SF1000 explicitly excludes ETFs (`docs/SF1000_SPEC.md` §1) but ranks the full CS eligible set. |
| **Update frequency** | At minimum each filing event (quarterly for most issuers, annual for some); a data product that only refreshes on its own schedule (e.g. monthly snapshot) must still preserve the true first-available timestamp of the underlying filing, not the snapshot date. |
| **Delivery format** | REST or bulk flat-file, either is acceptable — same duality already handled for price data (`reports/UNIVERSE_CAPACITY_PLAN.md` §4.7: grouped-daily REST vs. flat files, flat files currently unverified in this account). |
| **Licensing terms needed** | Internal research use only; no redistribution requirement (SF1000 output is never sold, published externally, or offered as an investable product — `docs/SF1000_SPEC.md` §0/§10). |
| **Acceptance tests before trusting it** | (1) Pick a known 2018 filing for a covered issuer; confirm the vendor's record shows the pre-restatement, as-originally-filed value with a first-available timestamp on/after the actual filing date, and confirm a query "as of 2018-06-01" (before that filing) does **not** return it. (2) Pick an issuer with a known historical restatement; confirm both the original and restated values exist as separate dated records. (3) Spot-check 5–10 names' quality/valuation figures against the issuer's own public filings for one period. |
| **Cost** | to be filled by owner — ask before purchase |

## Gap 2 — Historical constituents / index or universe membership

| | |
|---|---|
| **Purpose in SF1000** | `docs/SF1000_SPEC.md` §1 builds SF1000's universe from the *latest* `UniverseScreenRun` only. Reconstructing "what SF1000 would have held on a past date" needs to know who was *eligible* (liquid, priced, listed) at that past date — not today's active list projected backward. Without it, any backtest of SF1000's own membership-selection mechanism (§3's rank-buffer hysteresis, §4's turnover cap) is untestable against real history. |
| **Required fields** | Ticker, security type, a start/eligible-from date and an end/eligible-to date for each membership interval; enough to answer "was ticker X eligible as of date D" for any D in the backtest span, not just "is it active today." |
| **Point-in-time semantics** | Membership intervals must reflect what was **knowable at the time**, not reconstructed with hindsight (e.g. a ticker's true listing/delisting dates, not a later data vendor's cleanup pass that silently drops short-lived listings). |
| **History depth** | Same target as Gap 1 — ≥10 years preferred; validation-gate minimum is whatever span is needed to run `docs/SF1000_SPEC.md` §8's walk-forward + sealed-test windows across bull/bear/range regimes. |
| **Coverage** | All U.S.-listed common stocks, **including** every ticker that delisted, merged, or was acquired within the backtest span — this is the entire point of the gap. |
| **Update frequency** | At minimum each listing/delisting event; daily is adequate given SF1000's own monthly rebalance cadence (§3). |
| **Delivery format** | REST or bulk flat-file. |
| **Licensing terms needed** | Internal research use only; no redistribution. |
| **Acceptance tests before trusting it** | (1) Reconstruct the eligible/active universe as of a specific historical date (e.g. 2019-03-01) from the vendor's data and compare the resulting list against an independently known reference list for that date (e.g. a contemporaneous index membership list or a known set of names). (2) Confirm a ticker known to have delisted before the query date is **absent** from an "as of" query for a date after its delisting, and **present** for a query date before it. (3) Cross-check against this repo's own `SymbolContinuityMapping` case study (`reports/FB_META_CONTINUITY_INVESTIGATION.md`) — the vendor's data should show FB's delisting/rename to META at the correct date. |
| **Cost** | to be filled by owner — ask before purchase |

## Gap 3 — Delisted symbols (with delist date, reason, last price)

| | |
|---|---|
| **Purpose in SF1000** | Directly named in `docs/SF1000_SPEC.md` §7 ("Historical constituents / delisted-ticker history") and in `docs/CAPABILITY_MATRIX.md` ("Delisted-ticker history" row, status *delayed data/partial*, **(unverified)** whether `active=false` is even reachable on the current plan). Closely related to Gap 2 but distinct: Gap 2 is *membership over time*; this gap is the *per-symbol delisting record* — why and when a name left the tradeable universe, and at what price it was last marked, which is needed to close out a simulated position honestly in a historical backtest rather than letting it silently vanish. |
| **Required fields** | Ticker, delist date, reason (e.g. acquisition, bankruptcy, voluntary deregistration, exchange non-compliance), and last traded/marked price at or near delisting — needed to compute a realistic exit for a simulated holding rather than assuming a $0 or unchanged-price exit. |
| **Point-in-time semantics** | The delist date and reason must be the date/reason as they were actually determined at the time — not a later reclassification. |
| **History depth** | ≥10 years preferred; validation-gate minimum same as Gaps 1–2. |
| **Coverage** | Every U.S.-listed common stock that delisted within the backtest span — this is what makes Gap 2's membership reconstruction usable rather than survivorship-biased by construction (`universe/discovery.py` module docstring already states today's discovery is "active-only... NOT a survivorship-free membership history"). |
| **Update frequency** | Event-driven (as delistings occur); no meaningful "staleness" tolerance for a research-only backtest use case since it's applied retroactively. |
| **Delivery format** | REST or bulk flat-file. |
| **Licensing terms needed** | Internal research use only; no redistribution. |
| **Acceptance tests before trusting it** | (1) Verify a small, independently-known set of delisted names (e.g. a handful of well-documented 2015–2020 acquisitions or bankruptcies) appear with the correct delist date and reason. (2) Confirm the last-price field is populated and plausible (not zero/null) for those same names. (3) Confirm the delisted list, combined with Gap 2's membership history, reproduces a sensible "why did this name leave the eligible set" narrative consistent with `universe/screen.py`'s own exclusion-reason taxonomy (`corporate_action_continuity`, `inactive_listing`). |
| **Cost** | to be filled by owner — ask before purchase |

## Gap 4 — Point-in-time market cap

| | |
|---|---|
| **Purpose in SF1000** | The Size factor (30% target weight, §2) currently uses `UniverseTicker.market_cap` — explicitly a **current-value-only** field (`universe/discovery.py` docstring: "current values only"; `reports/UNIVERSE_CAPACITY_PLAN.md` §4.4 already flags that using it as a historical backtest input "would leak the future"). Also needed for any future move away from equal-weighting toward cap-weighting (`docs/SF1000_SPEC.md` §6, "Weighting scheme" row: cap-weighting explicitly deferred until this is licensed). |
| **Required fields** | Market capitalization (or shares outstanding + a price series sufficient to derive it) as of each historical date needed for scoring/rebalancing. |
| **Point-in-time semantics** | The value used for a rebalance dated D must be the market cap **as it was knowable on D** (shares outstanding and price as of D) — not today's shares-outstanding count applied retroactively to a historical price, which silently bakes in every subsequent buyback/issuance. |
| **History depth** | ≥10 years preferred; validation-gate minimum same as Gaps 1–3. |
| **Coverage** | All U.S.-listed common stocks in the eligible universe, including delisted names for the periods before they delisted (ties to Gaps 2–3). |
| **Update frequency** | At minimum whenever shares outstanding changes (buyback, issuance, split) plus daily price — daily granularity is sufficient for SF1000's monthly rebalance cadence. |
| **Delivery format** | REST or bulk flat-file. May be bundled with a fundamentals product (Gap 1) — **this must be separately confirmed, not assumed**, exactly as `docs/SF1000_SPEC.md` §7 already cautions ("Likely bundled... but must be separately confirmed"). |
| **Licensing terms needed** | Internal research use only; no redistribution. |
| **Acceptance tests before trusting it** | (1) Pick a name with a known historical share buyback or issuance; confirm the vendor's point-in-time shares-outstanding figure changes at the correct date rather than being flat/retroactive. (2) Recompute market cap for a small sample of dates/names from (shares outstanding as of D) × (price as of D) and confirm it matches the vendor's reported point-in-time cap. (3) Confirm that querying cap "as of" a date before a known acquisition/split shows the pre-event figure, not the post-event one. |
| **Cost** | to be filled by owner — ask before purchase |

---

## Which purchases are genuinely necessary before SF1000 can be tested honestly?

Reasoning from `docs/SF1000_SPEC.md` directly, not restated as a blanket "buy
everything":

- **Forward-only construction needs none of the four gaps.** Building
  *today's* 1,000-name basket going forward, on liquidity + market cap only,
  is already possible with entitled data — `docs/SF1000_SPEC.md` §1 says
  this explicitly ("acceptable for forward, live construction... building
  today's basket going forward never needs historical point-in-time
  membership, only today's eligibility, which the screen already provides
  honestly"). The four-factor score simply runs at 60% `data_coverage_pct`
  (§2.1) and is labelled provisional; that is a disclosure requirement, not
  a purchase requirement.
- **Any historical *backtest of membership*** — i.e., "what would SF1000
  have held on a past date, and would the rank-buffer/turnover mechanism
  have behaved reasonably" — **needs Gap 2 (historical constituents) and
  Gap 4 (point-in-time market cap) at minimum.** Without them, §1's own
  stated caveat applies verbatim: "not acceptable for backtesting SF1000's
  methodology over history... requires point-in-time membership and
  point-in-time market cap that do not exist in this system today." Gap 3
  (delisted symbols) is effectively required alongside Gap 2 — a membership
  history without delisting records cannot honestly close out a position.
- **The full 4-factor composite score** (adding Quality/Profitability and
  Valuation) **needs Gap 1 (point-in-time fundamentals)** — without it the
  score stays permanently capped at `available_weight = 0.60` and every
  output keeps carrying the "(PROVISIONAL — ranked on liquidity + market cap
  only...)" label mandated by §2.1/§10, regardless of history depth.
- **Gap 4 (point-in-time market cap) may or may not be a separate purchase
  from Gap 1** — §7 flags this as unconfirmed bundling, not something to
  assume either way.
- **None of the above is authorized spend.** Per
  `docs/PORTFOLIO_RESEARCH_ROADMAP.md` Phase C: *"Only after identifying the
  exact gap and asking the owner before purchase... This roadmap does not
  select a vendor or authorize spend."* This document inherits that rule
  unchanged — every cost line above reads **ask the owner before purchase**,
  and no vendor is named or implied as a recommendation anywhere in this
  document.

---

## Sources cited

`docs/SF1000_SPEC.md` §1, §2, §2.1, §7, §8, §9, §10 · `docs/CAPABILITY_MATRIX.md`
("Point-in-time market cap", "Fundamentals", "Historical index/universe
membership", "Delisted-ticker history" rows) · `docs/PORTFOLIO_RESEARCH_ROADMAP.md`
Phase C · `src/signalforge/universe/discovery.py` (module docstring) ·
`src/signalforge/universe/screen.py` (exclusion-reason taxonomy) ·
`reports/UNIVERSE_CAPACITY_PLAN.md` §4.4, §4.7 · `reports/FB_META_CONTINUITY_INVESTIGATION.md` ·
`data/signalforge.sqlite` (`ohlcv_daily`, `universe_member` — read-only, no secret).
