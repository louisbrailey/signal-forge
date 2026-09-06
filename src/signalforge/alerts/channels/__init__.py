"""Notification channel adapters.

``local`` (on-disk log) is always available. ``email`` requires SMTP settings.
Discord / Slack / push / SMS are Phase 2.
"""

from __future__ import annotations

from typing import Protocol

from signalforge.domain import AlertChannel


class Channel(Protocol):
    channel: AlertChannel

    def send(self, subject: str, body: str) -> bool: ...


def available_channels() -> list[Channel]:
    from signalforge.alerts.channels.email import EmailChannel
    from signalforge.alerts.channels.local import LocalChannel

    channels: list[Channel] = [LocalChannel()]
    email = EmailChannel.from_settings()
    if email is not None:
        channels.append(email)
    return channels
