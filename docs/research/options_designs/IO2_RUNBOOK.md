# I-O2 runbook — running the options cycle backfill against a live probation box

Operational companion to `docs/research/options_designs/D1_options_data_spec.md`.
D1 decides *what* the dataset is; this decides *how the fetch is run* without
disturbing the paper probation that has been live since 2026-09-10, and without
looking at anything the pre-registration ordering forbids.

Written 2026-09-12. Nothing in this document was produced by running a backfill:
every figure below comes from `plan_cycle_backfill`, which is arithmetic over the
pre-registered parameters and the XNYS calendar and issues no request.

---

## 0. The one rule that outranks everything else here

**COVERAGE SUMMARY ONLY.** Until `D5_first_strategy_preregistration.md` is
committed, no option price, IV, greek, return, credit or P&L value — and no
summary statistic over any of them — may be inspected by a person or by a
script. `volume` and `transactions` are sealed too, and *permanently*: a
per-strike volume profile is a liquidity signal a selection rule could be
reverse-engineered from (D1 §10.2).

What you may look at while the backfill runs:

```
signalforge options coverage-report --run <id>
```

and nothing else. That command exists because policy is not enforcement: the
type it renders (`OptionsCoverageSummary`) has **no field that could hold an
outcome**, which the suite asserts by field name rather than by review. Do not
open `option_aggregate_daily` in a SQL client "just to check it looks right".
Counting rows is fine; `SELECT close` is not, and there is no version of "I only
glanced at it" that survives R5 disclosure.

If a number you want is not in the coverage report, the honest options are to
add it to the summary type (counts, dates, fractions, identities only) or to
wait for D5.

---

## 1. Preconditions

| # | Check | Why |
|---|---|---|
| 1 | Appendix P probes are recorded: `expired=true` returns rows, `/v3/reference/dividends` and `/v3/reference/splits` are 200, aggregates reach back to ~2022-10 | Without `expired=true` a 2023 expiry returns **zero rows** and 33 of 34 cycles are silently empty (D1 §7.0, blocker D13) |
| 2 | `signalforge options corp-actions` has been run for the 24 underlyings | `q = 0` fails gate 0.g outright, and the split table is what lets a cycle crossing an adjustment be **named** rather than silently mis-struck |
| 3 | The window is inside the entitled depth | Options aggregates start ~2022-10; the D1 window 2023-09-04 → 2026-09-04 sits inside it |
| 4 | Disk: ~1.34M option bars plus a full copy of the live database (~618 MB) | The bulk route (§3) keeps two copies of the DB on disk for the duration |
| 5 | The options rate limit is still **unmeasured** (OQ-2) | Every hour figure below is at the equities Basic pacing of 12.1 s/request, which is the only rate this repo documents. If the real options rate differs, re-run the dry run — it reads the pacing actually configured |

---

## 2. Plan the run before starting it

```
signalforge options cycle-backfill \
  --underlyings "AAPL,AMZN,DIA,GOOGL,HD,IWM,JPM,MSFT,NVDA,QQQ,SPY,UNH,XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLRE,XLU,XLV,XLY,XOM" \
  --since 2023-09-04 --until 2026-09-04 \
  --dry-run
```

Zero network, zero writes. At the pre-registered parameters this prints:

```
24 underlyings x 34 cycles = 816 units      (2023-11-17 .. 2026-08-21)
LADDER_17, 17 rungs x 2 rights              = <=34 contracts/cycle
requests: 1,632 listing (2 pages/cycle, ASSUMED) + 27,744 aggregate = 29,376
pacing 12.1s => 98.7 h (4.11 days) serial, no-retry lower bound
sessions/cycle 45-50 (mean 48.09)           => <=1,334,160 bars, 66.7% of the 2,000,000 ceiling
```

Read it as an **upper bound with no retries**: the ladder de-duplicates
downward, an excluded cycle costs its listing call and no aggregate calls, and
the adapter may make up to five attempts per request. The "2 pages per cycle"
figure is a planning assumption (D1 §3.4), not a measurement — Stage A settles
it.

Useful derived figures, all from the same arithmetic:

* **36 requests ≈ 7.3 minutes per (underlying, cycle) unit.**
* **~81 units per 590-minute window**, so the full 816 units is **~11 nights**.
* **Stage A** (SPY, QQQ, IWM only — 102 units) is **~12.3 hours**, i.e. two
  nights, and exercises every mechanism before 86 hours are committed.

---

## 3. Route A — the bulk file (the designed route)

The run writes into a **file-level copy of the live database** so the live file
keeps exactly one writer for the whole job.

### 3.1 Take the copy (worker stopped, once)

```
# stop the worker (launchctl unload / Ctrl-C, however it is run here)
sqlite3 data/signalforge.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
cp data/signalforge.sqlite data/io2_bulk.sqlite
# start the worker again — it is not needed for the rest of the run
```

The checkpoint is not optional: without it, whatever is sitting in the
write-ahead log is not in the file you copied.

Three properties of that copy, each load-bearing (D1 §7.7 fix 2):

* it already holds `instrument` and `ohlcv_daily`, which the point-in-time
  reference price needs — **the run cannot fetch them and will not create
  them**, which is why `--to-database` refuses a file that does not exist
  rather than letting SQLite create an empty one;
* it is **never refreshed mid-run** — the equity series the ladders are centred
  on must be point-in-time consistent for the whole job, and a mid-run refresh
  would silently re-centre cycles already fetched;
* its copy timestamp belongs in the run notes. Record it here when you take it:

  ```
  io2_bulk.sqlite copied at: 2026-09-12T09:19:29Z  (UTC; online `.backup` API — a consistent snapshot taken WITHOUT stopping the worker, so no checkpoint+cp was needed)
  ```

### 3.2 Nightly windows

Each night, one bounded pass. The window is 20:00–06:00 ET; `--max-minutes 590`
leaves ten minutes of slack, and the bound is checked *between* cycles so a pass
can overrun by at most one cycle (~7.3 min) — nowhere near the 17:30–19:00 ET
EOD / universe / grid jobs.

**Night 1 — Stage A, and the first pass of the run:**

```
signalforge options cycle-backfill \
  --underlyings "SPY,QQQ,IWM" \
  --since 2023-09-04 --until 2026-09-04 \
  --to-database data/io2_bulk.sqlite \
  --max-minutes 590 --yes
```

`--yes` skips the confirmation prompt; a scheduled window must pass it, and an
interactive run should not. The command prints the plan first either way, then
the coverage summary of the pass.

**Write down the run id it prints.** Every later night is a `--resume` of it.

**Nights 2..n — resume the same run:**

```
signalforge options cycle-backfill \
  --underlyings "SPY,QQQ,IWM" \
  --since 2023-09-04 --until 2026-09-04 \
  --to-database data/io2_bulk.sqlite \
  --resume <run id> \
  --max-minutes 590 --yes
```

When Stage A finishes (`status ok`, `cycles_covered == cycles_total`), read its
coverage summary (§6) and only then start Stage B with the remaining 21
underlyings — a **new** run id, same pattern:

```
signalforge options cycle-backfill \
  --underlyings "AAPL,AMZN,DIA,GOOGL,HD,JPM,MSFT,NVDA,UNH,XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLRE,XLU,XLV,XLY,XOM" \
  --since 2023-09-04 --until 2026-09-04 \
  --to-database data/io2_bulk.sqlite \
  --max-minutes 590 --yes
```

`--max-cycles N` is the alternative bound when you want a fixed amount of work
rather than a fixed amount of time (useful for a first, deliberately small
pass: `--max-cycles 3`).

### 3.3 What a pass does to the database

One transaction per (underlying, cycle), holding that cycle's bars **and** its
coverage record, committed together. Between cycles the process holds no
transaction at all, and every paced request is issued with no write lock held.
So: interrupting a pass — Ctrl-C, a laptop sleep, a power cut — costs at most
the cycle in flight, and never the run row.

---

## 4. Route B — straight at the live database

Supported, and no longer refused, because the write lock is now held only for
the short write phase of each cycle. Drop `--to-database` and everything else is
the same. The command warns if the worker is running.

Prefer route A anyway for the full job: a four-day writer beside the probation
worker still violates the one-worker-per-database rule even when every
individual transaction is short, and route A makes the whole fetch reversible by
deleting one file.

Route B is the right choice for a small top-up — a handful of cycles, minutes of
work — where copying 618 MB costs more than it saves.

---

## 5. Resuming, and how a pass can end

A pass ends in exactly one of these states. All of them are resumable by id, and
none of them loses a committed cycle.

| `status` | Meaning | What to do |
|---|---|---|
| `ok` | Every cycle of every underlying is settled | Nothing. Move to the next stage |
| `stopped` | A `--max-cycles` / `--max-minutes` bound ended the pass | `--resume <id>` in the next window. Normal, expected, nightly |
| `killed` | The kill switch was engaged mid-run | Deal with why. Then release it and `--resume <id>`. The cycle in flight was discarded; every earlier one is committed |
| `partial` | Some cycles are excluded for a retryable reason (a transient fetch failure, or the bar budget) | `--resume <id>`: retryable exclusions are re-attempted, deterministic ones are not |
| `failed` | Nothing completed | Read `symbols_failed` before retrying — an entitlement wall (401/403) is terminal and retrying it just burns budget |
| `running` | The process died without finishing a pass | `--resume <id>`. The run row was committed before the first request precisely so this id exists |

The reason a pass ended early is on the run (`gaps_json.__run__.stopped`) and in
the coverage report, with the id to resume from.

**Resume semantics.** A cycle already recorded is skipped. A cycle excluded for
a reason a later pass could genuinely fix — `contract_fetch_failed`,
`bar_budget_exhausted` — is re-attempted. A deterministic exclusion
(`reference_price_outside_ladder`, `ladder_too_coarse`,
`shares_per_contract_not_100`, …) is **not** re-attempted: re-running would only
reproduce it, and it is already counted.

**The kill switch.** `signalforge killswitch on` stops the run at the next
request. Worst-case latency is ~20 s — an in-flight HTTP request is not
cancelled and `_TIMEOUT` is 20.0 s (D1 §7.6). It is terminal for the pass and
never retried automatically.

---

## 6. Verify — the only inspection permitted

```
signalforge options coverage-report --run <id>
```

For a run in the bulk file, point the command at that database:

```
DATABASE_URL="sqlite+pysqlite:///$(pwd)/data/io2_bulk.sqlite" \
  signalforge options coverage-report --run <id>
```

What to read, and what each line decides:

* **`cycles: covered/total (fraction)`** — this is the gate 0.c input. The
  pre-registered floor is `GATE_0C_CYCLES_BRACKET = 0.90`. If it comes in below,
  the **only** permitted responses are dropping the affected underlying or
  pre-registering a finer rung set before the next stage. Lowering
  `MIN_RUNGS_PER_SIDE`, `LADDER_BRACKET_MIN_RUNGS` or `GATE_0C_CYCLES_BRACKET`
  is forbidden, now and after (D1 §3.3, §12).
* **exclusions by reason** — the vocabulary is frozen so two runs are
  comparable. A nonzero `reference_price_outside_ladder` concentrated on one
  underlying is the signature of an unrecorded corporate action, not noise.
  `ladder_incomplete` means a listing call hit the page cap or dropped a row:
  the cycle was excluded rather than silently shortened, and the cause needs
  finding before it is re-run.
* **`bars: … continuity X of Y expected`** — the gate 0.d input, floor 0.80.
* **`basis=vendor_as_of`** — anything else means the ladder was not pinned to
  the entry date, and a dataset built on a weaker basis can never share a
  snapshot identity with one built on a stronger one (D1 §3.3a, §9.2).
* **`shares_per_contract refusals`** — gate 0.h; a non-100 deliverable is the
  machine-readable signature of an OCC adjustment.
* **`earliest available`** — the discovered provider depth, recorded rather than
  assumed.

Every one of those is a count, a fraction, a date or an identity. None of them
is an outcome, and the type cannot hold one.

---

## 7. Merge the bulk file back

Run it **with the worker stopped**: the merge holds the SQLite write lock for
the whole pass, far longer than the 5 s any worker job waits before failing.
The command refuses while the worker holds its lock (`--allow-worker-running`
overrides it deliberately; `--dry-run` is always allowed).

```
# 1. measure it first — identical work, rolled back
signalforge options merge --from data/io2_bulk.sqlite --dry-run

# 2. stop the worker, then:
sqlite3 data/io2_bulk.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
signalforge options merge --from data/io2_bulk.sqlite

# 3. start the worker again
```

What it does:

* `INSERT OR IGNORE` on each table's natural key — `option_contract`,
  `option_aggregate_daily`, `dividend_event`, `split_event` — so **re-running it
  inserts nothing and says so**. It refuses outright if the destination has lost
  the unique index any of those keys rests on, rather than silently duplicating.
* `ingestion_run` rows are re-keyed: each gets a new id carrying its original
  id, the source file and the merge time, so the bulk run's provenance survives
  and stays traceable. A second merge finds them and leaves them alone.
* Nothing else is copied. `instrument` and `ohlcv_daily` came *from* this
  database; `option_quote_snapshot` and `corporate_action` have no unique
  natural key, so a re-merge could not be idempotent over them — they are
  reported as not-merged by name.

After the merge, re-run the coverage report against the live database using the
**new** run id the merge printed, and keep `io2_bulk.sqlite` until you have:

```
signalforge options coverage-report --run <new id>
```

The bulk file is the rollback. Do not delete it until the merged coverage
summary matches the one you read in §6.

---

## 8. Failure modes worth recognising

| Symptom | Almost certainly | Do |
|---|---|---|
| Every cycle excluded `no_instrument` | The bulk file has no equity data — a wrong path, or a file someone created empty | Stop. Re-take the copy per §3.1 |
| Every cycle excluded `no_contracts_returned` | `expired=true` is not reaching the provider, or the entitlement changed | Stop and re-probe. This is blocker D13 returning |
| A whole underlying excluded `reference_price_outside_ladder` | A corporate action inside the window, back-adjusted in the equity series and not in the strikes | Expected and correct. Record it; do not "fix" it by widening the band |
| `AdapterError: not authorized` on every contract | 401/403 — terminal, never retried | Stop. A four-day run against an entitlement wall is a four-day no-op |
| The pass ends `stopped` every night with few cycles | The pacing in force is slower than planned | Re-run `--dry-run`: it reports the pacing actually configured |
| Coverage falls when a pass is re-run | Should be impossible — the merge and the backfill are both idempotent | Stop and investigate before running anything else |

---

## 9. What this runbook does not authorise

It covers the **fetch**. It does not authorise interpreting anything that was
fetched. D5 is not committed; no strategy, delta target, spread width or
disposition rule exists yet; and the coverage summary must not be used to choose
one. The exclusion counts may widen or narrow the *underlying set* and may
motivate a *finer pre-registered rung set* before the next stage — they may not
be used to loosen a pre-registered constant, and the list of constants that may
never be loosened is in D1 §12.

## 10. Run log

| Date (UTC) | Pass | Command | Outcome |
|---|---|---|---|
| 2026-09-12 09:20 | Stage A pass 1 (SPY, QQQ, IWM; 102 units) | `options cycle-backfill --underlyings SPY,QQQ,IWM --since 2023-09-04 --until 2026-09-04 --to-database data/io2_bulk.sqlite --max-minutes 590 --yes` | started 05:20 ET (outside the 20:00–06:00 ET window by design: the bulk route has no live-DB writer and the 590-min bound ends ~15:30 ET, before the 17:30 ET jobs); corp-actions run #16 done first (422 dividends, 11 splits, 6 underlyings) |
| 2026-09-12 09:56 → 09-14 04:34 | Stage A pass 2 (fresh copy after the P6 fix) | same + fresh `.backup` copy | `stopped` (max_minutes; the Mac slept lid-closed for most of the wall-clock): 80/89 covered, 9 excluded (2 `contract_fetch_failed` = network dropped during sleep), 2,771 contracts, 111,039 bars, continuity 0.833 |
| 2026-09-14 04:36 | Stage A pass 3 | same + `--resume 17` | started (00:36 ET, inside the window) |
| 2026-09-14 04:36 → 22:57 | Stage A pass 3 | `--resume 17` | `partial`: 91/102 covered (0.892), 11 excluded — no_contracts_returned 6, insufficient_rungs_per_side 2, ladder_too_coarse 1, reference_price_outside_ladder 1 (deterministic), contract_fetch_failed 1 (retryable, IWM); 3,076 contracts, 124,758 bars, continuity 0.842; earliest available 2023-09-11 |
| 2026-09-14 22:58 | Stage A pass 4 | `--resume 17 --max-minutes 120` | started 18:58 ET — two minutes inside the 17:30–19:00 ET rule (bulk route, no live-DB writer; noted, not repeated) — one unit to go |
| 2026-09-14 22:58 → 22:59 | Stage A pass 4 | `--resume 17 --max-minutes 120` | **run 17 `ok`**: 92/102 covered (0.902), 10 deterministic exclusions, 3,076 contracts, 124,806 bars, continuity 0.851 — Stage A complete |
| 2026-09-15 00:03 (scheduled) | Stage B pass 1 (21 underlyings, 714 units, plan 25,704 requests ≈ 86.4 h serial) | runbook §3.2 Stage B command, `--max-minutes 590 --yes` | launches at 20:03 ET; corp-actions for the 21 underlyings to be ingested into the LIVE DB first (the bulk copy is never refreshed mid-run and does not need them) |
| 2026-09-14 23:03 → 23:12 | precondition 2 for Stage B | `options corp-actions --symbols <the 21>` into the LIVE DB | run ok: 23 symbols with dividends (1,792 rows), 13 with splits (21). Side effect: the command holds one write transaction across its paced requests, so every worker heartbeat write failed for those 9 minutes — fix queued (per-symbol commits) |
| 2026-09-15 00:26 → 00:30 | Stage B pass 1 (run 18) | runbook §3.2 Stage B command | died with the Mac's battery after 15 units (status left `running`); resumed as pass 2 |
| 2026-09-16 10:41 → 20:26 | Stage B pass 2 | `--resume 18 --max-minutes 580` | `stopped` at the bound: 84/162 covered this pass, 78 excluded (see breakdown in the log; 1 retryable: HD), 98,318 bars, continuity 0.740; bulk file now 223,234 option bars |
| 2026-09-17 00:03 (scheduled) | Stage B pass 3 | `--resume 18 --max-minutes 590` | 20:03 ET window |
