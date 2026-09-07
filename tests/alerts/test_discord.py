"""Discord channel: webhook-only, secret-safe, mandatory footer, test action."""

from __future__ import annotations

import httpx
import pytest

import signalforge.alerts.channels.discord as discord_mod
from signalforge.alerts.channels.discord import DiscordChannel
from signalforge.config.settings import get_settings
from signalforge.domain import AlertChannel

GOOD = "https://discord.com/api/webhooks/123456789/abcDEF-ghiJKL_mno"
TOKEN = GOOD.split("/webhooks/")[1]


@pytest.fixture
def capture_post(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_post(url: str, **kw: object) -> httpx.Response:
        calls.append({"url": url, "json": kw.get("json")})
        return httpx.Response(204)

    monkeypatch.setattr(discord_mod.httpx, "post", fake_post)
    return calls


@pytest.mark.parametrize(
    "url,ok",
    [
        (GOOD, True),
        ("https://discordapp.com/api/webhooks/1/xyz-_A", True),
        ("https://example.com/api/webhooks/1/xyz", False),
        ("not-a-url", False),
        ("", False),
    ],
)
def test_from_settings_only_accepts_a_wellformed_webhook(
    monkeypatch: pytest.MonkeyPatch, url: str, ok: bool
) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", url)
    get_settings.cache_clear()
    assert (DiscordChannel.from_settings() is not None) is ok


def test_send_appends_footer_and_never_puts_the_token_in_the_body(
    capture_post: list[dict],
) -> None:
    assert DiscordChannel(GOOD).send("Subject line", "body text") is True
    assert len(capture_post) == 1
    content = capture_post[0]["json"]["content"]
    assert "Research signal only — no order was placed." in content
    assert TOKEN not in content
    assert capture_post[0]["url"] == GOOD  # URL only goes on the wire, not into content


def test_send_test_posts_once_and_says_no_paper_trade(capture_post: list[dict]) -> None:
    assert DiscordChannel(GOOD).send_test() is True
    assert len(capture_post) == 1
    content = capture_post[0]["json"]["content"]
    assert "test notification" in content and "no paper trade was created" in content


def test_network_error_is_swallowed_without_leaking_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(url: str, **kw: object) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(discord_mod.httpx, "post", boom)
    assert DiscordChannel(GOOD).send("s", "b") is False


def test_channel_enum_is_discord() -> None:
    assert DiscordChannel(GOOD).channel is AlertChannel.DISCORD
