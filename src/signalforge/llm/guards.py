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


def _date_tokens(node: object) -> set[str]:
    """Year / month / day tokens of a timestamp value (never its time of day)."""
    d: date | None
    if isinstance(node, datetime):
        d = node.date()
    elif isinstance(node, date):
        d = node
    else:
        try:
            d = date.fromisoformat(str(node).strip()[:10])
        except ValueError:
            return set()
    return {str(d.year), f"{d.month:02d}", str(d.month), f"{d.day:02d}", str(d.day)}


_TIMESTAMP_KEYS = frozenset({"ts", "as_of", "date", "time", "timestamp", "datetime"})
_TIMESTAMP_KEY_ENDINGS = ("_at", "_ts", "_date", "_time", "_timestamp", "_datetime")


def _is_timestamp_key(key: object) -> bool:
    """Whole-token match only: "limits" or "items" are NOT timestamp keys."""
    if not isinstance(key, str):
        return False
    k = key.lower()
    return k in _TIMESTAMP_KEYS or k.endswith(_TIMESTAMP_KEY_ENDINGS)


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
            # A narrative may restate the DATE ("September 11, 2026"); the time of
            # day (hours/minutes/seconds) is never grounded — "18:45" must not
            # legitimise "45%".
            grounded.update(_date_tokens(node))
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if _is_timestamp_key(k):
                    # the date part of a timestamp may still be restated
                    grounded.update(_date_tokens(v))
                    continue
                # window lengths live in key names ("market_ret_20d", "pct_above_50sma")
                if isinstance(k, str):
                    grounded.update(extract_numeric_tokens(k.replace("_", " ")))
                walk(v)
        elif isinstance(node, (list, tuple, set)):
            for v in node:
                walk(v)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            grounded.add(_normalise(str(node)))
            if isinstance(node, float):
                grounded.add(_normalise(f"{node:g}"))
                # a deterministic summary legitimately rounds; accept 1–6 decimals
                for nd in range(1, 7):
                    grounded.add(_normalise(f"{node:.{nd}f}"))
                # a fraction in [0, 1] may be restated as a percentage (0.6 -> 60%)
                if 0 < abs(node) <= 1:
                    pct = node * 100
                    for nd in range(3):
                        grounded.add(_normalise(f"{pct:.{nd}f}"))
            else:
                grounded.add(_normalise(f"{node:.2f}"))
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
