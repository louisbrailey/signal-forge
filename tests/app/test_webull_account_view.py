import json
from datetime import UTC, datetime

from signalforge.account_view import normalize_account


def test_authenticated_real_account_view_is_read_only_and_not_cached(
    registered_client, tmp_path, monkeypatch
):
    from signalforge.config.settings import get_settings

    path = tmp_path / "account.json"
    stamp = datetime.now(UTC).isoformat()
    path.write_text(
        json.dumps(
            {
                "schema": "webull-readonly-v1",
                "environment": "production",
                "trading_enabled": False,
                "checked_at": stamp,
                "last_success": stamp,
                "status": "connected",
                "accounts": [
                    normalize_account(
                        "PRIVATE1234",
                        {"total_asset_currency": "USD", "total_cash_balance": "42.50"},
                        [],
                    )
                ],
                "secret": "private-sentinel",  # pragma: allowlist secret
            }
        )
    )
    monkeypatch.setenv("WEBULL_READONLY_SNAPSHOT_PATH", str(path))
    get_settings.cache_clear()
    response = registered_client.get("/accounts/webull")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    for expected in (
        "42.50",
        "Connected",
        "No open positions",
        "Real-money trading disabled",
        "not labelled live",
    ):
        assert expected in response.text
    assert "PRIVATE1234" not in response.text and "private-sentinel" not in response.text
    assert registered_client.post("/accounts/webull").status_code == 405
    path.write_text("broken")
    assert "Unavailable" in registered_client.get("/accounts/webull").text
    registered_client.cookies.clear()
    assert registered_client.get("/accounts/webull", follow_redirects=False).status_code == 303
