"""Email channel via stdlib smtplib. Only active when SMTP settings are present.

``smtplib`` is stdlib, not a network *dependency* of the app graph in the sense
the S2 contract cares about (that contract is scoped to ``signalforge.portfolio``).
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from signalforge.config import get_settings
from signalforge.domain import AlertChannel
from signalforge.observability import get_logger

_log = get_logger("alerts.email")


class EmailChannel:
    channel = AlertChannel.EMAIL

    def __init__(self, host: str, port: int, username: str, password: str, sender: str, to: str):
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._from, self._to = sender, to

    @classmethod
    def from_settings(cls) -> EmailChannel | None:
        s = get_settings()
        pw = s.smtp_password.get_secret_value()
        if not (s.smtp_host and s.smtp_from and s.smtp_to):
            return None
        return cls(s.smtp_host, s.smtp_port, s.smtp_username, pw, s.smtp_from, s.smtp_to)

    def send(self, subject: str, body: str) -> bool:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._from
        msg["To"] = self._to
        msg.set_content(body)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=15) as smtp:
                smtp.starttls()
                if self._username:
                    smtp.login(self._username, self._password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            _log.warning("alert.email_failed", error=f"{type(exc).__name__}: {exc}")
            return False
        _log.info("alert.email_sent", subject=subject)
        return True
