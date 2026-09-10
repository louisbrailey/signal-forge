"""Output guards for AI-written narratives (ARCHITECTURE.md §11).

An AI narrative may only rephrase deterministic facts. These guards reject output
that:
* introduces a numeric token (number, percentage, price, multiple) not present
  in the frozen ``facts`` it was given, or
* omits the required footer.

Deterministic, no network — safe to unit test and to run inline on every call.
"""

from __future__ import annotations

import re
from datetime import date, datetime

AI_FOOTER = "AI explanation, not a trading instruction."
RESEARCH_ONLY_LINE = "Research signal only — no order was placed."

# Numbers like 12, 12.5, 1,234.56, 3.2%, -0.5, $10, 2x
_NUMERIC = re.compile(r"[-+]?\$?\d[\d,]*(?:\.\d+)?\s*(?:%|x)?", re.IGNORECASE)
# Tokens we never treat as "claims" needing grounding.
_TRIVIAL = {"0", "1", "2", "a", "one", "two"}
# Evidence keys whose values are timestamps/dates, never quantities. A narrative
# number is NOT grounded by coincidentally matching a digit run inside a
# timestamp ("2026-09-10T18:45:00" must not ground "45%" or "18x").
_TIMESTAMP_KEY_SUFFIXES = ("_at", "as_of", "_date", "date", "_ts", "ts", "timestamp", "time")
# ISO-8601 date / datetime (with optional fractional seconds and offset).
_ISO_TIMESTAMP = re.compile(
    r"^\s*\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\s*$"
)


class GuardViolation(RuntimeError):
    """Raised when an AI narrative fails a guard."""


def _normalise(token: str) -> str:
    """Lower-case, drop grouping/sign/currency so ``+3.2%`` and ``3.2%`` compare equal.

    Grounding compares magnitudes, not signs: a narrative that says ``-0.5%`` is
    still grounded by a fact value of ``0.5``.
    """
    cleaned = token.strip().lower().replace(",", "").replace("$", "").replace(" ", "")
    return cleaned.lstrip("+-")


def extract_numeric_tokens(text: str) -> set[str]:
    """Return the set of normalised numeric tokens found in ``text``."""
    out: set[str] = set()
    for m in _NUMERIC.finditer(text):
        norm = _normalise(m.group(0))
        if norm and norm not in _TRIVIAL:
            out.add(norm)
    return out


def _is_timestamp_key(key: object) -> bool:
    return isinstance(key, str) and key.lower().endswith(_TIMESTAMP_KEY_SUFFIXES)


def _is_timestamp_value(node: object) -> bool:
    return isinstance(node, (datetime, date)) or (
        isinstance(node, str) and bool(_ISO_TIMESTAMP.match(node))
    )


def _grounded_numbers(facts: object) -> set[str]:
    """Numeric tokens a narrative may legitimately use.

    Timestamps are skipped entirely — by key (``*_at``, ``as_of``, ``*_date``,
    ...) and by shape (ISO-8601 strings, ``datetime``/``date`` objects) — so a
    fabricated small number cannot be "grounded" by a date fragment.
    """
    grounded: set[str] = set()

    def walk(node: object) -> None:
        if _is_timestamp_value(node):
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if _is_timestamp_key(k):
                    continue
                walk(v)
        elif isinstance(node, (list, tuple, set)):
            for v in node:
                walk(v)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            grounded.add(_normalise(str(node)))
            grounded.add(_normalise(f"{node:.2f}"))
            if isinstance(node, float):
                grounded.add(_normalise(f"{node:g}"))
        elif isinstance(node, str):
            grounded.update(extract_numeric_tokens(node))

    walk(facts)
    return grounded


def assert_grounded(narrative: str, facts: object, *, require_footer: bool = True) -> None:
    """Raise :class:`GuardViolation` if ``narrative`` is not fully supported by ``facts``."""
    if require_footer and AI_FOOTER not in narrative:
        raise GuardViolation(f"missing required footer: {AI_FOOTER!r}")

    used = extract_numeric_tokens(narrative)
    grounded = _grounded_numbers(facts)
    ungrounded = {t for t in used if t not in grounded and t.rstrip("%x") not in grounded}
    if ungrounded:
        raise GuardViolation(
            f"narrative introduces numbers not present in facts: {sorted(ungrounded)}"
        )
