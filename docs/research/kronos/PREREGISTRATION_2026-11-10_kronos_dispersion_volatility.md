# Pre-registration — does Kronos path dispersion forecast volatility beyond simple measures? (2026-11-10)

Status: written 2026-11-10 after the cross-sectional rank-IC study returned FAIL and before
any analysis of this study. No new inference: it re-uses the saved primary forecasts of that
study. ADR 0004 stays closed and ADR 0005 stays research-only. No sealed look, no
operating-database write, no change to the frozen comparison books.
Outputs, named in advance, in `docs/research/kronos/2026-11-10-cross-sectional/`:
`KRONOS_DISPERSION_VOLATILITY_2026-11-10.md` and `dispersion_summary.json`.

## Why, and what has already been seen

The rank-IC study closed zero-shot Kronos-small as a direction signal (mean rank IC +0.0156
at 10 sessions, Newey–West t +0.66). Its one non-null descriptive row was dispersion: the
spread of the ten sample paths ranked realised absolute return with a rank correlation of
+0.15 to +0.18, and +0.058 to +0.083 after allowing for 20-session realised volatility
(Newey–West t 6.7 to 8.2). Those numbers were seen before this was written. One trailing
measure is a weak control: the model reads 90 sessions of open, high, low, close and volume,
so its spread may simply restate longer-window or range-based volatility. If it adds
information beyond a fair set of simple measures, the place it could matter is risk — three
gap-through stops made 70% of the operating paper book's realised loss. If it does not,
Kronos-small has no zero-shot use here.

## Data (fixed)

The 60 saved primary origin files (paper configuration: look-back 90, T = 0.6, top-p 0.9, 10
paths, 20 steps; 500 names; every fifth session from 2024-07-01), exactly as scored by the
rank-IC study, and the same bars file (nothing after 2025-09-05). An origin is scored at
horizon h only if session origin + h is on or before 2025-09-05.

## Definitions (fixed)

- **Targets** over sessions origin+1..origin+h, h ∈ {5, 10}: **T1 (primary)** realised
  volatility, the root mean square of daily close-to-close log returns; **T2** absolute
  close-to-close return at h (the row already seen); **T3** the largest absolute overnight
  gap, max |open ÷ previous close − 1|.
- **Kronos predictors:** **D1 (primary)** standard deviation across paths of the path return
  at h (as in the rank-IC study); **D2** mean across paths of the root mean square of each
  path's own daily log returns over steps 1..h.
- **Simple measures known at the origin** (bars up to the origin only): realised volatility
  over 5, 20, 60 and 90 sessions; ATR14 ÷ close; 20-session Parkinson range volatility;
  absolute 5-session return.
- **Statistic:** per origin, the cross-sectional ordinary-least-squares regression of the
  target's rank on the Kronos predictor's rank and the seven simple ranks (ranks rescaled to
  [−0.5, 0.5]); the Kronos coefficient series is averaged with a Newey–West t (Bartlett, lag
  ⌈h/5⌉) and reported for each half of the window. Also shown: the plain rank correlation of
  each predictor and each simple measure with each target, and the gain in mean R² from adding
  the Kronos rank to the seven simple ranks.

## Decision rule (fixed)

**PASS** only if, for T1 with D1 at **both** h = 5 and h = 10: mean Kronos coefficient ≥ 0.03,
Newey–West t ≥ 3, and the same sign in both halves. Everything else (D2, T2, T3) is reported
without a verdict. A pass justifies pre-registering a candidate-level study with daily-origin
forecasts (does predicted dispersion flag the trades that gap through their stops?); it
authorises nothing else. A fail closes zero-shot Kronos-small as a risk input as well.

## Expectations (stated in advance)

The coefficient will shrink towards 0.01–0.03 once 60- and 90-session and range volatility
are in the regression; a fail is the more likely outcome. An earlier study here found the
model's volatility forecast no better than trailing 20-session volatility on index ETFs.

## Limits

Same forecasts and window as a study whose dispersion row has been seen; one model size; 60
overlapping origins; a survivor-conditioned list; nominal p-values run small with this few
origins. A pass would be a reason to test further, not a risk model.

Research signal only — no order was placed.
