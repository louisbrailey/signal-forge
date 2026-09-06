"""S5 — secrets are redacted from logs and never rendered in the clear."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from signalforge.config.settings import Settings
from signalforge.observability import redact
from signalforge.observability.logging import configure_logging, get_logger

pytestmark = pytest.mark.safety

LEAK = "SUPER-SECRET-VALUE-123"


def test_redact_masks_by_key_and_by_type() -> None:
    out = redact(
        {
            "api_key": LEAK,
            "nested": {"password": LEAK, "fine": "keep"},
            "token_list": [SecretStr(LEAK)],
            "count": 3,
        }
    )
    assert LEAK not in repr(out)
    assert out["nested"]["fine"] == "keep"
    assert out["count"] == 3


def test_secretstr_field_never_prints_value() -> None:
    settings = Settings(market_data_api_key=LEAK, app_encryption_key=LEAK)
    assert LEAK not in repr(settings)
    assert LEAK not in str(settings.market_data_api_key)
    assert settings.market_data_api_key.get_secret_value() == LEAK


def test_structlog_pipeline_redacts(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json_output=True)
    log = get_logger("s5-test")
    log.warning("provider.configured", api_key=LEAK, bearer=SecretStr(LEAK), symbol="SPY")
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "provider.configured" in combined
    assert "SPY" in combined
    assert LEAK not in combined
