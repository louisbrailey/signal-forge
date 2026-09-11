# Orchestrator decisions — 2026-09-10

Record of decisions taken by the orchestrator across the volatility_breakout,
mean_reversion, and intraday_orb design documents and the open questions they raised
against `STRATEGY_COMPLETION_MAP.md`. These decisions are binding; they are not
re-litigated by any downstream agent. Nothing here authorises any write to the live
database — see the hard rules in effect for this program.

## 1. Look-count convention

**Decision:** k = the number of existing `StrategySealedTest` rows for the strategy
**family** (all versions, all snapshots combined), not per-version and not per-angle.
The next sealed evaluation for that family is look **k+1**. Today's ledger has 20
sealed-test rows across versions 2–6 (§0.1 of the map), giving k = 5 uniformly across
every strategy family currently in scope; the next sealed test any of them takes —
whichever family it belongs to — is **look 6**.

**Rationale.** Three independent design documents converged on the same fault and
proposed the same fix, which is itself evidence the convention is the right one to
adopt rather than litigate per-document. `volatility_breakout` design §13 Q2 flags
that MAP §0.1/R2 ("look 5") and MAP §4.2 item 10 ("look 6") disagree by one and
states explicitly that "nine proposals write ledgers against the same baseline; they
will not reconcile until this is named." `mean_reversion` design §14.2 Q3 names the
same conflict, adds that the hardening spec independently adopted `k_prior = 4,
this_look = 5` (a third, incompatible framing), and recommends picking one before any
counter ships. `intraday_orb` design §A.1 J1-10 treats it as an accepted judge
defect, locates the contradiction precisely in the map's own text
(`MAP.md:69` and `:341` say "look 5", `:1321-1322` says "look 6"), and adopts "k = 5
baseline, next = look 6" as its own report's convention, with version 1's own count
disclosed alongside. The map's §4.2 item 10 was already internally consistent with
this convention (k=5, next=look 6); §0.1 and R2 in §1 were not, and are corrected by
this decision. This is a counting-defect fix under R4 (STRATEGY_COMPLETION_MAP.md §1)
— it makes the look-count accounting more searching, not less, and touches no gate
threshold.

## 2. Spread stress convention

**Decision:** the mandatory spread-sensitivity check on any expanded-snapshot run
(MAP §4.2 item 8, §3(a)) reports at **26 and 66 bps round trip**, stated alongside the
implied quoted spread they represent (≈4× and ≈12× the modelled 5 bps quoted spread
in `engine.py:90`).

**Rationale.** The map's own §0.4 and §4.2 item 10 already used "26 bps and 66 bps
round trip," but §4.2 item 8 separately described the same requirement as "2× and 5×
the modelled spread," which is arithmetically wrong on its own terms (5 bps × 2 = 10
bps, not 26; 5 bps × 5 = 25 bps, not 66) and was flagged as such. `volatility_breakout`
design §13 Q1 states the exact numeric conflict: "MAP §0.4 names 26 and 66 bps; W1
§7.1 reads '2×/5×' as 16 and 31 bps. All four are reported until the operator picks
one." `mean_reversion` design §14.2 Q6 independently derives the correct multiple
from the quoted spread and asks to "confirm that MAP §4.2 item 8's '2× and 5× the
modelled spread (26 and 66 bps round trip)' is understood as 4× and 12× the modelled
5.0 bps quoted spread," recommending the map's wording be fixed while the 26/66 bps
figures stay the binding requirement. Adopting 26/66 bps as the number and stating
the true multiple resolves the conflict by correcting a wording error, not by
changing the requirement — the bps figures were never in dispute, only their
arithmetic gloss.

## 3. Gate 7 docstring correction

**Decision:** `promotion.py`'s gate 7 docstring is corrected to describe what the
code actually computes — all pre-sealed trades, not out-of-sample trades. The code
in `promotion.py:775` is unchanged.

**Rationale.** Both `volatility_breakout` design §13 Q3 and `mean_reversion` design
§14.2 Q5 independently identify the same divergence: `config/research.py:111-113`'s
docstring says OOS while `promotion.py:775` computes all pre-sealed trades, and both
recommend fixing the docstring rather than the code, since changing the code would
alter a gate's behaviour under R4 (not permitted without the disclosure-and-strictly-
more-searching test, and no such case is made here). This is documentation brought
into line with verified behaviour; it changes no threshold, no computation, and no
sealed-test outcome.

## 4. Engine risk-unit fix (P1, opt-in `stop_anchor_blend`) — deferred

**Decision:** the engine risk-unit correctness fix proposed in `mean_reversion`
design §13.2 (opt-in per strategy, no `VERSION` bump, zero sealed looks) is
**deferred**. It is documented as a known, quantified defect in the engine and is not
implemented as part of this design cycle.

**Rationale.** `mean_reversion` design §14.2 Q1 recommends "Yes" — the defect is
verified and real (four `stop` exits booked as wins; a 0.0043-ATR risk unit
rendering 5.5 bps as −3.099R; median realised risk 2.127 ATR against an intended
2.000 ATR) and distorts R-accounting for every strategy, including both live
PAPER_APPROVED strategies. But it is explicitly framed as a correctness fix, not an
edge (invariant value +0.0079R at 1.74 SE — not a result to act on), and its release
is gated behind seven separate release-gate checks in §13.2 that have not been run.
Given the live paper-trading probation currently in effect and the binding
requirement that the two PAPER_APPROVED strategies (version ids 2 and 5) keep a
byte-identical `spec_json_hash`, deferring an engine change with cross-strategy
blast radius until it can be evaluated deliberately, on its own cycle, is the
conservative choice. Per the design's own "if declined" branch (§14.2), the defect
is recorded as a known, quantified distortion of R-accounting affecting all
strategies and is to be re-raised when the next engine change is proposed.

## 5. W1 universe re-derivation on the pre-sealed liquidity window

**Decision:** W1-SEL(2) symbol selection is re-derived using the median of
`close × volume` over the 60 most recent **pre-sealed** `massive_grouped` sessions,
2025-06-11 → 2025-09-05 (A0, approved), instead of the original 2026-06-12 →
2026-09-08 window. The resulting ~126-call backfill (A1) is approved and will be
executed by the orchestrator directly, not delegated to any agent. Stage B — the
sealed look for `volatility_breakout` v0.2.0 against the resulting expanded
snapshot — is **deferred** until Stage A evidence exists on the re-derived universe.

**Rationale.** `volatility_breakout` design §13 A0 states the reason directly: symbol
selection on the original window is chosen by how heavily each symbol traded
**inside the year gate 9 measures**, which contaminates the sealed test by
construction. Re-deriving on the pre-sealed window uses no new data and no API calls
and "can only make the universe less hindsight-favoured" — it is a correction to a
selection-leakage defect, not a threshold change, and is therefore permitted under
R4's carve-out for gate-integrity strengthening (STRATEGY_COMPLETION_MAP.md §1, R4).
A0 is marked blocking in the design precisely because, if declined, "gate 9's sealed
test is contaminated by construction." The backfill (A1) is unchanged from W1 §10.1
and is data-only (paced GETs, `source = "massive"`, no code or gate change), so it
carries no sealed-look cost and needs no further approval beyond execution
discipline; the orchestrator executes it directly rather than delegating it because
it is the one step in this chain that both writes to the live database's ingest
tables and gates whether Stage B can be attempted at all. Stage B stays deferred
because it is irreversible on approval (per A2, an `evaluate_promotion` pass writes
`PAPER_APPROVED` unconditionally and consumes a sealed look for the family,
`promotion.py:922, 943-952`) and should not be spent before Stage A evidence exists
to justify spending it.

---

*This document records decisions already taken by the orchestrator; it does not
authorise any additional action beyond what is stated above. No file under `src/`
was modified in producing it, no row in `data/signalforge.sqlite` was written, and
no sealed-look-consuming entry point was invoked.*
