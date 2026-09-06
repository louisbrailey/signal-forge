"""structlog configuration with a hard secret-redaction pass (invariant S5).

No log line may contain a credential. Redaction happens by key name and by type
(``pydantic.SecretStr`` is always masked), recursively, before rendering.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from pydantic import SecretStr

_SENSITIVE_KEY = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|token|authorization|auth|bearer|credential)"
)
_MASK = "***redacted***"
_MAX_DEPTH = 8


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return ``value`` with secrets masked, recursively."""
    if isinstance(value, SecretStr):
        return _MASK
    if _depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _SENSITIVE_KEY.search(k):
                out[k] = _MASK
            else:
                out[k] = redact(v, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        seq = [redact(v, _depth=_depth + 1) for v in value]
        return type(value)(seq) if isinstance(value, tuple) else seq
    return value


def _redaction_processor(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = redact(event_dict)
    return result


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    """Idempotently configure structlog + stdlib logging."""
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redaction_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        # Do not cache: a cached logger can outlive the stream it was bound to
        # (e.g. a captured stderr in a test), which raises on the next write.
        cache_logger_on_first_use=False,
    )
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=logging.getLevelNamesMapping().get(level.upper(), logging.INFO),
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
