# Pre-registration — strategy program across every available data domain (2026-11-02)

**Status: pre-registered before any backtest of the rules below.** Operator request
(2026-11-02): "develop strategies for 5–10 symbols each that cover the entire available
universe of data … everything must be 100% true, evidence based and researched deeply."
Every rule here is frozen in this document and in code **before** it is run. Results go to
`docs/research/RESULTS_universe_program_2026-11.md` whatever they are.

What "evidence based" means here: each design is taken from a peer-reviewed or widely
replicated published result, cited with the publication record that was checked on
2026-11-02 (web lookups; where only secondary sources were reachable that is stated). The
published effect is the *hypothesis*; our own out-of-sample gates decide whether it exists
in our data, on our universe, after our costs. A published paper is never treated as
evidence that the strategy works for us.

## 0. Data domains in this installation (verified by query, 2026-11-02)

| Domain | Source | Coverage in `data/signalforge.sqlite` | Used by |
|---|---|---|---|
| US equities / ETFs, daily | Massive Stocks (`massive`) | 1,016 instruments 2016-09-12 → today; history probe on 2026-11-02 found bars back to **2003-09-03**, so deeper history is being ingested for the ETF universes below | A, B, E |
| US equities, 15-minute | Massive Stocks | 23 symbols, 1.52M bars, 2016-09-01 → 2026-10-26 | F (intraday ORB, separate pre-registration) |
| FX spot, daily | Massive Currencies (`massive_fx`) | 7 majors + XAUUSD, 2010-01-04 → today | C |
| Crypto spot, daily | Massive Currencies (`massive_crypto`) | BTC 2015-01, ETH 2015-08, SOL 2021-02 → today; **10 further USD pairs verified available** on 2026-11-02 (XRP, ADA, DOGE, LTC, LINK, AVAX, DOT, BCH, XLM, BNB), being backfilled | D |
| Crypto spot, hourly | Massive Currencies | BTC/ETH/SOL 2017/2022 → today (222k bars) | CRYPTO-H1 (already evaluated; near miss) |
| Options | Massive Options | SPY chain snapshots Sep–Oct 2026 + bounded per-contract daily aggregates; no NBBO | not evaluable for a multi-year backtest (OR-0c) |
| News | licensed multi-publisher feed | 788 items, 2026-09 → 2026-10; Benzinga stale | no history → no backtest; excluded |
| Free web data | stooq adapter (daily) | not ingested | robustness only, if needed |

Other API keys in `.env` (LLM, notifications, SMTP, Discord) carry no market data.

## 1. Program

Each family trades a **5–10 symbol universe**, is implemented in the existing engines, and
is judged by the existing gates (equity promotion ladder, or the FX/crypto development
gates + one-time sealed year). Nothing is armed by this document.

| Id | Family | Universe (frozen) | Engine / gates | Published basis |
|---|---|---|---|---|
| A | Diversified-ETF time-series momentum, `tsmom_etf.medium_swing` v0.1.0 | SPY, QQQ, IWM, EFA, EEM, TLT, IEF, GLD, DBC, VNQ (10) | equity ladder, gates 0–10 | Moskowitz–Ooi–Pedersen (2012); Hurst–Ooi–Pedersen (2017); Faber (2007) |
| B | Turn-of-the-month, `turn_of_month.short_swing` v0.1.0 | SPY, QQQ, DIA, IWM, EFA, EEM (6) | equity ladder | McConnell–Xu (2008) |
| C | FX one-month momentum, `fx_mom_21`, version **FX-3** | EURUSD, USDJPY, GBPUSD, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD (8) | FX harness, FX-2 gates (incl. 1 bp/day holding cost) | Menkhoff–Sarno–Schmeling–Schrimpf (2012) |
| D | Crypto, version **CRYPTO-2**: the three CRYPTO-1 rules unchanged **plus** `crypto_mom_21` | BTC, ETH, XRP, BNB, SOL, DOGE, ADA, LINK, AVAX, LTC (10, vs USD) | crypto harness, CRYPTO-1 gates | Liu–Tsyvinski–Wu (2022) for the momentum rule; CRYPTO-1 rules carried over unchanged |
| E | Existing six equity strategies on two new 5–10 symbol universes | E1 sector SPDRs: XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY + SPY (10); E2 mega-caps: AAPL, AMZN, GOOGL, HD, JPM, MSFT, NVDA, UNH, XOM (9) | equity ladder, no new code | the strategies' own existing pre-registrations |

Documented as **not run**, with the reason:

- **Overnight premium** (Lou–Polk–Skouras 2019; buy close / sell open): the frozen engine
  fills every entry at the *next open*, so a close-to-open position cannot be expressed
  without changing the engine; and at 11 bps round-trip cost against a per-night effect of
  a few bps it is rejected by construction. Not implemented.
- **Volatility-managed exposure** (Moreira–Muir 2017): a sizing overlay, not an entry rule;
  out-of-sample support is contested (Cederburg et al.; Reschenhofer–Zechner 2025). Not a
  candidate for this engine.
- **Options**: no multi-year history on this plan (`OPTIONS_EXECUTION_PROGRAM_MAP` §0.4).
- **News / LLM**: no historical feed; the project forbids news from shaping a signal (S12).

## 2. Frozen rules

### A. `tsmom_etf.medium_swing` v0.1.0

- **Signal (own-asset trend, evaluated on the last exchange session of each month only,
  using the exchange calendar — a deterministic, known-in-advance input):**
  `mom = close[t] / close[t-252] - 1` (12-month return, MOP 2012 use the trailing 12-month
  excess return; cash yield is not subtracted here — stated, not tuned) and
  `close[t] > SMA(close, 210)` (Faber's 10-month moving average ≈ 210 sessions).
  LONG when `mom > 0` and the SMA filter holds; SHORT (only when shorts are enabled) when
  `mom < 0` and `close < SMA(210)`.
- **Entry:** next session's open (engine convention). **Stop:** 3 × ATR(20) from the signal
  close (disaster stop only; the literature sizes by volatility, which this engine cannot).
  **No target. Time stop:** 21 sessions, so the position is re-decided at the next month end.
- **Regime gate:** none. The equity-market regime proxy is not an input to a strategy whose
  whole content is each asset's own trend.
- **Gate-5 grid (pre-registered):** `lookback ∈ {189, 252, 315}` × `sma_window ∈ {168, 210,
  252}`.
- **Data window:** `--since 2006-03-01` (DBC, the youngest member, lists 2006-02-03) to
  `--until 2025-09-07`; gate 9 on a new snapshot is a diagnostic window on development data.
- **Expectation stated in advance:** positive expectancy across the universe with low
  turnover (≤ 12 entries per symbol per year); the bootstrap CI gate (+0.02R) is the one
  most likely to fail because trades are few.

### B. `turn_of_month.short_swing` v0.1.0

- **Signal:** on the session two sessions before the month's last session (so the engine's
  next-open fill lands on the last session, McConnell–Xu's day −1). Determined from the
  exchange calendar, never from future bars.
- **Hold:** time stop 3 sessions after entry → exit at the close of the third session of the
  new month (McConnell–Xu's −1 … +3 window). **Stop:** 3 × ATR(14) disaster stop. No target.
  Long only. No regime gate.
- **Gate-5 grid:** `hold_bars ∈ {2, 3, 4}` × `stop_atr ∈ {2.0, 3.0, 4.0}`.
- **Data window:** `--since 2003-10-20 --until 2025-09-07` (all six ETFs list by 2003-04).
- **Expectation stated in advance:** small positive expectancy per trade (the published
  effect is a few tenths of a percent over four days) against an 11 bps round trip; gate 4
  (CI low > +0.02R) and gate 7 (Sharpe vs SPY) are the likely failures. Twelve trades per
  symbol per year give ~1,500 trades over the window, so power is not the issue.

### C. `fx_mom_21` (FX-3)

- **Signal:** direction = sign of the 21-day return `close[-1]/close[-22] - 1`; one position
  per pair at a time (engine convention). **Stop:** 2 × ATR(20). **Time stop:** 21 bars.
- **Gates:** FX-2 gates (FX-1 gates + 1 bp/day holding-cost stress), unchanged.
- **Expectation stated in advance:** Menkhoff et al. report the effect cross-sectionally
  across up to 48 currencies and note it is partly explained by transaction costs; Sarno is
  quoted saying majors-only momentum lost money over the last decade of their sample. A
  fail on majors is the more likely outcome and will be reported as such.

### D. CRYPTO-2 (10 pairs)

- **Rules:** `crypto_donchian_55`, `crypto_tsmom_126_ma50`, `crypto_zfade_20` exactly as in
  CRYPTO-1, plus `crypto_mom_21` = rule C with crypto costs.
- **Costs:** BTC 24 / ETH 26 / SOL 40 bps per side as before; every other pair the
  pre-existing default of **50 bps per side** (`CRYPTO_DEFAULT_SPREAD_BPS`), 2× stress.
- **Gates:** CRYPTO-1 gates unchanged. The sealed year for CRYPTO-2 is a *new* version and
  needs its own operator-authorised look; this run evaluates the development window only.
- **Expectation stated in advance:** Liu–Tsyvinski–Wu find 1–4 week momentum strongest among
  large coins; `crypto_donchian_55` passed on 3 pairs (sealed +0.98R/17); whether either
  survives a 10-pair universe with 50 bps costs is the question.

### E. Existing strategies on new universes

No new rules. Snapshot keys `research_sector10_2003_2025` and `research_megacap9_2003_2025`;
`--since 2003-10-20 --until 2025-09-07` once the deep history is ingested (fallback
`--since 2016-10-17` if any member lacks 2003 bars; gate 0 decides, not us).

## 2.1 Data amendments recorded BEFORE any run (2026-11-02, after ingestion, before backtests)

- **HYG excluded from every universe and reserve list.** Massive returns bars for `HYG` from
  2004-02-04 at ~$25 with volumes of ~1,400 shares; the iShares high-yield ETF listed on
  2007-04-04. The pre-2007 rows are a different security that reused the ticker. Symbol
  reuse is a known hazard of this feed; HYG was a reserve name only and is dropped.
- **QQQ deep history unavailable.** The 2003 → 2016 range for `QQQ` fails Massive's own
  completeness check twice ("unavailable, incomplete, or invalid daily data"; the fund traded
  as `QQQQ` 2004–2011). QQQ's bars start 2016-10-17. Rule for families A and B, fixed now:
  run each **twice** — (i) the frozen universe including QQQ with `--since 2016-10-17`
  (9 years), and (ii) the frozen universe **minus QQQ** with the long window stated in §2.
  Both results are reported; neither is chosen after the fact. Gate 0 is still the judge of
  data availability in each run.
- Every other member of the A, B and E universes has `massive` bars from 2003-10-20 (SPDRs,
  SPY, DIA, IWM, EFA, EEM, TLT, IEF) or from its own listing date (VNQ 2004-09, GLD 2004-11,
  DBC 2006-02), verified by query on 2026-11-02 after ingestion runs #83/#84.

## 3. Commands (scratch copies; one writer per copy)

```
# A + B + E (equity ladder; all default strategies run, gate 0 filters the rest)
uv run signalforge evaluate-promotion --symbols SPY,QQQ,IWM,EFA,EEM,TLT,IEF,GLD,DBC,VNQ \
  --snapshot-key research_etf10_tsmom_2006_2025 --since 2006-03-01 --until 2025-09-07
uv run signalforge evaluate-promotion --symbols SPY,QQQ,DIA,IWM,EFA,EEM \
  --snapshot-key research_index6_tom_2003_2025 --since 2003-10-20 --until 2025-09-07
uv run signalforge evaluate-promotion --symbols XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY,SPY \
  --snapshot-key research_sector10_2003_2025 --since 2003-10-20 --until 2025-09-07
uv run signalforge evaluate-promotion --symbols AAPL,AMZN,GOOGL,HD,JPM,MSFT,NVDA,UNH,XOM \
  --snapshot-key research_megacap9_2003_2025 --since 2003-10-20 --until 2025-09-07
# C
uv run signalforge fx research --version FX-3
# D
uv run signalforge crypto research --version CRYPTO-2 \
  --pairs BTCUSD,ETHUSD,XRPUSD,BNBUSD,SOLUSD,DOGEUSD,ADAUSD,LINKUSD,AVAXUSD,LTCUSD
```

## 4. Sources checked (2026-11-02)

- Moskowitz, Ooi, Pedersen, "Time Series Momentum," *Journal of Financial Economics* 104
  (2012) 228–250, doi:10.1016/j.jfineco.2011.11.003. 58 futures/forwards, 1985–2009; the
  past 12-month excess return predicts the next month's return in every contract. (AQR
  article page and dataset page; Yale-hosted PDF.)
- Hurst, Ooi, Pedersen, "A Century of Evidence on Trend-Following Investing," *Journal of
  Portfolio Management*, Fall 2017 (SSRN 2993026). 67 markets, four asset classes, gross and
  net of simulated costs.
- Faber, "A Quantitative Approach to Tactical Asset Allocation," *Journal of Wealth
  Management*, Spring 2007 — 10-month SMA rule. Only secondary sources were reachable; the
  rule itself (price vs 10-month SMA, monthly) is what is used, not any quoted return.
- Menkhoff, Sarno, Schmeling, Schrimpf, "Currency Momentum Strategies," *JFE* 106(3) (2012)
  660–684, doi:10.1016/j.jfineco.2012.06.009. Cross-sectional spread up to 10%/yr, partly
  explained by transaction costs, strongest at the 1-month horizon.
- Liu, Tsyvinski, Wu, "Common Risk Factors in Cryptocurrency," *Journal of Finance* 77(2)
  (2022) 1133–1177, doi:10.1111/jofi.13119. Market, size and momentum (CMOM, 1–4 week)
  factors; momentum stronger among large coins; the 3-week window is the best in-sample
  choice (data-snooping caveat noted by secondary sources).
- McConnell, Xu, "Equity Returns at the Turn of the Month," *Financial Analysts Journal*
  64(2) (2008) 49–64. 1926–2005: outside the four-day turn-of-month interval the equity
  premium is essentially zero; effect present in 31 of 35 countries.
- Lou, Polk, Skouras, "A tug of war: Overnight versus intraday expected returns," *JFE*
  134(1) (2019) 192–213, doi:10.1016/j.jfineco.2019.03.011. (Not run; see §1.)
- Moreira, Muir, "Volatility-Managed Portfolios," *Journal of Finance* 72(4) (2017)
  1611–1644, doi:10.1111/jofi.12513. (Not run; see §1.)
- Zarattini, Aziz, "Can Day Trading Really Be Profitable?" SSRN 4416622 (2023): 5-minute
  ORB on QQQ, 2016–2023, no spread/slippage modelled; an independent replication reports
  the gross result reproduced and the net result ≈ zero. Governs the cost caveat on the
  intraday family, which has its own pre-registration.

Massive crypto pair availability (XRP, ADA, DOGE, LTC, LINK, AVAX, DOT, BCH, XLM, BNB) was
verified by fetching 13 days of bars for each on 2026-11-02 into a scratch copy, not by
documentation. Massive Stocks history depth (2003-09-03) was discovered by the ingest's own
binary-search probe on 2026-11-02 and is recorded on the `ingestion_run`.

## 7. Refinement round 1 — pre-registered 2026-11-02 evening, BEFORE these variants are run

**Disclosure of looks.** Each parent rule below has been evaluated ONCE on its development
window (results in `RESULTS_universe_program_2026-11.md`). The refinements are not parameter
sweeps on those results: each is a single, literature-motivated change, fixed here before it
is run, and each parent's result stands as reported. Operator request: "keep refining all
strategies and trading modalities."

### 7.1 A2 — `tsmom_etf.position` v0.1.0 (quarterly hold)

- **Parent:** `tsmom_etf.medium_swing` (§2A): dev OOS +0.130R / 93 trades on 10 ETFs 2016+,
  +0.077R / 224 on 9 ETFs 2006+; CI gate and benchmark gate failed; 100% of the grid positive.
- **Hypothesis:** MOP (2012) and HOP (2017) report trend persistence of 1–12 months; a rule
  that exits every 21 sessions and re-enters pays an 11 bps round trip every month and
  truncates the holding period the evidence is about. Holding for a quarter (63 sessions)
  should raise expectancy per trade and lower turnover at the same signal.
- **The single change:** `time_stop_bars` 21 → **63**. Signal, filter, stop, universes,
  grid (`lookback` × `sma_window`), windows: unchanged. Registered as its own key so the
  parent stays reproducible.

### 7.2 CRYPTO-3 — `crypto_mom_21_long_u10` (long only)

- **Parent:** `crypto_mom_21_u10` (CRYPTO-2): +0.115R / 620, CI low −0.052R, 7/10 pairs
  positive, 2/4 folds.
- **Hypothesis:** Liu–Tsyvinski–Wu's cryptocurrency momentum premium is documented in the
  long leg of large coins; a spot paper book cannot short; the short leg in a market with a
  strong positive drift over the sample is the likely source of the negative folds.
- **The single change:** drop SHORT signals. Everything else (21-day lookback, 2×ATR(20)
  stop, 21-bar hold, costs, 10-pair universe, gates) unchanged.

### 7.3 CRYPTO-H2 — the three CRYPTO-H1 hourly rules on 6 pairs

- **Parent:** CRYPTO-H1 `crypto_h_donchian168_trail72`: +0.390R / 425 on BTC/ETH/SOL, CI low
  +0.010R (gate needs +0.02R); the other two H1 rules fail outright.
- **Hypothesis:** the near miss is a power problem (425 trades, CI half-width ≈ 0.38R); the
  same rule on six liquid pairs roughly doubles the trade count. No parameter changes.
- **Universe (frozen):** BTC, ETH, SOL, XRP, BNB, DOGE vs USD, hourly bars backfilled from
  2017-01-01 (or each pair's start). Costs as CRYPTO-2 (50 bps/side default for the new
  pairs). Gates: CRYPTO-1 gates.

### 7.4 Explicitly NOT refined

- `turn_of_month.short_swing`: 0% of the gate-5 grid is positive on 2016+ data — no
  neighbourhood to refine towards; the published effect does not survive costs here.
- `fx_mom_21`: 0/4 folds positive, 38% of pairs positive — rejected, not refined.
- The three live-approved equity strategies: any change would be fitted to results already
  seen on the development data; they stay as approved and are judged by paper forward results.
