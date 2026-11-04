import importlib.util
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from signalforge.data.series import PriceSeries


def load_script(monkeypatch):
    root = Path(__file__).parents[2]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "cost_attribution_report", root / "scripts/cost_attribution_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_factorial_changes_only_declared_cost_axes(monkeypatch):
    module = load_script(monkeypatch)
    values = module.scenarios()
    base, spread = values["base"]
    fee, fee_spread = values["commission_only"]
    friction, friction_spread = values["friction_only"]
    stress, stress_spread = values["combined_stress"]
    assert fee_spread == spread and fee.slippage_bps == base.slippage_bps
    assert friction.commission(10) == base.commission(10) == 0
    assert stress.commission(10) == fee.commission(10) == 1
    assert friction_spread == stress_spread
    assert friction.slippage_bps == stress.slippage_bps
    assert asdict(stress) == {**asdict(fee), "slippage_bps": friction.slippage_bps}


def test_report_cannot_overwrite_an_existing_experiment(tmp_path, monkeypatch):
    module = load_script(monkeypatch)
    output = tmp_path / "experiment"
    output.mkdir()
    sentinel = output / "evidence.json"
    sentinel.write_text("preserve this")
    with pytest.raises(FileExistsError):
        module.run(tmp_path / "absent", tmp_path / "absent.sqlite", None, output)
    assert sentinel.read_text() == "preserve this"


def test_report_records_effective_risk_and_source_before_results(tmp_path, monkeypatch):
    module = load_script(monkeypatch)
    day = date(2024, 1, 2)
    bars = PriceSeries.from_bars("SPY", [(day, 100, 101, 99, 100, 1000000)])
    metadata = {"SPY": {"instrument_type": "etf", "sector": "broad"}}
    monkeypatch.setattr(module, "read_metadata", lambda *_: (metadata, ()))
    monkeypatch.setattr(
        module,
        "load_dataset",
        lambda *_: SimpleNamespace(
            series={"SPY": bars}, start=day, end=day, splits=(), manifest_hash="test-only"
        ),
    )
    monkeypatch.setattr(module, "default_strategies", lambda: [])
    output = tmp_path / "report"
    assert module.run(tmp_path, tmp_path / "unused.sqlite", None, output) == {}
    design = json.loads((output / "design.json").read_text())
    assert design["risk_limits"]["max_position_concentration_pct"] == 5
    assert design["risk_limits"]["max_correlated_exposure_pct"] == 20
    assert design["metadata"] == metadata
    assert design["max_drawdown_pct"] == 10
    assert len(design["runner_sha256"]) == 64
    assert "funded.py" in design["runtime_source_hashes"]
