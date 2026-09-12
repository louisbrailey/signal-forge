"""The equity core is byte-identical — proved, not promised (D2 §1.3).

``STRATEGY_COMPLETION_MAP.md`` §1 R4 freezes ``CostModel`` for the program's
duration and the options program's standing constraint is that the equity path
stays byte-identical.  "By construction" is a promise; a hash is a guarantee.

**This test fires on whitespace and comment edits too, and that is the intended
behaviour.**  Any edit to these two files becomes a deliberate act that must update
the constant below in the same commit, visible in the diff, rather than something
that can slip through under "just a comment".  Two independent checks run here: the
hashes, and a behavioural replay of ``run_backtest`` on the existing fixtures.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import EntrySignal, run_backtest
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction

# The two digests below are pinned sha256 file hashes, not credentials, but
# detect-secrets reads any 64-character hex string as a possible one — so each
# carries the inline allowlist pragma, exactly as the config-hash constants in
# tests/research/test_promotion.py do.  The pragma must sit on the secret's own
# line and the line budget is 100 characters, which is why these names are three
# characters long; ENG is engine.py's digest and CST is costs.py's.
ENG = "62faa6dda709d5ae0efff15fe1165f1c206a792b4ef7cfca9a6e7cfd6fa68c02"  # pragma: allowlist secret
CST = "51f624bb9dca84ccd6421ded552b23de0ede058995598fb1a1ab433fc5147d60"  # pragma: allowlist secret

FROZEN: dict[str, str] = {
    "src/signalforge/backtest/engine.py": ENG,
    "src/signalforge/backtest/costs.py": CST,
}

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.safety
@pytest.mark.parametrize(("rel_path", "expected"), sorted(FROZEN.items()))
def test_equity_core_file_is_unchanged(rel_path: str, expected: str) -> None:
    digest = hashlib.sha256((_REPO_ROOT / rel_path).read_bytes()).hexdigest()
    assert digest == expected, (
        f"{rel_path} changed.  The options program requires the equity path to stay "
        "byte-identical (D2 §1.3) and R4 freezes CostModel.  If the edit is "
        "deliberate, update FROZEN in the same commit so the change is visible in "
        "the diff."
    )


@pytest.mark.safety
def test_sim_trade_behaviour_is_unchanged_on_the_existing_fixtures(
    uptrend_with_dips: PriceSeries,
) -> None:
    """A behavioural replay, so the freeze is not only a file-content claim."""

    def buy_the_dip(series: PriceSeries, t: int) -> EntrySignal | None:
        if len(series) < 3:
            return None
        prev, now = float(series.close[-2]), float(series.close[-1])
        if now / prev - 1.0 > -0.02:
            return None
        return EntrySignal(
            direction=Direction.LONG,
            stop_price=now * 0.965,
            time_stop_bars=10,
            target_price=now * 1.04,
        )

    outcome = run_backtest(uptrend_with_dips, buy_the_dip, cost_model=CostModel())
    assert outcome.trades, "the fixture must produce trades or this test asserts nothing"
    first = outcome.trades[0]
    # Entries fill at the NEXT bar's open, never the signal bar's close.
    entry_idx = uptrend_with_dips.dates.index(first.entry_date)
    raw_open = float(uptrend_with_dips.open[entry_idx])
    assert first.entry_price == pytest.approx(raw_open * (1 + 0.00055), abs=1e-4)
    assert first.costs_bps == pytest.approx(11.0)
    assert first.bars_held >= 1
