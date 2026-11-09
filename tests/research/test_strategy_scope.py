import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from signalforge.backtest.actions import TickerChange
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.research.action_replay import ActionDataset, compare
from signalforge.research.prospective_funded import freeze
from signalforge.research.strategy_scope import resolve_strategy_scope

V1 = Path(__file__).parents[1] / "fixtures/studies/funded_forward_v1_metadata.json"


def test_real_v1_metadata_resolves_five_and_actual_compare_executes_only_five(tmp_path):
    parent = json.loads(V1.read_text())
    chosen = resolve_strategy_scope(parent["strategies"])
    assert len(chosen) == 5 < len(resolve_strategy_scope())
    changes = tuple(
        TickerChange(
            c["old"], c["new"], date.fromisoformat(c["effective"]), c["source"], c["evidence"]
        )
        for c in parent["ticker_changes"]
    )
    child = freeze(
        tmp_path / "child",
        parent["metadata"],
        changes,
        parent["symbols"],
        date.fromisoformat(parent["history_start"]),
        strategy_specs=parent["strategies"],
    )
    assert len(child["strategies"]) == 5
    # Real deterministic replay on small, synthetic offline prices, without a
    # patched registry, replay engine or strategy functions. No outcome tuning.
    days = sessions(date(2024, 1, 2), date(2024, 3, 1))
    prices = PriceSeries.from_bars("SPY", [(d, 100, 102, 99, 101, 10000000) for d in days])
    data = ActionDataset({"SPY": prices}, (), (), (), "synthetic", days[0], days[-1])
    result = compare(
        data,
        {"SPY": {"instrument_type": "etf", "sector": "broad"}},
        prospective=True,
        strategy_specs=child["strategies"],
    )
    assert set(result["books"]) == {s.spec().versioned_key for s in chosen}
    assert len(result["books"]) == 5
    for book in result["books"].values():
        assert all(s["diagnostics"] is None for s in book["scenarios"].values())


@pytest.mark.parametrize("fault", ["empty", "unknown", "duplicate", "definition"])
def test_scope_rejects_unknown_changed_or_duplicate_definitions_before_freeze(tmp_path, fault):
    specs = json.loads(V1.read_text())["strategies"]
    if fault == "empty":
        specs = []
    elif fault == "unknown":
        specs[0]["name"] = "unknown"
    elif fault == "duplicate":
        specs.append(specs[0])
    else:
        specs[0]["rule_definition"] = "changed definition"
    with pytest.raises(ValueError):
        freeze(tmp_path / "never-created", {}, (), [], date(2020, 1, 1), strategy_specs=specs)
    assert not (tmp_path / "never-created").exists()


def test_only_code_provenance_can_change_in_frozen_definitions():
    specs = json.loads(V1.read_text())["strategies"]
    specs[0]["git_sha"] = "different-code-provenance"
    assert len(resolve_strategy_scope(specs)) == 5
    assert [asdict(s.spec())["name"] for s in resolve_strategy_scope(specs)] == [
        s["name"] for s in specs
    ]
