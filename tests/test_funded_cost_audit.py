import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "funded_cost_audit", Path(__file__).parents[1] / "scripts/funded_cost_audit.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def report():
    return {
        "status": "DESCRIPTIVE_UNVALIDATED",
        "dataset_sha256": "test",
        "books": {
            "strategy@1": {
                "scenarios": {
                    "stress": {
                        "diagnostics": {
                            "calendar_evidence": {
                                "data_kind": "backtest",
                                "opening_equity_usd": "10000",
                            },
                            "modeled_costs_usd": "4",
                            "closed_trades": 1,
                        },
                        "result": {
                            "marks": [{"net_liquidation_usd": "9999", "open_positions": 0}],
                            "open_lots": {},
                            "costs": "4",
                            "fills": [
                                {"side": "buy", "commission": "1"},
                                {"side": "sell", "commission": "1", "realized_pnl_usd": "-3"},
                            ],
                            "corporate_events": [
                                {"kind": "dividend_entitlement", "amount_usd": "2"},
                                {"kind": "dividend_payment", "amount_usd": "2"},
                            ],
                        },
                    }
                }
            }
        },
    }


def scenario(r):
    return r["books"]["strategy@1"]["scenarios"]["stress"]


def test_attribution_reconciles_and_never_promotes_or_mutates():
    r = report()
    before = deepcopy(r)
    row = module.audit(r)["rows"][0]
    assert r == before
    assert row["net_pnl_usd"] == "-1"
    assert row["fixed_fill_pre_cost_attribution_usd"] == "3"
    assert row["spread_slippage_rounding_usd"] == "2"
    assert row["status"] == "COSTS_ERASE_REALIZED_EDGE"
    assert row["promotion_allowed"] is False


def test_gross_loser_cannot_be_fixed_by_cost_reduction():
    r = report()
    s = scenario(r)
    s["result"]["marks"][0]["net_liquidation_usd"] = "9990"
    s["result"]["fills"][-1]["realized_pnl_usd"] = "-12"
    row = module.audit(r)["rows"][0]
    assert row["status"] == "GROSS_LOSS"
    assert row["cost_only_breakeven_possible_on_fixed_fills"] is False


@pytest.mark.parametrize("defect", ["forward", "open", "reconciliation", "cost", "nan"])
def test_incomplete_or_inconsistent_evidence_fails(defect):
    r = report()
    s = scenario(r)
    if defect == "forward":
        s["diagnostics"] = None
    elif defect == "open":
        s["result"]["marks"][0]["open_positions"] = 1
    elif defect == "reconciliation":
        s["result"]["fills"][-1]["realized_pnl_usd"] = "99"
    elif defect == "cost":
        s["result"]["costs"] = "1"
    else:
        s["result"]["costs"] = "NaN"
    with pytest.raises(ValueError):
        module.audit(r)
