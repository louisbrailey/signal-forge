# Results — full-pipeline strategy review (2026-11-02)

> **Audit correction (2026-11-02):** CRYPTO-2's stored `SEALED_PASS` is not reliable
> promotion evidence: BNBUSD has only 244 of the 365 sealed-year daily bars and a
> 1,735-day interior historical gap. The locked row is preserved; its paper book is
> held against new entries through `crypto_paper_data_holds`. The provider recheck
> for 2025-11-03..09 returned zero bars. Prior monthly dollar totals in this session
> were unconstrained fixed-risk illustrations, not validated portfolio forecasts.
> They should not be used to size capital or estimate income. See
> `REPAIR_AUDIT_2026-11-02.md` and the coverage-audit JSON for the corrected evidence.


Every registered strategy family, re-run through the repo's own gates on
2026-11-02, with a verdict for each. Paper-only. No order was placed, no gate
threshold or cost model was changed, and no new real sealed look was taken.

Code: branch `claude/apple-restyle`, `git_sha 7655c1c` (evaluations) plus the
test/lint fixes committed with this report. Live database read only; every
evaluation ran on a scratch copy taken with `sqlite3 .backup` at 2026-11-02
12:58 PT. Scratch evaluation ids below (48–53, 54–59, 60) exist only in those
copies and are quoted so the log lines can be matched; they are **not** rows in
`data/signalforge.sqlite`.

No strategy yet has a sufficiently sized, positive prospective paper record to establish
that a backtested edge holds in operation. Existing approvals permit observation; the
"viable" research labels below are provisional and do not establish monthly income.
The expanded CRYPTO-2 evidence is specifically invalidated by the coverage audit above.

## 1. Headline

| Rank | Strategy | Verdict | One-line reason |
|---|---|---|---|
| 1 | `crypto_donchian_55` CRYPTO-1 (daily BTC/ETH/SOL) | **viable, in paper** | Dev +0.69R / 61 OOS trades, CI low +0.14R; sealed year +0.98R / 17 trades (SEALED_PASS); paper book open since 2026-10-26, 2 open trades, 0 closed |
| 2 | `trend_continuation.short_swing` v0.1.0 | **viable, in paper** | 10/10 gates on snapshot 3; OOS +0.26R / 341, CI low +0.11R; sealed +0.30R / 109; paper 4 closed, mean −0.21R (too few to judge) |
| 3 | `relative_strength.medium_swing` v0.1.0 | **marginal, approved but idle** | 10/10 gates on snapshot 3 but sealed test is 16 trades (0.79 SE from zero); month-block bootstrap CI low −0.02R; live scan gate rejects every candidate on its latest 4-year OOS record (CI low −0.19R, bull-only) — 0 paper trades |
| 4 | `trend_continuation.medium_swing` v0.1.0 | **marginal, in paper** | Approved via snapshot 11 (150 symbols); on snapshot 3 the locked sealed year is −0.03R / 95 (fails gate 9); paper 9 closed, mean −0.16R |
| 5 | `volatility_breakout.short_swing` v0.2.0 | **reject (power)** | OOS +0.36R but 25 trades, CI low −0.02R, 1 bear trade; needs ~5,000 trades to clear gate 4 at its dispersion |
| 6 | `mean_reversion.short_swing` v0.2.0 | **reject** | OOS +0.03R / 194, CI low −0.08R, 6 bear trades, Sharpe 0.20 vs SPY 0.68; pre-registration allows no further iteration |
| 7 | `options_short_vertical.medium_swing` v0.1.3 | **reject (not evaluable)** | 1 structure entered in 2023-09..2026-09; 0 OOS; every gate 1–7 fails on an empty sample |
| 8 | `intraday_orb.intraday` v0.2.0 | **reject on 9-stock universe** | OOS −0.032R / 1,633; 0/18 sensitivity points positive; separate 23-symbol run pending (§3.6) |
| 9 | FX-1 (3 rules) and FX-2 (1 rule), 8 pairs, 2010–2025 | **reject** | DEV_FAIL on every gate, 32 strategy×pair tests; no carry model, no rate data |
| 10 | `crypto_tsmom_126_ma50`, `crypto_zfade_20` CRYPTO-1 | **reject** | OOS −0.14R and −0.10R, 0% of pairs positive |
| 11 | CRYPTO-H1 (3 hourly rules) | **reject (near miss on one)** | Hourly data ingested today; `donchian168_trail72` +0.39R / 425 trades but CI low +0.010R < +0.02R; the other two negative |
| — | SF1000 mechanical grid | **not a strategy** | Rebalancing rule; no walk-forward, no sealed test, deliberately outside the promotion ladder |
| — | Kronos filter | **reject** | "no zero-shot skill; not a settings artefact" (2026-10-03 diagnostic); disconnected |

**Plain reading.** Two things have evidence of an edge that survived a sealed
test: the daily crypto 55-day breakout and the short-swing trend strategy. Both
are already in paper simulation, which is the only forward test left. Nothing
new qualified today, and nothing was armed for execution.

## 2. How this was run (reproducible)

```bash
# scratch copy, worker untouched
sqlite3 "file:data/signalforge.sqlite?mode=ro" ".backup $S/sfdata/signalforge.sqlite"
export SIGNALFORGE_DATA_DIR=$S/sfdata DATABASE_URL="sqlite+pysqlite:///$S/sfdata/signalforge.sqlite"

# A. daily equities, snapshot 3 (24 symbols, ex-META) — evaluation ids 48–53 in the scratch copy
uv run signalforge evaluate-promotion --dataset ex_meta --until 2025-09-07

# B. daily equities, snapshot 11 (150-symbol research selection)
uv run signalforge evaluate-promotion --symbols "<150 symbols of data_snapshot 11>" \
  --snapshot-key research_150_massive_10y_presealed_sel --until 2025-09-07

# C. intraday ORB on the 23 symbols that have complete 15m history
uv run signalforge evaluate-promotion --strategy intraday_orb \
  --symbols AAPL,AMZN,DIA,GOOGL,HD,IWM,JPM,MSFT,NVDA,QQQ,SPY,UNH,XLB,XLE,XLF,XLI,XLK,XLP,XLRE,XLU,XLV,XLY,XOM \
  --snapshot-key research_23_intraday15m_2016_2025 --since 2016-10-17 --until 2025-09-07

# D. options short vertical, read-only preview (no sealed read)
uv run signalforge options evaluate-promotion --strategy options_short_vertical.medium_swing \
  --snapshot-key options_idx3_massive_2023-09-04_2026-09-04_0ae681d590 --dry-run --grid \
  --since 2023-09-04 --until 2026-09-04

# E. hourly crypto (live DB, additive table only) then the pre-registered CRYPTO-H1 development run
uv run signalforge data crypto-hourly-ingest --since 2017-01-01
uv run signalforge crypto research-hourly

# F. forward evidence
uv run signalforge strategy-health      # scratch copy: all versions "insufficient_data" (<20 paper trades)
uv run signalforge crypto paper status
```

`--until 2025-09-07` follows the 2026-10-26 round: every run ends before the
already-viewed sealed year (2025-09-08..2026-09-08). Versions with a locked
sealed test replay it verbatim (gate 9 says "LOCKED REPLAY"); versions without
one get a diagnostic "sealed" window 2024-09-07..2025-09-07 inside development
data, in the scratch copy only. That is **not** a real sealed test and the live
`strategy_sealed_test` ledger is unchanged (22 rows). The standalone
`sensitivity <key>` command was deliberately not re-run: it measures the last
three calendar years, which include the sealed year, so parameter stability is
reported from gate 5 (pre-sealed data only).

Costs in every equity number: $0 commission, 3.0 bps slippage, half of a 5 bps
spread on each fill (11 bps round trip). Crypto: 24/26/40 bps per side for
BTC/ETH/SOL plus 1 bp slippage; "2x" is double that.

## 3. Per-strategy evidence

Columns: IS = in-sample part of the pre-sealed span; OOS = last 40% of each
symbol's pre-sealed bars; sealed = the locked final year. Drawdown and turnover
are gate 7's portfolio figures over all pre-sealed trades. Stability = gate 5
(fraction of grid points positive / one-step neighbours positive).

### 3.1 `trend_continuation.short_swing` v0.1.0 — viable, PAPER_APPROVED

| Dataset | OOS trades | OOS exp. | CI low | Sealed | MaxDD | Turnover | Sharpe vs SPY | Stability | Gates |
|---|---|---|---|---|---|---|---|---|---|
| snap 3 (24) | 341 | +0.265R | +0.113R | +0.298R / 109 (id 11) | 27.8% | 132/yr | 0.81 vs 0.72 | 100% / 100% | **10/10** |
| snap 11 (150) | 1,919 | +0.155R | +0.078R | diag. +0.161R / 516 | 52.9% | 783/yr | 1.96 vs 0.68 | 100% / 100% | 10/10 (diag.) |

Caveats that stand: month-block bootstrap CI low is +0.0125R (fails the +0.02R
bar under calendar-time clustering, `diagnostics/clustered_bootstrap_all.md`);
CAGR 6.4% is below SPY's 13.4% — the edge is risk-adjusted, not absolute.
Paper (`book-sv2`, since 2026-10-08): 4 scored closes, realized +$5.12,
mean −0.21R, 3 open. Nothing can be concluded from 4 trades; the health monitor
needs 20.

### 3.2 `relative_strength.medium_swing` v0.1.0 — marginal, approved but producing nothing

| Dataset | OOS trades | OOS exp. | CI low | Sealed | MaxDD | Turnover | Sharpe vs SPY | Stability | Gates |
|---|---|---|---|---|---|---|---|---|---|
| snap 3 (24) | 197 | +0.300R | +0.090R | +0.294R / **16** (id 14) | 17.8% | 64/yr | 1.17 vs 0.72 | 100% / 100% | **10/10** |
| snap 11 (150) | 1,556 | +0.169R | +0.095R | diag. +0.325R / 160 | 58.0% | 525/yr | 2.76 vs 0.68 | 100% / 100% | 10/10 (diag.) |

Why it is marginal despite 10/10: the sealed test is 16 trades (SE ≈ 0.37R,
point estimate 0.79 SE from zero); bear-regime coverage is 11 trades, one above
the floor; month-block CI low is −0.024R.

Why it has zero paper trades: the live scan's per-candidate evidence gate reads
the **latest** `backtest_metric` row for the version, which is the
`backtest-report` run of 2026-10-03 (window 2022-09-23..2026-10-02, 25 symbols
incl. META). On that recent window the strategy's OOS CI low is −0.193R
(< −0.15R) and only the bull regime has ≥10 trades, so all 1,572 relative-strength
candidates since 2026-10-01 were `NO_TRADE`. This is the scan gate doing its
job on recent evidence, not a bug, and it was not relaxed. It does mean the
approval is not being forward-tested.

### 3.3 `trend_continuation.medium_swing` v0.1.0 — marginal, in paper

| Dataset | OOS trades | OOS exp. | CI low | Sealed | MaxDD | Turnover | Sharpe vs SPY | Stability | Gates |
|---|---|---|---|---|---|---|---|---|---|
| snap 3 (24) | 319 | +0.306R | +0.121R | **−0.029R / 95** (id 12) | 28.5% | 121/yr | 1.16 vs 0.72 | 100% / 100% | 9/10 (gate 9) |
| snap 11 (150) | 1,986 | +0.221R | +0.149R | **+0.039R / 602** (id 21) | 56.7% | 693/yr | 2.79 vs 0.72 | 100% / 100% | **10/10** |

PAPER_APPROVED on 2026-09-11 via snapshot 11 (evaluation 45, sealed id 21), not
snapshot 3. The snapshot-3 sealed year is −0.16 SE from zero and 1.65 SE below
its own pre-sealed mean. Paper (`default`, since 2026-09-25): 9 scored closes,
realized +$3.76, mean −0.16R, 3 wins, 6 open; 2 September fills voided. Too few
to judge, but the direction so far matches the weaker sealed number rather than
the +0.31R development number.

### 3.4 `volatility_breakout.short_swing` v0.2.0 — reject (statistical power)

snap 3: 25 OOS trades, +0.358R, CI low −0.024R, sealed-diagnostic +0.234R / 9
(below the 10-trade floor); regimes bull 97 / bear 1 / range 12; MaxDD 6.3%,
turnover 15/yr, exposure 0.38; stability 100%/100% on 51 evaluable points.
Fails gates 2, 4, 6, 9. The point estimate is good and stable but the strategy
trades ~15 times a year on 24 symbols; at its dispersion it would need ~5,400
trades to clear gate 4. Snapshot 11 result in §3.9. Per the 2026-10-26
pre-registration no parameter change is justified; more breadth or a
pre-registered bear-side rule would be a new hypothesis.

### 3.5 `mean_reversion.short_swing` v0.2.0 — reject

snap 3: 194 OOS trades, +0.029R, CI low −0.078R, bear 6 trades, Sharpe 0.20 vs
SPY 0.68, MaxDD 17.8%, stability 67%/75%; fails gates 4, 6, 7. The SMA(200)
filter (the one pre-registered change) moved it from −0.08R to +0.03R and
halved the drawdown, but there is no positive edge after costs. Family sealed
looks k=5; the pre-registration forbids further iteration.

### 3.6 `intraday_orb.intraday` v0.2.0 — reject on the completed nine-stock test

The nine-mega-cap run completed on scratch copy `sfdata6`, evaluation **57**, snapshot
**31**, source `massive`, git SHA `e86b16e`, window 2016-10-17..2025-09-07:

- Gate 0 passes: 462,762 actual 15-minute bars, 9 symbols × 1,985 pre-sealed sessions,
  every required regular-session bar present.
- OOS 1,633 trades, expectancy **−0.0320R**, bootstrap CI low **−0.0610R**.
- Walk-forward: **0 of 4** folds positive with the minimum trade count.
- Sensitivity: **0 of 18** grid points positive; no positive one-step neighbours.
- Development portfolio metric: Sharpe −2.28, max drawdown 72.9%, turnover 562.6/year.
- Diagnostic final window (2024-09-07..2025-09-07): **−0.0605R / 464 trades**.
  This is development data, not a new genuine sealed look.
- Fails gates 1, 3, 4, 5, 7 and 9. No paper approval.

Reproduction: `evaluate-promotion --symbols AAPL,AMZN,GOOGL,HD,JPM,MSFT,NVDA,UNH,XOM
--snapshot-key research_megacap9_2016_2025 --since 2016-10-17 --until 2025-09-07`
(the complete default-strategy invocation on `sfdata6`; raw local log `run_megacap_sf6.log`).

The earlier attempts on the 23-symbol universe encountered the fixed date-comparison bug,
session termination and slow full-history opening-range scans. Those interrupted attempts
have no result and are not counted as failures. The replacement 23-symbol run uses the
same frozen gates with a 7,200-second command budget; its separate numerical result remains
pending. Performance changes in `64223fb` preserve causal feature values and calendar
counts, with parity tests. The completed nine-stock rejection above is sufficient to record
a family verdict; it is not represented as the 23-symbol result.

### 3.7 `options_short_vertical.medium_swing` v0.1.3 — reject (not evaluable)

Dry run (no sealed read, k=0 unchanged): gates 0.a–0.i and 0.5 pass (3/3
underlyings, bracketing 0.989, continuity 1.000); then **1 structure** in the
whole development window, 0 OOS, so gates 1–7b all fail on an empty sample and
gate 5's 96-point grid tests nothing ("axis does not change the pre-sealed
trade count"). The pooled credit band of v0.1.3 did not make entries reachable
in practice. Note: the run still prints "OR-0c is open" although commit
`f23c251` says the decision was recorded; the decisions file wording should be
checked against what `options evaluate-promotion` looks for before any
`--confirm`.

### 3.8 Crypto — CRYPTO-1 daily (in paper) and CRYPTO-H1 hourly (near miss)

`crypto_donchian_55`: dev OOS +0.692R / 61 trades, CI low +0.137R, all 4 folds
positive (+0.60/+0.57/+0.78/+0.83), +0.645R at 2x costs, 3/3 pairs positive
(SOL on 11 trades); sealed year 2025-10-26..2026-10-25: **+0.982R / 17 trades**,
win rate 65%, profit factor 3.8, max DD 2.1R, +0.92R at 2x costs
(`currency_sealed_test` id 1, SEALED_PASS). Paper book CRYPTO-PAPER-1 since
2026-10-26, $100 risk per trade, observation to 2027-04-24: 0 closed, ETHUSD
short (−0.14R mark) and SOLUSD short (+0.06R mark) open since 2026-10-30. This
is the strongest evidence in the system, but 17 sealed trades at ~10 trades a
year means the paper book needs its full six months.

`crypto_tsmom_126_ma50` −0.144R / 62, `crypto_zfade_20` −0.103R / 222: reject,
0% of pairs positive. Perpetual funding and exchange counterparty risk are not
modelled; costs are spot-style.

CRYPTO-H1 (hourly, first data today — 222,270 bars 2017-01-01..2026-11-02):
`RESULTS_CRYPTO-H1_2026-11-02.md`. All three rules DEV_FAIL under the
pre-registered gates. `crypto_h_donchian168_trail72` misses on one gate only:
CI low +0.010R vs the +0.02R floor, with +0.390R on 425 OOS trades, 4/4 folds
positive (+0.78/+0.17/+0.62/+0.05), +0.222R at 2x costs, 3/3 pairs positive.
`crypto_h_tsmom72_sma168` −0.055R / 715 and `crypto_h_zfade48` −0.337R / 2,044
fail outright. Per the pre-registration there are no variants and no sealed
test; the near-miss is recorded for a future pre-registration, not acted on.

### 3.9 Snapshot 11 (150 symbols) — breadth helps the sample, not the edge

Run B, scratch evaluation ids 48–53 on `research_150_massive_10y_presealed_sel`
(snapshot 11). Same gates, same costs.

| Strategy | OOS trades | OOS exp. | CI low | Gate 9 | MaxDD | Turnover | Sharpe | Fails |
|---|---|---|---|---|---|---|---|---|
| trend_continuation.short_swing | 1,919 | +0.155R | +0.078R | diag. +0.161R / 516 | 52.9% | 783/yr | 1.96 | none |
| trend_continuation.medium_swing | 1,986 | +0.221R | +0.149R | **locked +0.039R / 602** (id 21) | 56.7% | 693/yr | 2.79 | none |
| relative_strength.medium_swing | 1,556 | +0.169R | +0.095R | diag. +0.325R / 160 | 58.0% | 525/yr | 2.76 | none |
| volatility_breakout 0.2.0 | 142 | +0.124R | −0.073R | diag. +0.150R / 62 | 18.3% | 83/yr | 1.25 | 4 (CI), 6 (bear 4 trades) |
| mean_reversion 0.2.0 | 1,038 | −0.046R | −0.090R | diag. +0.140R / 79 | 51.2% | 372/yr | −0.64 | 3, 4, 5 (0% of grid positive), 7 |
| intraday_orb 0.2.0 | — | — | — | — | — | — | — | 0: no 15m bars for 127 of 150 symbols |

Read the Sharpe/CAGR column with care. Gate 7's portfolio metric sizes every
signal at fixed R with exposure 1.00 and no capital or daily-cap constraint, so
"CAGR +80.7%" at 693 trades a year is a ranking statistic, not a return anyone
could book on a $30k paper account with a 2-trade daily cap. The drawdowns
(53–58% of R-equity) are real features of these strategies at that breadth. The
per-trade expectancy is the comparable number: it falls from +0.26–0.31R on 24
symbols to +0.15–0.22R on 150 — breadth dilutes the edge while making the
confidence interval tighter.

"diag." = diagnostic sealed window 2024-09-07..2025-09-07 on development data
in the scratch copy; not a real sealed look (§2). `trend_continuation.medium_swing`'s
row is the exception: its real sealed test on snapshot 11 (id 21, 2025-09-08..
2026-09-08) is +0.039R on 602 trades, the thin positive that carried its
2026-09-11 approval.

### 3.10 Forex — reject, no change

FX-1 `fx_donchian_55` −0.201R / 261, `fx_tsmom_126_ma50` −0.006R / 261,
`fx_zfade_20` −0.008R / 676; FX-2 `fx_donchian_55_trail20` −0.29R / 233, 0 of 4
folds positive. 16 years, 8 pairs, 32 tests, all DEV_FAIL. The data pipeline
keeps running for context only. Not re-run today: nothing changed in the rules
or data since 2026-10-26 and the results are deterministic.

## 4. What is actually in paper simulation now

| Book | Strategy | Since | Closed | Realized | Open | Status |
|---|---|---|---|---|---|---|
| `default` ($30k) | trend_continuation.medium_swing (sv3) | 2026-09-25 | 9 (+2 voided) | +$3.76, mean −0.16R | 6 | auto-simulate on, 2/day cap |
| `book-sv2` ($30k) | trend_continuation.short_swing (sv2) | 2026-10-08 | 4 | +$5.12, mean −0.21R | 3 | auto-simulate on |
| CRYPTO-PAPER-1 | crypto_donchian_55 (CRYPTO-1, 3 pairs) | 2026-10-26 | 0 | — | 2 | daily cycle, $100/trade |
| CRYPTO-PAPER-1 | crypto_donchian_55_u10 (CRYPTO-2, 10 pairs) | 2026-11-03 | 0 | — | 0 | started this evening after SEALED_PASS (+0.693R/55); daily cycle, $100/trade; observation to 2027-05-02 |
| (none) | relative_strength.medium_swing (sv5) | — | 0 | — | 0 | approved; scan gate rejects every candidate (§3.2) |
| `options` ($25k) | — | — | 0 | — | 0 | auto-simulate off, nothing approved |
| `grid` ($5k) | mechanical grid | — | — | — | — | research lane, off |

Execution layer: `armed_strategy` is empty, `execution_limits` is empty,
`execution.enabled` is False. Nothing was armed by this review.

## 5. What was changed in the repo

- `tests/conftest.py`: tests now force `FOREX_INGEST_ENABLED`,
  `CRYPTO_INGEST_ENABLED` and `CRYPTO_PAPER_ENABLED` to false, so the suite is
  hermetic against the local `.env`. This fixes the pre-existing failure
  `tests/paper/test_crypto_ledger.py::test_scheduled_cycle_is_off_by_default`
  (`no such table: crypto_paper_book`): the job was enabled by `.env` and
  queried an unmigrated test database. No migration was missing.
- `src/signalforge/cli.py`: mypy arg-type fix in `ingest-intraday`.
- This document.

No strategy code, threshold, cost model, scope, status or setting was changed.

## 6. What the subscriptions still need to be kept for

| Subscription | Needed for | If it lapses |
|---|---|---|
| Massive Stocks (daily + 15m) | Daily EOD ingest feeding both equity paper books and the approved-scope scans; paper marks | Paper probation stops accruing evidence; the two approved equity strategies cannot be forward-tested |
| Massive Currencies (crypto daily + hourly) | CRYPTO-PAPER-1 daily cycle; CRYPTO-H1 if it passes | The only sealed-pass strategy loses its forward test |
| Massive Options | Nothing live. Short vertical is not evaluable; no options book is active | No research loss today |
| Benzinga / news | Context and briefing text only; never on the decision path | None for strategy evidence |
| LLM provider | Narrative only (`llm_narratives`); never on the decision path | None for strategy evidence |
| Forex pairs | Context only; all FX rules rejected | None |

## 7. Operator decisions this review did not take

**Evening addendum (2026-11-02, after the user's instructions in the session).** Decisions 1
and 3 below were overtaken: the operator authorised two sealed looks (CRYPTO-2
`crypto_donchian_55_u10` → SEALED_PASS, now in paper; CRYPTO-3 `crypto_mom_21_long_u10` →
SEALED_FAIL, rejected), tried and reverted a 12.33% open-risk limit the same evening
(approvals re-scoped and then restored), and asked for a cross-domain strategy program whose
results are in `RESULTS_universe_program_2026-11.md` and whose dollar view is in
`PROFIT_SUMMARY_2026-11-02.md`. Gate 9 gained a 730-day indicator warm-up (`07a91fe`). The
worker was restarted at 20:5x PST to load the version-aware crypto ledger (`f580498`).


1. **Sealed looks.** No new real sealed test was run. Any new version (intraday
   ORB, CRYPTO-H1, a bear-side breakout rule) needs an explicit authorisation for
   look k+1 of its family.
2. **relative_strength.** Leave it approved-but-idle (current state), or
   re-run `backtest-report` so the scan gate reads the full-history record. The
   second option is a choice of evidence window, not a bug fix, and the recent
   window is the more honest one.
3. **Risk override.** `research_overrides` carries `per_trade_risk_pct: 10.0`
   and `max_portfolio_exposure_pct: 60`. The paper ledger clamps per-trade risk
   to `HARD_MAX_PER_TRADE_RISK_PCT` (0.5%), and every accepted trade's
   `risk_decision` records `effective_limits.per_trade_risk_pct = 0.5`, so the
   override has no effect on sizing today. It is still misleading and should be
   reset to the 0.5% default.
