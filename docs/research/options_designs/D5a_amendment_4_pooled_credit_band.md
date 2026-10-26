# D5a Amendment 4 — pooled put + call credit-floor band (v0.1.3)

**Status: PRE-REGISTRATION — legitimate only at k = 0.** Written 2026-10-26, before any
sealed look for `options_short_vertical` (k = 0, confirmed: no `options_*` sealed test row).
**Decision:** OR-F15, operator Louis Brailey, 2026-10-26 (recorded in
`DECISIONS_2026-09-12_wave3.md`).

## 1. What changes

Only the credit-floor band. The values are the alternative Amendment 2 §4.6 already
derived and left un-adopted:

| Parameter | v0.1.2 (put-only band) | **v0.1.3 (pooled band)** |
|---|---|---|
| `min_credit_to_width` baseline | 0.150 | **0.130** |
| gate-5 grid axis | (0.150, 0.155) | **(0.130, 0.150)** — second value is the harder side |
| OAT loosening (reported, never selectable) | 0.140 | **0.110** |
| `CREDIT_TO_WIDTH_QUANTILES` | 0.140 / 0.150 / 0.155 | **0.110 / 0.130 / 0.150** |

**Derivation (unchanged rule, wider population).** D5a's quartile rule applied to the
pooled put + call attainable adverse ratio at `width_usd = 8.00` over Stage A × the IV
grid: 60 cells, all positive, quartiles 0.11375 / 0.13125 / 0.15156, rounded down at 0.005.
The arithmetic is a test:
`tests/research/test_options_short_vertical.py::test_the_v013_band_is_read_off_the_pooled_put_and_call_design_space`.

Everything else is exactly v0.1.2: width $8, delta target 0.20 / max 0.35, stop 2.0, DTE 35
(window 28–45), profit target 0.50, time stop 7 DTE, exact wings, print-eligibility
thresholds, the frozen cost model, underlyings SPY/QQQ/IWM (Amendment 3), the $900 / $3,600
caps and the 4-structure portfolio concurrency cap (D5a §3.5, implemented as IMPL-3.3).

## 2. Why — and the disclosure R1 requires

- **F15** (Amendment 2 §4.6): under the put-only band the call-side mirror enters nothing
  anywhere, so gate 6's bear bucket is structurally empty and the regime filter reduces to
  "sell puts or stand aside". The pooled band makes the bear side reachable (puts admit 28
  of 30 cells and calls 6 of 30 at 0.130, per Amendment 2).
- **Disclosed:** the decision was taken **after** the development-window rejection
  breakdown (`REJECTION_BREAKDOWN_2026-10-06_snapshot17.md`) showed 0 of 11 setups clearing
  the v0.1.2 floor. That is pre-sealed (development) evidence, which R1 permits to inform
  design; **no sealed number was consulted.** The band itself was derived on 2026-09-23,
  before that breakdown existed.

## 3. Variant budget and looks

- This is the O3 family's one design variant after the k = 0 amendments (D5 §10: budget 1,
  hard cap 2). No further band change is permitted before the first look.
- The first `--confirm` evaluation of v0.1.3 is **look 1** for the family. It is not taken
  by this amendment.
- OR-0c is decided **pooled** (2026-10-26); `--confirm` still requires
  `--accept-pooled-coverage OR-0c`.

## 4. Pass / fail

The unchanged D4 gates (0.a–0.i, 0.5, 1–10). A fail is reported as a fail; no v0.1.4
re-tuning of the band follows from this evaluation's numbers.
