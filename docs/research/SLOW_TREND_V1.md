# Slow trend v1 — separate, paper-only hypothesis

Registered before this evaluation on 2026-11-03. This does not change either
frozen study, any operating strategy, or promotion thresholds.

Hypothesis: a monthly entry cadence and longer holding period may retain more
price movement after commissions than the rejected short-swing cost filter.
This is an experiment, not a promise of a positive edge.

- Universe fixed to SPY, QQQ, IWM, DIA: four existing liquid US broad-index ETFs.
- At the first observed session close of each month, with 252 prior sessions,
  enter long only if close > SMA200 and 252-session price return > zero.
- ATR14 stop at signal close minus 3 ATR; target at close plus 6 ATR;
  time exit after 126 sessions. No trend exit or trailing stop is implied.
- Next-session open fills; existing gap/stop/target ordering, split quantities,
  dividends, shared cash and historical eligibility gates apply unchanged.
- $10,000 shared cash, no leverage/shorts, 5% maximum initial position,
  20% correlated exposure, existing 0.5% trade / 1.5% aggregate open-risk limits,
  60% portfolio exposure and 10% drawdown entry halt. Four ETFs therefore have
  at most 20% initial invested capital; idle cash earns zero in this model.
- Base costs: project defaults (3bp slippage, 5bp full spread, zero commission).
  Stress: 10bp slippage, 10bp full spread, $0.005/share with $1 minimum per order.
- Fixed simpler comparator: identical monthly cadence, ATR exits and risk limits
  with the two trend conditions removed. Cash is a second, zero-return reference.
  This comparator is NOT buy-and-hold. No benchmark mixes unlike risk budgets.
- One-factor sensitivity: SMA160/SMA240; stop 2.4/3.6 ATR; hold 100/151 sessions.
  Target stays 6 ATR. No winner selection or deployment from these tests.
- Development history ends 2020-12-31; fixed annual folds 2021–2023 are validation;
  2024–latest are previously observed follow-up. Also report one continuous replay
  from 2018 through latest. No parameters are fit; expanding prefixes supply
  only past feature observations. All these dates have been seen in prior work;
  there is NO untouched historical final test and NO new sealed look.
- Report after-cost P&L, trade counts, costs, drawdown, exposure, symbol dependence,
  annual folds, regime entry attribution and sensitivity. Compare paired monthly
  portfolio returns against the simpler comparator with a deterministic circular
  3-month block bootstrap (2,000 draws, seed 20261103, 95% interval). Correlated
  ETF trades are not independent evidence. A positive point return is not proof
  of predictive skill. A CI spanning zero or weak fold stability prevents an
  edge claim. Any future confirmation requires a separately registered study.

Limitations: present-day survivor universe, four correlated ETFs, modeled spreads
instead of historical NBBO, no cash interest/taxes/borrow, revised vendor history,
daily OHLC ambiguity and current sector labels. No optimization or income target
is used to select parameters. All raw input and protocol hashes are recorded.

Research signal only — no order was placed.
