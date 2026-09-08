"""Versioned strategy registry (ARCHITECTURE.md §6).

A strategy may only run in a scan when its :class:`StrategySpec` is complete and
its status is ``EXPERIMENTAL`` (paper only, no alerts) or ``PAPER_APPROVED``
(alerts allowed). Promotion is earned automatically by clearing every gate in
``signalforge.research.promotion`` on genuine licensed data — never a manual
action. A human may only move a strategy *down* (to ``experimental`` or
``disabled``); the dashboard and CLI both enforce this.

Phase 0: the data structures and completeness validation. Phase 1 wires the
baseline strategies and their committed backtest reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from signalforge.domain import Direction, Horizon, StrategyStatus

__all__ = [
    "Direction",
    "Horizon",
    "StrategyRegistrationError",
    "StrategyRegistry",
    "StrategySpec",
    "StrategyStatus",
]


@dataclass(frozen=True, slots=True)
class StrategySpec:
    name: str
    version: str
    git_sha: str
    horizon: Horizon
    rule_definition: str
    required_data_sources: tuple[str, ...]
    feature_definitions: tuple[str, ...]
    entry_conditions: str
    invalidation_conditions: str
    exit_logic: str
    stop_logic: str
    time_stop: str
    liquidity_requirements: str
    event_filters: str
    assumed_transaction_costs: str
    slippage_model: str
    permits_long: bool
    permits_short: bool
    known_failure_modes: tuple[str, ...]
    test_date_range: str
    in_sample_period: str
    out_of_sample_period: str
    walkforward_result_ref: str
    status: StrategyStatus = StrategyStatus.EXPERIMENTAL
    notes: str = ""

    def missing_fields(self) -> list[str]:
        """Return names of required fields that are empty (blocks scan use)."""
        optional = {"status", "notes"}
        out: list[str] = []
        for f in fields(self):
            if f.name in optional:
                continue
            value = getattr(self, f.name)
            if value in ("", (), None):
                out.append(f.name)
        return out

    @property
    def key(self) -> str:
        """Stable strategy name (already carries the horizon, e.g. ``trend.short_swing``)."""
        return self.name

    @property
    def versioned_key(self) -> str:
        return f"{self.name}@{self.version}"


class StrategyRegistrationError(RuntimeError):
    pass


@dataclass(slots=True)
class StrategyRegistry:
    _specs: dict[str, StrategySpec] = field(default_factory=dict)

    def register(self, spec: StrategySpec) -> None:
        missing = spec.missing_fields()
        if missing:
            raise StrategyRegistrationError(
                f"{spec.versioned_key}: incomplete StrategySpec, missing {missing}"
            )
        if spec.versioned_key in self._specs:
            raise StrategyRegistrationError(f"{spec.versioned_key}: already registered")
        self._specs[spec.versioned_key] = spec

    def get(self, versioned_key: str) -> StrategySpec:
        return self._specs[versioned_key]

    def scan_eligible(self) -> list[StrategySpec]:
        return [
            s
            for s in self._specs.values()
            if s.status in (StrategyStatus.EXPERIMENTAL, StrategyStatus.PAPER_APPROVED)
        ]

    def alert_eligible(self) -> list[StrategySpec]:
        return [s for s in self._specs.values() if s.status is StrategyStatus.PAPER_APPROVED]
