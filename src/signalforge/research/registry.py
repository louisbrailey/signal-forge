"""Versioned strategy registry (ARCHITECTURE.md §6).

A strategy may only run in a scan when its :class:`StrategySpec` is complete and
its status is ``EXPERIMENTAL`` (paper only, no alerts) or ``PAPER_APPROVED``
(alerts allowed). Promotion is a manual, audited action.

Phase 0: the data structures and completeness validation. Phase 1 wires the
baseline strategies and their committed backtest reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import StrEnum

from signalforge.config.research import Horizon


class StrategyStatus(StrEnum):
    EXPERIMENTAL = "experimental"  # runs in paper only; never alerts
    PAPER_APPROVED = "paper_approved"  # alert-eligible
    DISABLED = "disabled"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    AVOID = "AVOID"


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
                f"{spec.key}: incomplete StrategySpec, missing {missing}"
            )
        if spec.key in self._specs:
            raise StrategyRegistrationError(f"{spec.key}: already registered")
        self._specs[spec.key] = spec

    def get(self, key: str) -> StrategySpec:
        return self._specs[key]

    def scan_eligible(self) -> list[StrategySpec]:
        return [
            s
            for s in self._specs.values()
            if s.status in (StrategyStatus.EXPERIMENTAL, StrategyStatus.PAPER_APPROVED)
        ]

    def alert_eligible(self) -> list[StrategySpec]:
        return [s for s in self._specs.values() if s.status is StrategyStatus.PAPER_APPROVED]
