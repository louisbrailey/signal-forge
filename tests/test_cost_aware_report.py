import importlib.util
from datetime import date
from pathlib import Path

import pytest

from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.research.action_replay import ActionDataset


@pytest.fixture
def runner(monkeypatch):
    scripts = Path(__file__).parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "cost_aware_report", scripts / "cost_aware_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dataset():
    days = sessions(date(2018, 1, 2), date(2021, 2, 1))
    bars = PriceSeries.from_bars("SPY", [(d, 100, 101, 99, 100, 1000000) for d in days])
    return ActionDataset({"SPY": bars}, (), (), (), "synthetic-contract-only", days[0], days[-1])


def test_prefix_cannot_include_later_prices(runner):
    data = dataset()
    old = runner.prefix(data, date(2020, 12, 31))
    data.series["SPY"].close[-1] = 10000
    new = runner.prefix(data, date(2020, 12, 31))
    assert old.end <= date(2020, 12, 31)
    assert list(old.series["SPY"].close) == list(new.series["SPY"].close)


def test_runner_records_separate_design_and_refuses_rewrite(runner, tmp_path):
    output = tmp_path / "separate-experiment"
    metadata = {"SPY": {"instrument_type": "etf", "sector": "broad_market"}}
    result = runner.run(dataset(), metadata, output)
    assert (output / "design.json").exists()
    assert (output / "fold-2021.json").exists()
    assert result["no_untouched_historical_test"]
    fold = result["folds"][0]
    assert fold["model"]["trained_through"] < date.fromisoformat(fold["evaluation_start"])
    assert fold["model"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert fold["results"]["stress"]["candidate"]["closed_trades"] == 0
    before = (output / "summary.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner.run(dataset(), metadata, output)
    assert (output / "summary.json").read_bytes() == before
