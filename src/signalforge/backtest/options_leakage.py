"""Chain-aware look-ahead detector — the sibling ``leakage.py`` cannot be (D2 §13).

D2 correction C4: ``leakage.FeatureFn = Callable[[PriceSeries, int], float]`` takes
a single underlying series, and **every** options feature is a function of the
*chain* — ATM IV, IV rank, term-structure slope, the surface-interpolated delta at
a target strike, credit-to-width at the selected strikes, and the strike selector
itself.  None of them can be typed as ``(PriceSeries, int) -> float``, so gate 8's
leakage self-check says nothing whatsoever about an options strategy until this
sibling exists.

The same class of blindness is already realised on the equity side:
``research/strategies/base.py:62-63`` records that ``assert_no_lookahead`` cannot
see the ``regime_by_date`` lag "because it lives in the plumbing and not in any
feature function".  For options the chain *is* the plumbing, which is why
:func:`assert_no_lookahead_chain` and the ``head(t)`` visibility rule of
``option_chain`` are one design and not two: a ``head`` that truncated sessions
but left the contract set at full extent would let a feature read a strike that
did not yet exist, and this harness would pass.

Adding checks here can only create new ways to **fail** gate 8, never make it
easier to satisfy — the same R4 carve-out that permits adding a missing
sensitivity axis (``promotion.py:525-535``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from signalforge.backtest.leakage import LookaheadDetected
from signalforge.data.option_chain import OptionChainSeries
from signalforge.data.series import PriceSeries

ChainFeatureFn = Callable[[OptionChainSeries, PriceSeries, int], float]


def assert_no_lookahead_chain(
    feature_fn: ChainFeatureFn,
    chain: OptionChainSeries,
    underlying: PriceSeries,
    *,
    indices: list[int] | None = None,
    tol: float = 1e-9,
) -> None:
    """Call the feature truncated and untruncated at each ``t`` and compare.

    A correct feature returns the same value both times.  If it does not, it is
    reading sessions — or contracts — after ``t``.
    """
    if len(chain) != len(underlying):
        raise ValueError("chain and underlying must share one session index (D2 §3.5)")
    n = len(chain)
    check = indices or list(range(max(1, n - 25), max(1, n - 1)))
    for t in check:
        truncated = feature_fn(chain.head(t), underlying.head(t), t)
        full = feature_fn(chain, underlying, t)
        if truncated != truncated:  # NaN
            continue
        if abs(truncated - full) > tol:
            raise LookaheadDetected(
                f"chain feature at t={t} changed from {truncated!r} to {full!r} when "
                "future sessions/contracts were revealed — it is reading the future"
            )


# ---------------------------------------------------------------------------
# The required check list (D2 §13.3)
# ---------------------------------------------------------------------------
#
# Each entry mirrors ``promotion.py:536-545``'s ``(name, fn)`` shape so an options
# gate-8 extension (I-O4) can run them exactly as the equity list is run.  The
# lagged ``@ t-5`` variants are not padding: ``promotion.py:542`` already carries
# one because a feature can be clean at ``t`` and still read the future when
# evaluated at an earlier index.


def _sorted_expiry_tickers(chain: OptionChainSeries, t: int) -> list[str]:
    """Contracts visible at ``t``, in a total order (S4 determinism, D2 §15.1)."""
    return sorted(chain.visible_contracts(t))


def visible_contract_count(chain: OptionChainSeries, underlying: PriceSeries, t: int) -> float:
    """Asserts the §3.3 visibility rule is actually applied by ``head``."""
    del underlying
    return float(len(chain.visible_contracts(t)))


def printed_contract_count(chain: OptionChainSeries, underlying: PriceSeries, t: int) -> float:
    del underlying
    return float(len(chain.printed_tickers(t)))


def mean_printed_premium(chain: OptionChainSeries, underlying: PriceSeries, t: int) -> float:
    """A stand-in for the chain-cross-sectional features D5 will pre-register.

    Reduces over a **sorted** ticker list so dict iteration order can never affect
    a result (D2 §15.1).
    """
    del underlying
    tickers = [tk for tk in _sorted_expiry_tickers(chain, t) if chain.print_at(t, tk) is not None]
    if not tickers:
        return float("nan")
    prints = [chain.print_at(t, tk) for tk in tickers]
    return sum(p.last_print for p in prints if p is not None) / len(tickers)


def underlying_to_chain_ratio(chain: OptionChainSeries, underlying: PriceSeries, t: int) -> float:
    close = chain.underlying_close(t)
    if close is None or close <= 0.0:
        return float("nan")
    return float(underlying.close[t]) / close


def select_nearest_strike(chain: OptionChainSeries, underlying: PriceSeries, t: int) -> float:
    """The strike selector — the single most important entry on this list (D2 §13.3 #6).

    A strike selector is where a future-peeking chain bites hardest, and it is not
    a "feature" in the usual sense, so it is the one most likely to be omitted.
    Typed as a float-returning feature so the harness can check it.  Ties break on
    ``(abs(strike - spot), strike, option_ticker)`` — a total order.
    """
    del underlying
    close = chain.underlying_close(t)
    visible = chain.visible_contracts(t)
    if close is None or not visible:
        return float("nan")
    best = min(
        visible.values(),
        key=lambda c: (abs(c.strike - close), c.strike, c.option_ticker),
    )
    return best.strike


def _lag(fn: ChainFeatureFn, k: int) -> ChainFeatureFn:
    def lagged(chain: OptionChainSeries, underlying: PriceSeries, t: int) -> float:
        idx = t - k
        if idx < 0:
            return float("nan")
        return fn(chain, underlying, idx)

    return lagged


OPTIONS_LEAKAGE_FEATURE_CHECKS: Sequence[tuple[str, ChainFeatureFn]] = (
    ("visible_contract_count", visible_contract_count),
    ("visible_contract_count@t-5", _lag(visible_contract_count, 5)),
    ("printed_contract_count", printed_contract_count),
    ("mean_printed_premium", mean_printed_premium),
    ("mean_printed_premium@t-5", _lag(mean_printed_premium, 5)),
    ("underlying_to_chain_ratio", underlying_to_chain_ratio),
    ("select_nearest_strike", select_nearest_strike),
    ("select_nearest_strike@t-5", _lag(select_nearest_strike, 5)),
)


def chain_leakage_self_check(
    chain: OptionChainSeries,
    underlying: PriceSeries,
    *,
    indices: list[int] | None = None,
) -> str | None:
    """Run every registered check.  Returns an error string, or ``None`` on a pass.

    Same shape as ``promotion._leakage_self_check`` so the options gate-8 wiring
    (I-O4) is a call, not a redesign.
    """
    for name, fn in OPTIONS_LEAKAGE_FEATURE_CHECKS:
        try:
            assert_no_lookahead_chain(fn, chain, underlying, indices=indices)
        except LookaheadDetected as exc:
            return f"{name}: {exc}"
    return None
