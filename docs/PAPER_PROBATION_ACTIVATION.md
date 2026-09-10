# Limited U.S. Equity Paper-Probation Trial — Activation Preparation

**Status: prepared, NOT activated (2026-09-10).** Alerts OFF, every alert type OFF,
paper probation OFF, auto-simulation OFF, no Discord message sent. Research /
paper-trading only: no order is ever placed; every candidate and alert carries
"Research signal only — no order was placed."

## Eligible strategy versions (and nothing else)

| Strategy | Version | strategy_version_id | Approved scope (five-part, exact) |
|---|---|---|---|
| `trend_continuation.short_swing` | 0.1.0 | 2 | dataset snapshot **#3 `universe_24_ex_meta`** (24 symbols, META excluded) · source `massive` · config_hash `11b54aee64db…` · spec_json_hash `2ed9743170bd…` |
| `relative_strength.medium_swing` | 0.1.0 | 5 | dataset snapshot **#3 `universe_24_ex_meta`** · source `massive` · config_hash `11b54aee64db…` · spec_json_hash `dfe696b662dd…` |

Enforcement: a candidate can only be alerted when `Strategy.status == PAPER_APPROVED`
**and** its `ScanRun` matches one of that version's passing evaluations on all five
parts (`research/approval_scope.py::scan_scope_matches`); otherwise it is logged as
`NO TRADE — approval does not apply to this dataset.` Only the scheduled
`approved_scope_scan` (end of `daily_eod_update`, gated on fresh, complete data)
produces matching candidates. Universe-pipeline scans and any other scan cannot.

## Gates retained (unchanged)

| Gate | Where |
|---|---|
| Stale data | `alerts/dispatch.py` (any stale feed ⇒ no candidate alerts); `research/approved_scope_scan.py::data_readiness` (source feed fresh, last daily ingest ok <24 h, newest bar ≤5 days, ≥90 % coverage) |
| Liquidity, event window, missing/short history | `research/scan.py` exclusions (`min_price`, `min_avg_dollar_volume`, earnings window) |
| Cost / slippage | `Candidate.slippage_assumption_json`; `paper/ledger.py` simulated fill with spread + slippage |
| Portfolio risk / concentration | `risk/engine.py::size_position`, `risk/portfolio.py::exposure_report`, `ResearchConfig.risk` limits |
| Quiet hours, 2-per-day cap, briefing once/day, dedupe | `alerts/dispatch.py::run_alert_cycle` |
| Kill switch | every job/action (`killswitch.ensure_not_engaged`) |

## Auto-simulation is impossible

There is **no scheduled or automatic caller** of paper acceptance anywhere in
`src/signalforge` (verified by `tests/paper/test_activation_guards.py::test_nothing_in_the_scheduler_calls_automatic_acceptance`).
The only acceptance paths are the manual dashboard action and the CLI. The guard
`paper/ledger.py::assert_auto_simulate_allowed` documents and enforces what any
future automatic path would need: setting ON **and** every quality gate passed
**and** a U.S. stock/ETF instrument **and** `PAPER_APPROVED` version **and** an
exact scope match — options, futures, forex, unapproved strategies, and scope
mismatches raise `AutoSimulateForbidden`.

## Evidence on every paper trade

`PaperTrade.signal_snapshot_json` (immutable — invariant S9 triggers reject UPDATE/DELETE)
now holds the complete candidate record: entry/stop/target/time-stop, reward:risk,
calibrated probability, sizing, liquidity, slippage assumption, event risk, portfolio
context, data freshness, ranking, every failed gate and failure reason, the exact scan
scope (scan id, source, dataset snapshot, config hash), the strategy version and live
parameter hash, whether the scan matched the approved scope, and the code SHA.
`why_might_fail` carries the failure rationale text.

## Pending settings (exact) — applied only by the activation action

| Setting | Now | Pending |
|---|---|---|
| `alerts_enabled` | False | **True** |
| `paper_probation_enabled` | unset (False) | **True** |
| `alert_type_enabled:candidate` | False | **True** |
| `alert_type_enabled:system_health` / `data_issue` / `daily_briefing` | False | stays **False** |
| `auto_simulate_qualified_signals` | False | stays **False** |
| `max_alerts_per_day` | 2 | 2 (re-asserted) |
| Discord | webhook configured, nothing sent | candidate-only delivery once the above are on |

## Dry-run result (2026-09-10 12:2x UTC, `signalforge paper-probation-dry-run`)

```
DRY RUN — nothing was changed, logged, or sent
assumed settings: alerts_enabled=True, paper_probation_enabled=True,
                  alert_type_enabled:candidate=True, max_alerts_per_day=2
channels configured: local, discord · quiet hours now: True · candidate alerts sent today: 0
  blocked  daily_briefing "Daily research briefing — 2026-09-07" — alert type daily_briefing is off
would send: 0
```
No qualified candidate exists on the latest research scans (all 24 NO-TRADE on
both approved horizons), so nothing would go out today even if activated.

## Activation preconditions (live, `signalforge paper-probation-activate` without `--yes`)

OK: exactly two approved versions · exact scopes · non-candidate types OFF · auto-sim
OFF · Discord configured · worker running · kill switch released · approved-scope
readiness. **FAIL: daily bars current** (newest 2026-09-08 vs expected 2026-09-09) —
the launchd worker is still on the pre-fix adapter (`de7e414` fetches the day's
closed bar from 17:30 ET); it clears after `launchctl kickstart -k
gui/$(id -u)/com.signalforge.worker` and the next 17:30 ET run. The activation
command refuses until every precondition is green.

## Remaining data limitations

- Research universe is 24 symbols (`ex_meta`); no survivorship-free history; no
  delisted names; adjustments as-of-fetch on the bulk universe (not used here).
- NBBO spread not licensed — costs use a nominal spread + slippage model.
- Exchange holidays not modelled (freshness shows "1 behind" on a holiday).
- Calibrated win probabilities are provisional (small paper sample).
- 0 live paper trades yet for either strategy — probation evidence starts at activation.

## Independent adversarial review (2026-09-10) — findings and fixes

A read-only review agent tried to refute every safety claim above. It found no
path by which an agent writes trading state, sends anything, reaches the network,
or activates alerts/probation/auto-sim/options/forex. Four hardening items were
raised and fixed before commit:

| # | Where | Finding | Fix |
|---|---|---|---|
| 1 | `llm/guards.py` | digits inside evidence timestamps (`…T18:45:00`) could "ground" a fabricated `45%`/`18x` in an LLM narrative | timestamps skipped by key (`*_at`, `as_of`, `*_date`, …) and by shape (ISO-8601, `datetime`/`date`); regression tests added |
| 2 | `alerts/dispatch.py` | the real send cycle read `alerts_enabled` / `max_alerts_per_day` / per-type switches through the same helper the dry-run overlay uses | real cycle reads persisted settings only and fails fast (`RuntimeError`) if entered under an overlay; test added |
| 3 | `docs/AGENT_ROLES.md` | overstated S14 as forbidding all of `data.adapters` | doc now lists the five concrete adapters the contract forbids |
| 4 | `scheduler.py` | disabled `agents_daily` took the SQLite write lock before checking its flag | flag read under a plain read session first |

## The single final activation action

```bash
uv run signalforge paper-probation-activate --yes
```
It re-checks every precondition, refuses on any failure, and otherwise applies the
four pending settings in one audited transaction (`AppSettingHistory` +
`AuditLog paper_probation.activated`). Reverse with
`uv run signalforge paper-probation-deactivate`. Not run.


## Operator authorization — 2026-09-10 (supersedes the "kept OFF" statements above)

The operator authorized, in chat: alerts ON, Discord delivery ON, the paper
probation lifted (activation to proceed), and **automatic SIMULATED paper
acceptance ("auto-simulation")**. Paper only, as before: no brokerage
integration, no order placement, no LLM decisions.

| Item | State | How |
|---|---|---|
| Discord webhook | verified — one test message delivered (HTTP 204) | `signalforge notify test-discord --yes`, audited `notify.discord_test` |
| `auto_simulate_qualified_signals` | **ON** | audited `auto_simulation.authorized` (AppSettingHistory + AuditLog + file audit) |
| `auto_simulate_max_per_day` | 2 | same change |
| Activation (`alerts_enabled`, `paper_probation_enabled`, candidate alerts, cap 2) | **DONE 2026-09-10 20:00 UTC** — `paper-probation-activate --yes`, all nine preconditions OK after the restarted worker's startup catch-up ingested the 9/9 bars | audited `paper_probation.activated`; the "auto-simulation is OFF" precondition became informational |
| Options / forex | **not possible yet** — no options or forex candidate pipeline, strategy, risk model, or forex data adapter exists; the guard still refuses anything that is not a U.S. stock/ETF | requires a separate build phase |

### How auto-simulation works (`paper/auto_simulate.py`)

Runs only inside `job_approved_scope_scan`, right after the approved-scope scan,
on that scan's own gate-PASSED candidates. Each candidate must pass
`assert_auto_simulate_allowed` (setting ON, every quality gate PASSED, U.S.
stock/ETF, PAPER_APPROVED version, exact five-part approved scope), then:

- kill switch engaged → nothing runs;
- candidate already has any PaperTrade decision → skipped (idempotent on retry);
- open paper position on the instrument → REJECTED with that reason;
- daily cap reached (all ACCEPTED trades today, manual included) → WATCH;
- guard refusal → REJECTED with the exact refusal reason frozen into the evidence;
- otherwise `accept_candidate` (same ledger call, fill model, and immutable
  evidence snapshot as a manual acceptance) + `AuditLog paper.auto_simulated`.
  Each decision commits on its own.

Tests: `tests/paper/test_auto_simulate.py` (inert unless ON; single accepted
trade with full evidence + audit; idempotent; guard refusal recorded immutably;
scope mismatch refused; daily cap and one-open-position rule; kill switch) and
`test_automatic_acceptance_has_exactly_one_guarded_entry_point`.
