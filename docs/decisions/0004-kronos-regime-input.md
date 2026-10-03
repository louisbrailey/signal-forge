# ADR 0004 — Kronos as a tighten-only regime input (NOT PROCEEDING)

- **Status:** **Closed — not proceeding (2026-10-03).** This proposal is withdrawn.
  Nothing in it was implemented, enabled or authorised, and nothing is awaiting
  engineering work. The import-linter contracts keeping Kronos off the decision path
  stay exactly as they are. See "Decision record" below. The original text is kept
  unchanged beneath it as the record of what was proposed.
- **Deciders:** Louis Brailey (operator). Decision: not proceeding, 2026-10-03.
- **Related:** `docs/decisions/0003-execution-layer.md` (style and boundary discipline),
  `src/signalforge/kronos/README.md`, import-linter contracts "Kronos is never an input
  to deterministic signals, risk, paper or execution" and "Kronos cannot reach trading,
  credentials, providers or alerts" (`pyproject.toml`), ARCHITECTURE.md S3.


## Decision record — not proceeding (2026-10-03)

**Decision.** The operator closes this proposal. Kronos is not integrated as a regime
input or in any other decision-path role under this ADR.

**Evidence.** The pre-registered forecast-skill study
(`docs/research/kronos/PREREGISTRATION_2026-10-03_kronos_skill.md`) was executed as
written: 160/160 windows, no failed calls, pilot calls retained. Report and data:
`docs/research/kronos/2026-10-02/`.

| Gate | Outcome |
|---|---|
| G1 pre-registration before inference | met |
| G2 skill (Tier A SPY, 12 origins) | **not met** — MAE ratio vs drift 1.04 (h=20), 1.25 (h=5); vs unchanged 1.34, 1.26; no Holm-adjusted p < 0.05 |
| G3 direction | **not met** — h=20 8/12, BH p = 0.77 |
| G4 calibration | not rejected at h=5 (5/12); h=20 coverage 3/12 against a 50% nominal band |
| G5 Tier B pooled (11 sector ETFs) | **not met** — ratio vs drift 1.22 (h=20), 1.26 (h=5, CI [1.09, 1.43], i.e. worse than drift) |
| G6–G10 | not started; not reachable without G2–G5 |

**Scope of the evidence.** The study addressed G1–G5 only, for one configuration
(Kronos-small, 128-bar context, 3 sampled paths, daily US-equity bars). It could not
have authorised this ADR even had it passed: a tighten-only filter still changes which
trades occur and needs its own validation (G6, G7).

**What this does not close.** Kronos remains available as the isolated research
dashboard and offline study tool. Investigating *why* this configuration shows no
skill (context length, sample count, model size, return-space metrics) is separate
research with its own pre-registration. Any future integration proposal is a **new
ADR** with new evidence; this one is not reopened or amended into acceptance.

## Context

`signalforge.kronos` is an isolated, offline historical-replay surface for
`NeoQuasar/Kronos-small`. Two import contracts make it structurally impossible for
research, risk, backtest, paper or execution code to import it, and for it to reach
trading, providers, alerts or the LLM layer. The dashboard shows per-window MAE beside
the unchanged baseline; the README states that pretraining overlap is unknown and that a
good replay is not a reason to promote anything.

The only place a forecast could conceivably be useful without becoming a trade signal is
the market-regime filter (`research.regime.RegimeState`), which already gates every
baseline strategy through `risk_off` / `risk_on`. This ADR scopes that single possibility
so narrowly that, even if accepted, the model could never make the system take a risk
it would not otherwise take.

## Decision scope (what would be built, if ever accepted)

1. **One field.** `RegimeState` gains one optional field, `kronos_tilt: bool | None`,
   derived from the stored SPY 20-session forecast at the regime's `as_of`. It is
   **tighten-only**: `risk_off` becomes `trend is BEAR or vol is HIGH or kronos_tilt is
   True`; `risk_on` is unchanged and can never be made true by the field. A missing or
   stale forecast yields `None`, which is identical to today's behaviour (fail-to-current,
   never fail-to-cautious and never fail-to-permissive).
2. **No inference on the decision path, ever.** The regime builder reads an append-only
   `kronos_forecast` table: `symbol`, `origin` (input_end), `horizon`, `predicted`,
   `lower`, `upper` (per bar, JSON), replay `id` digest, `model`, `weights_sha256`,
   `seed`, `samples`, runtime versions, `generated_at`. Rows are written only by the
   research study/backfill script (the same `service.replay` path) and are never updated
   or deleted. The reader is a pure function over rows with `origin <= as_of` and a
   maximum staleness; it imports nothing that can load a model.
3. **No look-ahead.** The reader selects the newest row whose `origin <= t` and whose
   `generated_at` precedes the regime evaluation; a forecast made after `t` for an origin
   before `t` is rejected (the replay id digest and `generated_at` make this checkable).
4. **Feature flag, default OFF.** `ResearchConfig.regime.kronos_tilt_enabled = False`
   (new `RegimeConfig` sub-model; `regime` would be added to `SCOPE_HASH_FIELDS`, so
   turning it on re-scopes every approval and forces the re-evaluation in §Promotion)
   plus a **pinned-weights-hash gate**: rows whose `weights_sha256` differs from the
   pinned value in config are ignored even when the flag is on.
5. **Exact contract amendment.** The forbidden contract stays. One edge is added to its
   `ignore_imports`: `signalforge.research.regime_kronos -> signalforge.kronos.features`,
   where `kronos.features` is a NEW inference-free module (pure row-to-tilt arithmetic, no
   import of `runtime`, `service` or `worker`). Safety tests would assert: (a) the
   `features` module imports nothing from `runtime`/`service`/`worker`/`subprocess`;
   (b) `research.regime_kronos` is the only research module importing anything under
   `kronos`; (c) with the flag off, `RegimeState` serialisation is byte-identical to
   today; (d) `risk_on` is unaffected under every value of `kronos_tilt`.

## Promotion

A strategy that consumes `kronos_tilt` is a **new strategy version**. It walks the full
ladder (grid → sealed look → paper probation → PAPER_APPROVED) with its own
pre-registration and its own sealed-look accounting. No existing approval is inherited,
no threshold is changed, and the tighten-only ablation (same version with the tilt forced
`None`) is a required comparison in its pre-registration.

## S3 discussion

Kronos is not `signalforge.llm`: it is a local, offline, deterministic-seed numeric model
with no prompt, no provider and no credentials. It nevertheless shares the S3 risk class
— an opaque learned model whose output could leak into a decision in a way nobody can
audit from the code. The mitigations here are therefore the S3 mitigations, made
structural: the decision path consumes **stored point-in-time numbers** (never a live
call), those numbers are **pinned to a weights hash** (a silent model change produces
ignored rows, not a changed decision), and the effect is **tighten-only** (the worst case
of a bad forecast is a missed trade, never an extra one). ADR 0003's principle that
"no LLM decides, shapes, ranks, sizes, times or describes an order" extends verbatim to
Kronos: it cannot shape, rank, size or time anything; it can only say "not today".

## What remains prohibited

- Any call to `kronos.runtime`, `kronos.service` or `kronos.worker` from `research`,
  `risk`, `backtest`, `paper` or `execution`, directly or through any hop.
- Any field that can set `risk_on`, raise a size, widen a stop, extend a hold, or rank
  candidates.
- Any per-symbol forecast on the decision path; only the SPY proxy, only horizon 20.
- Any update or delete on `kronos_forecast`; any row without a weights hash; any row
  whose runtime, seed or sample count differs from the pinned values.
- Any change to promotion thresholds, sealed-look rules, or `min_oos_regimes`.
- Any use before G1–G10 are all marked done in the table below by the operator.

## Consequences

- **Cost of being wrong is bounded by construction:** an uninformative tilt reduces
  participation and nothing else; the ablation in G6/G7 measures exactly that cost.
- **Backfill cost.** Weekly SPY h=20 origins over the ~4 years the promotion ladder
  evaluates ≈ 210 calls ≈ 3–5 h at the measured 50–90 s per call; daily origins ≈ 1,000
  calls ≈ 1–2 days of wall-clock on the shared inference lock, contending with the live
  worker's CPU. Either must be scheduled by the operator, not run opportunistically.
- **Scope-hash churn.** Adding `regime` to `SCOPE_HASH_FIELDS` is deliberate: the tilt
  changes which candidates exist, so it must re-scope approvals (the opposite reasoning
  from `execution`/`grid`, which were excluded because they do not).
- **Complexity.** One new table, one new config sub-model, one new pure module, one
  `ignore_imports` edge, four safety tests. If G2–G5 fail, none of this is built and the
  ADR is marked Rejected with the study linked.

## Gate status

| Gate | Description | Status |
|---|---|---|
| G1 | pre-registration before inference | not started (record written; no inference run) |
| G2 | skill: Tier A h=20 and h=5 MAE ratio vs drift and vs unchanged all <1, Holm p<0.05, CI upper<1, point ≤0.95 at h=20 | not started |
| G3 | direction: h=20 horizon-end accuracy >50%, BH p<0.10, not worse than drift sign | not started |
| G4 | calibration: coverage not rejected at 50% (p≥0.10), bands non-degenerate | not started |
| G5 | Tier B pooled MAE ratio vs drift CI upper<1 at h=20 | not started |
| G6 | second pre-registered regime-relevance study on ≥2 non-bull spans with tighten-only ablation | not started |
| G7 | per-strategy pre-registered promotion re-evaluation, no threshold changes | not started |
| G8 | engineering: forecast table + inference-free reader, flag default OFF, safety tests, explicit ignore_imports amendment | not started |
| G9 | reproducibility: report regenerates byte-identical summary; ≥5-window re-inference spot check | not started |
| G10 | operator sign-off | not started |

Research signal only — no order was placed, and no decision path reads Kronos today.
