"""Execution boundary — disabled by default, nothing armed by default.

D6 and ADR 0006 separate two paths: paper/sandbox strategy execution uses the
existing registry, risk limits, arming and is_paper proof; production operations
use immutable human reviews and explicit per-action confirmation through the CLI.
Production adapters never enter the strategy registry or automated cycle.

No LLM, app, research, or scheduler import path may reach either order surface.
No automatic liquidation, credential acquisition, credential persistence, browser
automation, or blind retry is provided. Credentials are operator-provisioned
references only. Production shares durable account admission with other apps.
The kill switch blocks openings and transfers; exact protective close/cancel
still requires its own confirmation and validated account/order identity.

Explicit account export may use the official SDK for three allowlisted GETs;
it cannot place orders, refresh credentials or enter the strategy registry.
Importing this package performs no network call, reads no credential, and
constructs no adapter. The dashboard consumes sanitized files, not this package.
"""

from __future__ import annotations

#: Asserted by a safety test. Two independent gates exist, neither sufficient
#: alone: this constant plus the ``execution.enabled`` setting (default False),
#: and even with both, zero orders can be submitted while no unexpired
#: ``armed_strategy`` row exists.
EXECUTION_DISABLED_BY_DEFAULT = True

__all__ = ["EXECUTION_DISABLED_BY_DEFAULT", "execution_enabled"]


def execution_enabled() -> bool:
    """Whether the execution layer is enabled at all.

    Reads the version-controlled ``ResearchConfig.execution.enabled`` flag,
    which ships **False** and is deliberately excluded from the approval-scope
    hash (``SCOPE_HASH_FIELDS``): an execution setting shapes no signal, and
    moving ``config_hash`` would put every live PAPER_APPROVED approval out of
    scope — the exact incident of 2026-09-11.

    This being True is necessary and nowhere near sufficient: nothing is armed
    by default, and arming is a separate, audited, expiring operator ceremony.
    """
    from signalforge.config import get_settings

    return bool(get_settings().research.execution.enabled)
