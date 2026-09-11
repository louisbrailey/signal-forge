# Design — `trend_continuation.medium_swing` v0.1.0 (version 3)

**Synthesis of three proposals (null option / exits & risk / signal quality & regime) and four
judge verdicts, into one design.**
Date: 2026-09-10. Structure: the eleven mandatory sections of `STRATEGY_COMPLETION_MAP.md`
§4.2, preceded by the path decision and the judge-defect disposition, and followed by the
consolidated pre-registration block, the implementation/validation checklist, and the
operator decision list.

---

## 0. Provenance, conventions, and the R1 disclosure

**FACT — everything in this document is read-only.** No file under `src/` or `tests/` was
touched. `data/signalforge.sqlite` was opened only with `mode=ro` `SELECT`s (to re-verify the
sealed ledger and the disputed line citations); no writing entry point was run, no scratch
copy was needed, no provider API was called, no service was restarted. **No
`StrategySealedTest` row and no `StrategyPromotionEvaluation` row was created: verified
read-only, `strategy_sealed_test` = 20 rows, `strategy_promotion_evaluation` = 42 rows,
`strategy_version` = 6 rows, `paper_trade` = 0 rows.**

**Labelling.** Every claim is **FACT** (verified by `file:line`, a query, or a reproduction),
**DERIVED** (arithmetic on FACTs, derivation shown), or **HYPOTHESIS**. Every estimate carries
a standard error. **A difference under 2 SE is not evidence** and is not treated as one
anywhere below — including where the difference favours the incumbent.

**SE convention (a correction this synthesis imposes on all three proposals).** Two
re-pricings of the *same* trade list are compared with the **paired** SE (sd of the per-trade
difference ÷ √n); two *disjoint* groups with the unpaired SE; a *bound* (a best- or worst-case
re-pricing that is physically unreachable) is reported **in R units with its construction
stated, never in SE units**, because dividing a deterministic bound by a sampling SE
manufactures a significance for an event of probability zero. Two of the three proposals
violated this in opposite directions; see §C.

**Clustering convention.** Every OOS figure is reported iid **and** with its month-block
counterpart where one has been measured on that sample. A design effect measured on one
sample (v3's OOS deff = 3.04, `clustered_bootstrap_all.md` §3.1) is **not** transported to a
different sample (e.g. the 95-trade sealed year) as if it were a constant; where a clustered
figure has not been computed on the sample in question, that is stated rather than imputed.

**R1 disclosure — where sealed numbers appear in this document.** R1 permits sealed numbers to
inform *disposition* (ship / stop / document a fail) and forbids them from motivating any
parameter, filter, entry, exit or universe choice. This design's recommendation **is** a
disposition: change nothing. Sealed numbers appear, and are marked inline as
*(sealed-informed — disposition only, R1)*, in: §1 (framing), §5 (gate 9 row), §8 (the
cost-vs-shortfall comparison), §10 (the ledger), §11 (the report contents), and §12.5. **No
sealed number motivates any change to `src/`, because this design makes none, and no sealed
number is used to set any threshold, bar, or criterion in §4 or §12.** The sections that
constrain future design — §3, §4, §6, §12 — are built exclusively from pre-sealed data.

---

## A. The chosen path

### A.1 Decision

> **Chosen path: the NULL OPTION — a documented "does not pass", with an empty change set
> under `src/` and `tests/`, k unchanged at 5 — plus one pre-registered read-only closure
> diagnostic (D4) for the single exits-and-risk lever that measurement has *not* actually
> closed, and the escalation of one engine defect (H14) to the pipeline-hardening track.**

All three independent angles arrived at "no change" from three different directions, and no
judge disputed the disposition. What the judges did dispute, correctly, is several of the
*arguments* used to get there — including one closure claim that is false. That is the
substance of this synthesis: the verdict survives, three of its supporting claims do not, and
one lever that was declared closed must be re-opened as a pre-registered read-only diagnostic
before the lane can honestly be shut.

### A.2 Why the null, stated as a claim about markets rather than a shrug

FACT: the only coded difference between v3 and the **PAPER_APPROVED, live** v2 is one line —
`TrendParams(time_stop_bars=40) if horizon is Horizon.MEDIUM_SWING else TrendParams()`
(`src/signalforge/research/strategies/trend_continuation.py:37-39`, ternary literal on `:38`;
verified). Every other parameter is byte-identical (`:21-29`) and entry/exit logic is shared
verbatim (`:85-133`). **There is no medium-swing-specific rule to have overfit and no
medium-swing-specific defect to fix.** Every mechanism the map nominated has now been tested
on pre-sealed data on all four snapshots and is dead, unsupported, or structurally impossible
(§1, §3). The one gate v3 fails is a sign test at a threshold of exactly zero, read at a
sample size where it cannot locate the centre of the distribution it is testing.

### A.3 What was grafted from the runners-up, and on what evidence

| Grafted from | What carries over | Why it carries (evidence + falsification survive) |
|---|---|---|
| exits & risk | Items C–G: the MFE/MAE distributions, the time-stop attainable-range arithmetic, the exact tighter-target re-pricing, the gate-5 grid reading, and the H14 engine finding | All are pre-sealed re-pricings of already-shipped configurations, reproduced independently by a judge to the digit, with their own pre-registered kill conditions (F1–F4). Corrections in §C apply. |
| exits & risk | **D4** — the trailing-family closure diagnostic, *inverted*: the proposal claimed the family was closed; the judges refuted that, so the same machinery becomes a pre-registered open diagnostic rather than a closure claim | The refutation is itself pre-sealed and reproducible; the falsification criterion transfers cleanly once re-expressed against a realised path-level replay instead of an unreachable bound (§12.2) |
| exits & risk | Escalation of **H14** (engine entry-bar risk-unit collapse) to the hardening track with an operator question | Reproduced by both exits judges from code and data; out of scope for a v3 strategy change on three independent grounds (§1.4) |
| signal quality & regime | **H15** (regime axis saturated: 0 of 1,071 pre-sealed trades enter in any bear or high-vol `RegimeState`), the **H4 falsification**, and the **15-conditioner screen with its four in-sample survivors that reverse out of sample** | Measured on all four snapshots and both cuts, with SEs; the screen's disclosure is the strongest multiple-testing artefact the program has produced and constrains every future proposer |
| signal quality & regime | The **per-instance version** construction (`self.version` as a function of behaviour) as the mandatory shape of any future v0.2.0 in this family | It is the only one of the three proposals that correctly diagnosed the module-level `VERSION` trap; the exits proposal's diff would have broken the live v2 (§C, defect E-L2) |
| null option | The §4.3 **qualifying vs non-qualifying re-run trigger table**, the five-condition evidentiary bar (made symmetric per §C), and the structural finding that v0.1.0 can **never** pass on snapshot 3 | Verified from code: `_get_or_create_sealed_test` returns the locked row (`promotion.py:376-385`), `evaluate_promotion` pins the window from it (`:545-557`), `passed = all(gates)` (`:922`) |
| null option | The shadow-confirmation plan **D2/D3**, rebuilt to the judges' specification | The structural insight (v3 is EXPERIMENTAL, so `PaperTrade` evidence is impossible, but a status-blind scan already persists candidates) is verified and is the only legitimate forward-evidence channel |

### A.4 What was **not** grafted, and why

- **SR-1 (the no-chase entry filter) is not adopted, in any form.** At its own pre-registered
  threshold of 2.0 ATR — not the p67 cut its tables were computed at — the retained-minus-
  suppressed contrast is **+0.1388R ± 0.1017 (1.36 SE)** all-pre-sealed and **+0.3174R ±
  0.1967 (1.61 SE)** OOS on snapshot 3. Its mechanism sub-test fails in the wrong direction.
  Its gate-7 Sharpe is non-monotone with a spike at exactly the chosen threshold (1.082 /
  **1.190** / 1.044 across 1.5 / 2.0 / 2.5 against a baseline of 1.156 — both neighbours are
  *worse than making no change at all*). It creates two zero-margin gates that do not exist
  today. And under v3's own measured month-block design effect its gate-4 lower bound is
  **−0.0145R**, a fail. It is the best of fifteen screened conditioners, which is a reason to
  discount it further, not to round it up.
- **V-A as specified (a one-shot profit-armed static lock) is not adopted.** Its bracket
  arithmetic was mis-scaled, its diff would have broken the live v2's approval scope, its
  gate-5 grid would have *reduced* gate-5 coverage, and its name did not match its diff. The
  *ratcheting* form it was mis-named after is a different rule and is handled by D4.
- **No `time_stop_bars` sweep, no `stop_atr`/`target_atr` re-scaling, no snapshot-shopping,
  and no widening of the shared `trend_continuation` grid from a medium-swing proposal.** Each
  is individually foreclosed in §12.6.

---

## B. Hypothesis renumbering — a collision the panel must fix before anything else

**The two change proposals independently minted H13 and H14 with different meanings.** Left
unresolved, the final report would contain two mutually contradictory H13s and two H14s. This
design fixes the numbering, and every downstream document must use it:

| Number | Meaning | Origin | Status |
|---|---|---|---|
| H1–H5 | as in map §2.1 | map | H1, H2, H4, H5 falsified; H3 not supported |
| **H13** | **Exit-geometry local optimum** — the shipped exit geometry sits at a local maximum along every exits-and-risk axis that can be measured | exits & risk proposal | **Supported on five of six axes; NOT established on the sixth (ratcheting trail) — D4 decides** |
| **H14** | **Engine entry-bar risk-unit collapse** — `risk_per_share = abs(entry_fill − sig.stop_price)` (`engine.py:111`) with `entry_fill` = bar *t+1*'s open (`:109-110`) against a stop fixed off bar *t*'s close | exits & risk proposal | **Real, reproduced, escalated — not a v3 lever** |
| **H15** | **Regime axis saturated** — the inherited `not ctx.regime.risk_off` conjunct has already removed every bear and high-vol session, so no `RegimeState` conditioner has anything to remove (was "H14" in the signal-quality proposal) | signal quality & regime | **Verified; closes the regime lane by construction** |
| **H16** | **Entry over-extension ("chase")** — a continuation entry after a large recent run-up buys the end of a thrust (was "H13" in the signal-quality proposal) | signal quality & regime | **Not evidence: 1.36 SE / 1.61 SE at the pre-registered threshold; mechanism signature absent** |

---

## C. Judge-defect disposition

Thirty-eight defects were raised across four judgements. **Thirty-four are accepted as real
and are corrected below. Four are rejected or accepted only in part, with reasons.** The
accepted ones are grouped; the rejected ones are stated individually, because a synthesis that
silently drops a judge finding is worse than one that argues with it.

### C.1 Accepted — corrections applied throughout this document

**Legitimacy / rules (all accepted).**
Route A's pre-emptive discounting of gate 9's pass/fail bit is struck (§4.3, §12.5). The R7b
hazard is carried into Route A explicitly, not only into the do-nothing branch (§5.4). The
sealed-look numbering is resolved to a single convention (§10). The five-condition evidentiary
bar is made symmetric and the incumbent-favouring leash result is scored against it (§3.4,
§4.1). "v3 is stronger than the live v2" is restated as **+0.0416R ± 0.1251 unpaired = 0.33
SE, not evidence**, and the bare CI-lower-bound comparison is deleted (§3.1). The R1 inline
markings are applied to every sealed number inside an argument. The diagnostic-search count is
stated (§9). Citation drift is fixed against the source (§C.3). The shadow plan's
optional-stopping surface ("periodic read-outs") is deleted, its fill contract and R
denominator are pinned, its arrival rate is downgraded to a HYPOTHESIS with a
de-duplication rule, and its "model-fidelity finding" clause is bounded away from motivating
design (§11.2).

**Statistics (all accepted).**
Paired SEs replace unpaired SEs for every re-pricing of a fixed trade list; bounds are
reported in R, not SE (§0, §3). The `MAE ≤ 0 = 100%` statistic is deleted as a definitional
artefact of a long-only book filled at the entry bar's open (`engine.py:104-111, 119-126`) and
every argument leaning on it is withdrawn. The tighter-target table is netted against its own
2.0R control cell, which does **not** reproduce the incumbent (residual −0.0426R OOS snap 3),
so the closure claim is narrowed to the 0.5R–1.0R end of the band. Cost is reported at the
**mean** (0.060R, IQR 0.042–0.075R) alongside the median (0.0568R). The expanded-spread rows
are restated as **increments** over the 11.0 bps already netted out. Every gate delta carries
an SE. The gate-9 power table's normal approximation is stated explicitly. H1's retirement is
attributed to its pre-registered falsification condition, not to a post-treatment duration
gradient.

**Code / safety (all accepted).**
A v0.2.0 in this family must carry a **per-instance** version, never a module-level `VERSION`
bump — and `trend_continuation.py:81`'s `walkforward_result_ref=f"reports/{self.key}-{VERSION}.md"`
is a **third** consumer of the module constant that must route through `self.version`
(verified). Any `rule_definition` / `feature_definitions` extension must be **conditional** on
the new behaviour being active, or it changes v2's `spec_json_hash` and breaks
`scan_scope_matches`. `_sensitivity_plan` dispatches on `key.startswith("trend_continuation")`
(`promotion.py:178`) and `BaselineStrategy.key` carries no version, so scoping a grid to one
version **requires changing the dispatch** — and adding an axis to the shared prefix branch
would either raise `TypeError` in `_replace` on the live v2 (`promotion.py:50`) or, if the
field is defaulted onto `TrendParams`, silently destroy gate 5's baseline anchor and neighbour
test for v0.1.0. Both are recorded as blocking pre-conditions in §13.

**The one closure claim that is false (accepted, and it changes the design).**
The exits proposal's headline — *"no member of this family can produce evidence on the current
OOS sample even if every path resolves in its favour"* — is **withdrawn**. It was computed
only for a *fixed* arm-and-lock rule, and the map's lever 3 names an **ATR-trailing
(ratcheting)** stop, which credits a rescued stop-out with (peak − giveback) rather than a
fixed +bR. A judge's read-only recomputation puts the ratcheting best case far above the
fixed-lock one even after excluding the H14 entry-bar bucket and the MFE ≥ 5R tail. Those
figures are **bounds, not estimates** (see C.2), but a bound that high means the lever is
**not closed by measurement**. Hence D4.

### C.2 Rejected, or accepted only in part

**R1. Rejected in part — "SR-1 / the sealed test must be re-scored at deff = 3.04."**
*(Null judge 2, defect 1; signal judge 2, defect 1.)* Accepted for the **OOS pre-sealed**
sample, where deff 3.04 was actually measured (`clustered_bootstrap_all.md` §3.1), and applied
throughout. **Rejected for the 95-trade sealed year.** A design effect estimated from ~108
calendar-month blocks over a nine-year OOS span is not a property of the strategy that can be
carried to a one-year window containing ~12 blocks; the block count, the block-size-to-sample
ratio and the regime composition all differ, and a transported deff is an assumption presented
as a measurement. **Resolution:** where a clustered figure is wanted for the sealed sample it
must be *computed on that sample* (a read-only bootstrap over the 95 sealed trades would
require re-deriving them, which is a sealed-window computation and is therefore **not**
authorised); until then the sealed SE is reported iid, explicitly labelled as iid, with the
statement that clustering would widen it by an unmeasured factor. The same rejection applies
to the "n = 220 read-out has 1.5 SE not 2.63 SE" arithmetic in §11.2 — the shadow stream's own
deff must be measured on the shadow stream, and until it is, the read-out triggers are stated
in **n**, not in claimed resolving power.

**R2. Rejected in part — "falsification criterion F1 already fires today."**
*(Exits judge 2, defect 1.)* The **arithmetic is accepted**: scaling a paired re-pricing by
the unpaired base SE was an error, and the fixed-lock BEST case is ≈ +6.4 paired SE rather
than +1.72 SE. The **conclusion is rejected.** The BEST case is a deterministic upper bound
constructed by rescuing every qualifying stop-out and clipping no winner — an event of
probability zero (the same judge's defect 7 says exactly this). A "≥ 2 SE" test applied to
such a bound is a category error, and reporting that the angle's own trigger has fired would
be reporting an artefact of a malformed criterion as a finding. **Resolution:** F1 is
discarded as written and replaced (§12.2) with a criterion on a **realised path-level
re-pricing** with a paired SE — which is what D4 computes. This is the more demanding of the
two readings, not the more convenient one: it requires an actual measured effect rather than a
bound.

**R3. Rejected in part — "H4's kill criterion is unreachable, so H4 is a pre-registered
no-op."** *(Null judge 1, defect 4.)* The estimator/power complaint is well taken as a
**standing requirement** (any future v3−v2 differential must state whether it is paired or
unpaired and give its minimum detectable effect), and is adopted in §12.2. But the specific
charge is **moot**: H4 was subsequently run by the signal-quality angle and returned a v3
tercile contrast of **+0.0085R ± 0.1193 (0.07 SE)** on snapshot 3 and at most **+0.0390R ±
0.1179 (0.33 SE)** anywhere — an order of magnitude below any bar, paired or unpaired, so the
differential criterion never needed to fire. H4 is falsified on the v3 gradient alone.

**R4. Rejected — "the ratcheting trailing stop shows +2.2 to +5.1 SE and is therefore
promising."** *(Implied by exits judge 1's framing.)* Accepted that the family is **not
closed**; rejected that the recomputation is evidence *for* it. Every number in that
recomputation is an upper bound built on a rescue rule that never clips a winner — the mirror
of the impossibility already identified in the fixed-lock case. A bound is a reason to
measure, not a reason to believe. D4 measures it, under a bar deliberately set above the
program's nominal 2 SE because of the search that precedes it (§12.2).

### C.3 Citation corrections (verified read-only for this document)

| Claim | Correct | Wrong in |
|---|---|---|
| `VERSION = "0.1.0"` | `trend_continuation.py:**17**` (module-level; read at `:46` **and `:81`**) | null option (`:19`) |
| horizon branch | `trend_continuation.py:**37-39**` (ternary literal on `:38`) | null option (`:36-39`), exits & risk (`:37-39`, correct) |
| `risk_per_share` | `engine.py:**111**` | null option (`:110`) |
| `costs_bps = slip * 2 * 10_000.0` | `engine.py:**144**` | null option (`:143`) |
| "95.07 sealed-year round trips" | **95 sealed trades**; `95.07` is `turnover_per_year` in sealed test id 12's `metrics_json` (verified) — the two are different quantities and must not be conflated | null option §8 |
| `P(sealed mean < 0 \| pre-sealed, n = 95)` | **4.2%** at the measured sd 1.7259; **4.3%** at map §0.3's CI-inverted sd 1.741. Cite the sd with the figure | null option (attributed 4.2% to §0.3, which says 4.3%) |
| "2× / 5× modelled spread" | The map's own formula `round_trip = 2 × (3.0 + spread_bps/2)` makes 26 and 66 bps round trip correspond to **20 and 60 bps quoted spread** (4× and 12× the modelled 5 bps quoted), not 2× and 5× of it. The 26/66 bps figures are retained for §4.2 item 8 compliance; the **label** is corrected to round-trip bps and the map's mislabel is raised as an operator item | all three proposals (inherited from map §0.4) |
| `_is_neighbour` behaviour when the baseline lacks a grid axis value | It **does not raise**: `values.index(baseline[axis])` throws `ValueError`, which is **caught and returns `False`** (`sensitivity.py:106-110`). The consequence is worse than a crash — `neighbours` comes back empty, so the ≥75% guard at `sensitivity.py:194` never fires and the neighbour test is **silently skipped** (§6.2) | an earlier draft of this synthesis; corrected here |
| `approved_scope` as a database table | **No such table exists** (verified against the live schema). `ApprovedScope` is a frozen dataclass derived at read time from *passing* `StrategyPromotionEvaluation` rows (`approval_scope.py:36-66`), so the R7b pre-state to record is the set of passing evaluations and their `dataset_snapshot_id`s (§2, §13.1 step 1) | an earlier draft of this synthesis; corrected here |
| The live approvals' stored spec hashes | Present on `strategy_promotion_evaluation.spec_json_hash`: v2 (evals 20, 32) `2ed9743170bd3bbd…`, v5 (evals 23, 35) `dfe696b662dd02b8…`. Both reproduce **exactly** from live code today, and a module-level `VERSION` bump moves v2's to `8447205d7592b531…` — **executed read-only for this synthesis**, which is the direct confirmation of the exits proposal's most dangerous defect. §13.1 step 2 is consequently a mechanical assertion, not an eyeball check | exits & risk V-A's diff (which would have broken it) |

---

## 1. Mechanism

The claim is negative, and it is a claim about markets: **there is no identified defect in
`trend_continuation.medium_swing`'s rule set, and the one gate it fails is a measurement with
no power at the point where it is being read.**

### 1.1 The rule works as designed, on nine years of pre-sealed data

FACT: v3 is a *target-driven* continuation rule. On snapshot 3's 1,071 pre-sealed trades,
41.5% exit at the 3.0×ATR target at **+1.8156R ± 0.0493** after a mean 10.9 bars, 57.1% exit
at the 1.5×ATR stop at **−1.0375R ± 0.0164**, and **+807.92R of the +813.50R of gross positive
exit-reason P&L (99.3%) comes from target hits** (`v3_duration_exits.md` §2a, §5). The 40-bar
leash is what makes the target reachable, not a liability.

FACT (matched pair — same entries, only `time_stop_bars` differs): holding past bar 10
converts 59.2% of the positions v2 abandons into full target hits, netting **+0.1770R ±
0.0777 per affected trade** (2.3–2.7 SE) and **+0.0524R ± 0.0231 (2.3 SE) per matched trade**
on the all-pre-sealed cut, on all four snapshots (`v3_duration_exits.md` §4).

**And that result is scored against this design's own bar, symmetrically** (§C.1): on the
**OOS** cut it is **+0.0326R ± 0.0439 (0.7 SE)**, and under the month-block condition this
design imposes on any challenger it is ≈1.3 SE. **It is therefore not evidence either, and
this design makes no affirmative claim that the 40-bar leash is superior to the 10-bar one.**
The null option requires no such claim: it requires only that no change be motivated.

### 1.2 Every nominated mechanism is dead, unsupported, or structurally impossible

| Hyp | Status | Decisive pre-sealed number (all four snapshots) |
|---|---|---|
| **H1** duration mismatch | **FALSIFIED against its own pre-registered condition** — the map required buckets 11–40 to be *net negative in per-bar R*; they are the **best** buckets. OOS per-bar R: 11–20 **+0.0394…+0.0438**, 21–40 **+0.0393…+0.0401**, 1–5 **−0.035…−0.042**; per-trade **+0.5654 ± 0.2097** (11–20) and **+1.0791 ± 0.3919** (21–40). *Note (accepted judge correction): realised duration is a **post-treatment** conditioner, so this retires H1 by failing its stated falsifier — it is **not** a ≥2 SE causal gradient and must never be cited as one.* | `v3_duration_exits.md` §5 |
| **H2** target unreachable in the leash | **FALSIFIED, both limbs** — time stop is the *rarest* exit: **8 of 1,071** pre-sealed (0.75%), **1 of 319** OOS, paying **+0.3493R ± 0.1716** | ibid. §2a |
| **H3** stale volatility scale | **NOT SUPPORTED, criterion met** — ATR@exit/ATR@entry median **1.0565 ± 0.0047**, 83.9% within ±25%; v3−v2 median **+0.0012 ± 0.0062** (0.19 SE) | `v3_atr_at_exit.md` §1, §7 |
| **H4** volume confirmation decays | **FALSIFIED** — entry-`vol_ratio` tercile T3−T1: **+0.0085R ± 0.1193 (0.07 SE)** snap 3 ALL; largest anywhere **+0.0390R ± 0.1179 (0.33 SE)**; OOS −0.36 to −0.05 SE | signal-quality §3.2 |
| **H5** short-side asymmetry | **STRUCTURALLY ABSENT** — 0 short trades exist under any gate; `evaluate_promotion` never passes `allow_short`, so `trend_continuation.py:113-133` is dead code | `v3_duration_exits.md` §0, §6b |
| **H15** regime conditioning | **IMPOSSIBLE BY CONSTRUCTION** — snapshot 3: **858 bull/low + 213 neutral/low = 1,071; zero bear, zero high-vol.** `not ctx.regime.risk_off` (`trend_continuation.py:100`; `risk_off = BEAR or HIGH`, `regime.py:41-42`) has already removed everything a regime filter could remove. The only remaining split favours **neutral** (+0.2523R ± 0.1137 vs +0.1455R ± 0.0534; contrast 0.85 SE), so tightening would remove the better trades | signal-quality §3.1 |
| **H16** entry over-extension | **NOT EVIDENCE** — at the pre-registered 2.0 ATR threshold: **+0.1388R ± 0.1017 (1.36 SE)** ALL, **+0.3174R ± 0.1967 (1.61 SE)** OOS on snapshot 3; mechanism sub-test fails in the wrong direction; gate-7 Sharpe non-monotone with a spike at exactly the chosen threshold; best of **15** screened conditioners | signal-quality §3.3–3.4, as corrected by its legitimacy judge |
| **H13** exit-geometry local optimum | **SUPPORTED ON FIVE OF SIX AXES; the ratcheting-trail axis is NOT closed** — see §3.5 and D4 | exits & risk §3, as corrected |

### 1.3 Why gate 9 carries almost no information at this sample size

FACT: gate 9 is `n ≥ 10 and expectancy ≥ 0.0R` (`config/research.py:121-123`,
`promotion.py:402`) — a **sign test at a threshold of exactly zero**. DERIVED, at the measured
pre-sealed OOS per-trade sd of 1.7259 and the sealed count n = 95, **iid SE = 0.1771R** (a
normal approximation to a strongly skewed two-point-mixture per-trade distribution — 57.1% at
−1.0375R, 41.5% at +1.8156R — so the tail cells below are the least reliable; a bootstrap over
the actual pre-sealed distribution should replace them in D1):

| true per-trade expectancy | P(sealed 95-trade mean < 0) |
|---|---|
| +0.3064R (pre-sealed OOS estimate) | **4.2%** (4.3% at map §0.3's sd 1.741) |
| +0.1667R (pre-sealed all-trades mean) | 17.3% |
| **0.0000R** | **50.0% — at any sample size** |

*(sealed-informed — disposition only, R1)* The observed −0.0294R is **−0.166 SE** from zero;
the other three snapshots' +0.0109R on 98 is **+0.063 SE** from zero. Both draws say the same
thing. The verdicts differ only because the threshold sits inside the point estimate's own
neighbourhood. DERIVED: total sealed R on snapshot 3 is 95 × (−0.0294) = **−2.79R** — **1.5
average target hits**; two average target hits added to the sealed year would produce +0.0086R
on 97 trades, a pass. FACT: the entire difference between snapshot 3 and snapshots 1/2/4 is
**3 META trades worth +3.86R**.

### 1.4 H14 — the one real defect found, and why it is not this design's change

**FACT (reproduced independently by two judges from code and data).** `engine.py:111` computes
`risk_per_share = abs(entry_fill − sig.stop_price)` where `entry_fill` is bar *t+1*'s open
(`:109-110`) but `sig.stop_price` was fixed off bar *t*'s close (`trend_continuation.py:105`).
When the entry bar gaps toward the stop the R denominator collapses; when it gaps *through*,
`abs()` inverts the risk unit and `_resolve_exit`'s entry-bar branch (`px = sig.stop_price`)
books the immediately-stopped trade as ≈ **+1R**.

| | n (`bars_held == 0`) | share | expectancy ± SE | total R | gap-through-stop "wins" | worst trade |
|---|---|---|---|---|---|---|
| v3 snap 3 | 106 | 9.9% | **−0.7527 ± 0.0889** | −79.79R | 16 (+12.38R) | −6.13R |
| v2 snap 3 (**live-approved**) | 118 | 10.1% | **−0.8338 ± 0.1291** | −98.39R | 18 (+14.24R) | −12.38R |

**Accepted judge correction:** "−79.79R = 44.7% of v3's total pre-sealed R" is a *descriptive
share*, **not** an estimate of the distortion, and this design does not present it as one. The
size of the distortion is the difference between these trades priced on the collapsing
denominator and priced on a stable risk unit (`stop_atr × ATR` at signal time) — a read-only
computation that has **not** been done and that the operator needs before deciding (§14).

**Out of scope here on three independent grounds:** (i) it cannot be fixed in the strategy
without reading `series.open[t+1]`, which `assert_no_lookahead` correctly forbids; (ii) it is
present *identically and proportionally larger* in v2, so it cannot explain any
medium/short-swing difference; (iii) fixing it in `engine.py` re-prices the evidence
underpinning a **live approval** without changing any `spec_json_hash` — the silent-invalidation
pattern R3/R7 exist to prevent, arriving from the engine side.

---

## 2. Exact change — file, symbol, before → after

**The change set under `src/` and `tests/` is empty.** Stated per touchpoint, because "no
change" is a claim that must be auditable:

| File / symbol | Before | After |
|---|---|---|
| `research/strategies/trend_continuation.py:17` `VERSION` | `"0.1.0"` | **unchanged** — no new `StrategyVersion` row; R3's staleness trap cannot be tripped because nothing is edited |
| `…/trend_continuation.py:21-29` `TrendParams` | 8 fields as shipped | **unchanged**, including the MEDIUM_SWING branch `time_stop_bars=40` at `:37-39` |
| `…/trend_continuation.py:42-83` `spec()` | as generated | **unchanged** → `spec_json_hash` untouched |
| `…/trend_continuation.py:85-133` `evaluate` | long/short branches as shipped | **unchanged** |
| `research/strategies/__init__.py:43-51` `default_strategies()` | 6 entries | **unchanged** |
| `research/promotion.py:178-187` `_sensitivity_plan` | `{sma_fast:[15,20,25], stop_atr:[1.2,1.5,1.8]}` | **unchanged** (see §6 for why touching it is not free) |
| `backtest/engine.py` | `run_backtest`, `_resolve_exit`, `EntrySignal` as shipped | **unchanged** — H14 escalated, not patched |
| `tests/` | — | **unchanged** |

**R7 / R7b safety of the empty change set (FACT).** `persistence.spec_json_hash` hashes every
`StrategySpec` field except `git_sha`, `status`, `notes` (`persistence.py:29,32-43`) — it never
hashes `TrendParams`. Because `spec()` does not change, v2's stored hash `2ed97431…` and v5's
`dfe696b6…` (on the passing evaluations scoping the two live approvals: evals 20 & 32, 23 & 35)
are untouched, `scan_scope_matches` (`approval_scope.py:69-94`) keeps returning `True`, and
the live probation is undisturbed. **FACT, verified for this synthesis:** there is no
`approved_scope` table — an `ApprovedScope` is a frozen dataclass **derived at read time** from
that version's *passing* `StrategyPromotionEvaluation` rows (`approval_scope.py:36-66`). So the
operative statement is: no new **passing evaluation** is created on any snapshot, therefore no
new scope exists, and the R7b `scopes[0]` selection stays deterministic (v2 → sealed id 11,
v5 → sealed id 14, both snapshot 3). The two live approvals' stored hashes are
`2ed9743170bd3bbd…` (v2, evals 20 & 32) and `dfe696b662dd02b8…` (v5, evals 23 & 35), read from
`strategy_promotion_evaluation.spec_json_hash` and re-computed identically from live code
today. **This safety claim is scoped to the
do-nothing branch and does *not* extend to Route A; see §5.4.**

FACT: v3 remains `EXPERIMENTAL` and therefore carries **zero live-trading risk by
construction, not by policy** — `assert_auto_simulate_allowed` raises
`AutoSimulateForbidden("strategy version is not PAPER_APPROVED")` (`paper/ledger.py:500-502`)
and `plan_alerts` gates candidate alerts on paper-approved status
(`alerts/dispatch.py:238, 259, 265`).

### 2.1 The four deliverables this design produces (documents and read-only tools only)

| | Deliverable | Nature |
|---|---|---|
| **D1** | `docs/research/results/trend_continuation_medium_swing--does_not_pass.md` — the documented non-pass | document; contents in §11.1 |
| **D2** | The pre-registered shadow-confirmation plan | document; §11.2 |
| **D3** | A standalone **read-only** shadow-ledger script (no `src/` module, no DB write, no API call) | script, outside `src/` |
| **D4** | The **ratcheting-trail path-level closure diagnostic** — read-only, pre-sealed, zero looks, zero variants | script, outside `src/`; pre-registered in §12.2 |

### 2.2 The contingent variant, pre-specified now so it cannot be re-specified later (V-A′)

Registered **only** so that if D4 clears its bar (§12.2) or the operator overrules this
recommendation, the variant is fixed before its result is seen (R5). It is **not requested**.
Every element below is a correction of the exits proposal's V-A against the judges' findings:

1. **Version — per instance, never module-level.** `VERSION = "0.1.0"` stays; add
   `VERSION_TRAIL = "0.2.0"`; make `self.version` a function of *behaviour*
   (`trail_arm_r is not None`); route **all three** consumers through it — `spec(...,
   version=self.version)` at `:46` **and** `walkforward_result_ref=f"reports/{self.key}-{self.version}.md"`
   at `:81`. A bare module bump makes `current_spec_json_hash` return `None` for the live v2
   (`approval_scope.py:97-121` matches `default_strategies()` on `(name, version)`) and breaks
   every live auto-sim and alert scope check.
2. **Spec strings — conditional.** Any extension of `rule_definition` / `feature_definitions`
   must be emitted **only** when the trailing behaviour is active; an unconditional append
   changes v2's `spec_json_hash` and is itself the breakage.
3. **Rule — the *ratcheting* form, named for what it is.** Arm when open profit reaches `aR`
   (evaluated on closed bars; **arming takes effect from the next bar, never same-bar**);
   thereafter the effective stop is `max(entry + bR, peak_favourable_price − g·R)`, ratcheting
   upward only. Three parameters: `trail_arm_r`, `trail_lock_r`, `trail_give_r`.
4. **R unit — the engine's own.** Arm and lock levels are computed inside `_resolve_exit` from
   `risk_per_share` (`engine.py:111`), *not* from the close-based risk the strategy sees;
   otherwise "lock at +0.5R" is not +0.5R in the engine's units on the ~10% of trades H14
   identifies.
5. **Shared-surface change, with two load-bearing regressions.** `EntrySignal`
   (`engine.py:29-41`) and `_resolve_exit` are shared by all six strategies including two live
   approvals. Mandatory: (a) with the trail fields `None`, snapshot 3 reproduces **v2 = 1,169
   pre-sealed / +0.2648R OOS** and **v3 = 1,071 / +0.3064R** bit-for-bit; (b) no same-bar
   arm-and-fire.
6. **Gate-5 grid — more searching, never less** (§6.2), with the `_sensitivity_plan` dispatch
   change specified as part of the diff, not deferred.

---

## 3. Pre-sealed evidence, with standard errors

All figures are pre-sealed only. Spans: `[2016-09-10 … 2025-09-07]` on snapshots 2–4 and
`[… 2025-09-06]` on snapshot 1, exactly `sealed_start − 1 day` as `promotion.py:557` computes.
Reproduced independently by three in-process `run_strategy_over_universe` runs across two
proposals and re-verified by three judges.

### 3.1 The incumbent's pre-sealed profile (snapshot 3, eval 33)

| Quantity | Trade set | Value ± SE |
|---|---|---|
| OOS expectancy | OOS (319) | **+0.3064R ± 0.0966** (measured sd 1.7259) |
| All-pre-sealed expectancy | 1,071 | +0.1667R ± 0.0484 (sd 1.5839) |
| Bootstrap CI low (gate 4, iid) | OOS | +0.1205 (vs +0.02) |
| **Same, calendar-month block** | OOS | **−0.0191**, deff **3.04**, effective n ≈ 105 |
| Walk-forward folds (gate 1) | all pre-sealed | +0.1822/310, +0.0772/323, +0.0343/179, +0.3513/259 → **4 of 4** |
| Sharpe (gate 7) | all pre-sealed | 1.156 vs SPY 0.719 |
| Sensitivity (gate 5) | OOS per cell | 9/9 positive, cells n = 296–336 |
| Other snapshots | OOS | snap 1/2: 326 / +0.2936R (sd 1.7179); snap 4: 336 / +0.3169R (sd 1.7219) |

**Comparison with the live v2, scored under this design's own rule.** v3 +0.3064R ± 0.0966
(n=319) vs v2 +0.2648R ± 0.0795 (n=341, sd 1.4673). DERIVED: difference **+0.0416R against an
unpaired SE of 0.1251 = 0.33 SE. This is not evidence, and this design does not claim v3 is
better than v2.** The bare comparison of bootstrap CI lower bounds (+0.1205 vs +0.1129) is
deleted from all downstream reporting: CI lower bounds are not effect sizes.

### 3.2 The exits-and-risk measurements (grafted, corrected)

**Stop-out and winner excursion structure** (v3, all pre-sealed, snapshot 3; stable to ±0.01
across snapshots 1/2/4):

| Exit reason | n | MFE median | MFE p75 | MFE p90 |
|---|---|---|---|---|
| stop | 612 | **+0.471** | +0.966 | +1.672 |
| target | 445 | +1.857 | +2.425 | +3.379 |
| time_stop | 8 | +1.054 | +1.188 | +1.439 |

Share of stop-outs that ever showed at least aR: **48.4% ≥ 0.5R, 23.4% ≥ 1.0R, 11.3% ≥ 1.5R**
(OOS: 52.6 / 19.4 / 9.7). Robust to dropping the entry-bar bucket and the MFE ≥ 3 tail
(23.5% and 22.9% ≥ 1.0R).

**Deleted (accepted judge correction):** the statistic "100% of target exits have MAE ≤ 0" is
a definitional artefact — with `allow_short=False`, `entry_fill = open × (1+slip)` and `mae`
taken over `series.low[entry_idx : exit_idx+1]` (`engine.py:104-111, 119-126`), the entry
bar's own low is ≤ open < fill, so **every trade of every exit reason has mae < 0.** It
carries zero information and the asymmetry argument that leaned on it is withdrawn. The
statistic that *would* bear on the mechanism — among target exits, the minimum excursion
measured from the **first bar on which MFE ≥ a** — has never been computed. D4 computes it.

**Time-stop attainable range (kills any `time_stop_bars > 40` change).** 8 of 1,071 pre-sealed
and **1 of 319 OOS** trades exit on `time_stop`, on all four snapshots. The entire attainable
range on the deciding (OOS) trade set is **+0.0071R (ceiling: every time-stop trade instead
runs to full target) to −0.0023R (floor)** — *stated in R, not in SE, per §0*. For scale, the
paired z of the ceiling is ≈ **1.0**, not the 0.07 the source proposal reported (which
divided by the unpaired base SE). The verdict is unchanged: **a lever confined to one OOS
trade cannot produce evidence.**

**Exact tighter-target re-pricing, netted against its own control (accepted correction).** A
fixed 2.0R target should reproduce the incumbent (target 3.0×ATR over a 1.5×ATR stop) but does
not — snapshot 3 OOS Δ **−0.0426R ± 0.0543** — because the strategy sets stop and target off
bar *t*'s close (`trend_continuation.py:105-107`) while the engine divides by
`|entry_fill − stop_price|` with `entry_fill` = bar *t+1*'s open. That residual is a
reconstruction-error term and must be netted out:

| Target | OOS snap 3, raw Δ ± paired SE | **netted against the 2.0R control** | verdict |
|---|---|---|---|
| 0.50R | −0.1984 ± 0.0862 (−2.30 SE) | ≈ −0.156 (≈ −1.8 SE) | worse |
| 1.00R | **−0.2183 ± 0.0701 (−3.11 SE)** | ≈ **−0.176 (≈ −2.5 SE)** | **worse at ≥ 2 SE** |
| 1.25R | −0.1677 ± 0.0647 (−2.59 SE) | ≈ −0.125 (≈ −1.9 SE) | worse, **under 2 SE** |
| 1.50R | −0.1284 ± 0.0597 (−2.15 SE) | ≈ −0.086 (≈ −1.4 SE) | worse, **under 2 SE** |

Same pattern on snapshots 1 and 4 (raw 1.0R: −2.95 / −3.15 SE). Excluding the entry-bar
bucket, 1.0R is −3.36 / −3.53 / −3.56 SE raw. **Corrected closure claim: the aggressive end of
the target lever (0.5R–1.0R) is closed at ≥ 2 SE; 1.25R–1.5R are worse but not at 2 SE.** The
source proposal's "worse at ≥ 2 SE across the whole 1.0R–1.5R band" is withdrawn. Note also
that this re-prices a fixed-**R** target, which is a *proxy* for the map's lever (a change to
`target_atr`, which stays ATR-parameterised); the residual above is exactly the difference.

**Gate-5 grid as risk-axis evidence.** All eight non-baseline cells are **below** baseline
(worst +0.0933 at `sma_fast` 15 / `stop_atr` 1.2; the two `stop_atr` neighbours at the shipped
`sma_fast` are −0.1380R and −0.0541R). No cell exceeds the baseline *at all*, so no paired SE
is needed to conclude no cell exceeds it by 2 SE. **HYPOTHESIS, and it cuts against the
strategy:** shipped parameters sitting at the maximum of a 9-point OOS grid is the signature of
parameters chosen on this data, and is a reason to treat +0.3064R as somewhat
selection-inflated. This belongs in D1 precisely because it is adverse. *(The source proposal
supported this caveat partly with a sealed-window comparison; that clause is dropped — the
pre-sealed grid maximum supports it on its own, and citing the sealed gap here would have
been an unmarked R1 use.)*

### 3.3 The signal-quality measurements (grafted)

- **H15 (regime saturation)** — §1.2, and a quantified instance of the map's two-labeller
  caveat: the same 1,071 trades are labelled **0 bear** by `research/regime.py` and **22 bear**
  by `backtest/regime.py:label_regimes` (the labeller gate 6 uses). Any gate-6 claim must
  therefore be *measured*, never inferred from `RegimeState`.
- **The 15-conditioner screen, and its pattern.** Four conditioners clear 2 SE on the
  all-pre-sealed cut — extension above SMA50 (−2.04/−2.22/−2.29), (SMA20−SMA50)/ATR
  (−2.26/−2.35/−2.36), ATR/price at signal (+2.28/+2.18/+2.19), proxy trailing 20d return
  (−2.36/−2.40/−2.62) — and **every single one collapses to ≈0 or reverses sign out of
  sample.** *The pattern is the finding, and it is the most valuable thing any of the three
  angles produced:* these are exactly the changes an unrigorous version of this program would
  have shipped.
- **H16 at its pre-registered threshold** — §1.2. Its fold table, mechanism sub-test and kill
  conditions were computed at the p67 cut (1.8636), the very cut the proposal disclaimed as
  sample-fitting; at 2.0 the effect is weaker (1.36 SE ALL, 1.61 SE OOS). The "largest single
  fold contrast 1.51 SE" figure appears in no published table (the maximum shown is 1.45 SE)
  and is discarded as unverifiable.

### 3.4 The evidence that cuts *against* the incumbent (stated in the body, not a footnote)

1. **The pre-sealed edge does not survive the stricter clustered diagnostic.** Month-block OOS
   CI **[−0.0191, +0.6406]**, deff 3.04. DERIVED: a month-clustered gate 4 would require
   **+0.3497R** against the observed +0.3064R, or equivalently n ≈ 426 against 319 held. This
   is a **disclosure**, not a gate (R4 permits reporting a stricter statistic). **Applied
   symmetrically per §C.1: v2's month-block low is +0.0125 and v5's is −0.0238 — both live
   strategies are at or below the same bar, so this statistic cannot by itself decide between
   incumbent and challenger, and it is stated as a reporting requirement applied equally to
   both.**
2. **The sealed year is mildly disappointing relative to the pre-sealed estimate on every
   snapshot.** *(sealed-informed — disposition only, R1)* z = **−1.88** treating the
   pre-sealed mean as known, **−1.65** on the two-sample SE; `P(sealed mean < 0 | pre-sealed
   estimate, n = 95) = 4.2%` at sd 1.7259. This is mild evidence the pre-sealed estimate is
   optimistic — an argument for **more caution about promoting**, i.e. an argument *for* the
   null.
3. **The shipped parameters sit at the gate-5 grid maximum** (§3.2).
4. **The evidence base is computed on a biased risk unit** (H14, §1.4), and the size of that
   bias has not been measured.

### 3.5 The one lever measurement has **not** closed

| Lever (map §2.1) | Axis | Best pre-sealed evidence | Verdict |
|---|---|---|---|
| 3 — time-stop redesign ↑ | `time_stop_bars` | attainable range **+0.0071R / −0.0023R** on 1 OOS trade | **closed — cannot produce evidence** |
| 3 — time-stop redesign ↓ | `time_stop_bars` | matched pair −0.18R ± 0.078 per affected trade (ALL cut only) | **closed — wrong direction** |
| 3 — ATR-refreshed stop | ATR@exit/@entry | v3 − v2 median +0.0012 ± 0.0062 | **closed — nothing to refresh** |
| 3 — target to horizon | `target_atr` ↓ | netted −2.5 SE at 1.0R; **under 2 SE at 1.25R–1.5R** | **closed at the aggressive end only** |
| 4 — risk geometry | `stop_atr` | all 8 non-baseline cells below baseline | **closed — no free improvement** |
| 1/2 — signal & regime | entry conditioners | 15 screened; best survivor 1.36–1.61 SE; regime axis saturated | **closed** |
| **3 — ratcheting ATR trail** | `(arm, lock, give)` | **not measured.** The published bracket covers only a *fixed* arm-and-lock rule; a ratcheting rule credits (peak − giveback). Judge recomputation of the ratcheting **upper bound**, snapshot 3 OOS, excluding the entry-bar bucket and MFE ≥ 5R: ≈ +0.56R at g = 0.5R against a base of +0.30R | **OPEN — D4 decides** |
| — (new) | H14 engine risk unit | −79.79R descriptive share on v3; **worse in the live v2** | **escalate, not a v3 lever** |

---

## 4. Falsification — stated before the fact, required on all four snapshots

### 4.1 What would kill this design (the symmetric bar)

A change proposal becomes legitimate **only** on a pre-sealed observation meeting all of:

1. **Mechanism-specific**, with the sign predicted before measurement.
2. **≥ 2 SE on the OOS cut**, using the **paired** SE where the comparison is a re-pricing of a
   fixed trade list and the unpaired SE where the groups are disjoint; a *bound* never
   qualifies.
3. **Same sign on all four snapshots**, spread well inside one SE (R10) — while acknowledging
   that snapshots 1 and 2 are identical, 3 is 2 minus one symbol and 4 is 2 with `META_CONT`,
   so four-snapshot agreement is close to **one** observation. Independent replication must
   come from the **four walk-forward folds**.
4. **Stable across the IS→OOS split** — the cut that killed the ATR tercile gradient
   (−0.5461 ± 0.1362 IS → −0.1320 ± 0.2533 OOS) and all four of the signal-quality screen's
   in-sample survivors.
5. **Not a post-treatment conditioner** — nothing measured at or after exit (at-exit ATR,
   realised duration, realised exit reason, MFE/MAE as a *rule input*).
6. **Reported alongside a calendar-month block resampling.** *This is a **reporting**
   requirement applied equally to incumbent and challenger, not a bar the challenger alone
   must clear* — v3, v2 and v5 all fail it today, so it cannot by itself decide between them.
   Where a change proposal claims superiority, the month-block figure must be shown; where the
   incumbent is defended, as here, no affirmative superiority claim is made and none is
   needed.

**Symmetry check, performed:** the incumbent-favouring matched-pair leash result
(+0.0524R ± 0.0231 ALL) fails clauses 2 and 6 (0.7 SE OOS; ≈1.3 SE month-block) and is
therefore **not treated as evidence anywhere in this design** (§1.1).

### 4.2 The falsifier that is actually live: D4

H4 is no longer the open lever — it has been run and falsified. **The only surviving lever is
the ratcheting trail**, and its falsifier is pre-registered in full in §12.2 before any run.

### 4.3 What would later justify a promotion re-run — and what would not

**FACT — v0.1.0 can never pass on snapshot 3, however many times it is re-run.**
`_get_or_create_sealed_test` returns any existing row as-is, *"locked — never recomputed, never
overwritten"* (`promotion.py:376-385`); `evaluate_promotion` then pins
`sealed_start`/`sealed_end` from that row and derives `pre_sealed_end = sealed_start − 1 day`
(`:545-557`); `passed = bool(gates) and all(g.passed for g in gates)` (`:922`). A re-run in
2030 still replays sealed test id 12. All seven of v3's evaluations (ids 3, 9, 15, 21, 27, 33,
39) returned `NO TRADE`.

**FACT — v3 has never had an all-gates pass on any snapshot.** On snapshots 1, 2 and 4 gate 9
passes (+0.0109R / 98) but gate 8 fails (`META`: 90 missing sessions; `META_CONT`:
`continuity_bridge:1`, not `massive`). *"Passes gate 9 on three of four snapshots"* is true and
must be disclosed; *"would have been approved on three of four snapshots"* is **false** and
must never be written.

| Route | Qualifies when… |
|---|---|
| **A** — a new snapshot with the **unchanged** v0.1.0 | The snapshot was built for reasons independent of v3 (today: W1's 150-symbol snapshot, built for v6's power problem); its symbol and composition rules were pre-registered before any v3 number on it existed; v3's inclusion **and the intention to report whatever it returns** are pre-registered in writing beforehand; the run is disclosed as a new look for **every** version simultaneously (§5.4, §12.5) |
| **B** — a v0.2.0 with a real rule change | Motivated by a pre-sealed finding meeting all of §4.1; motivation documented before the variant is run; §12.3's budget and stopping rule respected. **Today the only admissible source of such a finding is D4.** |

**Non-qualifying triggers** (each is a mistake this program is at real risk of making): the
sealed miss itself; any duration / leash / exit-timing change (H1, H2 falsified); any
ATR-refresh change citing the at-exit ATR work (post-treatment); a sweep over
`time_stop_bars`; leading with snapshot 1, 2 or 4 because gate 9 passes there
(snapshot-shopping — and they fail gate 8 anyway); waiting for the calendar to roll
(structurally impossible); building a snapshot *in order to* get v3 another draw; live-paper or
shadow-ledger results in either direction (R8); re-running after a pipeline-hardening change
(those change reporting and counting, not the pinned verdict).

**Struck (accepted judge correction).** The source proposal's pre-registration that *"the
number to read from Route A is the sealed expectancy ± SE, not the pass/fail bit"* is
**deleted**. It pre-authorised discounting the one gate v3 fails, on the one future run that
could change its disposition. Replacement, binding: **Route A's gate-9 pass/fail bit remains
binding for promotion (`promotion.py:922`). The estimate and its SE are reported *alongside*
it, never in place of it. A Route A gate-9 fail is a `NO TRADE` verdict and closes the lane; a
Route A pass is reported as "passed on look k" with the multiple-testing discount and the
five-simultaneous-looks context stated.**

---

## 5. Gate-by-gate forecast, with trade sets

### 5.1 Under the recommendation (empty change set) — snapshot 3

Gates 1–8 are unchanged **by construction**: they are computed over `[start, pre_sealed_end]`
with `pre_sealed_end` pinned by the locked sealed row, from code that is not being edited. The
only way a number here moves is a change in the underlying bars — a data event, not a proposal
effect. **This forecast predicts every recorded value exactly, which makes it unusually easy to
falsify.**

| # | Gate | Trade set | Forecast | At risk? |
|---|---|---|---|---|
| 0 | `data_availability` | — | pass (span unchanged) | no |
| 1 | `rolling_walkforward` | **all pre-sealed (1,071)** | 4 of 4 folds clear (+0.1822/310, +0.0772/323, +0.0343/179, +0.3513/259) against a 2-of-4 bar; per-fold floor 15 = `sensitivity_min_grid_trades` (`promotion.py:632` — **gate 1 shares gate 5's constant**) | no |
| 2 | `min_oos_trades` | **OOS (319)** | 319 ≥ 30 | no |
| 3 | `net_expectancy` | **OOS (319)** | **+0.3064R ± 0.0966** > 0 | no |
| 4 | `bootstrap_ci` | **OOS (319)** | low +0.1205 > +0.02. **Required n = 140** at measured sd 1.7259 (142 at §0.3's 1.741); snap 1 = 152 (has 326); snap 4 = 130 (has 336). *Disclosure, not a gate: month-block low **−0.0191**, deff 3.04, required expectancy +0.3497R, required n ≈ 426* | no as specified; **fails the stricter diagnostic** |
| 5 | `parameter_sensitivity` | OOS per cell | 9/9 positive, 9/9 neighbours, worst cell +0.0933, every cell n ≥ 296 vs the 15 floor — on **2 of 8** `TrendParams` fields, excluding `time_stop_bars` | no |
| 6 | `regime_coverage` | **all pre-sealed (1,071)** | bull **857** / bear **22** / range **69**; **unbucketed 123 (11.5%)**, decomposed **warmup 123 / no-proxy-bar 0**. Binding margin: bear 22 vs floor 10 | no |
| 7 | `benchmark_comparison` | **all pre-sealed (1,071)** — per the code (`promotion.py:775`), *not* OOS as the docstring at `config/research.py:111-113` says | Sharpe **1.156** vs SPY **0.719** (+0.437); turnover 120.55/yr, maxDD 28.455%, CAGR 10.153% | no |
| 8 | `data_quality_and_leakage` | — | pass **on snapshot 3 only** | no |
| **9** | `sealed_final_test` | sealed year | **replayed, not recomputed** — id 12, **−0.0294R / 95, passed = 0**; ids 2/7/17 replay +0.0109R / 98, passed = 1. *(sealed-informed — disposition only, R1)* | **n/a — this is the documented outcome, and it is unchangeable** |
| 10 | `live_paper_probation` | — | `health_monitor.enabled` → pass | no |

**Trade-count effect: exactly zero.** Turnover delta: **0.0000R**.

### 5.2 Zero-margin cases required by §4.2 item 5

- **v6's gate-5 neighbour fraction** — exactly **0.750** on snapshot 3 (passes; `sensitivity.py:194`
  tests `nb_frac < min`) and **0.500 / FAIL** on snapshot 4. **Effect of this design: none** —
  different `_sensitivity_plan` prefix, no grid edit, no evaluation.
- **v5's bear bucket** — **11** against a floor of 10 (unbucketed 0). **Effect: none.**
- **v3's own thinnest margin** — gate 6's bear bucket at **22**; a trade-count cut of >55%
  would breach it. Nothing here cuts trade count.
- **The two zero-margin cases SR-1 *would have created* and this design refuses:** gate 6 bear
  **13** (margin 3, and **11** at `max_run_up_atr = 1.5`) and walk-forward fold F3 at
  **+0.0007R** against a `> 0` test — a fold that clears today by 49×.

### 5.3 What the rejected changes would have cost (recorded so the refusal is auditable)

| | SR-1 (H16 filter, at 2.0) | V-A (fixed arm-and-lock) |
|---|---|---|
| Gate 3 (OOS) | +0.3064 → +0.3480R; **delta +0.0416R ± 0.1455 = 0.29 SE — not evidence** | point estimate unknown; sign not predictable |
| Gate 4 | iid low +0.1401, required n 111 of 262. **Month-block at v3's own deff 1.744×: low ≈ −0.0145 — a FAIL**, indistinguishable from v3's own −0.0191 | passes iff the realised estimate exceeds ≈ +0.21R at ~330 OOS trades |
| Gate 6 | bear **13** (from 22) | bear ~22–24 |
| Gate 7 | Sharpe 1.190 — but **1.082 at 1.5 and 1.044 at 2.5, both below the 1.156 baseline**: a one-point spike at exactly the chosen threshold | direction unpredictable (compresses both R and variance) |
| Gate 5 | forecast given for a 9-cell grid that would **not run** (27 or 81 cells would) | grid as drafted **reduced** coverage and would have crashed v2's `_replace` |
| Gate 9 | *(R1-permitted disposition arithmetic)* sealed n falls ~18.7% to ≈77 → SE ≈ 0.197; granting the full, non-significant +0.0416R uplift moves P(gate 9 pass) from ≈43.5% to ≈**52.5%**. **Look 6 buys ≈ nine percentage points of pass probability, purchased with two new zero-margin gates and a clustered gate-4 fail.** | a brand-new draw; not forecast |

### 5.4 Route A's forecast — including the R7b hazard the null proposal scoped only to its do-nothing half

HYPOTHESIS throughout. Gate 8 is the **first** risk: every symbol must be genuinely
`massive`-sourced end to end (snapshot 4's failure mode). Gates 2, 5 and 6 improve with breadth
(bear bucket 22 → ~100+). Gates 3, 4 and 7 are point-estimate questions breadth cannot move,
and the honest risk is that the point estimate *falls* on a single-name-heavy universe with
wider real spreads (§8) and more heterogeneous per-symbol history, which worsens the
`_TRAIN_FRAC = 0.6` per-symbol IS/OOS misalignment. Gate 9 gets ≈600–750 sealed trades at SE
≈0.063–0.071R — **and its pass/fail bit remains binding** (§4.3).

**R7b precondition, binding on any Route A run.** (i) Re-record, **before** the run, the
current passing evaluations and `scopes[0]`-selected sealed tests: v2 evals 20, 32 → sealed id
11; v5 evals 23, 35 → sealed id 14; both on snapshot 3, so the selection is deterministic
today. (ii) After the run, check whether any new passing evaluation landed on a **different**
`dataset_snapshot_id` — `approved_scopes` (`approval_scope.py:45-66`) issues its select with
**no `order_by`**, and `paper_probation.py:113-122` displays `scopes[0].dataset_snapshot_id`,
so a second scope makes the sealed test shown for a **live** strategy order-dependent (for v2:
+0.3246R/112 vs +0.2982R/109). (iii) State explicitly that this is a live-strategy risk
**created by Route A**, and that §2's "effect: none" claim applies only to the do-nothing
branch.

---

## 6. Sensitivity-grid plan and the no-op check

### 6.1 Under the recommendation

**Zero parameters are introduced or changed, so zero axes are added.** The grid stays
`{sma_fast: [15,20,25], stop_atr: [1.2,1.5,1.8]}` (`promotion.py:187`). Three things are
pre-registered anyway:

**(a) The mechanical no-op check**, to be run before any future evaluation of this family on
any snapshot: for each axis, at least one off-baseline value must differ from the baseline by
**≥ 1 OOS trade or ≥ 0.001R OOS expectancy**. Rationale: `_replace` raises `TypeError` loudly
on a *renamed* field (`promotion.py:50`), but a **retained-but-unused** field silently makes
all cells identical, `positive_fraction` and `neighbour_positive_fraction` both return 1.0, and
gate 5 passes at 100% having tested nothing — `sensitivity.py:199`'s
`len(evaluable) >= 4 and len(positive) <= 1` guard does not catch it. Today the check passes
trivially (9/9 *positive* is not 9/9 *identical*), but it must be mechanical, not assumed.

**(b) Why `time_stop_bars` is not added here**, despite being the parameter that defines this
strategy and despite the axis being demonstrably live (10 → 40 moves pre-sealed trade count
~8%, target share ~17 pp, total R +53 to +70R): `_sensitivity_plan` is keyed on the
`trend_continuation` **prefix** (`promotion.py:178`) and `BaselineStrategy.key` carries no
version, so adding an axis changes gate 5 for the **live-approved v2**; and an on-`StrategySpec`
axis-declaration field would change v2's and v5's `spec_json_hash` and permanently break both
live approvals. §4.2 item 6 requires new axes only for parameters a v0.2.0 *introduces or
changes* — this design introduces none. **This is deferred to the hardening lane, not
abandoned** (§14).

**(c) On any new snapshot, re-run (a) there** — grid degeneracy is snapshot-dependent through
the 15-trade-per-cell floor, and that same constant is gate 1's per-fold floor.

### 6.2 If V-A′ is ever authorised (pre-registered now)

- **Axes:** `trail_arm_r [0.75, 1.0, 1.25]` × `trail_lock_r [0.25, 0.5, 0.75]` ×
  `trail_give_r [0.5, 1.0, 1.5]` × **`stop_atr [1.2, 1.5, 1.8]` retained** = **81 cells**,
  under `MAX_GRID_POINTS = 120` (`sensitivity.py:29`). **The incumbent risk-geometry axis is
  kept:** dropping it would make gate 5 *less* searching than eval 33's evidence, which R4's
  symmetric carve-out does not permit. The "keep 9 cells so the 15-trade floor behaves as
  today" rationale is withdrawn as unsound — per-cell n is 296–336 and is independent of cell
  count.
- **Dispatch:** `_sensitivity_plan` **must** be changed to discriminate by version (dispatch on
  `spec.versioned_key`, or an explicit per-version grid) as part of the same diff. Leaving it
  on the shared prefix is not a neutral option. **Mechanism, verified line by line for this
  synthesis:** with the new fields defaulted onto `TrendParams`, v2's baseline carries
  `trail_arm_r = None` while the grid axis holds `[0.75, 1.0, 1.25]`, so (i)
  `is_base = all(overrides[a] == baseline.get(a) for a in axes)` (`sensitivity.py:163`) is
  **False for every point**, `baseline_point` is `None` and `baseline_exp` falls back to
  **0.0** (`:181-182`) — no baseline anchor; and (ii) `_is_neighbour` hits
  `values.index(None)` → `ValueError`, which is **caught and returns `False`**
  (`sensitivity.py:106-110` — it does *not* raise; the source claim that it raises is
  corrected here), so `neighbours` is **empty**, `nb_frac` is 0.0, and the guard
  `if neighbours and nb_frac < neighbour_fraction_min` (`:194`) **never fires** — the ≥75%
  neighbour test is silently skipped. Meanwhile every cell runs *with* the trailing rule on,
  so gate 5 stops testing the shipped v0.1.0/v2 rule entirely. Without the fields defaulted,
  `_replace` raises `TypeError` (`promotion.py:50`) and v2's evaluation fails outright. Both
  branches are unacceptable; the dispatch change is therefore mandatory, not optional.
- **No-op assertion (mandatory, blocking):** at least **7 of 9** cells along each new axis must
  differ from the baseline cell in `oos_expectancy_r` by > 1e-6, and **no two cells** may be
  byte-identical in `(n_trades, oos_expectancy_r)`. Plus the sharper case the map does not yet
  name: a v0.2.0 that bumps the version but **forgets to emit** the trail fields from
  `evaluate()` is byte-identical to v0.1.0 while creating a new `StrategyVersion` row and
  **spending a sealed look on nothing.** The same assertion catches it.
- **Pre/post assertion:** the sensitivity report for **v2** and for **v3 v0.1.0** must still
  contain a baseline point and ≥ 4 neighbour points.

---

## 7. Leakage argument

**For the strategy: nothing changes, so no new leakage surface exists.** `sma`, `volume_ratio`
and `atr` continue to be read as `(series, t)` with slices ≤ t; `run_backtest` calls
`signal_fn(series.head(t), t)` (`engine.py:102`), so later bars are *absent*, not merely
unused; `assert_no_lookahead` (`leakage.py:23-41`) covers the same call sites. No
cross-sectional or breadth term, so `StrategyContext` (`base.py:15-19`) is untouched and there
is **no shared-surface change**.

**Three leakage-adjacent facts that bear on how the §3 evidence may be used:**

1. **`mfe_r` / `mae_r` are post-treatment** — computed over `[entry_idx, exit_idx]`, a window
   whose right edge is set by the trade's own outcome. They are used **only** to bound or
   re-price counterfactuals on realised paths. **No rule reads them and none is proposed that
   would**, and any conditioner measured at or after exit is inadmissible as motivation (§4.1
   clause 5).
2. **The tighter-target re-pricing holds the trade set fixed** — an earlier exit would free the
   engine to re-enter sooner (`engine.py:149`). Stated as an approximation; it cannot flip a
   −2.5 SE result.
3. **D4's real leakage risk is not in the signal function**, so `assert_no_lookahead` cannot
   see it: arming and firing a trail on the **same daily bar** assumes an intra-bar ordering of
   the high and the low that a daily OHLC bar does not contain. D4's replay and any V-A′
   implementation must arm on closed bars with effect from the next bar, and a test asserting
   it is a condition of either running.

**D3's point-in-time argument** is structural and stronger than the backtest's: `Candidate`
rows are frozen by a scan at wall-clock time (`scan.py:265-300`) and evaluated only against
strictly later bars. **Pinned contract (accepted judge correction):** `entry_zone_low/high` are
recorded **for audit only and are NOT a fill condition** — the engine fills unconditionally at
the next session's open (`engine.py:108-110`) and has no entry-zone concept, so gating on the
zone would add a rule the strategy does not have. Shadow R uses
`risk_per_share = abs(entry_fill − invalidation_level)` to match `engine.py:111`. A shadow
trade whose next-session open is unavailable is reported as a **gap, not dropped**. Scan gaps
are non-random with respect to market conditions (scans block on stale feeds, which correlate
with disorderly markets) and must be reported as a known bias, not averaged over.

---

## 8. Cost-model statement (quantitative)

**The cost model is unchanged (R4), and this design changes turnover by exactly zero.**
FACT: `costs.py:11-16` — commission 0, `slippage_bps = 3.0`, `half_spread_fill_penalty = True`;
`engine.py:90` `spread_bps = 5.0`; `engine.py:94` `slip = (3.0 + 5.0/2)/10,000 = 5.5 bps` per
side; `engine.py:144` records **11.0 bps of notional per round trip**. FACT:
`backtest_runner.py:205-206` never passes `spread_bps`, so the term is **universe-independent**.

**Per-trade cost in R, at the measured geometry and reported at the mean as well as the
median** (accepted judge correction — cost in R is convex in 1/(ATR/price), so the median
understates the portfolio aggregate). Measured ATR/price at v3's own entries: median **1.29%**,
IQR 0.98%–1.76%.

| Round trip | quoted spread | **cost in R (median ATR/price)** | **cost in R (mean)** | **increment over today** |
|---|---|---|---|---|
| **11.0 bps (in force)** | 5 bps | **0.0568R** | **0.060R** (IQR 0.042–0.075) | — |
| 26 bps | 20 bps | 0.1344R | ≈0.142R | **+0.0777R** |
| 66 bps | 60 bps | 0.3411R | ≈0.360R | **+0.2849R** |

**Restated as increments, not gross costs (accepted correction).** The published expectancies
are **already net of 11.0 bps**, so comparing a gross cost against them double-counts. At 26
bps round trip v3's OOS expectancy becomes ≈ **+0.229R** and gate 4's required n rises 140 →
**262** (of 319 held); at 66 bps it becomes ≈ **+0.022R** and gate 4 is effectively
unreachable. The claim that a 5× spread "exceeds the whole OOS expectancy" is withdrawn: it
**erodes** it to near zero.

**Three consequences.**
1. **Map §0.4's 0.037R understates this family's modelled cost by ~50%.** Every downstream use
   of 0.037R for `trend_continuation` should be re-derived at **0.057R (median) / 0.060R
   (mean)**. This is a program-level correction, not a v3 one.
2. *(sealed-informed — disposition only, R1)* **The snapshot-3 sealed shortfall is roughly half
   of one trade's modelled cost**: 0.0294 / 0.0568 = **52%** at the median, **49%** at the mean.
   A change sized to close that number is targeting half a trade's frictions.
3. **This is a live constraint on Route A**, not a footnote — a 150-name universe outside the
   mega-cap/ETF set plausibly quotes wider than 5 bps flat.

**Labelling correction (§C.3).** The 26 / 66 bps figures satisfy §4.2 item 8 verbatim, but
under the map's own formula `round_trip = 2 × (3.0 + spread_bps/2)` they correspond to **20 and
60 bps quoted** (4× and 12× the modelled 5 bps), not "2× and 5× the modelled spread". The map's
label needs correcting alongside its reference-ATR figure.

---

## 9. Variant budget, stopping rule, and the search count

### 9.1 Variants

**Strategy variants proposed by this design: 0. Variants spent across all three angles to
date: 0.** No new `evaluate()` was written or run by any angle; every measurement is a
re-pricing or a re-run of the two already-shipped configurations. **0 `StrategyVersion` rows,
0 sealed tests, 0 promotion evaluations, 0 database writes.**

**Whole-strategy budget across all angles combined, pre-registered:**

- **Recommended: 0.**
- **Contingent maximum: 1** — V-A′ only, and only if **D4 clears the §12.2 bar** or the
  operator overrules this design in writing.
- **Hard cap: one v0.2.0, ever.** If it fails any gate, the lane closes with a documented fail
  stating the variant count and the look number. **There is no v0.3.0.** A second variant would
  make the survivor's bootstrap CI optimistic by roughly the selection it survived (R5).
- **Gate 5's grid is a robustness test, not a candidate pool: its best cell may never be
  promoted into the shipped parameter set.**
- **Route A is not a variant** and does not consume this budget — but it does consume a look
  (§12.5).
- **Symmetric commitment (R5), recorded before any number is seen:** if V-A′ is run and returns
  a favourable point estimate that does not clear the pre-registered bar, **that is not a
  finding and must not be reported as one.**

### 9.2 The diagnostic-search count — disclosed because the variant count alone understates it

R5's purpose is that a later reader can see the size of the search. The variant count of 0 is
literally true and materially incomplete. **Pre-sealed conditioner and counterfactual searches
run on this strategy family to date:**

| Source | Searches |
|---|---|
| `v3_duration_exits.md` | duration buckets, exit-reason mix, matched-pair leash, within-stop duration buckets — **4 families** |
| `v3_atr_at_exit.md` | ATR@exit/@entry distribution, v3−v2 median, terciles (IS / OOS / within-stop), entry-time ATR(14)/ATR(50) terciles — **4 families** |
| `clustered_bootstrap_all.md` | month-block re-analysis — **1** |
| exits & risk angle | MFE/MAE distributions; time-stop ceiling; entry-bar bucket; **~32 trailing-bracket cells** (4 (a,b) × 2 cuts × 4 snapshots); **~56 tighter-target cells** (7 levels × 2 cuts × 4 snapshots) — **≈88 counterfactual cells, none adopted** |
| signal quality & regime angle | **15 conditioners × 4 snapshots × 2 cuts = 120 screens**, plus 3 threshold re-runs and 9 grid re-runs — **none adopted** |
| **This design (D4)** | **6 pre-registered cells**, fixed in §12.2 before any run |

**Consequence, stated plainly:** a nominal 2 SE bar carries no multiplicity adjustment, and
after ~20 search families and 200+ cells the family-wise false-positive probability at that bar
is far above 5%. That is why (i) the 1.36–1.61 SE survivor is discounted rather than rounded
up, and (ii) **D4's bar is deliberately set above 2 SE** (§12.2). Raising an *evidentiary* bar
is not an R4 gate change and is never a weakening.

---

## 10. Sealed-look accounting

**This design consumes zero sealed looks.** No `StrategyVersion` row is created, no snapshot is
introduced, no `evaluate_promotion` is run — and even if one were run against snapshot 3,
`_get_or_create_sealed_test` returns the locked row (`promotion.py:376-385`) and the unique
constraint on `(strategy_version_id, dataset_snapshot_id)` (`db/models/research.py:263`)
guarantees no new draw.

**The §0.1 ledger, reproduced in full and re-verified read-only for this document**
(`strategy_sealed_test` = 20 rows, exactly 4 per version for versions 2–6):

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| **3** | **`trend_continuation.medium_swing`** | **id 2: +0.0109R / 98 ✅** | **id 7: +0.0109R / 98 ✅** | **id 12: −0.0294R / 95 ❌** | **id 17: +0.0109R / 98 ✅** |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |

Windows: 2025-09-07 → 2026-09-07 (snap 1); 2025-09-08 → 2026-09-08 (snaps 2–4). v3's snapshot-3
row records n = 95, expectancy −0.0294R, hit rate 0.379, profit factor 0.957, Sharpe −0.187,
maxDD 8.906%, **`turnover_per_year` = 95.07** (verified — this is turnover, *not* "95.07 round
trips"; the trade count is 95). Sealed **iid** SEs at the measured pre-sealed sd 1.7259:
n = 95 → SE **0.1771**, z = **−0.166**; n = 98 → SE **0.1743**, z = **+0.063**. These are iid;
clustering would widen them by a factor that has **not** been measured on the sealed sample and
is not imputed (§C.2, R1).

### 10.1 The look-number convention — resolved to one number

The program's own documents number the same future event three different ways. **This design
adopts the binding brief and map §4.2 item 10 and applies it everywhere:**

> **Baseline k = 5** (four locked sealed rows per version, one per snapshot). **The next sealed
> draw for this family — Route A or Route B, whichever comes first — is look 6.** A second
> v0.2.0 after a Route B is look 7 only if no Route A intervened. **Route A is a look for every
> version simultaneously**, because a new snapshot mints a fresh sealed test per version.

**Under this design, none of it moves: 0 looks added, k stays 5.**

**Operator reconciliation item (§14):** map **R2** and **§2.1 lever 1** say a v0.2.0 sealing on
snapshot 3 is *"the fifth look"*; map **§4.2 item 10** says the same draw is *"look 6"*;
`pipeline_hardening_spec.md` §4 implements a mechanical counter as `k_prior = 4`,
`this_look = 5`. The **verified fact** is four locked rows per version. The three documents must
be reconciled before any report ships, or the look number in the final report is disputable.

### 10.2 Lead snapshot, pre-registered

**Snapshot 3**, because it is the **only** snapshot on which gate 8 `data_quality_and_leakage`
passes for any version — snapshots 1 and 2 fail `validate_daily` on META's 90 missing sessions
(6.9%) and snapshot 4 fails because `META_CONT` carries source `continuity_bridge:1`, not
`massive`. **The choice is forced by a pre-sealed data-quality gate, not selected after seeing
gate 9.** All four sealed draws are disclosed alongside it in every table, with an SE beside
every sealed number, and the report must state that v3 has never had an all-gates pass on any
snapshot.

---

## 11. Null option — which is the recommendation

### 11.1 D1 — the documented "does not pass"

`docs/research/results/trend_continuation_medium_swing--does_not_pass.md`, carrying at minimum:

1. **The verdict, stated precisely.** *"`trend_continuation.medium_swing` v0.1.0 does not pass
   promotion on dataset snapshot 3 (`universe_24_ex_meta`). It fails one gate — gate 9
   `sealed_final_test`, at −0.0294R on 95 trades. It has never passed all gates on any
   snapshot: on snapshots 1, 2 and 4 gate 9 passes at +0.0109R on 98 trades but gate 8 fails.
   Because sealed tests are locked per (version, snapshot), **this version can never pass on
   snapshot 3.**"*
2. **The full §10 ledger** — four draws with ids, windows, counts and **iid SEs**, with the
   clustering caveat stated.
3. **The §5.1 gate table** with trade sets tagged, gate 4 as a **required n** (140/142 against
   319) *and* its month-block counterpart (required +0.3497R, n ≈ 426), gate 6's unbucketed
   count (123, warmup 123, no-proxy-bar 0), and gate 7 flagged as computed over all pre-sealed
   trades despite its docstring.
4. **The power statement**, with the normal approximation named and — replacing at least the
   true-zero and true-+0.3064R rows — a bootstrap over the actual skewed pre-sealed trade
   distribution.
5. **The refuted mechanisms** under the §B numbering, each with its own pre-registered
   falsification condition and the number that met it, so a future reader cannot re-propose
   them unknowingly. Including: **the four conditioners that clear 2 SE in sample and reverse
   out of sample.**
6. **The §3.4 counterweight** — the month-block CI low with deff 3.04 (and v2's / v5's, so the
   statistic is not used one-sidedly), the sealed year's −1.65 to −1.88 z, the gate-5 grid
   maximum caveat, and the unmeasured H14 bias.
7. **The §8 cost arithmetic**, including the 0.037R → 0.057R/0.060R correction and the
   increment-not-gross restatement.
8. **The variant count (0), the diagnostic-search count (§9.2), the look number (k = 5, none
   added), and the §4.3 qualifying/non-qualifying re-run trigger table**, so the next person
   inherits the pre-registration rather than re-deriving it.
9. **D4's result**, whichever way it goes, with its pre-registration reproduced verbatim.
10. **What is *not* being claimed:** not that v3 is unprofitable; **not that it is superior to
    v2** (the difference is 0.33 SE); not that it should be deleted. It stays `EXPERIMENTAL`,
    keeps being scanned, and remains eligible for Route A.

### 11.2 D2 / D3 — the shadow-confirmation plan, rebuilt

**The structural constraint first.** FACT: v3 is `EXPERIMENTAL`, so no live-paper *ledger*
evidence can ever accrue — `assert_auto_simulate_allowed` raises (`paper/ledger.py:500-502`)
and `plan_alerts` gates on paper-approved status. A "live-paper confirmation plan" in the
`PaperTrade` sense would require promotion first, which is exactly what gate 9 blocks.
**But a shadow signal stream already exists at zero risk:** `scan.py:110-111` selects strategies
by **horizon, not status**, and `:298` persists both `PASSED` and `NO_TRADE` drafts as
`Candidate` rows; MEDIUM_SWING is scanned because v5 is PAPER_APPROVED on it. Version 3 already
holds 199 candidate rows, of which 3 are on snapshot 3 / source `massive`.

| Item | Pre-registration |
|---|---|
| **Population** | Every `candidate` row with `strategy_version_id = 3` from a scan run with `dataset_snapshot_id = 3` and `source = 'massive'`, **from 2026-09-11 forward** (today's 3 rows excluded as pre-registration-contaminated). **De-duplication is defined before the first row is counted: one entry per `(symbol, date)`** — scans run more than once per calendar day (scan_run ids 32 and 38 both dated 2026-09-10), so raw candidate rows are not trades. `NO_TRADE` desk drafts are included, because the research question is the rule's expectancy, not the desk's filter — and that inclusion rule is fixed here, before any outcome is known. |
| **Simulation rule** | Mirror the engine exactly: **fill unconditionally at the next session's open** (`entry_zone_low/high` are audit-only, **not** a fill condition); stop at `invalidation_level`; target at `target_level`; 40-session time stop; one open position per symbol; unchanged `CostModel` → 11.0 bps round trip |
| **R denominator** | `risk_per_share = abs(entry_fill − invalidation_level)`, matching `engine.py:111`. **Not** the signal-bar risk — otherwise every shadow R is on a different scale from the backtest R it is compared to |
| **Missing data** | A trade whose next-session open is unavailable is reported as a **gap**, never dropped; every read-out reports scan sessions covered and missed |
| **Metric** | Per-trade R and its empirical SE; equity curve; exit-reason mix; realised ATR/price against the 1.29% cost assumption |
| **Read-outs** | Exactly **two**, both **n-triggered only**: read-out 1 at **n ≥ 95**, read-out 2 at **n ≥ 220**. **No interim read will be produced, circulated, or cited.** (The "periodic read-outs" language of the source proposal is deleted as an optional-stopping surface.) |
| **Arrival rate** | **HYPOTHESIS, not a schedule input:** ≈119 de-duplicated signals/year, transferred from the *backtest* trade rate (4.96 per symbol-year × 24) to the *scan-candidate* process, which is a different generating process and has produced 3 rows over 2 scan days so far. Calendar triggers are therefore **not** used until an arrival rate has been measured on the stream itself |
| **Power** | iid SE at n = 95 is 0.177R (cannot separate +0.3064 from zero); at n = 220 it is 0.116R. **The stream's own design effect has not been measured and is not imputed**; the first read-out must report a block-resampled SE computed on the stream before any resolving-power claim is made |
| **What it can conclude** | (i) a realised expectancy ≥ 2 SE **below** +0.3064R strengthens the documented fail; (ii) a realised expectancy consistent with +0.3064R is **context only** and, under R8, is never an argument for promotion; (iii) exit-mix or ATR/price divergence from the backtest is a model-fidelity finding — **and it may motivate a change to *reporting* or to *disclosed cost assumptions* only. Under R8 and R1 it may never motivate a rule, parameter, filter, entry, exit or universe change to any strategy version.** |
| **What it can never do** | Promote, re-promote, or motivate a v0.2.0. FACT: no code path re-promotes from live evidence (`health_monitor.py:100-113` is one-way down) |
| **Disclosed dependency** | If v5 were downgraded, MEDIUM_SWING drops out of `approved_horizons()` and the stream **stops** |
| **Implementation** | D3 is a standalone read-only script — no `src/` module, no migration, no DB write, no API call — emitting dated markdown + JSON under `docs/research/` |

### 11.3 If D4 clears its bar, or the operator overrules

Then V-A′ (§2.2) is implemented as the **one** variant, under §12's pre-registration and §13's
checklist, and D1 is written anyway — with two additions: the variant's full pre-sealed record
per R5, and the statement that the family is now at look 6.

---

## 12. Consolidated pre-registration — fixed BEFORE any run

Everything in this section is fixed now and may not be re-specified after any result is seen.

### 12.1 Gate-5 axes

- **Under the recommendation:** no axis added; grid stays `sma_fast [15,20,25] × stop_atr
  [1.2,1.5,1.8]`; the mechanical no-op check of §6.1(a) runs before any future evaluation of
  this family on any snapshot.
- **Under V-A′:** `trail_arm_r [0.75,1.0,1.25]` × `trail_lock_r [0.25,0.5,0.75]` ×
  `trail_give_r [0.5,1.0,1.5]` × `stop_atr [1.2,1.5,1.8]` = 81 cells, with the
  `_sensitivity_plan` version-dispatch change in the same diff and the §6.2 no-op and
  baseline/neighbour assertions blocking.
- **Never:** widening the shared `trend_continuation` prefix grid from a medium-swing proposal;
  putting an axis declaration on `StrategySpec`.

### 12.2 D4 — the ratcheting-trail closure diagnostic, pre-registered in full

**Rule family (fixed):** arm when open profit reaches `aR` on a **closed** bar, effective from
the **next** bar; thereafter the effective stop is `max(entry + bR, peak_favourable_price −
g·R)`, ratcheting upward only; R is the engine's `risk_per_share`.
**Cells (fixed, and these six are the entire search):** `a ∈ {1.0, 1.5}` × `b = 0.5` ×
`g ∈ {0.5, 1.0, 1.5}` = **6 cells**. No seventh cell may be tried.
**Method:** an exact **path-level replay** over the same `PriceSeries` and the same
`CostModel`, in a scratch script outside `src/`, read-only, on the **pre-sealed span only**, on
**all four snapshots**, on **both cuts**. Two forms, both reported: (i) trade-set-fixed
(paired, exact paired SE — the inference instrument) and (ii) full re-run with the trade set
free (the reality check, since an earlier exit frees later bars).
**Also computed, because it is the statistic the mechanism argument actually needs and it has
never been measured:** among target exits, the distribution of the minimum excursion from the
**first bar on which MFE ≥ a**, per cell, with a paired SE.

**The bar to re-open the exits lane — all five must hold** (set above the nominal 2 SE because
of the ~20 prior search families, §9.2; raising an evidentiary bar is not an R4 change):

1. paired OOS difference **≥ +2 SE on all four snapshots**;
2. **≥ +2 SE under calendar-month block resampling** on snapshot 3;
3. positive in **at least 3 of the 4** walk-forward folds;
4. the trade-set-free re-run reproduces the sign with a point estimate **within 1 SE** of the
   paired estimate;
5. the best cell is **not adjacent to a sign change** in the 6-cell grid.

**If it clears:** exactly one variant, V-A′, under §9.1's hard cap.
**If it does not clear:** the exits-and-risk lane is **closed permanently** for this family;
D1 records the closure with the numbers.
**Symmetric commitment:** a favourable point estimate that fails any of the five clauses is
**not a finding** and must not be reported as one. **Bounds are reported in R, never in SE.**

### 12.3 Falsification criteria, per snapshot

| # | Criterion (re-opens the lane) | Required on |
|---|---|---|
| **F1′** | D4's §12.2 five-clause bar | all four snapshots + month-block + folds |
| **F2** | Any target level in [0.75R, 1.75R] beats the incumbent by ≥ 2 SE **paired and netted against the 2.0R control cell** on OOS | all four |
| **F3** | The share of v3 pre-sealed trades exiting on `time_stop` exceeds **5%** (today 0.72–0.75%) | any dataset |
| **F4** | A gate-5 grid on a better-powered snapshot shows `stop_atr` 1.8 or 1.2 beating 1.5 by ≥ 2 SE on OOS | all four |
| **F5** | Any entry-side conditioner reaches ≥ 2 SE on the **OOS** cut on all four snapshots **and** in ≥ 2 of 4 folds **and** survives month-block resampling **and** is not shared with v2 (v3−v2 differential stated **paired**, with its minimum detectable effect) | all four |
| **F6** | Any perturbation whose **realised, measured** effect (not a bound) lies above the incumbent by ≥ 2 SE paired on OOS on all four snapshots — this is the falsifier of **H13** itself | all four |

**Standing requirement carried from the judges:** any v3−v2 differential must state whether it
is paired or unpaired and give the minimum detectable effect at 2 SE for the chosen estimator
at the available n on each snapshot. If that minimum exceeds any plausible effect given the
verbatim-shared entry rule, the criterion must be withdrawn rather than pre-registered as
unreachable.

### 12.4 Variant budget and stopping rule — whole strategy, all angles

**0 recommended; contingent maximum 1 (V-A′ only); hard cap one v0.2.0 ever, no v0.3.0.** Full
statement in §9.1. Route A is not a variant.

### 12.5 Sealed-look accounting

**Baseline k = 5. This design adds 0 looks.** The next draw — Route A or Route B, whichever
comes first — is **look 6**; a v0.2.0 after a Route A is look 7. **Route A is one look for each
of five versions simultaneously**, so its results must be reported together: all five estimates
and SEs at once, and **no single version's pass/fail bit read in isolation**. Any pass is
reported as *"passed on look k"* with the multiple-testing discount stated. The
convention conflict across three program documents is an operator reconciliation item (§10.1).

### 12.6 Lead snapshot

**Snapshot 3**, forced by gate 8 (§10.2), with all four draws disclosed alongside and an SE
beside every sealed number.

---

## 13. Implementation and validation checklist

### 13.1 Under the recommendation

**Files written:** documents only.

| Path | Nature |
|---|---|
| `docs/research/designs/trend_continuation_medium_swing.md` | this design |
| `docs/research/results/trend_continuation_medium_swing--does_not_pass.md` | **D1** |
| `docs/research/results/trend_continuation_medium_swing--shadow_plan.md` | **D2** |
| a standalone read-only script outside `src/` (+ dated md/json under `docs/research/`) | **D3** |
| a standalone read-only script outside `src/` (+ `docs/research/diagnostics/v3_trailing_pathlevel.md` / `.json`) | **D4** |

**Files NOT touched:** everything under `src/` and `tests/`.

**Validation phase — exact commands, on a SCRATCH database.** The purpose is threefold: prove
the documented gate table reproduces exactly; prove that re-running the writing entry point on
the unchanged v0.1.0 creates **no new sealed test** (the claim D1 makes); and prove the two
live approvals' spec hashes are undisturbed.

```bash
# 0. Scratch copy — the live DB is never written by anything below.
export SCRATCH="$TMPDIR/scratch-tcms.sqlite"
cp /Users/louisbrailey/signal-forge/data/signalforge.sqlite "$SCRATCH"
export DATABASE_URL="sqlite+pysqlite:///$SCRATCH"
export SF=/Users/louisbrailey/signal-forge/.venv/bin

# 1. Record the pre-state. NOTE (verified): there is NO `approved_scope` table — an
#    ApprovedScope is a dataclass derived at read time from PASSING
#    strategy_promotion_evaluation rows (approval_scope.py:36-66). The R7b pre-state is
#    therefore the set of passing evaluations and their dataset_snapshot_ids.
$SF/python - <<'PY'
import os, sqlite3
c = sqlite3.connect(os.environ["SCRATCH"])
for t in ("strategy_sealed_test","strategy_promotion_evaluation","strategy_version"):
    print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
for r in c.execute("select id,strategy_version_id,dataset_snapshot_id,passed from strategy_sealed_test order by id"):
    print(r)
print("--- R7b: passing evaluations (these ARE the scopes) ---")
for r in c.execute("select id,strategy_version_id,dataset_snapshot_id,spec_json_hash "
                   "from strategy_promotion_evaluation where passed=1 order by strategy_version_id,id"):
    print(r)
PY

# 2. Spec-hash non-disturbance for the two LIVE approvals (v2, v5) — asserted mechanically
#    against the hashes stored on their passing evaluations (v2: 20, 32; v5: 23, 35), not
#    eyeballed. Verified present in strategy_promotion_evaluation.spec_json_hash.
$SF/python - <<'PY'
import os, sqlite3
from signalforge.research.persistence import spec_json_hash
from signalforge.research.strategies import default_strategies
STORED = {  # verified read-only for this design, 2026-09-10
    "trend_continuation.short_swing":   "2ed9743170bd3bbdb450ea03a004a7ffaeb64ccbbe6075db312ffd544072f382",
    "relative_strength.medium_swing":   "dfe696b662dd02b8fa3a02ce5b987c6eade84a40d88c1a2d8d52e206cb6f6c32",
}
c = sqlite3.connect(os.environ["SCRATCH"])
db = dict(c.execute("select strategy_version_id, spec_json_hash from strategy_promotion_evaluation "
                    "where id in (20,23,32,35)").fetchall())
assert db[2] == STORED["trend_continuation.short_swing"], db
assert db[5] == STORED["relative_strength.medium_swing"], db
for s in default_strategies():
    h = spec_json_hash(s.spec())
    if s.spec().name in STORED:
        assert h == STORED[s.spec().name], f"LIVE APPROVAL SCOPE BROKEN: {s.spec().name} {h}"
    print(s.spec().name, s.spec().version, h[:16])
print("live approval spec hashes undisturbed")
PY

# 3. Re-run the writing entry point on the UNCHANGED v0.1.0, on the scratch DB only.
$SF/signalforge evaluate-promotion --strategy trend_continuation.medium_swing --dataset ex_meta

# 4. Assert the invariants the documented fail depends on.
$SF/python - <<'PY'
import os, sqlite3
c = sqlite3.connect(os.environ["SCRATCH"])
n_sealed = c.execute("select count(*) from strategy_sealed_test").fetchone()[0]
assert n_sealed == 20, f"a new sealed test was created: {n_sealed}"          # no new look
n_ver = c.execute("select count(*) from strategy_version").fetchone()[0]
assert n_ver == 6, f"a new StrategyVersion row was created: {n_ver}"         # no new version
exp, = c.execute("select json_extract(metrics_json,'$.expectancy_r') "
                 "from strategy_sealed_test where id=12").fetchone()          # query form verified
assert abs(exp + 0.0294) < 1e-9, exp                                          # gate 9 replayed, not recomputed
print("sealed rows:", n_sealed, "| versions:", n_ver, "| id 12 expectancy:", exp)
PY

# 5. Discard the scratch DB.
rm -f "$SCRATCH"
```

**Note on the strategy filter:** `evaluate-promotion --strategy` matches with `startswith` on
`BaselineStrategy.key`, and a v0.2.0 medium_swing would carry the **same key**, so the filter
selects both versions. That is the same absence of a version component in the key that forces
the `_sensitivity_plan` dispatch change in §6.2.

**D4 runs read-only against the live DB** (in-process `run_strategy_over_universe` /
`run_backtest` contain no `session.add` / `flush` / `commit`) and needs no scratch copy; if any
future D4 variant touches a writing entry point it moves to the scratch path above.

### 13.2 Additional, blocking checklist if V-A′ is ever authorised

1. **Per-instance version**, with **all three** consumers routed through `self.version`
   (`trend_continuation.py:46`, `:81`, and the registry's `versioned_key`). Assert
   `current_spec_json_hash(session, <v2 approved version row>)` is **unchanged** and
   `scan_scope_matches` still returns `True` for the live v2 scan.
2. **Conditional spec strings** — `rule_definition` / `feature_definitions` extended only when
   the trailing behaviour is active.
3. **Engine inertness regression** — with the trail fields `None`, snapshot 3 reproduces
   v2 = 1,169 / +0.2648R and v3 = 1,071 / +0.3064R **bit-for-bit**.
4. **No same-bar arm-and-fire** — asserted by test; `assert_no_lookahead` cannot see this.
5. **`_sensitivity_plan` version dispatch** changed in the same diff; assert v2's and v3
   v0.1.0's sensitivity reports still contain a baseline point and ≥ 4 neighbours.
6. **No-op grid check** — ≥ 7 of 9 cells differ per axis by > 1e-6; no two cells byte-identical
   in `(n_trades, oos_expectancy_r)`; and the strategy actually **emits** the trail fields.
7. **Sealed-test staleness guard (R3, map §4.3)** — assert the v0.2.0's
   `StrategySealedTest.strategy_version_id` is a row **created by this run**, not replayed.
8. **R7b** — re-record `scopes[0]` state before and after (§5.4).
9. **Leakage** — `assert_no_lookahead` coverage extended to the v0.2.0 instance; gate 8's
   `leakage self-check: clean` must cover the new rule.
10. **Report the pass as "passed on look 6"**, with all four prior draws and the variant count.

---

## 14. What the operator must approve, and what is reported if it fails

### 14.1 Decisions required

| # | Decision | Why it is the operator's |
|---|---|---|
| **1** | **Accept the null option** — no change to `src/`, D1 published, k stays 5 | It is the disposition of a strategy the program was chartered to "bring to full operation"; declaring a documented fail is a program-level call |
| **2** | **Authorise D4** (read-only, pre-sealed, zero looks, zero variants, zero writes, no API) | It is the last open lever and the last search this family gets. It also re-opens a lane three documents had recorded as closed, so the operator should know it is being re-opened deliberately and under a stricter-than-nominal bar |
| **3** | **H14 — the engine entry-bar risk-unit collapse.** Re-price v2's approval evidence to fix it, or document it as a known bias and leave the live approval on the numbers it was granted on? **Prerequisite: the size of the distortion has not been measured** — the 106/118 entry-bar trades must be re-priced against a stable risk unit (`stop_atr × ATR` at signal time) with a paired SE on all four snapshots, before this can be decided. That re-pricing is read-only | Any fix re-prices the evidence underpinning a **live probation** without changing any `spec_json_hash` |
| **4** | **W1 universe expansion — 100–300 paced provider API calls (~20–60 min).** Required for Route A. **Not requested by this design**, and Route A must not be built *in order to* give v3 another sealed draw | Provider API spend, and it creates a fresh sealed test for **every** version at once (§12.5) |
| **5** | **Gate 7's docstring/code divergence** (`config/research.py:111-113` says OOS; `promotion.py:775` computes all pre-sealed) — fix the comment or the code | R4-adjacent; changing the code would change a gate for two live strategies |
| **6** | **Sealed-look numbering reconciliation** across map R2 / §2.1, map §4.2 item 10, and `pipeline_hardening_spec.md` §4 (§10.1) | Three documents number the same event differently; the report's look number is disputable until one is authoritative |
| **7** | **Map §0.4 corrections** — reference cost 0.037R → 0.057R/0.060R for the trend family, and the "2×/5× spread" mislabel (§8) | Program-level document correction affecting every strategy's cost statement |
| **8** | **Only if D4 clears §12.2's bar, or by explicit written override: authorise V-A′** as the single variant | It spends look 6, touches a shared engine surface used by two live approvals, and is capped at one attempt |

### 14.2 What is reported if it fails

- **If D4 does not clear the bar** (the pre-registered expectation): the exits-and-risk lane
  closes permanently, D1 ships with D4's numbers and its pre-registration reproduced verbatim,
  the variant count stays **0**, the diagnostic-search count is disclosed, and **k stays 5**.
  This is the expected outcome and it is a complete deliverable, not a failure to deliver.
- **If D4 clears and V-A′ is authorised and then fails any gate:** the lane closes with a
  documented fail stating the variant count (**1**), the look number (**6**), the full
  pre-sealed record of the variant (what changed, why, its OOS expectancy and CI, iid and
  month-block), and the fact that **there will be no v0.3.0**.
- **If V-A′ passes:** it is reported as *"passed on look 6"*, never as an unqualified pass, with
  all four prior sealed draws, the variant count, the diagnostic-search count, the
  multiple-testing discount, and the R7b re-check.
- **If Route A is ever run:** all five versions' sealed estimates and SEs are reported
  together; **no single version's pass/fail bit is read in isolation**; gate 9's bit remains
  binding; and the R7b precondition of §5.4 is executed before and after.
- **In every branch:** the report states what is *not* being claimed — that v3 is not shown to
  be unprofitable, that it is **not** shown to be better than the live v2 (0.33 SE), and that
  it stays `EXPERIMENTAL` and eligible for Route A.

---

*Read-only: no strategy code, no configuration, no database row, no gate threshold and no
service was changed in producing this document. Every number is a query result, a `file:line`
citation verified for this synthesis, a figure carried forward from a committed diagnostic or
a judged proposal (cited), or an arithmetic derivation whose inputs are those.*
