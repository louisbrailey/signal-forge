"""Report effective credential routing without claiming absent keys are present."""

from pydantic import SecretStr

from signalforge.app.views import settings_context
from signalforge.config.settings import Settings


def _settings(monkeypatch, **values):
    import signalforge.alerts.channels.discord as discord
    import signalforge.config as config

    cfg = Settings(_env_file=None, **values)
    monkeypatch.setattr(config, "get_settings", lambda: cfg)
    monkeypatch.setattr(discord, "get_settings", lambda: cfg)
    return cfg


def test_existing_shared_key_and_keyless_providers_are_reported_without_secrets(
    session, monkeypatch
):
    _settings(
        monkeypatch,
        market_data_provider="massive",
        market_data_api_key=SecretStr("fixture-market-credential"),
        llm_provider="lmstudio",
        discord_webhook_url=SecretStr("https://discord.com/api/webhooks/123456789/fixture-token"),
    )
    ctx = settings_context(session)
    assert ctx["keys"]["NEWS_API_KEY"] is False
    assert ctx["keys"]["LLM_API_KEY"] is False
    assert ctx["keys"]["NOTIFICATION_API_KEY"] is False
    assert "uses MARKET_DATA_API_KEY" in ctx["key_status"]["NEWS_API_KEY"]
    assert "not required" in ctx["key_status"]["LLM_API_KEY"]
    assert "Discord webhook configured" in ctx["key_status"]["NOTIFICATION_API_KEY"]
    assert ctx["keys"]["DISCORD_WEBHOOK_URL"] is True
    assert "fixture-market-credential" not in str(ctx)
    assert "fixture-token" not in str(ctx)


def test_a_missing_remote_llm_key_is_not_disguised_as_ready(session, monkeypatch):
    _settings(monkeypatch, llm_provider="anthropic")
    ctx = settings_context(session)
    unset = "not set"
    assert ctx["key_status"]["LLM_API_KEY"] == unset
    assert ctx["llm_enabled"] is False
    assert ctx["key_status"]["NEWS_API_KEY"] == unset
    assert "local log" in ctx["key_status"]["NOTIFICATION_API_KEY"]


def test_settings_page_explains_shared_news_and_optional_keys(registered_client, monkeypatch):
    _settings(
        monkeypatch,
        market_data_provider="massive",
        market_data_api_key=SecretStr("fixture-market-credential"),
        llm_provider="lmstudio",
        discord_webhook_url=SecretStr("https://discord.com/api/webhooks/123456789/fixture-token"),
    )
    response = registered_client.get("/settings")
    assert response.status_code == 200
    assert "uses MARKET_DATA_API_KEY for Massive news" in response.text
    assert "not required by configured OpenAI-compatible provider" in response.text
    assert "Discord webhook configured" in response.text
    assert "fixture-market-credential" not in response.text
    assert "fixture-token" not in response.text
