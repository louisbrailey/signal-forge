-- R3 dead-approvals diagnosis: the exact read-only SQL behind DIAGNOSIS.md.
-- Run:  sqlite3 -header -column 'file:<scratch>/db/signalforge.sqlite?immutable=1' < dead_approvals_queries.sql
-- Counts, statuses, gate strings and timestamps only. No price, level or P&L column is selected.
-- Gate 9 (sealed) evidence and sealed-test outcome columns are never selected.

.print '== Q1 strategy versions and status'
SELECT v.id AS sv, s.name, v.version, v.status AS version_status, s.status AS strategy_status,
       substr(v.git_sha,1,7) AS sha
FROM strategy_version v JOIN strategy s ON s.id=v.strategy_id ORDER BY v.id;

.print ''
.print '== Q2 development OOS evidence runs for versions 2,3,5,13 (purpose = development_oos only)'
SELECT r.id AS run, r.strategy_version_id AS sv, r.date_start, r.date_end,
       substr(r.config_hash,1,12) AS cfg, substr(r.git_sha,1,7) AS sha, datetime(r.created_at) AS created,
       json_extract(r.params_json,'$.promotion_evaluation_id') AS eval_id,
       json_extract(r.params_json,'$.allow_mismatch') AS allow_mismatch,
       json_extract(r.params_json,'$.dataset_snapshot.id') AS snap,
       json_array_length(json_extract(r.params_json,'$.symbols')) AS nsym
FROM backtest_run r
WHERE r.strategy_version_id IN (2,3,5,13) AND json_extract(r.params_json,'$.purpose')='development_oos'
ORDER BY r.strategy_version_id, r.created_at, r.id;

.print ''
.print '== Q3 per-regime OOS rows of runs 53 (sv2), 55 (sv3), 54 (sv5), 49 (sv13) — development window'
SELECT m.run_id AS run, r.strategy_version_id AS sv, m.phase, m.segment,
       CAST(json_extract(m.metrics_json,'$.n_trades') AS INTEGER) AS n_trades,
       round(json_extract(m.metrics_json,'$.expectancy_r'),3) AS expectancy_r
FROM backtest_metric m JOIN backtest_run r ON r.id=m.run_id
WHERE m.run_id IN (53,55,54,49)
ORDER BY r.strategy_version_id, m.phase, m.segment;

.print ''
.print '== Q3b the same rows collapsed to the trend the scan gate counts (scan.py:362-380)'
SELECT m.run_id AS run, r.strategy_version_id AS sv,
       substr(json_extract(m.metrics_json,'$.regime_label'),1,
              instr(json_extract(m.metrics_json,'$.regime_label'),'/')-1) AS trend,
       sum(CAST(json_extract(m.metrics_json,'$.n_trades') AS INTEGER)) AS n_trades,
       sum(CAST(json_extract(m.metrics_json,'$.n_trades') AS INTEGER)) >= 10 AS meets_10
FROM backtest_metric m JOIN backtest_run r ON r.id=m.run_id
WHERE m.run_id IN (53,55,54,49) AND m.phase='oos_by_regime'
GROUP BY 1,2,3 ORDER BY 2,3;

.print ''
.print '== Q4 promotion gate 6 ONLY, for the evaluation each run is linked to'
SELECT e.id AS eval, e.strategy_version_id AS sv, json_extract(g.value,'$.passed') AS passed,
       json_extract(g.value,'$.evidence.trades_per_regime.bull') AS bull,
       json_extract(g.value,'$.evidence.trades_per_regime.bear') AS bear,
       json_extract(g.value,'$.evidence.trades_per_regime.range') AS range_,
       json_extract(g.value,'$.evidence.min_trades_per_regime') AS min_per_regime,
       json_extract(g.value,'$.evidence.n_trades_considered') AS n_considered
FROM strategy_promotion_evaluation e, json_each(e.gates_json) g
WHERE e.id IN (52,53,54,51) AND json_extract(g.value,'$.number')=6
ORDER BY e.strategy_version_id;

.print ''
.print '== Q5 passing evaluations (approved scopes) for versions 2,3,5,13 — identity columns only'
SELECT e.id, e.strategy_version_id AS sv, datetime(e.evaluated_at) AS evaluated_at,
       e.dataset_snapshot_id AS snap, json_array_length(e.universe_json) AS nsym,
       e.window_start, e.window_end, substr(e.config_hash,1,12) AS cfg,
       substr(e.spec_json_hash,1,10) AS spec, substr(e.git_sha,1,7) AS sha, e.sealed_test_id AS sealed
FROM strategy_promotion_evaluation e
WHERE e.strategy_version_id IN (2,3,5,13) AND e.passed=1
ORDER BY e.strategy_version_id, e.id;

.print ''
.print '== Q6 sealed-test identities (no outcome columns): looks already taken per version'
SELECT t.id, t.strategy_version_id AS sv, t.dataset_snapshot_id AS snap, t.window_start, t.window_end
FROM strategy_sealed_test t WHERE t.strategy_version_id IN (2,3,5,13) ORDER BY 2,1;

.print ''
.print '== Q7 paper accounts, auto-simulation switches, book-creation audit rows'
SELECT id, name, strategy_version_id AS sv, initial_cash, datetime(created_at) AS created FROM paper_account ORDER BY id;
SELECT key, value_json, updated_by, datetime(updated_at) AS updated FROM app_setting
WHERE key IN ('auto_simulate_qualified_signals','auto_simulate_max_per_day');
SELECT id, datetime(ts) AS ts, actor, action, entity, after_json FROM audit_log WHERE action='paper.book_created';

.print ''
.print '== Q8 research_overrides: top-level keys only (no quality_gates or promotion override exists)'
SELECT j.key FROM app_setting a, json_each(a.value_json) j WHERE a.key='research_overrides' ORDER BY 1;

.print ''
.print '== Q9 all-time candidates per version and scan scope'
SELECT c.strategy_version_id AS sv, coalesce(sr.source,'') AS source, sr.dataset_snapshot_id AS snap,
       sr.universe_size AS usz, sr.horizon, count(*) AS cands,
       sum(c.quality_gate_status='PASSED') AS passed, sum(c.quality_gate_status='NO_TRADE') AS no_trade,
       count(DISTINCT sr.id) AS scans, min(datetime(sr.started_at)) AS first_scan,
       max(datetime(sr.started_at)) AS last_scan
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id
WHERE c.strategy_version_id IN (2,3,5,13) GROUP BY 1,2,3,4,5 ORDER BY 1,3,4;

.print ''
.print '== Q10 every distinct regime-coverage gate string, by version and scan scope (all time)'
SELECT c.strategy_version_id AS sv, sr.dataset_snapshot_id AS snap, coalesce(sr.source,'') AS source,
       j.value AS gate_string, count(*) AS n, min(datetime(sr.started_at)) AS first,
       max(datetime(sr.started_at)) AS last
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id, json_each(c.failed_gates) j
WHERE c.strategy_version_id IN (2,3,5,13) AND j.value LIKE 'OOS regime coverage%'
GROUP BY 1,2,3,4 ORDER BY 1,2;

.print ''
.print '== Q11 failed-gate categories for versions 5 and 13 (all time)'
WITH g AS (
  SELECT c.id, c.strategy_version_id AS sv, c.scan_run_id,
         CASE WHEN j.value LIKE 'OOS regime coverage%' THEN 'A regime coverage'
              WHEN j.value LIKE 'OOS provenance mismatch%' THEN 'OOS provenance mismatch'
              WHEN j.value LIKE 'OOS scope mismatch%' THEN 'OOS scope mismatch'
              WHEN j.value LIKE 'no out-of-sample backtest%' THEN 'no OOS backtest on record'
              WHEN j.value LIKE 'reward/risk%' THEN 'reward/risk'
              WHEN j.value LIKE 'risk:%' THEN 'risk sizing'
              WHEN j.value LIKE 'OOS trades%' THEN 'OOS trades'
              WHEN j.value LIKE 'OOS expectancy CI%' THEN 'OOS expectancy CI'
              WHEN j.value LIKE 'OOS expectancy%' THEN 'OOS expectancy'
              ELSE 'other' END AS cat
  FROM candidate c, json_each(c.failed_gates) j WHERE c.strategy_version_id IN (5,13))
SELECT sv, cat, count(DISTINCT id) AS candidates, min(scan_run_id) AS first_scan, max(scan_run_id) AS last_scan
FROM g GROUP BY 1,2 ORDER BY 1,3 DESC;

.print ''
.print '== Q12 approved-scope scans (source massive) since 2026-09-24, with candidate rows per version'
SELECT sr.id, datetime(sr.started_at) AS started, sr.dataset_snapshot_id AS snap, sr.horizon,
       sr.scanned_count AS scanned, sr.candidate_count AS passed_ct,
       (SELECT count(*) FROM candidate c WHERE c.scan_run_id=sr.id AND c.strategy_version_id=2) AS sv2,
       (SELECT count(*) FROM candidate c WHERE c.scan_run_id=sr.id AND c.strategy_version_id=3) AS sv3,
       (SELECT count(*) FROM candidate c WHERE c.scan_run_id=sr.id AND c.strategy_version_id=5) AS sv5,
       (SELECT count(*) FROM candidate c WHERE c.scan_run_id=sr.id AND c.strategy_version_id=13) AS sv13
FROM scan_run sr WHERE sr.source='massive' AND sr.started_at>='2026-09-24' ORDER BY sr.started_at, sr.id;

.print ''
.print '== Q13 which versions each approved-scope scan covered (audit payload), since 2026-09-24'
SELECT a.id AS audit, datetime(a.ts) AS ts, json_extract(r.value,'$.horizon') AS horizon,
       json_extract(r.value,'$.dataset_snapshot_id') AS snap, json_extract(r.value,'$.scan_run_id') AS scan,
       json_extract(r.value,'$.strategy_version_ids') AS versions, json_extract(r.value,'$.scanned') AS scanned
FROM audit_log a, json_each(a.after_json,'$.runs') r
WHERE a.action='approved_scope_scan.completed' AND a.ts>='2026-09-24' ORDER BY a.id, r.key;

.print ''
.print '== Q14 approved-scope scan blocks since 2026-09-24 (reason head)'
SELECT a.id, datetime(a.ts) AS ts, json_extract(a.after_json,'$.dataset_snapshot_id') AS snap,
       substr(json_extract(a.after_json,'$.reason'),1,90) AS reason
FROM audit_log a WHERE a.action='approved_scope_scan.blocked' AND a.ts>='2026-09-24' ORDER BY a.id;

.print ''
.print '== Q15 promotion and status audit rows (shows relative_strength was experimental before 2026-10-26)'
SELECT id, datetime(ts) AS ts, actor, action, entity, before_json, substr(after_json,1,70) AS after
FROM audit_log WHERE action IN ('strategy.promote','strategy.status_correction','strategy.status_change',
                                'strategy.downgrade','strategy.disable') ORDER BY id;

.print ''
.print '== Q16 version 13 candidates since 2026-11-08 (expected: none)'
SELECT count(*) AS sv13_candidates_since_2026_11_08 FROM candidate
WHERE strategy_version_id=13 AND created_at>='2026-11-08';
SELECT c.scan_run_id AS scan, datetime(sr.started_at) AS started, sr.dataset_snapshot_id AS snap,
       c.quality_gate_status AS status, c.failed_gates, count(*) AS n
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id WHERE c.strategy_version_id=13 GROUP BY 1,2,3,4,5;

.print ''
.print '== Q17 run 49 (sv13) provenance fields the scan checks (persistence.py:234-394)'
SELECT json_extract(params_json,'$.purpose') AS purpose,
       json_extract(params_json,'$.dataset_snapshot.id') AS snap,
       json_extract(params_json,'$.source') AS source,
       json_extract(params_json,'$.promotion_evaluation_id') AS eval_id,
       json_extract(params_json,'$.reproduces_evaluation') AS reproduces,
       json_extract(params_json,'$.allow_mismatch') AS allow_mismatch,
       json_extract(params_json,'$.mismatched_inputs') AS mismatched,
       json_extract(params_json,'$.window.until') AS until,
       json_type(params_json,'$.data_provenance') AS data_provenance_type,
       substr(json_extract(params_json,'$.spec_json_hash'),1,12) AS spec,
       substr(config_hash,1,12) AS cfg
FROM backtest_run WHERE id=49;

.print ''
.print '== Q18 version 5 rows that do NOT cite the regime gate (gate strings deliberately not selected)'
SELECT c.scan_run_id AS scan, datetime(sr.started_at) AS started, count(*) AS n
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id
WHERE c.strategy_version_id=5 AND c.failed_gates NOT LIKE '%OOS regime coverage%' GROUP BY 1,2;

.print ''
.print '== Q19 scans with passing version 2 candidates, 2026-09-25 to 2026-10-09 (book-sv2 was created 2026-10-08 22:00:45)'
SELECT c.scan_run_id AS scan, datetime(sr.started_at) AS started, count(*) AS passed
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id
WHERE c.strategy_version_id=2 AND c.quality_gate_status='PASSED' AND sr.source='massive'
  AND sr.dataset_snapshot_id=3 AND sr.started_at>='2026-09-25' AND sr.started_at<'2026-10-10'
GROUP BY 1,2 ORDER BY 2;

.print ''
.print '== Q20 which account decided version 2 candidates before 2026-10-09 (no price column)'
SELECT pt.id, datetime(pt.created_at) AS created, pa.name AS account, pt.decision, pt.actor
FROM paper_trade pt JOIN paper_account pa ON pa.id=pt.account_id JOIN candidate c ON c.id=pt.candidate_id
WHERE c.strategy_version_id=2 AND pt.created_at<'2026-10-09' ORDER BY pt.id;

.print ''
.print '== Q21 recorded runs for versions 2,3,5 since 2026-09-07 07:35: window and creation time only (no metrics)'
SELECT r.id AS run, r.strategy_version_id AS sv, r.date_start, r.date_end, datetime(r.created_at) AS created,
       coalesce(json_extract(r.params_json,'$.purpose'),'(none)') AS purpose
FROM backtest_run r WHERE r.strategy_version_id IN (2,3,5) AND r.id >= 38 ORDER BY r.created_at, r.id;

-- ---------------------------------------------------------------------------------------------
-- Repair pass (2026-11-10): queries added to confirm or refute the review findings. Read-only.
-- ---------------------------------------------------------------------------------------------

.print ''
.print '== Q22 provenance flags of the development OOS runs 49-55 (runs 50-52 are FORCED records, not backtest-report runs)'
SELECT id AS run, strategy_version_id AS sv, json_extract(params_json,'$.purpose') AS purpose,
       json_extract(params_json,'$.allow_mismatch') AS allow_mismatch,
       json_extract(params_json,'$.mismatched_inputs') AS mismatched_inputs,
       json_extract(params_json,'$.reproduces_evaluation') AS reproduces,
       datetime(created_at) AS created
FROM backtest_run WHERE id BETWEEN 49 AND 55 ORDER BY id;

.print ''
.print '== Q23 every candidate citing "OOS provenance mismatch", by version and scan (all time)'
SELECT c.strategy_version_id AS sv, c.scan_run_id AS scan, datetime(sr.started_at) AS started,
       coalesce(sr.source,'') AS source, sr.dataset_snapshot_id AS snap, count(*) AS n
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id
WHERE EXISTS (SELECT 1 FROM json_each(c.failed_gates) j WHERE j.value LIKE 'OOS provenance mismatch%')
GROUP BY 1,2,3,4,5 ORDER BY 2;

.print ''
.print '== Q24 candidates citing "OOS scope mismatch" (the check a provenance-less run would hit) — any version, all time'
SELECT count(*) AS candidates_citing_oos_scope_mismatch FROM candidate c
WHERE EXISTS (SELECT 1 FROM json_each(c.failed_gates) j WHERE j.value LIKE 'OOS scope mismatch%');

.print ''
.print '== Q25 last candidate per version; versions 2 and 3 rows created on or after 2026-11-05'
SELECT strategy_version_id AS sv, max(datetime(created_at)) AS last_candidate, count(*) AS total
FROM candidate WHERE strategy_version_id IN (2,3,5,13) GROUP BY 1;
SELECT count(*) AS sv2_sv3_candidates_since_2026_11_05 FROM candidate
WHERE strategy_version_id IN (2,3) AND created_at>='2026-11-05';

.print ''
.print '== Q26 session 2026-10-06: the approved-scope scan that ran, and the job failure after it'
SELECT id, datetime(started_at) AS started, datetime(finished_at) AS finished, horizon,
       coalesce(source,'') AS source, dataset_snapshot_id AS snap, scanned_count AS scanned
FROM scan_run WHERE started_at>='2026-10-06 20:00:00' AND started_at<'2026-10-07 20:00:00' ORDER BY id;
SELECT id, datetime(ts) AS ts, actor, action, entity FROM audit_log
WHERE ts>='2026-10-06 20:00:00' AND ts<'2026-10-07 20:00:00'
  AND (action LIKE 'approved_scope_scan.%' OR action='job.failed') ORDER BY id;

.print ''
.print '== Q27 version 5 rows on its approved scope (massive, snapshot 3, MEDIUM_SWING) since 2026-09-25, by UTC day of the scan'
.print '   (the auto-simulation cap is 2 accepted trades per book per UTC day: paper/auto_simulate.py:88-102)'
SELECT date(sr.started_at) AS utc_day, group_concat(DISTINCT sr.id) AS scans, count(*) AS rows_,
       count(DISTINCT c.instrument_id) AS symbols, min(2, count(DISTINCT c.instrument_id)) AS capped
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id
WHERE c.strategy_version_id=5 AND sr.source='massive' AND sr.dataset_snapshot_id=3
  AND sr.horizon='MEDIUM_SWING' AND sr.started_at>='2026-09-25'
GROUP BY 1 ORDER BY 1;
SELECT count(*) AS utc_days, sum(capped) AS ceiling_at_2_per_utc_day FROM (
  SELECT date(sr.started_at) AS utc_day, min(2, count(DISTINCT c.instrument_id)) AS capped
  FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id
  WHERE c.strategy_version_id=5 AND sr.source='massive' AND sr.dataset_snapshot_id=3
    AND sr.horizon='MEDIUM_SWING' AND sr.started_at>='2026-09-25'
  GROUP BY 1);

.print ''
.print '== Q28 completed approved-scope scan audits, 2026-10-01 to 2026-10-25: how many list version 5 in any run'
SELECT count(*) AS audits,
       sum(EXISTS (SELECT 1 FROM json_each(a.after_json,'$.runs') r, json_each(r.value,'$.strategy_version_ids') v
                   WHERE v.value=5)) AS audits_listing_version_5,
       min(datetime(a.ts)) AS first, max(datetime(a.ts)) AS last
FROM audit_log a
WHERE a.action='approved_scope_scan.completed' AND a.ts>='2026-10-01' AND a.ts<'2026-10-26';
