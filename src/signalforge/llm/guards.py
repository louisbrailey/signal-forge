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

AI_FOOTER = "AI explanation, not a trading instruction."
RESEARCH_ONLY_LINE = "Research signal only — no order was placed."

# Numbers like 12, 12.5, 1,234.56, 3.2%, -0.5, $10, 2x
_NUMERIC = re.compile(r"[-+]?\$?\d[\d,]*(?:\.\d+)?\s*(?:%|x)?", re.IGNORECASE)
# Tokens we never treat as "claims" needing grounding.
_TRIVIAL = {"0", "1", "2", "a", "one", "two"}


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


def _grounded_numbers(facts: object) -> set[str]:
    grounded: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for v in node.values():
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
