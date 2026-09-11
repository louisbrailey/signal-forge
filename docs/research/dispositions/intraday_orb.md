# Disposition — `intraday_orb.intraday` v0.1.0 (version 1)

**Verdict: DOES NOT OPERATE (capability finding).** This is **not** a "does not pass"
record — the strategy has never been measured past gate 0 and, under today's
entitlements, cannot be measured in a way that would mean anything live. Status stays
`EXPERIMENTAL`; no database row changes. **Sealed looks consumed: 0 (version 1 has
zero sealed rows, ever). Program k stays 5.**

Source: `docs/research/designs/intraday_orb.md` (design, read in full); this record
follows its §11 null option. All figures are pre-sealed (`2016-10-17…2025-09-07`,
source `massive`) or code arithmetic (R1: no sealed number motivates anything below).
Labels: **FACT**, **DERIVED**, **HYPOTHESIS** as in the design.

---

## 1. The distinguishing point

Versions 3, 4 and 6 fail on *evidence*. Version 1 has never been measured, and filing
it as though the rules had been tested and found wanting would be false. Its record is
a **capability finding**: five independent blocking layers, three of which the program
cannot remove by itself (design §0, §11).

## 2. Data and policy blockers (design §0, §11)

1. **Latency (blocking).** The entitled feed is `DELAYED` ≥15 min
   (`data/entitlements.py:246-257`, feed `stocks_intraday_aggs_5m`) against a 15-minute
   research bar (`config/research.py:303`). The engine signals on bar *t*'s close and
   fills at bar *t+1*'s open (`engine.py:106-109`) — the same instant as the signal.
   With delay *d* and bar size *b*, the earliest attainable live action is bar
   *t+1+ceil(d/b)* = bar *t+2* at *d=b=*15 min. **The backtest fill is exactly one bar
   early, permanently.** `LatencyCategory.REALTIME` is never set by any adapter.
2. **Cost (an order of magnitude worse than any daily strategy).**
   `risk_per_share=|entry_fill−stop_price|` and the stop is the opposite OR edge
   (`intraday_orb.py:108`), so `cost_R = 0.0011/(λ·w)` where *w* is OR width as a
   fraction of price. At **λ=1** and *w*∈[0.30%, 0.80%]: **0.37R–0.14R per round trip
   — 3.3×–8.7×** `volatility_breakout`'s 0.042R (the program's most expensive) and
   **6.3×–16.7×** `relative_strength`'s 0.022R (design §0, §8). This is an **upper
   bound** — λ>1 lowers it, but λ≥1 is not guaranteed by construction (the fill can
   print back inside the range). Break-even hit rate: **45.5% at c=0.1375R, 54.7% at
   0.3667R**, against a 40.0% random-walk baseline for a nominal 1.5:1 bracket — and
   the realised payoff ratio is strictly below 1.5.
3. **Promotion-path incapability (≥8 places, one unconditional gate-6 fail).**
   `promotion.py:744` looks up trades by `regimes.get(t.entry_date, "warmup")` against
   a `dict[date,str]`; an intraday `t.entry_date` is a `datetime`, which never matches
   — gate 6 reads **0/0/0, 100% unbucketed**, unconditionally, before any bundle fix
   (design §0 item 3, §5).
4. **EOD-only operating policy, structurally enforced in three places, contradicted
   in a fourth** — see §5 below.

## 3. The same-session regime lookahead (design §7, §0 item 5)

**FACT.** For an intraday entry inside session *D*, `ctx.regime` is derived from *D*'s
own daily close (`backtest_runner.py:183-185`; `strategies/base.py:39-40` normalises
the intraday stamp to its session date) — future information relative to a 10:15
entry. For a *daily* strategy this is harmless (signal at bar *t*'s close, fill at
*t+1*'s open — regime is strictly past); for an intraday one it is not.
`assert_no_lookahead` cannot catch it: it lives in the `regime_by_date` plumbing, not
in a feature function.

**Consequence, decisive for the budget.** The fix is behavioural → requires
`VERSION="0.2.0"` (R3/R7). **No promotion evaluation of the unchanged v0.1.0 may ever
be run** — it would spend version 1's first-ever sealed look on a rule set already
known to read the future. The first evaluable artifact is a v0.2.0, with its own §4.2
design document and its own variant budget. This disposition therefore pre-registers
**zero** evaluations and **zero** sealed looks (design §A item 1, §9).

Gate 6 is *not* part of this lookahead: it buckets descriptively on session *D* after
the fact, not a signal the strategy reads (design §2.3 reconciliation).

## 4. The gate-6 supply ceiling — configuration-dependent, not purely calendar (design §3.1, §3.2)

**FACT, recomputed independently:** crossing `label_regimes` (gate 6's labeller) with
`regime_lookup.risk_off` (the strategy's own gate), pre-sealed span:

| bucket | labelled sessions | long-tradeable (`not risk_off`) | short-eligible (`risk_off`) | long share ± SE |
|---|---|---|---|---|
| bull | 1,392 | 1,024 | 368 | 73.56% ± 1.18% |
| **bear** | **267** | **19** | **248** | **7.12% ± 1.57%** |
| range | 375 | 116 | 259 | 30.93% ± 2.39% |

Under the ladder's hard-wired **long-only** configuration (`allow_short` never passed
at `promotion.py:586`, `:386`, `sensitivity.py:148`), only **19 of 267** bear-labelled
sessions are tradeable, none after 2023-06-02, zero at any pre-sealed start ≥
2022-09-08. Under `allow_short=True` (an operator-togglable setting, passed on the
*live* scan path but not the ladder), 248 further bear sessions become eligible —
minimum viable depth shifts from 2021-09 to 2022-09. **The shortest gate-0-legal span
(start 2024-09-22) has 0 bear and 0 range labelled sessions under *either*
configuration** — option A (minimum-legal depth) is dead regardless (design §3.2, F1b).
The zero-margin quantity is **session supply**, not trade count: floor of 10 clears
only if realised entry rate exceeds **10/(19×24) = 2.19% per symbol-session** — a
parameter-free threshold independent of any synthetic rate estimate (design §5).

## 5. Four policy surfaces (design §A.2, §11 item 1)

| Surface | Behaviour | File:line |
|---|---|---|
| `approved_scope_scan.approved_horizons` | **excludes** INTRADAY | `approved_scope_scan.py:81`, policy comment `:19-22` |
| `alerts/dispatch.py` | **skips** INTRADAY | `:238, 241, 259, 265` |
| `MassiveAdapter` | declares **only** `BAR_DAILY`, `END_OF_DAY` — no intraday capability exists in any real adapter | `massive.py:86-100` |
| `ResearchConfig.enabled_horizons` | **includes** INTRADAY — contradicts the other three | `config/research.py:297-302` |

The EOD-only policy is inconsistent across surfaces — a fourth block the map's "three
blocks" framing (§2.4) does not name.

## 6. The requirements bundle B1–B10 (design §2.3, §2.4) — gate 0 must NOT ship alone

Converting gate 0 to a real data query (§2.2, R4-permissible: any real query is at
least as hard to satisfy as today's unconditional fail) is **necessary but not
sufficient**. Without the full bundle, gates 1–7 evaluate an INTRADAY strategy on
**daily** bars and read 0 trades — verified: `n_trades=0` over 53,196 daily bars.
Shipping gate 0 alone converts a truthful, self-explaining fail into zero-trade
failures that read as strategy defects.

| # | Defect (FACT) | Required |
|---|---|---|
| B1 | `intraday=`/`bar_size=` never passed at `promotion.py:586,386`, `sensitivity.py:148` | thread them through gates 1–5, 9 |
| B2 | gate 6 `datetime` vs `date` key mismatch — unconditional fail | normalise with `_as_date` before lookup |
| B3 | gate 8 validates **daily** bars for an intraday run | add `validate_intraday`, dispatch on horizon |
| B4 | leakage self-check covers 4 daily features only | add `opening_range`, `bars_since_open`, `session_bar_count` |
| B5 | `_sensitivity_plan` has no `intraday_orb` branch — gate 5 hard-fails | register the §6 grid |
| B6 | `opening_range` is `O(n²)` per symbol — one 10-gate eval ≈5.4h | precompute session boundaries; regression-test identical trades |
| B7 | `load_intraday` filters `bar_size`/`source` but not `session` | filter `session=="rth"` in the loader |
| B8 | `exposure` clamps at 1.0 for a strategy flat overnight; `ann_factor=sqrt(trades_per_year)` at ~1,500–3,000/yr | horizon-aware `exposure_days`, reported as diagnostic only |
| B9 | `ingest-intraday` CLI offers only trailing `--days`, no dated backfill | add `--since/--until` + calendar chunking |
| B10 | `evaluate-promotion --dataset` accepts 3 fixed names only | add `--dataset-key` or drive `dataset_snapshot=` from a script |

**API volume and time (design §3.3):**

| Option | Span | Sessions/sym | Rows | API calls | Paced wall-clock |
|---|---|---|---|---|---|
| A (dead, §4) | 2024-09-22→2026-09-08 | 491 | 306,384 | 48 | 9.7 min |
| B (min. viable) | 2021-09-08→2026-09-08 | 1,255 | 783,120 | 120 | 24.2 min |
| **C (parity, recommended if proceeding)** | 2016-10-17→2026-09-08 | 2,486 | 1,551,264 | **240** | **48.4 min** |

Storage: option C adds **0.53 GB** to a live 0.382 GB database → **0.91 GB (2.39×)**;
needs a maintenance window with the worker stopped. Compute: one full 10-gate
evaluation on option C at 15m is **~5.4h (4.6–6.2h)** before the B6 fix, ±15% hardware
band — pays again on every re-evaluation, variant, and sensitivity check.

## 7. Cost is the binding gate — a reversal of the pattern for every other strategy (design §0, §8)

Gate 3, not gate 4, is expected to bind. And once the program's own adopted clustering
diagnostic is applied, gate 4 is **not** the easy gate either: intraday trades are the
most calendar-clustered set in the program (up to 24 symbols entering inside the same
90-minute window of the same session). Effective independent units are ~1,337
pre-sealed sessions, not 12,800–25,700 trades; at n=5,400 and deff=2.5, the hurdle rises
to **+0.0540R to +0.0934R** (design §5 gate 4, corrected from "not power-limited — a
first for this program", which is withdrawn).

## 8. Falsification (design §4) — what would change the recommendation

| # | Claim | Status today |
|---|---|---|
| F1 | long-only span ≥2022-09-08 has 0 tradeable bear sessions | verified false on all 4 snapshots; already false under `allow_short=True` |
| F1b | shortest legal span (2024-09-22) has 0 bear AND 0 range labelled sessions | verified false on all 4 — **option A dead under every configuration** |
| F3 | cost ≥0.1375R/round trip | requires post-ingest measurement of median λ·w |
| F5 | live execution cannot reproduce the modelled fill on this entitlement | **holds today** — blocking |
| F8 | v0.1.0 evaluation is inadmissible (regime lookahead) | **holds today** — blocking |

**F1b, F5 and F8 all hold today.** Per the design's hard-stop rule, work stops
**before ingestion** whenever any of F1b/F4/F5/F8 holds — three already do.

## 9. Sealed-look accounting (design §10)

**Version 1: zero sealed rows, ever** — 7 promotion evaluations (ids 1,7,13,19,25,31,37
across all four snapshots), every one `passed=0`, verdict "NO TRADE — insufficient
evidence", all stopped at gate 0 before any sealed window opened. **Program k stays 5.**
The first admissible future evaluation (a v0.2.0, post regime-lag fix) would be
**program look 6 and version 1's own look 1**, simultaneously disclosed. Map
self-contradiction on *k* flagged (`MAP.md:69,341` say "look 5"; `:1321-1322` say
"look 6") — this record adopts k=5→look 6 per §4.2 item 10.

## 10. The explicit operator question (design, Operator questions §Q1)

**Q1 (decisive): do you want intraday operation at all, given that the policy is
currently also an entitlement fact?** EOD-only is enforced structurally in three
places and contradicted in a fourth. Relaxing the policy does **not** make intraday
operable — the entitled feed is `DELAYED` ≥15 min against a 15-minute bar regardless
of policy. **The real question is: will you buy a real-time equities entitlement?**
Until that answer is yes, the honest answer to Q1 is **no**, and this disposition is
the outcome. Absent both a real-time entitlement (A1) and an EOD-only policy change
(A2), decisions A3–A7 (API budget, database growth, v0.2.0 design authorisation,
`allow_short`, gate-7 docstring) are **not reached**.

**Re-entry condition, pre-registered (design §11):** all three, together — (i) a
**real-time** (not `DELAYED`) U.S. equities entitlement; (ii) a **measured** effective
opening-auction spread (today blocked by NBBO `403 not_authorized`); (iii) an
**operator decision** to change the EOD-only policy. Absent all three, the answer is
stable and should not be revisited per quarter.

---

*Read-only disposition. No strategy code, configuration, database row, or gate
threshold was changed in producing this record. No provider API was called. Source:
`docs/research/designs/intraday_orb.md` §§0–14 and Operator questions.*
