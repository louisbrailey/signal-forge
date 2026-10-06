"""Monthly expiry cycles and the pre-registered moneyness ladder (D1 §3, §4).

Pure arithmetic: no network, no database, no configuration lookup. Everything
here is a deterministic function of a date, a reference price, and a strike set,
so the selection rule can be tested exhaustively against fixture chains before
a single request is made.

Two defects this module exists to fix, both of which silently *under-cover* a
dataset rather than failing it — the worst failure mode for an evidence
pipeline:

* the shipped selection caps are per-underlying **across all expirations**, so a
  34-cycle window keeps the four nearest expiries and silently drops thirty
  cycles, with an ATM-ranked 40-contract slice shared between them;
* the shipped strike band is centred on **today's** price for the whole run, so
  a 2023 chain is centred on a 2026 level and the correct contracts are never
  requested at all.

The replacement is a **deterministic moneyness ladder** evaluated per
(underlying, cycle) against the cycle's own point-in-time reference price. The
ladder, not a cap, decides what is fetched: ``max_contracts_per_cycle`` exists
only as a runaway guard, and a ladder that wants more than the guard allows
fails that cycle loudly rather than truncating it.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from signalforge.data.calendar import sessions as _sessions
from signalforge.data.options_calendar import monthly_expiry as _monthly_expiry

# --------------------------------------------------------------------------- #
# Pre-registered constants (D1 §12). None of these may be LOOSENED after a
# coverage summary has been seen — R4 permits making a gate more searching and
# nothing else. The only permitted responses to a rung shortfall are dropping
# the affected underlying or pre-registering a FINER rung set.
# --------------------------------------------------------------------------- #
LADDER_ID = "LADDER_17"
LADDER_17: tuple[float, ...] = (
    -0.150,
    -0.125,
    -0.100,
    -0.080,
    -0.060,
    -0.045,
    -0.030,
    -0.015,
    0.000,
    0.015,
    0.030,
    0.045,
    0.060,
    0.080,
    0.100,
    0.125,
    0.150,
)
CYCLE_RULE_MONTHLY_THIRD_FRIDAY = "monthly_third_friday"
# How a cycle keyed on the third Friday resolves when that Friday is not an
# XNYS session (Good Friday 2025-04-18, Juneteenth 2026-06-19): the exchange
# lists the PRECEDING session, and the as-of listing is queried on that date.
# Recorded in run provenance so a dataset built on unadjusted calendar Fridays
# (which came back ``no_contracts_returned`` for those cycles) is never mistaken
# for one built on listed expiries.
CYCLE_EXPIRY_ADJUSTMENT = "holiday_preceding_session"

# Frozen exclusion vocabulary (D1 §8.2) — the coverage summary is machine
# comparable only if these strings never drift.
EXCL_NO_INSTRUMENT = "no_instrument"
EXCL_NO_BAR_ON_OR_BEFORE = "no_bar_on_or_before"
EXCL_REFERENCE_STALE = "reference_stale"
EXCL_REFERENCE_OUTSIDE_LADDER = "reference_price_outside_ladder"
EXCL_LADDER_TOO_COARSE = "ladder_too_coarse"
EXCL_INSUFFICIENT_RUNGS = "insufficient_rungs_per_side"
EXCL_NO_CONTRACTS_RETURNED = "no_contracts_returned"
EXCL_CONTRACT_FETCH_FAILED = "contract_fetch_failed"
EXCL_BAR_BUDGET_EXHAUSTED = "bar_budget_exhausted"
EXCL_SHARES_PER_CONTRACT_NOT_100 = "shares_per_contract_not_100"
EXCL_STRIKE_NOT_LISTED_AS_OF_ENTRY = "strike_not_listed_as_of_entry"
EXCL_LADDER_INCOMPLETE = "ladder_incomplete"

EXCLUSION_REASONS: frozenset[str] = frozenset(
    {
        EXCL_NO_INSTRUMENT,
        EXCL_NO_BAR_ON_OR_BEFORE,
        EXCL_REFERENCE_STALE,
        EXCL_REFERENCE_OUTSIDE_LADDER,
        EXCL_LADDER_TOO_COARSE,
        EXCL_INSUFFICIENT_RUNGS,
        EXCL_NO_CONTRACTS_RETURNED,
        EXCL_CONTRACT_FETCH_FAILED,
        EXCL_BAR_BUDGET_EXHAUSTED,
        EXCL_SHARES_PER_CONTRACT_NOT_100,
        EXCL_STRIKE_NOT_LISTED_AS_OF_ENTRY,
        EXCL_LADDER_INCOMPLETE,
    }
)

# How the point-in-time existence of a strike on the entry date was established.
# A dataset built on a weaker basis can never share a snapshot identity with one
# built on a stronger basis (D1 §3.3a, §9.2).
BASIS_VENDOR_AS_OF = "vendor_as_of"
BASIS_FIRST_BAR_PROXY = "first_bar_proxy"
BASIS_NONE = "none"
STRIKE_LISTING_BASES: tuple[str, ...] = (BASIS_VENDOR_AS_OF, BASIS_FIRST_BAR_PROXY, BASIS_NONE)


# --------------------------------------------------------------------------- #
# cycles
# --------------------------------------------------------------------------- #
def third_friday(year: int, month: int) -> date:
    """The calendar third Friday of the month, WITHOUT holiday adjustment.

    This is the cycle's *rule*, not the date the exchange lists. Use
    :func:`cycle_expiry` for the listed expiry a backfill must request.
    """
    fridays = [
        date(year, month, d)
        for d in range(1, _calendar.monthrange(year, month)[1] + 1)
        if date(year, month, d).weekday() == 4
    ]
    return fridays[2]


def cycle_expiry(year: int, month: int) -> date:
    """The monthly expiry the exchange actually lists for ``(year, month)``.

    The third Friday when it is an XNYS session, otherwise the preceding
    session (``options_calendar.monthly_expiry``). Requesting the unadjusted
    Friday from an as-of listing returns no contracts for that cycle, which the
    coverage summary then reports as ``no_contracts_returned`` with zero rungs
    seen — a silent hole, not an error.
    """
    return _monthly_expiry(year, month)


def monthly_cycles(window_start: date, window_end: date, *, dte_entry_max: int) -> tuple[date, ...]:
    """Monthly (third-Friday rule, holiday-adjusted) expiries whose DTE-max
    entry date falls inside the window.

    The ``window_start + dte_entry_max`` floor drops the leading cycles whose
    entry search would begin before the window opens — including them would
    centre a ladder on a reference price the window does not contain.
    """
    if window_end < window_start:
        return ()
    out: list[date] = []
    y, m = window_start.year, window_start.month
    while date(y, m, 1) <= window_end:
        e = cycle_expiry(y, m)
        if window_start + timedelta(days=dte_entry_max) <= e <= window_end:
            out.append(e)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return tuple(out)


def entry_as_of(expiry: date, *, dte_entry_max: int) -> date | None:
    """The cycle's band-centring session: the first XNYS session S with
    ``(expiry - S).days <= dte_entry_max``.

    Fixed **once per cycle, before any entry decision**, so the ladder cannot
    drift as an entry search walks forward through the DTE window. A strategy
    may place its entry anywhere in that window; it may not re-centre the
    ladder.
    """
    earliest = expiry - timedelta(days=dte_entry_max)
    days = _sessions(earliest, expiry)
    return days[0] if days else None


def fetch_span(
    expiry: date,
    *,
    dte_entry_max: int,
    pre_entry_buffer_sessions: int,
    window_start: date,
    window_end: date,
) -> tuple[date, date] | None:
    """The cycle's own trade window — NOT the whole backfill window.

    The shipped path fetches every contract from the window start, pulling ~500
    bars where ~48 are needed; over a three-year window that alone is what puts
    the run above the bar ceiling. The buffer gives the entry session's IV
    inversion and surface fit some context and absorbs a one- or two-session
    entry slip.
    """
    anchor = entry_as_of(expiry, dte_entry_max=dte_entry_max)
    if anchor is None:
        return None
    start = anchor
    if pre_entry_buffer_sessions > 0:
        # walk back `buffer` sessions from the anchor (generous calendar span,
        # then take the tail before the anchor)
        back = _sessions(anchor - timedelta(days=pre_entry_buffer_sessions * 4 + 14), anchor)
        earlier = [d for d in back if d < anchor]
        if earlier:
            start = earlier[-min(pre_entry_buffer_sessions, len(earlier))]
    start = max(window_start, start)
    end = min(window_end, expiry)
    return (start, end) if start <= end else None


# --------------------------------------------------------------------------- #
# ladder selection
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class LadderSelection:
    """What the ladder resolved to for one (underlying, cycle, right).

    ``excluded`` is either ``None`` or one of ``EXCLUSION_REASONS``. When it is
    set, ``strikes`` is empty: a cycle the ladder cannot serve is excluded and
    **counted**, never quietly shortened.
    """

    strikes: tuple[float, ...]
    rungs_below: int
    rungs_above: int
    excluded: str | None = None

    @property
    def ok(self) -> bool:
        return self.excluded is None


def brackets_reference(
    vendor_strikes: Iterable[float], reference: float, *, min_rungs: int
) -> bool:
    """Does the TRUE (unfiltered) vendor ladder straddle the reference price?

    The free, mechanical enforcement of the split-adjustment hazard. Stored
    equity bars are back-adjusted and option strikes are not, so a pre-split
    cycle's reference is off by the split factor; a 4x, 10x or 20x offset fails
    this test by orders of magnitude, as does a stale or wrong-symbol reference.
    Because the band filter is applied server-side, that failure is otherwise
    invisible — it looks exactly like "that cycle had no contracts".
    """
    ks = sorted(set(vendor_strikes))
    below = sum(1 for k in ks if k < reference)
    above = sum(1 for k in ks if k > reference)
    return below >= min_rungs and above >= min_rungs


def select_ladder(
    vendor_strikes: Sequence[float],
    reference: float,
    *,
    strike_band_pct: float,
    min_rungs_per_side: int,
    ladder: Sequence[float] = LADDER_17,
    eligible_strikes: Iterable[float] | None = None,
) -> LadderSelection:
    """Resolve the moneyness ladder against one right's vendor strike set.

    ``eligible_strikes`` restricts selection to strikes whose existence on the
    entry date has been established (D1 §3.3a). ``None`` means "every vendor
    strike is eligible", which is only correct when the listing call itself was
    point-in-time.
    """
    if reference <= 0:
        return LadderSelection((), 0, 0, EXCL_REFERENCE_OUTSIDE_LADDER)
    eligible = set(vendor_strikes) if eligible_strikes is None else set(eligible_strikes)
    # A relative epsilon on the band edges. Without it a strike sitting exactly
    # on the boundary is admitted or refused by binary rounding — which would
    # make a cycle's coverage depend on float representation rather than on the
    # pre-registered band.
    eps = 1e-9 * max(1.0, abs(reference))
    lo = reference * (1.0 - strike_band_pct) - eps
    hi = reference * (1.0 + strike_band_pct) + eps
    pool = sorted(k for k in set(vendor_strikes) if k in eligible and lo <= k <= hi)
    if not pool:
        return LadderSelection((), 0, 0, EXCL_STRIKE_NOT_LISTED_AS_OF_ENTRY)

    # A side that cannot offer the floor even before the ladder is applied is a
    # different failure from one the ladder's own coarseness collapses.
    if sum(1 for k in pool if k < reference) < min_rungs_per_side or (
        sum(1 for k in pool if k > reference) < min_rungs_per_side
    ):
        return LadderSelection((), 0, 0, EXCL_INSUFFICIENT_RUNGS)

    chosen: list[float] = []
    for m in ladder:
        target = reference * (1.0 + m)
        nearest = min(pool, key=lambda k: (abs(k - target), k))
        if nearest not in chosen:
            chosen.append(nearest)
    chosen.sort()
    below = sum(1 for k in chosen if k < reference)
    above = sum(1 for k in chosen if k > reference)
    if below < min_rungs_per_side or above < min_rungs_per_side:
        return LadderSelection((), below, above, EXCL_LADDER_TOO_COARSE)
    return LadderSelection(tuple(chosen), below, above, None)


def resolve_strike_listing_basis(*, as_of_sent: bool, first_bar_proxy_available: bool) -> str:
    """Which point-in-time instrument actually applied, in strict precedence.

    ``vendor_as_of`` > ``first_bar_proxy`` > ``none``. Under ``none`` the ladder
    may not be used for selection at all: an end-of-life ladder preferentially
    offers well-placed short strikes in the direction the underlying has already
    moved, which is favourable selection on realised outcomes — a lookahead in
    the selection rule itself, not a coverage question.
    """
    if as_of_sent:
        return BASIS_VENDOR_AS_OF
    if first_bar_proxy_available:
        return BASIS_FIRST_BAR_PROXY
    return BASIS_NONE
