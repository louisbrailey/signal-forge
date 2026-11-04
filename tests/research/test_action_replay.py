import json
from datetime import date

import pytest

from signalforge.data.accounting_snapshot import fetch_accounting_snapshot
from signalforge.research.action_replay import load_dataset


class Adapter:
    def _request(self, path):
        return json.dumps({"status": "OK", "adjusted": False, "results": []})


def test_loader_requires_raw_prices_and_detects_metadata_tampering(tmp_path):
    m = fetch_accounting_snapshot(Adapter(), tmp_path, ["SPY"], date(2024, 1, 1), date(2024, 2, 1))
    p = tmp_path / m["records"][0]["file"]
    r = json.loads(p.read_text())
    r["symbol"] = "EVIL"
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError, match="metadata"):
        load_dataset(tmp_path)


def test_dividend_missing_pay_date_is_a_hard_failure(tmp_path):
    class Bad(Adapter):
        def _request(self, path):
            if "dividends" in path:
                return json.dumps(
                    {
                        "status": "OK",
                        "results": [
                            {"ex_dividend_date": "2024-01-02", "cash_amount": 1, "currency": "USD"}
                        ],
                    }
                )
            return super()._request(path)

    fetch_accounting_snapshot(Bad(), tmp_path, ["SPY"], date(2024, 1, 1), date(2024, 2, 1))
    with pytest.raises(ValueError, match="pay date"):
        load_dataset(tmp_path)


def test_raw_data_through_all_books_enforces_eligibility_and_shared_account():
    from decimal import Decimal

    from signalforge.backtest.actions import Split
    from signalforge.data.calendar import sessions
    from signalforge.data.series import PriceSeries
    from signalforge.research.action_replay import ActionDataset, compare

    dates = tuple(sessions(date(2023, 1, 3), date(2024, 3, 1)))
    series = {}
    for symbol in ("SPY", "AAA"):
        rows = []
        for i, d in enumerate(dates):
            factor = 2 if symbol == "SPY" and i >= 230 else 1
            p = (100 + i * 0.2) / factor
            v = (3_000_000 if i % 10 == 0 else 1_000_000) * factor
            rows.append((d, p, p + 1 / factor, p - 1 / factor, p, v))
        series[symbol] = PriceSeries.from_bars(symbol, rows)
    data = ActionDataset(
        series,
        (Split("SPY", dates[230], Decimal(2), "synthetic"),),
        (),
        (),
        "synthetic-contract-only",
        dates[0],
        dates[-1],
    )
    report = compare(
        data,
        {
            "SPY": {"instrument_type": "etf", "sector": "broad"},
            "AAA": {"instrument_type": "stock", "sector": "test"},
        },
    )
    assert len(report["books"]) == 5
    assert any(
        s["result"]["fills"] for b in report["books"].values() for s in b["scenarios"].values()
    )
    for book in report["books"].values():
        for scenario in book["scenarios"].values():
            result = scenario["result"]
            assert all(f["symbol"] == "SPY" for f in result["fills"])
            assert any(d["reason"] == "earnings_coverage_unavailable" for d in result["decisions"])
            assert all(Decimal(m["cash_usd"]) >= 0 for m in result["marks"])
            assert (
                scenario["diagnostics"]["income_targets"]["reliability_status"] == "not_established"
            )
