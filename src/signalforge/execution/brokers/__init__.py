"""Broker adapters — selectable ONLY through config, never by import (D6 §2, §3).

This package is the **one** place in ``src/signalforge`` where a brokerage host
literal may appear (T5's allowlist). Today it holds a single adapter,
``paper_reference``: local, deterministic, and network-free, whose fills are
drill artifacts fenced off from every gate (§3.1 rule 4).

**Nothing here is instantiated at import time.** Importing this package — or
any module in it — builds no adapter, opens no socket, and reads no credential.
An adapter comes into existence only through :func:`build_adapter`, which
refuses twice before it constructs anything:

1. ``ResearchConfig.execution.enabled`` must be True. It ships **False**, and
   the ``EXECUTION_DISABLED_BY_DEFAULT`` constant says so a second time.
2. ``ResearchConfig.execution.adapter_name`` must name a registered adapter.
   An unknown name is a refusal, never a fallback to some default adapter —
   the fail-closed direction, because the failure mode of "fall back to
   something" is submitting through an adapter nobody selected.

Both gates together are still nowhere near sufficient: with no unexpired
``armed_strategy`` row, zero orders can be submitted whatever this returns.

The registry maps a name to a **loader**, not to a class object, so importing
this module does not import the adapter module either. That is not ceremony:
it keeps the one file that is permitted to contain a brokerage host literal out
of every import graph that has no business reaching it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from signalforge.config.research import ResearchConfig
    from signalforge.execution.protocol import BrokerAdapter

__all__ = [
    "ADAPTER_NAMES",
    "AdapterNotSelectable",
    "ExecutionDisabled",
    "UnknownAdapter",
    "build_adapter",
    "selected_adapter_name",
]

#: Every adapter this build can select, by name. A name absent from this tuple
#: cannot be selected however the config is written.
ADAPTER_NAMES: tuple[str, ...] = ("paper_reference",)


class AdapterNotSelectable(RuntimeError):
    """No adapter may be built. The message names the condition that refused."""


class ExecutionDisabled(AdapterNotSelectable):
    """``execution.enabled`` is False — the shipped default (D6 §2)."""


class UnknownAdapter(AdapterNotSelectable):
    """``execution.adapter_name`` names no registered adapter.

    Fail-closed: there is deliberately no default adapter to fall back to.
    """


def _load_paper_reference() -> Callable[..., BrokerAdapter]:
    from signalforge.execution.brokers.paper_reference import PaperReferenceBroker

    return PaperReferenceBroker


#: name -> a loader returning the adapter factory. The loader is called only
#: from :func:`build_adapter`; importing this module calls none of them.
_REGISTRY: dict[str, Callable[[], Callable[..., BrokerAdapter]]] = {
    "paper_reference": _load_paper_reference,
}


def _research_config(config: ResearchConfig | None) -> ResearchConfig:
    if config is not None:
        return config
    from signalforge.config import get_settings

    return get_settings().research


def selected_adapter_name(config: ResearchConfig | None = None) -> str:
    """The configured adapter name, or raise :class:`AdapterNotSelectable`.

    Separate from :func:`build_adapter` so a caller (the CLI status command,
    the arming ceremony) can report *which* adapter would be used without
    constructing one.
    """
    research = _research_config(config)
    execution = research.execution
    if not execution.enabled:
        raise ExecutionDisabled(
            "research.execution.enabled is False — the shipped default; no adapter is built, "
            "and enabling it is still not sufficient to submit anything (D6 §2)"
        )
    name = execution.adapter_name
    if name not in _REGISTRY:
        raise UnknownAdapter(
            f"execution.adapter_name={name!r} names no registered adapter; "
            f"known adapters: {', '.join(ADAPTER_NAMES)}. There is no default to fall back to."
        )
    return name


def build_adapter(config: ResearchConfig | None = None, **adapter_kwargs: Any) -> BrokerAdapter:
    """Construct the configured adapter, or raise :class:`AdapterNotSelectable`.

    The **only** sanctioned way an adapter object comes into existence. Keyword
    arguments are passed through to the adapter's constructor, which is where
    the expected account id, the pre-submission information set, the clock and
    the audit sink are supplied — none of them has a default that would let an
    adapter be built without them.
    """
    name = selected_adapter_name(config)
    factory = _REGISTRY[name]()
    adapter = factory(**adapter_kwargs)
    if adapter.name != name:
        # A registry whose key and adapter disagree would make the audit trail
        # lie about which adapter ran.
        raise UnknownAdapter(
            f"registry key {name!r} built an adapter calling itself {adapter.name!r}"
        )
    return adapter
