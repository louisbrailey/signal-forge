"""The one predicate that says whether the equity paper path may price a position.

A module of its own, and the reason is an import contract rather than taste:
``paper/portfolio.py`` needs the same assertion ``paper/ledger.py`` needs, but
``signalforge.agents`` imports ``paper.portfolio`` and contract **S14** forbids
``signalforge.agents -> signalforge.paper.ledger`` — including indirectly, since
``allow_indirect_imports`` is deliberately not set. Having ``portfolio.py`` import
``ledger.py`` for a three-line check would therefore have made the agents layer
reach the paper *decision* module through the back door and turned a green
contract red for a reason that has nothing to do with what the contract protects.
"""

from __future__ import annotations

from signalforge.db.models import Instrument

__all__ = ["EQUITY_INSTRUMENT_TYPES", "NotAnEquityPosition", "assert_equity_instrument"]

#: The instrument types the equity paper path can price. Identical to the
#: predicate ``assert_auto_simulate_allowed`` already applies, applied at the two
#: other places it matters (map §3.3, D3 §7.1-§7.2).
EQUITY_INSTRUMENT_TYPES = ("stock", "etf")


class NotAnEquityPosition(RuntimeError):
    """An equity function was handed a position it cannot price honestly.

    ``mark_to_market`` and ``portfolio_snapshot`` price every open position from
    the **underlying's** daily bars and test stop/target against the underlying's
    high/low. On an option that is not an approximation, it is a silent
    mis-pricing, so the functions refuse rather than produce a number.

    A distinct exception type, never ``ValueError``: ``scheduler.job_paper_mtm``
    must fail loudly and leave a named ``JobRun`` failure rather than have this
    swallowed by a broad handler.

    This is **defence in depth against a row this design never creates.** The
    options design introduces no new ``Instrument.instrument_type`` value at all —
    the discriminator is ``Candidate.structure_kind``, and options structures live
    in ``options_position``, never in ``paper_position``. Its value is that it
    fires if some *future* code path introduces an option-typed instrument, which
    is why its tests have to construct one that production never will.
    """


def assert_equity_instrument(inst: Instrument, caller: str) -> None:
    """NARROWS, never widens. Provably a no-op against current data: every
    ``instrument`` row is a stock or an ETF, and ``paper_position`` holds no
    options structure by construction."""
    if inst.instrument_type not in EQUITY_INSTRUMENT_TYPES:
        raise NotAnEquityPosition(
            f"{caller} prices positions from the UNDERLYING's daily bars; instrument "
            f"{inst.symbol!r} is {inst.instrument_type!r}. "
            "Use paper.options_marks.mark_options_to_market."
        )
