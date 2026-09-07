"""Notification channel adapters.

``local`` (on-disk log) is always available. ``email`` requires SMTP settings.
``discord`` requires a well-formed ``DISCORD_WEBHOOK_URL`` (incoming webhook only).
Slack / push / SMS are not implemented.
"""

from __future__ import annotations

from typing import Protocol

from signalforge.domain import AlertChannel


class Channel(Protocol):
    channel: AlertChannel

    def send(self, subject: str, body: str) -> bool: ...


def available_channels() -> list[Channel]:
    from signalforge.alerts.channels.discord import DiscordChannel
    from signalforge.alerts.channels.email import EmailChannel
    from signalforge.alerts.channels.local import LocalChannel

    channels: list[Channel] = [LocalChannel()]
    email = EmailChannel.from_settings()
    if email is not None:
        channels.append(email)
    discord = DiscordChannel.from_settings()
    if discord is not None:
        channels.append(discord)
    return channels
