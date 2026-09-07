"""Discord channel — incoming webhook only.

Reads exactly one value, ``DISCORD_WEBHOOK_URL``, from the local environment. It
is never a bot token, never OAuth, never a Discord login. The URL is treated as
a secret: it is never logged, echoed, cached, or included in an error message.
Only ``send()`` and the explicitly-confirmed test action ever POST.
"""

from __future__ import annotations

import re

import httpx

from signalforge.config import get_settings
from signalforge.domain import AlertChannel
from signalforge.observability import get_logger

_log = get_logger("alerts.discord")

_WEBHOOK_RE = re.compile(r"https://(discord(app)?\.com)/api/webhooks/\d+/[\w-]+")
_FOOTER = "Research signal only — no order was placed."


class DiscordChannel:
    channel = AlertChannel.DISCORD

    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url

    @classmethod
    def from_settings(cls) -> DiscordChannel | None:
        url = get_settings().discord_webhook_url.get_secret_value()
        if not url or not _WEBHOOK_RE.match(url):
            return None
        return cls(url)

    def _post(self, content: str) -> bool:
        # Discord hard limit is 2000 chars; leave room for the mandatory footer.
        body = content.rstrip()
        if _FOOTER not in body:
            body = f"{body}\n\n_{_FOOTER}_"
        body = body[:1990]
        try:
            resp = httpx.post(
                self._url,
                json={"content": body, "allowed_mentions": {"parse": []}},
                timeout=15.0,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            _log.warning("alert.discord.network_error")  # never log the URL
            return False
        ok = resp.status_code in (200, 204)
        _log.info("alert.discord.dispatch", status=resp.status_code, ok=ok)
        return ok

    def send(self, subject: str, body: str) -> bool:
        return self._post(f"**{subject}**\n{body}")

    def send_test(self) -> bool:
        return self._post(
            "**Signal Forge — test notification**\n"
            "If you can read this, the Discord webhook is wired correctly. "
            "No alert policy was evaluated and no paper trade was created."
        )
