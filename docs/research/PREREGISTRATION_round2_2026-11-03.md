# Pre-registration — strategy round 2 (2026-11-03)

**Status: pre-registered BEFORE any backtest of the rules below.** Authorised by the user
("Yes, both": keep the experimental 9-pair CRYPTO-2 book, and run a new pre-registered round)
and relayed by the parent session with these priorities: (1) a legitimate hourly-crypto
variant family as a fresh look, (2) two or three new families on the daily equity universes
(snapshots 3 and 11) or the clean crypto pairs, (3) nothing goes to a sealed year without the
user's say-so. BNB is in no universe. Paper-only; no gate threshold changes.

## 0. Data admissibility policy (pre-registered; replaces the zero-tolerance continuity rule)

The continuity gate added on 2026-11-02 (`research/fx/continuity.py`) failed a whole strategy
if any requested pair missed a single calendar bar. Measured on 2026-11-03 that rule leaves
only DOGE, ADA, AVAX, DOT and BCH testable on daily bars (BTC misses 1 day in 11 years, ETH 6,
XRP 13) and only BTC and ETH on hourly bars, so priorities (1) and (2b) could not run at all.

Replacement, fixed before any run, applied identically to development and sealed windows
and to every version past and future:

| Bars | Admissible when | Excluded by it (measured 2026-11-03) |
|---|---|---|
| daily | missing ≤ 1% of expected bars **and** longest interior hole ≤ 7 days | BNB (58% missing, 1,735-day hole), XLM (5.1%, 177-day hole) |
| hourly | missing ≤ 1% **and** longest hole ≤ 48 hours | BNB (67%), XRP (0.86% but a 192-hour hole) |

Admitted with their gaps disclosed: daily BTC (1 day), ETH (6), SOL (1), XRP (13, longest 7),
LINK (1), LTC (1); DOGE, ADA, AVAX, DOT, BCH have none. Hourly BTC, ETH (none), SOL (24 h),
DOGE (32 h, longest 8). Missing bars are never filled; the engine treats surviving bars as
adjacent, which every report states. A pair outside policy fails the strategy closed, exactly
as before. Tests pin the thresholds.

## 1. Families and frozen rules

### R2-H — CRYPTO-H3: hourly Donchian variants on the admissible hourly pairs

Universe (frozen): **BTC, ETH, SOL, DOGE** vs USD, hourly, from each pair's history start.
Parent: CRYPTO-H1 `crypto_h_donchian168_trail72` (+0.390R / 425, CI low +0.010R on 3 pairs;
+0.465R / 827, CI low −0.010R on 6 pairs including the now-inadmissible XRP and BNB). Two
genuinely different rules, not re-tuned copies; the parent rule is NOT re-run.

1. `crypto_h_donchian168_trail72_quiet` — the parent's entry (close beyond the prior 168 h
   high/low), stop (2 × ATR(24)), trailing exit (close back through the prior 72 h channel)
   and 720 h safety stop, **plus one entry filter**: ATR(24)/close at the signal bar must be at
   or below its median over the prior 240 h. Rationale: breakouts from compressed ranges
   carry more follow-through than breakouts in already-volatile tape (the same contraction
   logic as the daily `volatility_breakout` family, and the volatility-scaling of Moskowitz–
   Ooi–Pedersen 2012); the filter removes trades, so it can raise the CI lower bound only by
   raising expectancy, not by adding count.
2. `crypto_h_donchian336_trail168` — a two-week channel (336 h) with a one-week trailing exit
   (168 h), 2 × ATR(24) stop, 1,440 h safety stop. Rationale: a longer channel trades the
   multi-week trends that the daily `crypto_donchian_55` already shows (sealed +0.98R) at
   hourly resolution with fewer, larger trades and less cost drag.

Gates: CRYPTO-1 gates (`FxGates()`), the admissibility policy above, costs as CRYPTO-2
(BTC 24 / ETH 26 / SOL 40 / DOGE 50 bps per side, 2× stress).

### R2-E1 — `high52_breakout.medium_swing` v0.1.0 (daily equities; George & Hwang 2004)

- **Rule:** LONG when today's close exceeds the highest **high** of the prior 252 sessions
  (a new 52-week high), today's volume ≥ 1.3 × its 20-session average, and the market regime
  is not risk-off. No short side. Stop 2 × ATR(14); target entry + 4 × ATR(14); time stop
  40 sessions.
- **Published basis:** George & Hwang, "The 52-Week High and Momentum Investing," *Journal of
  Finance* 59(5) 2004, 2145–2176, doi:10.1111/j.1540-6261.2004.00695.x — nearness to the
  52-week high predicts returns better than past returns and does not reverse long-run
  (anchoring under-reaction). Our rule is the time-series, single-name version of that
  anchor: a breach of the anchor itself.
- **Gate-5 grid:** `lookback ∈ {189, 252, 315}` × `stop_atr ∈ {1.5, 2.0, 2.5}`.
- **Universes / windows:** snapshot 3 (`universe_24_ex_meta`, 24) and snapshot 11
  (`research_150_massive_10y_presealed_sel`, 150), `--since 2016-10-17 --until 2025-09-07`.
- **Also as CRYPTO-4 `crypto_high252_u9`** on the nine admissible daily pairs (BTC, ETH, SOL,
  XRP, DOGE, ADA, LINK, AVAX, LTC): close above the prior 252-day high, 2 × ATR(20) stop,
  40-bar time stop, no volume term (crypto bars carry no volume here), no regime term.
- **Expectation stated in advance:** overlaps the trend family; the test is whether the
  52-week anchor beats the 50-day SMA rule's +0.26R/+0.30R on the same universes, and whether
  it survives on 150 names where trend fell to +0.11R.

### R2-E2 — `trend_pullback.short_swing` v0.1.0 (daily equities; Jegadeesh 1990 within trend)

- **Rule:** LONG when close > SMA(200) (long-term trend intact), the close has fallen on each
  of the last 3 sessions, close < SMA(10), and the regime is not risk-off. Stop 2 × ATR(14);
  target entry + 2 × ATR(14); time stop 10 sessions. Long only.
- **Published basis:** Jegadeesh, "Evidence of Predictable Behavior of Security Returns,"
  *Journal of Finance* 45(3) 1990, 881–898 — significant negative first-order serial
  correlation in monthly returns (short-term reversal) alongside positive 12-month
  correlation; the rule buys the short-term reversal only where the long-term trend is up.
- **Gate-5 grid:** `sma_fast ∈ {5, 10, 15}` × `stop_atr ∈ {1.5, 2.0, 2.5}`.
- **Universes / windows:** snapshots 3 and 11 as above.
- **Expectation stated in advance:** many trades (good power); the risk is that an 11 bps
  round trip eats a 10-session mean-reversion edge, as it did for `mean_reversion` (+0.03R).

## 2. Commands (scratch copy `sfdata6`, one writer; crypto runs read the live DB read-only)

```
uv run signalforge evaluate-promotion --strategy high52_breakout --symbols "$(cat syms24_snap3.txt)"  --snapshot-key universe_24_ex_meta --since 2016-10-17 --until 2025-09-07
uv run signalforge evaluate-promotion --strategy high52_breakout --symbols "$(cat syms150_snap11.txt)" --snapshot-key research_150_massive_10y_presealed_sel --since 2016-10-17 --until 2025-09-07
uv run signalforge evaluate-promotion --strategy trend_pullback  --symbols ...24...  --snapshot-key universe_24_ex_meta ...
uv run signalforge evaluate-promotion --strategy trend_pullback  --symbols ...150... --snapshot-key research_150_massive_10y_presealed_sel ...
uv run signalforge crypto research --version CRYPTO-4 --pairs BTCUSD,ETHUSD,SOLUSD,XRPUSD,DOGEUSD,ADAUSD,LINKUSD,AVAXUSD,LTCUSD
uv run signalforge crypto research-hourly --version CRYPTO-H3 --pairs BTCUSD,ETHUSD,SOLUSD,DOGEUSD
```

Gate 9 on the equity runs is a diagnostic window on development data (the sealed years for
these new versions are untouched). Results, pass or fail, go to
`docs/research/RESULTS_round2_2026-11-03.md`. A development pass is reported as a sealed-look
candidate and stops there.
