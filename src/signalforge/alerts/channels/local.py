"""Local channel — appends every alert to a JSONL file under the data dir."""

from __future__ import annotations

import json

from signalforge.config import paths
from signalforge.db.types import utcnow
from signalforge.domain import AlertChannel
from signalforge.observability import get_logger

_log = get_logger("alerts.local")


class LocalChannel:
    channel = AlertChannel.LOCAL

    def send(self, subject: str, body: str) -> bool:
        path = paths.logs_dir() / "alerts.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"ts": utcnow().isoformat(), "subject": subject, "body": body},
                    ensure_ascii=False,
                )
                + "\n"
            )
        _log.info("alert.local", subject=subject)
        return True
