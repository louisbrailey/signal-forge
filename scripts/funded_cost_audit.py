"""Read-only cost attribution from completed historical funded replay reports.

No strategy selection, parameter tuning, provider calls or study writes. Removing
costs from fixed realized fills is accounting attribution, not a zero-cost replay.
"""

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path


def amount(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite accounting input")
    return result


def audit(report):
    if report.get("status") != "DESCRIPTIVE_UNVALIDATED":
        raise ValueError("Historical descriptive report required")
    rows = []
    for strategy, book in report["books"].items():
        for scenario, data in book["scenarios"].items():
            diagnostics = data.get("diagnostics")
            if not diagnostics or diagnostics["calendar_evidence"]["data_kind"] != "backtest":
                raise ValueError("Completed historical backtest required; forward books excluded")
            result = data["result"]
            terminal = result["marks"][-1]
            if terminal["open_positions"] or result.get("open_lots"):
                raise ValueError("Terminal liquidation required")
            initial = amount(diagnostics["calendar_evidence"]["opening_equity_usd"])
            net = amount(terminal["net_liquidation_usd"]) - initial
            costs = amount(result["costs"])
            commission = sum((amount(f["commission"]) for f in result["fills"]), Decimal(0))
            trades = [f for f in result["fills"] if f["side"] == "sell"]
            dividends = sum(
                (
                    amount(e["amount_usd"])
                    for e in result["corporate_events"]
                    if e["kind"] == "dividend_entitlement"
                ),
                Decimal(0),
            )
            realized = sum((amount(f["realized_pnl_usd"]) for f in trades), Decimal(0))
            if realized + dividends != net:
                raise ValueError("Realized P&L and dividends do not reconcile")
            if costs < commission or commission < 0:
                raise ValueError("Invalid cost decomposition")
            if costs != amount(diagnostics["modeled_costs_usd"]):
                raise ValueError("Cost totals disagree")
            if len(trades) != diagnostics["closed_trades"]:
                raise ValueError("Trade count disagrees")
            # Rounded aggregate cost ledger: never claim an executable gross-price book.
            gross_attribution = net + costs
            n = len(trades)
            rows.append(
                {
                    "strategy": strategy,
                    "scenario": scenario,
                    "closed_trades": n,
                    "net_pnl_usd": str(net),
                    "modeled_costs_usd": str(costs),
                    "commissions_usd": str(commission),
                    "spread_slippage_rounding_usd": str(costs - commission),
                    "dividend_entitlement_usd": str(dividends),
                    "fixed_fill_pre_cost_attribution_usd": str(gross_attribution),
                    "average_cost_per_round_trip_usd": str(costs / n) if n else None,
                    "average_pre_cost_attribution_per_round_trip_usd": (
                        str(gross_attribution / n) if n else None
                    ),
                    "cost_reduction_needed_for_historical_breakeven_usd": str(
                        max(-net, Decimal(0))
                    ),
                    "cost_only_breakeven_possible_on_fixed_fills": bool(
                        n and gross_attribution > 0
                    ),
                    "status": (
                        "NO_TRADES"
                        if not n
                        else (
                            "GROSS_LOSS"
                            if gross_attribution <= 0
                            else "COSTS_ERASE_REALIZED_EDGE" if net <= 0 else "POSITIVE_UNVALIDATED"
                        )
                    ),
                    "promotion_allowed": False,
                }
            )
    if not rows:
        raise ValueError("Empty report")
    return {
        "status": "DESCRIPTIVE_COST_AUDIT_ONLY",
        "dataset_sha256": report["dataset_sha256"],
        "rows": rows,
        "limitations": [
            "Fixed realized fills; not a counterfactual replay or forecast.",
            "Cost scenarios change sizing and admissions; their trades are not matched pairs.",
            "Historical breakeven is not a forecast or permission to lower assumed costs.",
            "No changes to strategies, operating books, frozen studies or promotion gates.",
        ],
        "disclaimer": "Research signal only — no order was placed.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.report.stat().st_size > 256 * 1024**2:
        parser.error("Historical report exceeds 256 MiB limit")
    raw = args.report.read_bytes()
    output = audit(json.loads(raw))
    output["input_report_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(output, indent=2))
