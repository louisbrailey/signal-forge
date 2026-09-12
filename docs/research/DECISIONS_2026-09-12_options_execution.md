# Decisions — options program and live-execution layer (2026-09-12)

Source: `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` §7 "Decisions only the operator
can make". The operator directed on 2026-09-11 that Signal Forge is "no longer research
use only" and granted end-to-end operational control. The orchestrator therefore takes
every decision that does not require the operator's own account, credentials, or money,
records it here with rationale, and lists the three that remain the operator's.

| # | Decision | Taken |
|---|---|---|
| 1 | Supersede the roadmap's "no brokerage, at any phase" boundary | **Yes, by operator direction (2026-09-11).** Recorded as ADR `docs/decisions/0003-execution-layer.md` (Phase D6). Paper-first evidence discipline (R1–R10) is unchanged. |
| 2 | Broker for the first paper adapter | **Assumed: Alpaca paper-trading API** (free paper endpoint, fractional shares — also required by the grid strategy's $5 orders, options on paper). **Operator must confirm and supply keys via env/keychain.** No other broker code is written until then. |
| 3 | Options approval level | **Operator-only.** Design assumes Level 2 (defined-risk spreads, cash-secured puts, covered calls). Nothing is armed for real money until the level is confirmed. |
| 4 | Capital limits (§3.2) — defaults | Per-structure max loss $250; aggregate open max loss $1,000; collateral cap $5,000; net delta ±$10,000 notional; net vega cap $50/vol-pt; per-order notional $1,000; daily order cap 10; account exposure cap 40%; arming expiry 7 days; PDT threshold acknowledged at $25,000 equity. **Operator may change any of these before arming.** |
| 5 | Data spend / NBBO | **No NBBO purchase now.** Modelled spreads stay a disclosed assumption on both asset classes; gate 4b (dual-spread) becomes permanent. |
| 6 | Raise `backfill_max_total_bars` past 200,000 | **Yes**, to 2,000,000, recorded with the run's `IngestionRun` provenance. |
| 7 | Greeks/IV path | **Local Black-Scholes inversion from daily aggregates + the §2.4b same-session surface** (history-capable); dated vendor snapshots collected forward as a secondary series. |
| 8 | Defer O2 (covered call) behind O3 | **Yes.** |
| 9 | `armed_strategy` auto-disarm | **On any status change** (not only downgrades). |
| 10 | Live paper evidence before real-money arming | **Yes:** a strategy may be armed only after ≥ 20 closed paper trades with non-negative expectancy under the health monitor, unless the operator overrides explicitly and the override is audited. |
| 11 | Dividend yield `q` | **Source and record `q` per underlying** (no allowlist), so SPY/IWM stay in scope. |
| 12 | First options structure | **O3 — short vertical (credit) spread, regime-filtered.** O1 (cash-secured put) cannot pass gate 6 while skipping bear regimes and hits the paper collateral wall. |
| 13 | Options paper account | **A separate options paper account sized to the strategy** (initial $25,000 SIMULATED), so backtest and paper streams are the same population. |

## Remaining operator items (blocking only the steps named)

1. Confirm the broker (Alpaca paper assumed) and place its paper API keys in the
   environment or keychain yourself — blocks I-E5 only.
2. State your options approval level — blocks arming any options structure.
3. Confirm or change the capital limits in row 4 — blocks arming.

## Standing constraints carried forward

No LLM decides an order (new import contract in the reverse direction, §6.8). Nothing is
armed by default. The kill switch blocks opening and never blocks closing. Every intent,
submission, fill, rejection, reconciliation, and arming change is audited. The "no order
was placed" notice is replaced only by the true execution status of each record.
