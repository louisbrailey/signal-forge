# Intraday operation — data, backfill, evaluation, and what is still unsupported

Operator reference for `intraday_orb.intraday` v0.2.0. It says exactly what the
intraday path needs, what it costs, the commands to run in order, and — the
part that matters most — what turning it all on still does **not** buy.

Design of record: `docs/research/designs/intraday_orb.md`. That design's own
recommendation is the **null option** (§11): do not build the pipeline, because
the entitled feed is delayed by at least the bar size. This document does not
overturn that recommendation. It makes the strategy *evaluable and operable* so
the decision is taken on a measurement rather than on the absence of a plan, and
it leaves every block the design names visible at the surface that enforces it.

---

## 0. The four facts to read before anything else

1. **The feed is DELAYED ≥ 15 min and the research bar is 15m**, so the delay
   equals the bar size. The backtest signals on bar *t*'s close and fills at bar
   *t+1*'s open; the earliest attainable live action is bar *t+2*'s open. **The
   modelled fill is exactly one bar early, permanently.** No code here fixes
   that — `MassiveAdapter`'s intraday capability is declared `DELAYED`, never
   `REALTIME`, and `research.intraday_policy.LATENCY_DISCLOSURE` carries the
   statement to every surface that operates on the horizon.
2. **Cost per round trip is 0.14R–0.37R** at the frozen 11.0 bps and an opening
   range of 0.30–0.80 % of price — 3.3×–8.7× `volatility_breakout`, the
   program's most expensive daily strategy (design §8). Gate 3, not gate 4, is
   the expected binding gate.
3. **v0.1.0 is not evaluable and never will be.** It read session *D*'s own
   daily close to gate an entry inside *D*. v0.2.0 lags that read by one
   completed session; the lag is validated `>= 1` so the lookahead cannot be
   reintroduced, including by a gate-5 grid point.
4. **Gate 6's bear bucket is supply-limited.** Under the pre-registered
   long-only configuration only 19 of 267 pre-sealed bear sessions are
   tradeable, none after 2023-06-02 — so the backfill must reach back to at
   least 2021-09, and 2016-10 for parity with the daily program (design §3.2).

---

## 1. Data requirements

Promotion gate 0 for an INTRADAY strategy is a real query against
`ohlcv_intraday` (`data/intraday_coverage.py`). It passes only when, for **every**
symbol and **every** NYSE session in the pre-sealed span, the store holds the
**full** expected RTH bar count:

| Requirement | Value | Enforced by |
|---|---|---|
| Bar size | exactly `research.intraday_bar_size` (`15m`) | `intraday_rth_coverage` |
| Source | the run's source filter (`massive`) | same |
| Simulated rows | never counted, at all | same |
| Session | `rth` only | same, plus `PriceSeries.load_intraday` |
| Session coverage | **100 %** of exchange sessions | same |
| Bars per session | **100 %** of the calendar's own count — 26 at 15m on a full day, 14 on an early close | `expected_rth_bars` |
| Pre-sealed span | ≥ `MIN_PRESEALED_DAYS` (350) before the sealed year | the shared window check, which INTRADAY now falls through to |

The 100 % bars are **frozen**. A coverage tolerance that can later be relaxed to
obtain a pass is a latent threshold, and this backfill is operator-controlled end
to end, so there is no legitimate reason to accept less than the calendar says
existed. A gate-0 failure reports which symbols are short and by how much
(absent sessions, short sessions, off-calendar rows) and returns the same **NO
TRADE** verdict as before — the ladder never reports gates 1–10 computed on data
it has just declared unfit.

Storage: ~1.55M rows for the full ten-year 24-symbol backfill, ≈ **0.53 GB**,
taking a 0.382 GB database to ~0.91 GB (**2.39×**). That is a live SQLite file a
paper probation and a background worker use — run the backfill in a maintenance
window with the worker stopped, or into a sidecar copy.

---

## 2. API volume

Recomputed from the adapter's own limits, not taken from the design's estimate.
The provider caps one aggregates response at 50,000 rows and the adapter
**rejects** a paginated response rather than silently truncating it, so the span
is split into calendar-year chunks:

| Item | Value |
|---|---|
| Universe | 24 symbols (snapshot 3, ex-META) |
| Span | 2016-10-17 → 2026-09-08 = **2,486 exchange sessions** |
| Chunks | 11 calendar years per symbol (2016 part, 2017–2025, 2026 part) |
| **Provider requests** | **264** |
| Pacing | 12.1 s (Basic plan, 5 req/min) |
| **Wall clock** | **≈ 53.0 min** (263 gaps × 12.1 s) |
| Max rows per request | 16,192 — ~3× headroom under the 50,000 cap even if the provider returns extended hours |
| Rows stored (RTH only) | **1,545,216** |

The design estimated 240 calls / 48.4 min by assuming exactly ten chunks; eleven
calendar-year chunks are needed for a span that starts in October and ends in
September. `intraday_request_plan()` refuses any chunk size that could exceed
the row cap, and `--dry-run` prints the plan for the exact arguments you intend
to run.

---

## 3. The exact backfill command

Run it against a **scratch copy first**. Nothing below may touch
`data/signalforge.sqlite` while the worker is running.

```bash
cd /Users/louisbrailey/signal-forge

# 0. Scratch database (read-only backup of the live file).
sqlite3 "file:data/signalforge.sqlite?mode=ro" ".backup $TMPDIR/scratch-intraday.sqlite"
export DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-intraday.sqlite"

# 1. Cost it before spending any quota.
.venv/bin/signalforge ingest-intraday --bar-size 15m \
  --since 2016-10-17 --until 2026-09-08 --dry-run

# 2. Gate 0 must STILL FAIL here — 0 rows in ohlcv_intraday. This is the
#    regression that proves the new query is not a fabricated pass.
.venv/bin/signalforge evaluate-promotion --strategy intraday_orb \
  --snapshot-key research_24_intraday15m_2016_2025 \
  --dataset ex_meta --since 2016-10-17 --until 2026-09-08

# 3. THE BACKFILL — 264 paced requests, ~53 min, ~1.55M RTH rows.
.venv/bin/signalforge ingest-intraday --bar-size 15m \
  --since 2016-10-17 --until 2026-09-08 \
  --symbols "$(.venv/bin/python -c 'from signalforge.config import get_settings; print(",".join(get_settings().research.universe))')"

# 3b. If it ends "partial", resume it — symbols already OK are not re-fetched.
.venv/bin/signalforge ingest-intraday --bar-size 15m \
  --since 2016-10-17 --until 2026-09-08 --resume-run-id <id printed above>

# 4. Re-run step 2. Gate 0 now passes only if coverage is 100%; if it fails it
#    names the symbols and sessions still missing. DO NOT relax the coverage
#    requirement to obtain a pass — it is pre-registered and frozen.
```

Notes that matter operationally:

- **Symbols**: `--symbols` above uses the configured universe. For the
  pre-registered 24-symbol ex-META set, pass that list explicitly and use the
  same list for `--snapshot-key`.
- **RTH only**: pre/post bars are dropped at ingest and again at load. They are
  counted in `bars_skipped`, never silently discarded.
- **No feed-status row.** A backfill deliberately does not register a
  `BAR_INTRADAY` `DataFeedStatus` row. `alerts.dispatch` blocks **all** candidate
  and briefing alerts while **any** feed row is stale, so a one-off backfill
  registering a feed nothing afterwards refreshes would silently switch the live
  EOD probation's alerts off 36 hours later. If you ever start a recurring
  intraday poll, that poll registers the feed — and you must then keep it fresh.
- **Concurrency**: one short write transaction per symbol, committed, so the
  SQLite write lock is released before each paced fetch. Still: one worker per
  database, and stop the worker for a run of this size.

---

## 4. Evaluating with `--snapshot-key`

```bash
.venv/bin/signalforge evaluate-promotion --strategy intraday_orb \
  --snapshot-key research_24_intraday15m_2016_2025 \
  --dataset ex_meta --since 2016-10-17 --until 2026-09-08
```

**Use the key. Always.** An unkeyed evaluation resolves its `DataSnapshot` by
exact symbol-set match among reusable snapshots — so an intraday run on the
24-symbol ex-META universe would silently attach to **snapshot id 3**, the daily
snapshot both live PAPER_APPROVED strategies sit on. Same symbols, entirely
different data, and gate 9's sealed test keyed to the wrong dataset.

Proposed key: **`research_24_intraday15m_2016_2025`** — it names the symbol
count, the bar size and the span, none of which the `DataSnapshot` table has a
column for. A key whose stored symbol set differs from the one requested is
refused, not reinterpreted.

**Sealed-look accounting.** `intraday_orb` has **zero** sealed tests; the
program's baseline count is **k = 5**. A v0.2.0 evaluation that reaches gate 9
is therefore **program look 6 and version 1's own look 1**, and both numbers must
appear in any report of it. The CLI prints the disclosure on failing evaluations
too, including "no sealed look taken by this evaluation".

Before scoring any gate, run the design's §12.7 post-ingest diagnostics —
measured λ·w, measured entry rate, session-block `deff`, single-pass wall clock,
and the trade count on the 19 long-tradeable bear sessions. **These are not
implemented here** (see §6).

---

## 5. Turning operating mode on

One flag, `research.intraday.operating_enabled` (default **false**), consulted
by every surface through `research/intraday_policy.py`:

```jsonc
// research_overrides AppSetting, or the Settings page
{"intraday": {"operating_enabled": true}}
```

| Surface | Flag OFF (default) | Flag ON |
|---|---|---|
| `approved_scope_scan.approved_horizons` | INTRADAY excluded | INTRADAY included, on its approved snapshot |
| `alerts.dispatch` | INTRADAY candidates skipped | INTRADAY candidates dispatched |
| scheduler | no intraday job registered | `intraday_scan` every 15 min (the bar size) during RTH |
| `enabled_horizons` (research scan) | includes INTRADAY — unchanged | includes INTRADAY — unchanged |

The fourth row is the one that looks inconsistent and is not: the routine
research scan has always covered the horizon. That is *research*, and with no
intraday bars it produces nothing. The other three are *operation*, and they now
share one switch. `policy_surfaces(cfg)` prints all four at once.

The flag is **not** in `SCOPE_HASH_FIELDS`. It changes no rule, threshold,
universe or cost — the same strategy on the same dataset produces the same
signals either way — and hashing it would have moved `config_hash` the moment
the section appeared, putting both live approvals out of scope for nothing.
`intraday_bar_size` and `enabled_horizons`, which *do* shape signals, remain
hashed.

Guards on the scheduled scan, all of them already in place: the kill switch
(`guarded`), the worker lock (only the lock-holding process runs jobs), the
`_EOD_UPDATE_LOCK` (never overlaps the post-close ingest + rescan), and the
exchange calendar (a no-op outside RTH, on holidays, and after an early close).
The job **scans only** — it never ingests, so it can only read bars the operator
has already backfilled, which on a delayed feed are at least one bar old.

Turn it off by setting the flag back to false and restarting the worker (the job
list is read at scheduler build time).

---

## 6. What remains unsupported

Implemented here: the v0.2.0 lag, gate 0, `intraday`/`bar_size` threading
through gates 1–5 and 9 (B1), gate 6's date normalisation (B2), the gate-5 grid
(B5), the RTH loader filter (B7), the dated backfill CLI (B9), `--snapshot-key`
(B10), and the operating mode. Still open, in the design's own numbering:

- **B3 — `validate_intraday`.** Gate 8 still runs `validate_daily` for an
  INTRADAY strategy. It therefore validates the *daily* bars of the universe and
  says nothing about the intraday bars actually traded: a gate-8 pass on an
  intraday run is **vacuous and must be read as such**.
- **B4 — intraday leakage self-check.** Gate 8's `_leakage_self_check` still
  covers the daily feature set only. `opening_range`, `bars_since_open` and
  `session_bar_count` are not exercised by the ladder. (The regime lookahead —
  the one that actually mattered — is fixed and directly tested.)
- **B6 — the O(n²) opening range.** `features/intraday.opening_range` rescans
  the session from index 0 for every bar, so one 24-symbol pass over ten years
  of 15m bars is ~32 min and a full 10-gate evaluation ~5.4 h. Everything still
  works; it is slow. Treat B6 as a prerequisite before iterating.
- **B8 — horizon-aware exposure.** `portfolio_metrics` sums `bars_held` into
  `exposure_days` and clamps at 1.0, so gate 7 reports ~100 % exposure for a
  strategy that is flat overnight, and annualises a ~1,500-trade year against
  SPY buy-and-hold. Gate 7's construction is an open operator question.
- **§12.7 post-ingest diagnostics** — λ·w, entry rate, session-block `deff`,
  wall clock, bear-session trade count. Not implemented; the design requires
  them before any gate is scored.
- **Live intraday ingest.** There is no recurring intraday poll. Operating mode
  scans what the backfill stored; it does not keep it current.
- **Real-time execution.** Unentitled, and the NBBO quotes needed to calibrate
  an opening-auction spread return `403 not_authorized`, so the 5.0 bps spread
  assumption can be neither validated nor calibrated for the one time of day
  this strategy trades.

Re-entry conditions for the design's null option are unchanged and all three are
still required together: a verified **real-time** equities entitlement, a
**measured** effective opening-auction spread, and an operator decision to
operate intraday. The flag in §5 implements the third; it does not substitute
for the first two.
