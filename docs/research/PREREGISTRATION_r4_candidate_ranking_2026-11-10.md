# Pre-registration — R4-K: does relative-strength ranking pick the better same-day candidates?

Status: written 2026-11-10 after the R3 results and before any run of this study. Operator
request (2026-11-10): "continue pushing for more profit within each strategy and the kronos ai
part of the workflow". No sealed look, no operating-database write, no change to any frozen
study, risk limit or approved version. Results file, named in advance:
`docs/research/RESULTS_r4_candidate_ranking_2026-11-10.md`.

## Why

R3-C found that which same-day signals are admitted moves the 150-symbol
trend_continuation.medium book by about 20 points of net return, and that ordering candidates
by 63-session relative strength (key K1) cleared the pre-registered bar for that book on the
operating caps in both periods. The pass is fragile: it does not hold on the maximum caps or
at stress costs, K1 did nothing for high52 or trend_continuation.short, and a funded replay
is path-dependent (one early admission changes every later one). A funded replay also scores
only the 4% to 5% of signals that get in. The direct question — on a day with several
candidates, do the higher-ranked ones do better? — uses every signal and has far more power.
The operating scan gives every passed candidate the same score (0.5), so a ranking that
works would be new information for admission, and is the place a forecast could later plug in.

## Scope (fixed)

- Primary book: trend_continuation.medium_swing on snapshot 11 (the one R3-C candidate that
  held up against the reviewer's wider random set). The other three approved books are
  reported with the same tables, labelled descriptive.
- Window 2016-10-17..2025-09-05, persisted `massive` adjusted daily bars from the read-only
  scratch copy; nothing on or after 2025-09-07 is loaded. IS and OOS as in R3-C
  (signal sessions whose entry session is on or before 2022-02-10, and after it).
- **Candidate:** every long signal the version's rule produces on a session, whether or not a
  funded account could have taken it. **Outcome:** the result of taking that signal alone at
  the next open under the funded replay's own fill-validity rules and the version's own
  exits, base costs, in units of planned risk (`(exit − entry) / (close_t − stop_t)`). A
  signal the replay would refuse at the open (crossed stop, reward-to-risk below its floor)
  is not a candidate outcome; such signals are counted.
- **Identity check (must pass first):** for the R3-C alphabetical replay of each book on the
  operating caps, every admitted trade's per-share result must equal the isolated outcome of
  the same symbol and signal session.
- **Keys**, from bars up to and including the signal session only, as defined in R3-C: K1
  63-session return (minus SPY's, which does not change a same-day ranking), highest first;
  K2 volume surge; K3 stop distance. K1 is the hypothesis; K2 and K3 are shown as controls.

## Statistics (fixed)

On every signal session with at least 3 candidates:

- **Top-2 lift (primary):** mean outcome of the two highest-K1 candidates minus the mean
  outcome of all that session's candidates. The operating cap admits two a day, so this is
  what ranking would change. Mean over sessions; one-sided p from a calendar-month block
  bootstrap of sessions (10,000 resamples, seed 20261110, null recentred).
- **Within-day rank IC:** Spearman correlation between key and outcome across the session's
  candidates, averaged over sessions, same bootstrap.
- **Rank buckets:** mean outcome by within-day tercile of the key, pooled over sessions.
- **Random-2 band:** the same top-2 lift for 1,000 random within-day rankings (seed
  20261110 + i), to show the noise of a two-a-day pick.

## Decision rule (fixed)

K1 is **confirmed as an admission ranker for trend_continuation.medium** only if all hold:
top-2 lift positive in IS and in OOS; OOS one-sided p < 0.05; within-day rank IC positive in
both; and the OOS top-2 lift is above the 95th percentile of the random-2 band. One
hypothesis, so no multiplicity adjustment; K2, K3 and the other books carry no verdict.
Anything else is reported as "not confirmed", and the R3-C candidate is then read as
admission luck. No added key, threshold or horizon after results are seen.

## Expectations (stated in advance)

Uncertain. R3-C points to a positive lift for this book; fifteen conditioners failed
out-of-sample as filters on the same rule, and K1 was at about twice chance across books.
A small positive lift that does not clear the bar is the most likely outcome.

## What a result does and does not license

The data are the same development sessions R3-C used, so a pass is a robustness result on an
existing candidate, not independent confirmation; only prospective evidence is clean. A pass
would justify building ranked admission behind an off-by-default setting and pre-registering
a prospective comparison for the next study generation. Nothing here changes the operating
scan, ledger, risk limits or any frozen study.

Research signal only — no order was placed.
