# Research Agents — Roles, Boundaries, and Proofs

Signal Forge's "multi-agent research operation" is seven **bounded, read-only
reporters** (`src/signalforge/agents/`). An agent is not an autonomous loop with
tools: it reads deterministic outputs the research/data/paper layers already
produced, writes exactly one `agent_report` row plus one `audit_log` event, and
nothing else. No agent can create a candidate, a paper trade, an alert, a setting
change, or a strategy-status change. Every summary ends with
"Research signal only — no order was placed."

## Shared contract (all seven)

| Aspect | Rule |
|---|---|
| Inputs | Only deterministic artefacts already in the database or config (feeds, ingestion runs, entitlement checks, scans, evaluations, sealed tests, health assessments, positions, journal, audit log, heartbeat). Never a provider API, never the network (`httpx`/`requests` forbidden by contract S14). |
| Timestamps | Every evidence item carries `source` and `as_of`/`published_at`/`checked_at`; the report row carries `as_of` and `created_at`. An absent input is listed in `missing_data` — never inferred. |
| Outputs | `AgentReport(agent, role, as_of, status, summary, narrative, evidence_json, citations_json, missing_data_json, duration_s, error)`. |
| May write | `agent_report` + `audit_log` only (base class `_persist`; `tests/agents/test_boundaries.py` asserts no other `session.add` exists in the package and that trading tables are unchanged after running every agent). |
| Audit events | `agent.run` (status ok) or `agent.failed`, actor `agent:<name>`, with report id, duration, missing-data list, narrative flag, error. |
| LLM | Optional, per-agent opt-in (`llm_narrative`), globally gated by `research.agents.llm_narratives` (default False) and the LLM layer being configured. The narrative is produced **after** the deterministic summary, must pass `llm.guards.assert_grounded` (no number not present in the frozen evidence; mandatory footer "AI explanation, not a trading instruction."), is stored in a separate field prefixed "LLM narrative — explanatory only; not a decision input", and is read by no decision path (contract S3). A rejected narrative degrades to `None` and is recorded in `missing_data`. |
| Failure behaviour | Any exception in collect/summarize → `status="failed"`, error recorded, `agent.failed` audited, **never re-raised**; the scheduler job and CLI continue with the next agent. |
| Scheduling | `agents_daily` job (18:45 ET) is config-gated OFF (`research.agents.enabled`); `signalforge agents run [--agent NAME]` runs on demand; `/agents` shows the latest report per agent. |
| Kill switch | `agents run` and the scheduled job are kill-switch guarded like every other job. |

## Prohibited actions (every agent)

Creating/altering candidates, scans, paper orders/fills/positions/trades, alerts or
alert logs, settings, strategy status/promotion/evaluations, universe archives or
bars; contacting any provider or channel; engaging/releasing the kill switch;
running ingestion, scans, promotion, health-monitor downgrades, or backfills;
emitting any recommendation, ranking, size, probability, entry or exit. Enforced by
import-linter **S14** (forbidden modules: `paper.ledger`, `alerts.dispatch`,
`alerts.channels`, `research.scan`, `research.candidates`, `research.promotion`,
`research.persistence`, `data.ingest`, the concrete network adapters
`data.adapters.{massive,massive_news,massive_options,stooq,registry}` (the
type-only `data.adapters.base` is reachable transitively via `data.series` and is
harmless), `universe.pipeline`, `killswitch`, `httpx`, `requests`) and the
source-level token scan in `tests/agents/test_boundaries.py`.

## Per-agent contract (generated from the code: `signalforge agents roles`)

| Agent | Role | Allowed inputs | Outputs | Prohibited | May write | LLM narrative |
|---|---|---|---|---|---|---|
| `data_quality` | Market-data quality agent | signalforge.data.feeds.feed_status_report; signalforge.data.validate.latest_validation; signalforge.db.models.IngestionRun; signalforge.db.models.EntitlementCheck; signalforge.db.models.UniverseScreenRun; signalforge.db.models.UniverseMember; signalforge.db.models.OHLCVDaily; signalforge.settings_store.effective_research_config; signalforge.config.get_settings | feed_coverage; stale_feed_list; entitlement_limitations; session_freshness; reconciliation_status | ingest_data; backfill_data; probe_provider; run_validation; run_universe_screen; write_setting | agent_report + audit_log only | never |
| `strategy_validation` | Deterministic strategy-validation agent | signalforge.db.models.Strategy; signalforge.db.models.StrategyVersion; signalforge.db.models.StrategyPromotionEvaluation; signalforge.db.models.StrategySealedTest; signalforge.db.models.DataSnapshot; signalforge.db.models.PaperPosition; signalforge.research.health_monitor.latest_health_by_strategy | promotion_status; approved_scope_report; sealed_test_summary; health_summary; paper_trade_summary | run_backtest; run_walkforward; run_sealed_test; run_health_monitor; approve_strategy; change_strategy_status; write_setting | agent_report + audit_log only | never |
| `market_regime` | Market-regime research agent | signalforge.data.series.PriceSeries (SPY proxy + research universe, research provider); signalforge.research.regime.regime_from_proxy; signalforge.research.features.daily.sma; signalforge.settings_store.effective_research_config (universe); signalforge.db.models.Instrument (sector) | agent_report | forecast; recommendation; trade; candidate; alert; setting change | agent_report + audit_log only | opt-in, explanatory only |
| `news_research` | News-research agent | signalforge.db.models.NewsItem (last 24h); signalforge.db.models.EntitlementCheck (feed=benzinga_news, latest) | agent_report | trade decision; candidate; alert; risk sizing; setting change; recommendation | agent_report + audit_log only | opt-in, explanatory only |
| `portfolio_risk` | Portfolio-risk agent | signalforge.paper.portfolio.portfolio_snapshot; signalforge.db.models.PaperPosition (open, qty/avg_price/side); signalforge.db.models.Instrument (sector); signalforge.risk.portfolio.exposure_report; signalforge.settings_store.effective_research_config (risk budgets); signalforge.data.series.PriceSeries (60-session returns, research provider) | agent_report | order; position size; rule override; trade; alert; setting change | agent_report + audit_log only | opt-in, explanatory only |
| `journal_review` | Journal-review agent | signalforge.paper.journal.weekly_review; signalforge.db.models.PaperTrade (last 30 days); signalforge.db.models.JournalEntry (last 30 days); signalforge.db.models.Candidate (failed_gates, joined via rejected PaperTrade) | agent_report | rule change; size change; signal change; recommendation; alert | agent_report + audit_log only | opt-in, explanatory only |
| `operations` | Operations agent | signalforge.db.models.WorkerHeartbeat; signalforge.db.models.JobRun; signalforge.db.models.AuditLog; signalforge.db.models.IngestionRun; signalforge.data.feeds.feed_status_report; signalforge.config.paths (kill_switch_state_path, data_dir) | operator_digest; job_outcomes; kill_switch_state; backup_status; audit_log_integrity | start_job; stop_job; engage_kill_switch; release_kill_switch; restart_worker; write_setting | agent_report + audit_log only | never |

## Tests proving agents cannot bypass deterministic trading/risk rules

| Test | Proves |
|---|---|
| `tests/agents/test_boundaries.py::test_agent_sources_contain_no_state_changing_calls` | No agent source contains `set_setting(`, `accept_candidate`, `record_decision(`, `run_alert_cycle`, `.send(`, `persist_scan(`, `run_scan(`, `evaluate_promotion`, `run_health_monitor(`, ingestion calls, kill-switch calls, `httpx`, `subprocess`, or any `session.add` outside the base class |
| `…::test_import_linter_contract_s14_present` + `lint-imports` | Contract S14 exists and is KEPT |
| `…::test_running_every_agent_changes_no_trading_state` | Running all seven leaves `candidate`, `paper_trade`, `paper_position`, `app_setting`, `strategy`, `strategy_version`, `scan_run`, `alert_log` row counts unchanged; exactly one report + one audit event per agent; every summary carries the notice |
| `…::test_agent_narrative_cannot_inject_numbers_or_instructions` | A hostile LLM output ("BUY 12345 shares now") is rejected by the grounding guard; an accepted narrative lives only in the labelled field while the deterministic summary is unchanged |
| `…::test_failed_agent_never_raises_and_is_audited` | A crashing agent yields `status=failed` + `agent.failed` audit, no exception |
| `…::test_no_broker_dependencies_or_connectors` | No brokerage/execution package in `pyproject.toml`/`uv.lock`; contract S1 stays |
| `tests/agents/test_agents_*.py` | Per-agent: empty-DB run is `ok` with explicit `missing_data`; seeded facts appear in the summary; the required sentences ("News is context only and cannot affect any trade decision.", "This agent explains deterministic risk outputs and cannot override any rule.", "Education only — …") are present |
| `tests/paper/test_activation_guards.py` | Auto-simulation refuses unapproved strategies, non-equities, failed gates, scope mismatches; no automatic acceptance caller exists; the alert dry run has no side effects; every paper trade carries the complete immutable evidence snapshot |
