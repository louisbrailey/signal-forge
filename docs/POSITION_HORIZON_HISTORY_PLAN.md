# POSITION-Horizon History Plan

**Status: plan only — no backfill has been run, no config changed, no code
changed.** This document reasons entirely from files already in the repo. It
does not run the app, does not touch `.env`, and does not print any secret.
Every date-range/session/storage estimate below is arithmetic on measured
facts; anything not directly measurable from a file in this repo is marked
**(unverified)**.

---

## a) Why the POSITION horizon currently scans 0

The proximate cause is **not** insufficient history. It is a strategy-registry
gap:

1. `src/signalforge/research/strategies/__init__.py::default_strategies()`
   (lines 43–50) instantiates exactly one relative-strength strategy:
   `RelativeStrength(Horizon.MEDIUM_SWING)` (line 49). It never instantiates
   `RelativeStrength(Horizon.POSITION)`, and no other strategy class in that
   list (`TrendContinuation`, `MeanReversion`, `VolatilityBreakout`,
   `IntradayORB`) supports `Horizon.POSITION` either.
2. `src/signalforge/research/strategies/relative_strength.py` (lines 43,
   36, 51) shows the `RelativeStrength` **class itself already supports**
   `Horizon.POSITION` — its constructor explicitly validates
   `horizon in (Horizon.MEDIUM_SWING, Horizon.POSITION)` and it already has a
   `time_stop_position: int = 126` parameter distinct from the swing time
   stop. The class is ready; it is simply never *called* with
   `Horizon.POSITION` anywhere in `default_strategies()`.
3. `src/signalforge/research/scan.py::_strategies_for()` (line 109) filters
   `default_strategies()` down to strategies whose `spec().horizon` matches
   the requested horizon. For `Horizon.POSITION` this list is **empty**.
4. `run_scan()` (lines 175–178) checks `if not strategies:` immediately after
   that filter and, when true, loops over the *entire* universe and excludes
   every symbol with `Exclusion.NO_STRATEGY` (`"no_strategy_for_horizon"`),
   then returns — **before any per-symbol history, liquidity, or event check
   ever runs.**

That is exactly the measured shape of the 2026-09-09 run: **scanned 0,
excluded 2,312, 100% of the exclusion reason is `no_strategy_for_horizon`**,
not `missing_or_short_history`. Extending the bulk archive's date range, by
itself, **will not change this number** — a POSITION strategy must first be
registered in `default_strategies()` (a code change, out of scope for this
document and not made here). This plan is about what the *history* side
additionally needs once that registration gap is closed, per your framing of
this as a history-history document; it is not a fix for the registration gap
itself.

**Once registered, does POSITION need more history than the scan already
loads?** No, for the scan step specifically. `run_scan()` (line 193) loads
`start = end - timedelta(days=365 * 6)` — a 6-year window — for every
horizon, and the shared minimum is `_MIN_HISTORY = 220` bars (line 36).
`RelativeStrengthParams` (lines 30–38) needs only a 100-session SMA window
and a 63-session lookback — both comfortably inside 220 bars and inside the
6-year window already used for MEDIUM_SWING, which scans successfully on the
same data today. So: **register the strategy and POSITION scanning works on
the data that exists right now.** The history gap described below is a
separate, additional need — for the *promotion pipeline* to evaluate a
POSITION strategy version honestly, not for the scan to stop returning 0.

---

## b) Proposed date-range options for the bulk archive

Current state (measured 2026-09-09): `BulkFile` archive has **420 sessions**,
2025-01-03 → 2026-09-08, **152 MB** gzip on disk (0.362 MB/session), and
**971,699** normalized rows for the 2,312 eligible symbols (`UniverseMember`,
latest `UniverseScreenRun`, CS 1,730 + ETF 582) ≈ 272 MB (280 B/row,
`src/signalforge/universe/pipeline.py` `_NORMALIZED_BYTES_PER_ROW = 280`,
line 45). Storage budget is `UniversePipelineConfig.max_storage_bytes`
(`src/signalforge/config/research.py`, line 169) = `5 * 1024**3` bytes =
**5 GiB (≈5.37 GB decimal)** — not a round 5,000,000,000-byte figure.

Session counts below are **(unverified)** to the exact trading day: no
authoritative NYSE holiday calendar was consulted. They are estimated by
applying the empirically measured ratio from the existing archive
(420 sessions / 438 calendar weekdays = 0.959) to the weekday count of each
proposed range — the same approach implicitly used by
`reports/UNIVERSE_CAPACITY_PLAN.md` §3's "2,520 sessions" figure for a
10-year span, which this table's Option 2 reproduces almost exactly.

| | Option 1 — extend to 2020-01-02 | Option 2 — extend to 2016-09-12 |
|---|---|---|
| Rationale | Includes the 2020 COVID crash, the 2022 bear market, and the 2023–25 bull run in one archive | Aligns with the existing 25-symbol research history (`ohlcv_daily`, `source='massive'`: measured 2016-09-12 → 2026-09-04, 61,878 rows, 26 instruments — read directly from `data/signalforge.sqlite`) |
| Total sessions (archive start → today) | ≈**1,680** | ≈**2,510** |
| New sessions to fetch (beyond the 420 already archived) | ≈**1,260** | ≈**2,090** |
| Requests | 1 grouped-daily request per **new** session (`GET /v2/aggs/grouped/locale/us/market/stocks/{date}?adjusted=true`, `universe/bulk.py::GroupedDailyClient.fetch_grouped`) | same |
| Wall time at 1 req/s | ≈**0.35 h** (~21 min) | ≈**0.58 h** (~35 min) |
| Wall time at the repo's conservative 5 req/min (`reports/REAL_DATA_STATUS.md:38`, `src/signalforge/config/settings.py:52`) | ≈**4.2 h** | ≈**7.0 h** |
| Gzip archive, total on disk | ≈**608 MB** (net new ≈456 MB) | ≈**909 MB** (net new ≈757 MB) |
| Normalized rows, current 2,312 eligible symbols (×280 B) | ≈**1.09 GB** | ≈**1.63 GB** |
| Normalized rows, hypothetical 1,000-name SF1000 set (×280 B) | ≈**0.47 GB** | ≈**0.70 GB** |
| Total (archive + 2,312-symbol normalized) vs 5 GiB budget | ≈1.58 GiB → **31.6%** | ≈2.36 GiB → **47.2%** |
| Total (archive + hypothetical 1,000-symbol normalized) vs 5 GiB budget | ≈1.01 GiB → **20.1%** | ≈1.50 GiB → **30.0%** |

Both options stay well inside the 5 GiB budget even stacked with a
1,000-name SF1000 archive sharing the same bulk files (the bulk archive is
market-wide and shared across any symbol subset — only the *normalized* row
count is symbol-scoped).

**Walk-back window.** `universe/bulk.py::backfill` walks back day by day from
the last completed session; its walk-back limit now scales with the
requested `--sessions` (`max(3 years, sessions × 1.6 + 30 calendar days)`),
so both options below are executable as budgeted, resumable runs — no
prerequisite code change remains. (Earlier drafts noted a fixed ~3-year
`_MAX_LOOKBACK_DAYS` cap; that has been removed.)

---

## c) Validation benefit — what becomes computable

Two separate gate systems are affected differently:

- **`QualityThresholds`** (`config/research.py`, scan-time, per-candidate):
  `min_oos_regimes = 2`, `min_trades_per_regime = 10` — already satisfiable
  on data that exists today for any horizon that has a registered strategy.
- **`PromotionThresholds`** (`config/research.py`, `research/promotion.py`,
  strategy-*version*-level, the only path to `PAPER_APPROVED`) — this is
  where more history matters:
  - Gate 0 (window-length floor): `MIN_PRESEALED_DAYS = ceil(200 *
    365.25/252) + 60 ≈ 350` calendar days (`promotion.py` line 94, built on
    `backtest/regime.py`'s `TREND_LOOKBACK = 200`-session warmup), plus
    `sealed_window_days = 365` (1-year sealed OOS window). **Absolute floor:
    ≈715 calendar days (~2 years)** of history before `evaluate_promotion`
    can even attempt gates 1–8 — below this it hard-fails at gate 0 with "window
    ... is too short."  Neither option is anywhere near this floor; both
    clear it easily.
  - Gate 1 (`min_walkforward_folds = 4`) and Gate 2 (`min_oos_trades = 30`):
    more sessions and more symbols (2,312 eligible today) both increase the
    odds a POSITION strategy — which trades far less often than SHORT/MEDIUM
    SWING given its 126-session hold and 5%-excess-return threshold — clears
    the trade-count bar inside a given fold.
  - **Gate 6 is the one that actually needs the longer history**:
    `min_regimes_covered = 3` (bull **and** bear **and** range-bound, not
    "2 of 3"), each needing `min_trades_per_regime = 10`. Regime labels come
    from `backtest/regime.py::label_regimes`, which needs **200 prior
    trading sessions of warmup** (≈290 calendar days) before it emits a real
    trend label at all — everything before that is labelled `"warmup"` and
    excluded from gate 6's buckets (`research/promotion.py::_oos_regime_coverage`).
  - **This is why Option 1 does *not* actually buy credit for the 2020
    COVID crash**, even though its raw price data would be archived: the
    crash (Feb–Mar 2020) falls only ~48 calendar days after Option 1's
    2020-01-02 archive start — far short of the ~290-day warmup the SMA
    trend label needs. Under Option 1, everything through roughly October
    2020, crash included, is `"warmup"` for gate-6 purposes. Option 1 *would*
    still credibly cover the 2022 bear market and the 2023–25 bull run as
    usable gate-6 evidence (both start well after the archive's own
    warmup period ends), and there are likely range-bound stretches in
    between — plausibly enough to satisfy the "3 distinct regimes" gate on
    its own, without the crash.
  - **Option 2 additionally captures the 2020 crash as usable regime
    evidence** (its ~290-day warmup consumes late 2016/early 2017, long
    before 2020), giving the promotion evidence a genuinely different kind
    of stress period — a sharp multi-week shock — on top of 2022's slower
    grinding bear and the 2023–25 bull. That is a materially broader test of
    whether a POSITION strategy's edge survives structurally different
    downturns, not just one flavor of bear market.
  - Whether either option actually *produces* 30+ OOS trades and 10+ trades
    per regime for a real POSITION strategy is **(unverified)** — that
    requires running the pipeline, which this plan deliberately does not do.
  - The project's own default evaluation window (`research/promotion.py`
    line 1031, `evaluate_all_default_strategies`: `start = end -
    timedelta(days=365 * 10)`) is 10 years — i.e., the codebase's own
    convention for "evaluate a strategy honestly" already assumes something
    close to Option 2, not Option 1.

---

## d) What neither option fixes

Extending the bulk archive's date range changes only *how much* history is
archived — it does not change *what kind* of history it is. Every one of
these limitations, already documented elsewhere in this repo, remains true
at any archive length:

| Limitation | Where it's already documented |
|---|---|
| **As-of adjustment, not point-in-time.** Split/dividend factors are applied as of the *fetch* date, not as they stood on each historical date. | `src/signalforge/universe/normalize.py` line 5, `ASOF_FLAG = "asof_adjusted_not_pit"` (line 28); `docs/SF1000_SPEC.md` §1 |
| **Survivorship bias.** Discovery (`universe/discovery.py::refresh_reference`) is active-tickers-only; a delisted name is invisible at any archive length. | `universe/discovery.py` module docstring: "NOT a survivorship-free membership history"; `src/signalforge/db/models/universe.py` lines 7–8, 83–86 (`adjustment_basis`/`survivorship_note`) |
| **No delisted names in the archive at all**, at any date range — extending back to 2016 does not retroactively add names that delisted between 2016 and today. | same discovery docstring; `docs/CAPABILITY_MATRIX.md` "Historical index/universe membership" and "Delisted-ticker history" rows (both "requires new data entitlement" / **(unverified)**) |
| **Flat-file access is unverified** (measured `403` with the current REST key per the lead's brief) — the grouped-daily REST path is the only confirmed bulk mechanism. | `reports/UNIVERSE_CAPACITY_PLAN.md` §1, "Flat files ... HTTP 403 with the REST key" |
| **How far back grouped daily is actually entitled is itself (unverified)** — the capacity plan *assumed* 10 years (2,520 sessions) by analogy to the per-symbol REST entitlement; nothing in this repo has probed the grouped-daily endpoint at a historical date to confirm it, as opposed to the near-term dates the existing 420-session archive already covers. | `reports/UNIVERSE_CAPACITY_PLAN.md` §4.7; lead's brief |

Net effect: **POSITION backtests run over the extended bulk universe remain
provisional** for the same reasons Module A's 25-symbol universe and
Module B's SF1000 spec already carry that label
(`docs/SF1000_SPEC.md` §1, §7) — a longer archive improves *regime coverage*
for the promotion gates, it does not resolve *point-in-time correctness* or
*survivorship*.

---

## e) Not started

**Nothing in this plan has been executed.** No config value has been
changed, no CLI command has been run, no backfill code path has been exercised beyond the 420 sessions already
archived (the former fixed ~3-year `_MAX_LOOKBACK_DAYS` walk-back limit in
`universe/bulk.py` now scales with the requested `--sessions`, so both
options are executable when an operator chooses to run them). The command that **would** run a
budgeted, resumable extension, once an operator decides to proceed, is:

```
signalforge universe update --sessions <N> --max-minutes <M>
```

(`src/signalforge/cli.py`, `universe_app.command("update")`, lines
1712–1737 — `--sessions` overrides `UniversePipelineConfig.backfill_sessions`,
`--max-minutes` overrides `max_runtime_seconds`; the run is resumable and
idempotent, skipping any session already archived). This document does not
instruct anyone to run it, and does not set a value for `N` or `M` — that is
an operator decision, to be made after reviewing the cost/benefit in (b)–(d) above.
