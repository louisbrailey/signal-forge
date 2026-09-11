# Disposition — `trend_continuation.medium_swing` v0.1.0 (version 3)

**Verdict: DOES NOT PASS (documented).** Status stays `EXPERIMENTAL`. No `src/` or
`tests/` file is touched. **Sealed looks consumed: 0. k stays 5** (next draw, whichever
route fires first, is **look 6** — §10.1 of the design).

Source: `docs/research/designs/trend_continuation_medium_swing.md` (design, read in full);
this record follows its §11/§12. Every number below carries its standard error (SE) and
the design section it is drawn from. Labels: **FACT** (verified `file:line` or query),
**DERIVED** (arithmetic on FACTs), **HYPOTHESIS**.

---

## 1. The verdict, precisely

`trend_continuation.medium_swing` v0.1.0 fails one gate on its lead snapshot (snapshot 3,
`universe_24_ex_meta`): gate 9 `sealed_final_test`, at **−0.0294R on 95 trades**
(design §10, §11.1). Because `StrategySealedTest` rows are locked per
`(strategy_version_id, dataset_snapshot_id)` — `_get_or_create_sealed_test` returns the
existing row as-is (`promotion.py:376-385`) — **this version can never pass on snapshot
3, however many times it is re-run** (design §4.3, §11.1).

## 2. The four-snapshot sealed ledger (design §10)

| Snap | Window | Sealed n | Expectancy | SE (iid) | z from 0 | passed |
|---|---|---|---|---|---|---|
| 1 (`universe_25_baseline_legacy`) | 2025-09-07→2026-09-07 | 98 | +0.0109R | 0.1743 | +0.063 | ✅ |
| 2 (`universe_25_baseline`) | 2025-09-08→2026-09-08 | 98 | +0.0109R | 0.1743 | +0.063 | ✅ |
| **3 (`universe_24_ex_meta`)** | 2025-09-08→2026-09-08 | **95** | **−0.0294R** | **0.1771** | **−0.166** | **❌** |
| 4 (`universe_25_meta_continuity_corrected`) | 2025-09-08→2026-09-08 | 98 | +0.0109R | 0.1743 | +0.063 | ✅ |

SEs are iid at the measured pre-sealed OOS sd of 1.7259 (design §1.3); clustering would
widen them by a factor not measured on the sealed sample and is not imputed (design §C.2,
R1). Snapshots 1/2/4 pass gate 9 but fail gate 8 (`data_quality_and_leakage`): snapshots
1–2 on META's 90 missing sessions (6.9%), snapshot 4 because `META_CONT` carries source
`continuity_bridge:1`, not `massive` (design §5.1, §10.2). **v3 has never had an
all-gates pass on any snapshot.** "Passes gate 9 on three of four snapshots" is true;
"would have been approved on three of four" is false (design §4.3).

## 3. What was tested and refuted, with SEs (design §1.2)

Every mechanism nominated by `STRATEGY_COMPLETION_MAP.md` for this family was tested on
pre-sealed data across all four snapshots:

| Hyp | Mechanism | Result | SE / evidence | Source |
|---|---|---|---|---|
| H1 | duration mismatch (11–40 bars net negative) | **FALSIFIED against its own condition** — buckets 11–40 are the *best* buckets, per-bar R +0.0393…+0.0438 | per-trade +0.5654 ± 0.2097 (11–20), +1.0791 ± 0.3919 (21–40) | §1.2 |
| H2 | target unreachable in the 40-bar leash | **FALSIFIED** — time-stop is rarest exit, 8/1,071 (0.75%), 1/319 OOS | +0.3493R ± 0.1716 | §1.2, §3.2 |
| H3 | stale volatility scale | **NOT SUPPORTED** — v3−v2 median ATR@exit/@entry | +0.0012 ± 0.0062 (0.19 SE) | §1.2 |
| H4 | volume confirmation decays | **FALSIFIED** — entry-`vol_ratio` tercile T3−T1 | +0.0085R ± 0.1193 (0.07 SE) snap 3; max +0.0390 ± 0.1179 (0.33 SE) anywhere | §1.2, §C.2 R3 |
| H5 | short-side asymmetry | **STRUCTURALLY ABSENT** — 0 short trades exist; `allow_short` never passed | — | §1.2 |
| H15 | regime conditioning | **IMPOSSIBLE BY CONSTRUCTION** — 858 bull/low + 213 neutral/low = 1,071; zero bear, zero high-vol | remaining split favours neutral: +0.2523R ± 0.1137 vs +0.1455R ± 0.0534 (0.85 SE) | §1.2 |
| H16 | entry over-extension ("chase"), 2.0 ATR threshold | **NOT EVIDENCE** | +0.1388R ± 0.1017 (1.36 SE) ALL, +0.3174R ± 0.1967 (1.61 SE) OOS; best of 15 screened conditioners | §1.2, §3.3 |
| H13 | exit-geometry local optimum | **SUPPORTED on 5 of 6 axes**; ratcheting trail axis not closed — see §5 below | §3.5 | §1.2 |

**The 15-conditioner screen** (signal-quality angle): 4 clear 2 SE in-sample and **all
four collapse to ≈0 or reverse sign out of sample** — the clearest multiple-testing
artefact the program has produced (design §3.3).

**Exits/risk levers, all closed** (design §3.5): time-stop attainable range on the
deciding OOS trade set is **+0.0071R ceiling / −0.0023R floor** on a single trade
(1 of 319 OOS); tighter-target re-pricing nets to **−0.176R (≈−2.5 SE)** at 1.0R,
worse but under 2 SE at 1.25–1.5R; all 8 non-baseline gate-5 grid cells sit below
baseline (worst +0.0933R).

## 4. The null-option evidence (design §A, §1.1)

The only coded difference between v3 and the **PAPER_APPROVED, live** v2 is one ternary
line, `time_stop_bars=40 if MEDIUM_SWING else TrendParams()`
(`trend_continuation.py:37-39`); every other parameter and all entry/exit logic is
byte-identical. There is no medium-swing-specific rule to have overfit. The
matched-pair leash result (holding to 40 bars vs 10) is **+0.0524R ± 0.0231 (2.3 SE)**
on the all-pre-sealed cut but only **+0.0326R ± 0.0439 (0.7 SE) OOS** — not evidence
under this design's own symmetric bar, so no affirmative claim is made. v3 vs v2 on
OOS: **+0.0416R against unpaired SE 0.1251 = 0.33 SE — not evidence** (design §3.1).
Evidence cutting *against* the incumbent is stated in the body, not a footnote: the
month-block OOS CI is **[−0.0191, +0.6406]** at design effect 3.04 (v2's own month-block
low is +0.0125, v5's is −0.0238 — same bar, applied symmetrically); the sealed year is
**z = −1.88 to −1.65** below the pre-sealed estimate (P(sealed mean<0)=4.2%, sealed-
informed, disposition only, R1); shipped parameters sit at the gate-5 grid maximum
(design §3.2, §3.4).

## 5. The one open lever and D4 (design §3.5, §12.2)

The exits proposal's closure claim — "no member of this family can produce evidence
even if every path resolves in its favour" — is **withdrawn**: it covered only a fixed
arm-and-lock rule. The map's lever 3 names an **ATR-trailing (ratcheting)** stop, whose
best-case upper bound (excluding the entry-bar bucket and MFE≥5R tail) reaches ≈+0.56R
against a base of +0.30R — a bound, not an estimate, but high enough that the lane is
**not closed by measurement**. **D4** is pre-registered to decide it: 6 fixed cells
(`a∈{1.0,1.5} × b=0.5 × g∈{0.5,1.0,1.5}`), read-only path-level replay on all four
snapshots, both cuts, with a five-clause bar set above the nominal 2 SE (paired ≥2 SE
on all four snapshots; ≥2 SE month-block on snapshot 3; positive in ≥3/4 folds; trade-set-
free re-run within 1 SE of paired; best cell not adjacent to a sign change — design §12.2).
If D4 clears, exactly one variant (V-A′) is authorised, capped hard at one v0.2.0 ever.
If it does not clear (the pre-registered expectation), the exits-and-risk lane closes
permanently.

## 6. Qualifying / non-qualifying re-run trigger table (design §4.3)

| Route | Qualifies when… |
|---|---|
| **A** — new snapshot, unchanged v0.1.0 | Snapshot built for reasons independent of v3 (today: W1); symbol/composition rules pre-registered before any v3 number exists on it; v3's inclusion and the intent to report whatever it returns are pre-registered beforehand; disclosed as one look for **every** version simultaneously |
| **B** — v0.2.0 with a real rule change | Motivated by a pre-sealed finding meeting all of §4.1's five-clause bar (mechanism-specific, ≥2 SE paired OOS, same sign on all four snapshots, stable IS→OOS, not post-treatment, reported with month-block); §12.3's budget/stopping rule respected. **Today the only admissible source is D4.** |

**Non-qualifying (each a live risk this program could make):** the sealed miss itself;
any duration/leash/exit-timing change (H1, H2 falsified); ATR-refresh citing at-exit ATR
(post-treatment); a `time_stop_bars` sweep; leading with snapshot 1/2/4 because gate 9
passes there (snapshot-shopping — they fail gate 8 anyway); waiting for the calendar to
roll; building a snapshot *in order to* get v3 another draw; live-paper or shadow-ledger
results in either direction (R8); re-running after a pipeline-hardening change.

## 7. D2/D3 — shadow-confirmation plan (design §11.2)

v3 is `EXPERIMENTAL`: no `PaperTrade` ledger evidence can ever accrue
(`assert_auto_simulate_allowed` raises; `plan_alerts` gates on paper-approved status).
But a shadow signal stream already exists at zero risk: `scan.py` persists both
`PASSED` and `NO_TRADE` `Candidate` rows regardless of status; v3 already holds 199
candidate rows (3 on snapshot 3/`massive`).

- **Population:** every `candidate` row, `strategy_version_id=3`, snapshot 3,
  `source='massive'`, from **2026-09-11 forward**; today's 3 rows excluded as
  pre-registration-contaminated. De-duplication fixed in advance: one entry per
  `(symbol, date)`. `NO_TRADE` drafts included (the research question is the rule's
  expectancy, not the desk's filter).
- **Simulation:** mirrors the engine exactly — fill unconditionally at next session's
  open, stop at `invalidation_level`, target at `target_level`, 40-session time stop,
  one open position per symbol, unchanged 11.0 bps cost. `entry_zone_low/high` are
  audit-only, **not** a fill condition.
- **R denominator:** `abs(entry_fill − invalidation_level)`, matching `engine.py:111`.
- **Missing data:** a trade whose next-session open is unavailable is a **gap**, never
  dropped.
- **Read-outs:** exactly two, **n-triggered only** — n≥95 and n≥220. No interim reads,
  no periodic circulation (deleted as an optional-stopping surface).
- **Arrival rate:** HYPOTHESIS ≈119/year, not a schedule input; calendar triggers are
  not used until measured on the stream itself.
- **Power:** iid SE at n=95 is 0.177R (cannot separate +0.3064R from zero); at n=220,
  0.116R. Stream's own design effect not measured, not imputed.
- **What it can never do:** promote, re-promote, or motivate a v0.2.0 (R8, R1). No code
  path re-promotes from live evidence (`health_monitor.py` is one-way down).
- **D3 implementation:** standalone read-only script, no `src/` module, no DB write, no
  API call — dated markdown+JSON under `docs/research/`.

## 8. Engine defect H14 — escalation (design §1.4, §14.1 item 3)

**FACT, reproduced independently.** `engine.py:111` computes
`risk_per_share = abs(entry_fill − sig.stop_price)`, where `entry_fill` is bar *t+1*'s
open (`:109-110`) but `sig.stop_price` was fixed off bar *t*'s close
(`trend_continuation.py:105`). When the entry bar gaps toward the stop the R denominator
collapses; when it gaps through, `abs()` inverts the risk unit and the entry-bar exit
branch books the immediately-stopped trade as ≈+1R.

| | n (bars_held=0) | share | expectancy ± SE | total R | worst trade |
|---|---|---|---|---|---|
| v3 snap 3 | 106 | 9.9% | −0.7527 ± 0.0889 | −79.79R | −6.13R |
| v2 snap 3 (**live-approved**) | 118 | 10.1% | −0.8338 ± 0.1291 | −98.39R | −12.38R |

The distortion is present *identically and proportionally larger* in the live v2. It
cannot be fixed inside the strategy (would require reading `series.open[t+1]`, which
`assert_no_lookahead` forbids), and fixing it in `engine.py` re-prices the evidence
underpinning a **live approval** without changing any `spec_json_hash`. **Escalated to
the pipeline-hardening track, not a v3 lever.** Prerequisite for any decision: the size
of the distortion — re-pricing the 106/118 entry-bar trades against a stable risk unit
(`stop_atr × ATR` at signal time), paired SE, all four snapshots — has **not** been
measured (design §14.1 item 3).

## 9. Sealed-look accounting (design §10, §10.1)

**k = 5 baseline (four locked sealed rows per version × 5 versions with sealed tests).
This disposition consumes 0 looks. k stays 5.** The next sealed draw for this family —
Route A or Route B, whichever comes first — is **look 6**, per the binding convention
(map §4.2 item 10). Route A is a look for every version simultaneously. Operator
reconciliation item: map §0.1/R2/§2.1 say "look 5" for the same event; the three program
documents must be reconciled before any final report ships (design §10.1).

## 10. What is not being claimed

Not that v3 is unprofitable; **not** that it is superior to v2 (difference is 0.33 SE);
not that it should be deleted. It stays `EXPERIMENTAL`, keeps being scanned, and remains
eligible for Route A.

## 11. Operator decisions outstanding (design §14.1)

1. Accept the null option (this record).
2. Authorise D4 (read-only, pre-sealed, zero looks, zero writes).
3. H14 — re-price v2's approval evidence, or document as a known bias? (prerequisite:
   distortion size unmeasured.)
4. W1 universe expansion (100–300 paced API calls, ~20–60 min) — not requested here.
5. Gate 7 docstring/code divergence (`config/research.py:111-113` vs `promotion.py:775`).
6. Sealed-look numbering reconciliation across three documents.
7. Map §0.4 cost correction: 0.037R → 0.057R (median) / 0.060R (mean) for this family.
8. Only if D4 clears, or by written override: authorise V-A′ as the single capped
   variant.

---

*Read-only disposition. No strategy code, configuration, database row, or gate threshold
was changed in producing this record. Source: `docs/research/designs/trend_continuation_medium_swing.md` §§0–14.*
