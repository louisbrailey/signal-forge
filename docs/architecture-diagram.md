# Signal Forge — architecture diagrams

Companion to `ARCHITECTURE.md`. Rendered on GitHub; run `mmdc` locally if you
want images.

## 1. System context

```mermaid
flowchart TB
    subgraph ext["External — read-only, licensed"]
      MD["Market data\n(fixture / Stooq EOD / paid later)"]
      LLMP["LLM provider\n(optional, explanation only)"]
      SMTP["SMTP\n(optional, outbound alerts)"]
    end

    subgraph sf["Signal Forge — local, 127.0.0.1"]
      ING["data.adapters + ingest"]
      DB[("SQLite\n(Postgres in Phase 2)")]
      RES["research: features · registry · scan · rank · candidates"]
      RISK["risk: sizing + portfolio limits"]
      BT["backtest: engine · walk-forward · bootstrap · regime"]
      PAPER["paper: ledger · journal · corrections"]
      BRIEF["briefing (deterministic)"]
      LLMX["llm.explain (guarded narrative)"]
      ALERT["alerts: policy · channels"]
      API["FastAPI + HTMX dashboard"]
      SCHED["APScheduler jobs"]
      KILL{{"kill switch"}}
    end

    USER(("you"))
    CSV["broker CSV\n(manual, offline)"]

    MD --> ING --> DB
    DB --> RES --> RISK --> PAPER
    DB --> BT --> RES
    RES --> BRIEF --> LLMX
    LLMP --> LLMX
    BRIEF --> ALERT
    RES --> ALERT --> SMTP
    API <--> USER
    CSV -. upload .-> PAPER
    SCHED --> ING
    SCHED --> RES
    SCHED --> PAPER
    SCHED --> BRIEF
    SCHED --> ALERT
    KILL -. halts .-> SCHED
    KILL -. halts .-> ALERT
    KILL -. halts .-> PAPER
```

No path exists from Signal Forge to a brokerage. External systems are data
sources and outbound notifications only.

## 2. The research loop (one horizon)

```mermaid
flowchart LR
    U["universe = watchlist + ETF preset"] --> F{"liquidity / history\n/ freshness / earnings\nfilters"}
    F -- excluded --> X["exclusions_json\n(reason -> count, symbols)"]
    F -- passes --> EVAL["per strategy:\nevaluate(series, t, regime)"]
    REG["regime filter\n(SPY trend + vol)"] --> EVAL
    EVAL -- no signal --> NT1["NO TRADE\n(no strategy triggered)"]
    EVAL -- signal --> GATE{"quality gates\n· reward:risk\n· OOS expectancy + CI + n\n· risk engine can size"}
    GATE -- fail --> NT2["NO TRADE\n(failed gate recorded)"]
    GATE -- pass --> RANK["rank_in_horizon\n(transparent score)"]
    RANK --> CAND["candidate rows persisted"]
    NT1 & NT2 --> CAND
    CAND --> UI["evidence page"]
    CAND --> PAPER["paper accept / reject / ignore / watch"]
```

`NO TRADE` is a first-class, persisted outcome — expected to be the common case.
On the fixture (random-walk) data every candidate is `NO TRADE` because no
strategy has positive out-of-sample expectancy net of costs.

## 3. Backtest → evidence

```mermaid
flowchart LR
    BARS["adjusted daily bars"] --> ENGINE["engine\nsignal at t sees head(t)\nfill at t+1 open\nstop→target→time-stop\ncosts baked into fills"]
    ENGINE --> TR["SimTrade[]"]
    TR --> M["metrics (net of costs)"]
    TR --> WF["walk-forward\nIS head vs OOS tail (n folds)"]
    TR --> MC["bootstrap CI\n(seeded)"]
    TR --> RG["regime segmentation\n(entry-date regime)"]
    M & WF & MC & RG --> REP["reports/<key>-<ver>.md\n+ backtest_run / backtest_metric rows"]
    REP --> GATE["scanner OOS-expectancy gate"]
```

## 4. Safety controls

```mermaid
flowchart TB
    KS["kill switch\n(file-backed, audited)"] --> J["every scheduled job: guarded() no-ops"]
    KS --> A["alert dispatch: run_alert_cycle raises"]
    KS --> P["accept_candidate / record_decision: raise"]
    KS --> API["state-changing routes: 423 Locked"]

    IL["import-linter contracts"] --> S1["S1 no brokerage / execution / browser automation"]
    IL --> S2["S2 portfolio import has no network in its graph"]
    IL --> S3["S3 research/risk/backtest/paper never import llm"]

    ADP["adapter capability descriptor"] --> S7["S7 'live' only for a REALTIME entitlement"]
    FG["FreshnessGate"] --> S8["S8 stale feed → no live alerts, results marked"]
    TRIG["paper_trade BEFORE UPDATE/DELETE triggers"] --> S9["S9 immutable; corrections are separate rows"]
    DISP["display.probability_display"] --> S10["S10 probability only with a calibration_ref"]
```
