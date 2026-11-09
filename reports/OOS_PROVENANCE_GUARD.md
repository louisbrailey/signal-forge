# Forced-mismatch OOS evidence guard

The PR65 base `bc37836cb16f6318c6e233f88500e8f64da4a727` validates numeric OOS
inputs but does not reject ordinary backtest runs explicitly recorded with an
input-mismatch override. Recording an exploratory run must not make it eligible
candidate evidence for the evaluated inputs.

## Bounded metadata verification

On 2026-11-09 UTC, SQLite URI `mode=ro`, `PRAGMA query_only=ON`, and an explicit
read transaction were used to inspect **only** backtest_run IDs 50, 51 and 52.
The selected columns were id, strategy_version_id, date_start/date_end, and JSON
extractions of purpose, allow_mismatch, mismatched_inputs and
reproduces_evaluation. No complete params blob was selected.

All three rows have purpose `development_oos`, JSON boolean `allow_mismatch=true`,
and `mismatched_inputs=["config_hash", "until"]`. Their saved reproduction flags
explicitly mark those two inputs false. These flags are top-level params_json
fields, as written by persist_development_oos_record.

No live metric, outcome, evaluation, sealed, study or interim-result table was
read. This metadata inspection establishes no conclusion about those runs'
numeric gates, performance or profitability. No live database writes occurred.

## Resulting behavior

- The exact latest OOS metric for the current registered strategy version is
  still selected. There is no filtering or fallback to an older good run.
- A shared read-only oos_provenance_failures guard rejects explicit
  allow_mismatch=true, nonempty mismatched_inputs, or explicit false evaluation
  reproduction flags. Malformed explicit override/mismatch fields also refuse.
- The real candidate quality path adds a clear OOS provenance mismatch reason
  and returns NO_TRADE even when every numeric gate passes.
- The strategy inventory and existing strategy-page template display
  `ambiguous_provenance` / “Ambiguous OOS evidence: forced or mismatched inputs”,
  together with the reason and unchanged saved numbers.
- Legacy absent provenance stays unknown. No input source is invented, no saved
  flag is cleared, and no metric, confidence interval, strategy parameter,
  configured numeric threshold or promotion status is rewritten.

## Callers and scope

Normal scans and approved_scope_scan both reach scan._build_draft, which now
checks the shared guard. evidence_inventory/metric_evidence provide the strategy
UI's evidence label and warnings. The OOS writer may still retain an explicitly
overridden exploratory result; its write authorization is separate from evidence
eligibility. Persistence and its selector behavior are otherwise unchanged.

evaluate_promotion computes its own development backtest with
run_development_backtest rather than qualifying from latest_oos_metric. Its
thresholds, gates, sealed handling and status transitions are unchanged.

The health monitor has a separate _latest_oos_expectancy reader; it only supports
protective downgrade/disable decisions, not promotion or candidate admission.
That reader is outside this patch's assigned files and remains unmodified. The
orchestrator can review guard integration there separately. Previously stored
candidates are retained; this patch does not retroactively reclassify decisions.

## Regression evidence

Synthetic passing rows exercise the actual candidate builder, including both
regime coverage and risk checks. Tests verify refusal for forced/mismatched
inputs, unchanged unforced passing behavior, legacy unknown provenance, current-
version selection without fallback, retained metrics/flags/statuses, and the
actual authenticated strategy page's ambiguous label and warning.

The new tests on the unmodified pinned base produce nine expected failures and
four passing controls. The fixed implementation passes all thirteen new cases.
Full focused-suite and lint evidence is retained in the isolated worktree's
ignored .toolkit-runs logs and final handoff. Main owns PR65 integration and any
release review/CI; no merge, deployment, provider or real-money action occurs here.
