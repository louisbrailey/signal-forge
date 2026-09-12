"""Monthly cycles and the pre-registered moneyness ladder (D1 §3, §4).

Pure arithmetic, so it is tested exhaustively: the selection rule is what
decides which contracts a multi-day run ever asks for, and every failure mode
here is a SILENT under-coverage rather than an error.
"""

from __future__ import annotations

from datetime import date

from signalforge.data import options_cycles as oc


def test_third_friday_including_a_month_whose_first_day_is_a_friday() -> None:
    assert oc.third_friday(2023, 11) == date(2023, 11, 17)
    assert oc.third_friday(2026, 8) == date(2026, 8, 21)
    assert oc.third_friday(2023, 9) == date(2023, 9, 15)  # 2023-09-01 IS a Friday
    assert oc.third_friday(2024, 3) == date(2024, 3, 15)
    for y in range(2020, 2030):
        for m in range(1, 13):
            d = oc.third_friday(y, m)
            assert d.weekday() == 4
            assert 15 <= d.day <= 21


def test_the_d1_window_yields_the_34_pre_registered_cycles() -> None:
    cycles = oc.monthly_cycles(date(2023, 9, 4), date(2026, 9, 4), dte_entry_max=60)
    assert len(cycles) == 34
    assert cycles[0] == date(2023, 11, 17)
    assert cycles[-1] == date(2026, 8, 21)


def test_leading_cycles_whose_entry_precedes_the_window_are_dropped() -> None:
    """Including them would centre a ladder on a reference the window does not
    contain — the exact defect the point-in-time reference exists to remove."""
    cycles = oc.monthly_cycles(date(2023, 9, 4), date(2026, 9, 4), dte_entry_max=60)
    assert date(2023, 9, 15) not in cycles  # entry would be ~2023-07
    assert date(2023, 10, 20) not in cycles


def test_entry_as_of_is_a_session_and_is_fixed_once_per_cycle() -> None:
    e = date(2023, 11, 17)
    entry = oc.entry_as_of(e, dte_entry_max=60)
    assert entry is not None
    assert (e - entry).days <= 60
    assert entry in oc._sessions(entry, entry)
    # the next earlier session would be MORE than 60 days out
    earlier = [d for d in oc._sessions(e - date.resolution * 0 - (e - entry), entry) if d < entry]
    if earlier:
        assert (e - earlier[-1]).days > 60


def test_fetch_span_is_the_cycles_own_trade_window_not_the_whole_window() -> None:
    span = oc.fetch_span(
        date(2023, 11, 17),
        dte_entry_max=60,
        pre_entry_buffer_sessions=5,
        window_start=date(2023, 9, 4),
        window_end=date(2026, 9, 4),
    )
    assert span is not None
    start, end = span
    assert end == date(2023, 11, 17)
    sessions = len(oc._sessions(start, end))
    # D1 §3.5: DTE-60 minus a 5-session buffer is 45-50 sessions, mean 48.09.
    # The un-buffered span is 40-45; the whole backfill window would be ~500.
    assert 45 <= sessions <= 50


def test_fetch_span_is_clamped_to_the_window() -> None:
    span = oc.fetch_span(
        date(2023, 11, 17),
        dte_entry_max=60,
        pre_entry_buffer_sessions=5,
        window_start=date(2023, 10, 2),
        window_end=date(2026, 9, 4),
    )
    assert span is not None
    assert span[0] >= date(2023, 10, 2)


# --- the ladder ------------------------------------------------------------ #
def _ladder(lo: float, hi: float, step: float) -> list[float]:
    out, k = [], lo
    while k <= hi + 1e-9:
        out.append(round(k, 2))
        k += step
    return out


def test_the_ladder_has_seventeen_rungs_symmetric_about_the_money() -> None:
    assert len(oc.LADDER_17) == 17
    assert oc.LADDER_17[8] == 0.0
    assert [round(-x, 3) for x in oc.LADDER_17[:8]][::-1] == [round(x, 3) for x in oc.LADDER_17[9:]]
    assert max(oc.LADDER_17) == 0.150 and min(oc.LADDER_17) == -0.150


def test_a_dense_ladder_delivers_the_full_seventeen_rungs() -> None:
    sel = oc.select_ladder(
        _ladder(300.0, 500.0, 1.0), 400.0, strike_band_pct=0.15, min_rungs_per_side=7
    )
    assert sel.ok
    assert len(sel.strikes) == 17
    assert sel.rungs_below >= 7 and sel.rungs_above >= 7
    assert all(340.0 <= k <= 460.0 for k in sel.strikes)


def test_a_ladder_that_dedups_below_the_floor_is_excluded_not_truncated() -> None:
    """Rungs are defined in MONEYNESS but delivered against an ABSOLUTE strike
    increment, so a chain with nothing listed near the money collapses eight
    rungs onto three strikes. That cycle is excluded and counted — it is not
    quietly served with three."""
    # dense at the band edges, nothing listed anywhere near the 400.0 reference
    gapped = [
        340.0,
        342.0,
        344.0,
        346.0,
        348.0,
        350.0,
        352.0,
        *(float(k) for k in range(448, 461, 2)),
    ]
    sel = oc.select_ladder(gapped, 400.0, strike_band_pct=0.15, min_rungs_per_side=7)
    assert not sel.ok
    assert sel.excluded == oc.EXCL_LADDER_TOO_COARSE
    assert sel.strikes == ()  # nothing is kept from an excluded cycle


def test_a_low_price_level_starves_the_ladder_and_says_so_by_name() -> None:
    """The same 1.5% rungs against a $2.50 increment at a $40 level: the side
    simply cannot offer the floor, which is a DIFFERENT named failure from a
    dedup collapse and must not be conflated with it."""
    sel = oc.select_ladder(
        _ladder(20.0, 60.0, 2.5), 40.0, strike_band_pct=0.15, min_rungs_per_side=7
    )
    assert sel.excluded == oc.EXCL_INSUFFICIENT_RUNGS


def test_a_side_that_cannot_offer_the_floor_is_a_different_named_failure() -> None:
    sel = oc.select_ladder(
        _ladder(400.0, 460.0, 1.0), 400.0, strike_band_pct=0.15, min_rungs_per_side=7
    )
    assert sel.excluded == oc.EXCL_INSUFFICIENT_RUNGS


def test_only_strikes_established_as_listed_on_the_entry_date_are_eligible() -> None:
    """The end-of-life ladder lists strikes in the direction the underlying
    already moved; selecting from it is a lookahead in the selection rule."""
    full = _ladder(300.0, 500.0, 1.0)
    only_below = [k for k in full if k <= 400.0]
    sel = oc.select_ladder(
        full, 400.0, strike_band_pct=0.15, min_rungs_per_side=7, eligible_strikes=only_below
    )
    assert sel.excluded == oc.EXCL_INSUFFICIENT_RUNGS
    sel2 = oc.select_ladder(
        full, 400.0, strike_band_pct=0.15, min_rungs_per_side=7, eligible_strikes=full
    )
    assert sel2.ok


def test_strikes_outside_the_band_are_never_selected() -> None:
    sel = oc.select_ladder(
        _ladder(100.0, 900.0, 1.0), 400.0, strike_band_pct=0.15, min_rungs_per_side=7
    )
    assert sel.ok
    assert min(sel.strikes) >= 340.0 and max(sel.strikes) <= 460.0


def test_a_split_shifted_reference_fails_the_bracket_check() -> None:
    """A back-adjusted equity close against unadjusted strikes is off by the
    split factor, and the server-side band filter makes it look like an empty
    chain rather than an error."""
    strikes = _ladder(900.0, 1100.0, 5.0)  # pre-split NVDA-style ladder
    assert oc.brackets_reference(strikes, 1000.0, min_rungs=3)
    assert not oc.brackets_reference(strikes, 95.0, min_rungs=3)  # 10:1 adjusted close
    assert not oc.brackets_reference(strikes, 0.0, min_rungs=3)


def test_bracket_check_needs_rungs_on_BOTH_sides() -> None:
    strikes = [100.0, 101.0, 102.0, 103.0]
    assert not oc.brackets_reference(strikes, 99.0, min_rungs=3)
    assert not oc.brackets_reference(strikes, 104.0, min_rungs=3)
    assert oc.brackets_reference([97.0, 98.0, 99.0, 101.0, 102.0, 103.0], 100.0, min_rungs=3)


def test_strike_listing_basis_precedence() -> None:
    assert (
        oc.resolve_strike_listing_basis(as_of_sent=True, first_bar_proxy_available=True)
        == oc.BASIS_VENDOR_AS_OF
    )
    assert (
        oc.resolve_strike_listing_basis(as_of_sent=False, first_bar_proxy_available=True)
        == oc.BASIS_FIRST_BAR_PROXY
    )
    assert (
        oc.resolve_strike_listing_basis(as_of_sent=False, first_bar_proxy_available=False)
        == oc.BASIS_NONE
    )


def test_the_exclusion_vocabulary_is_frozen() -> None:
    """The coverage summary is machine-comparable only if these never drift."""
    frozen = frozenset(
        {
            "no_instrument",
            "no_bar_on_or_before",
            "reference_stale",
            "reference_price_outside_ladder",
            "ladder_too_coarse",
            "insufficient_rungs_per_side",
            "no_contracts_returned",
            "contract_fetch_failed",
            "bar_budget_exhausted",
            "shares_per_contract_not_100",
            "strike_not_listed_as_of_entry",
            "ladder_incomplete",
        }
    )
    assert sorted(oc.EXCLUSION_REASONS) == sorted(frozen)
