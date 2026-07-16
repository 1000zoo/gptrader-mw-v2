from datetime import datetime
from typing import Protocol

from src.domain.regime.selection import (
    AuditedSelectStrategyResult,
    RegimeSelectionState,
    SelectionEventType,
    SelectStrategyResult,
)


class ConcurrentSelectionStateError(RuntimeError):
    """Raised when a selector result was computed from a stale state version."""


class RegimeSelectionStateRepositoryPort(Protocol):
    """Stores decisions keyed by symbol, boundary, and evaluated artifact identity."""

    def load(self, symbol: str) -> RegimeSelectionState | None:
        ...

    def commit(
        self,
        expected_state_version: int,
        result: SelectStrategyResult,
    ) -> SelectStrategyResult:
        ...

    def find_committed_result(
        self,
        symbol: str,
        boundary_at: datetime,
        evaluated_artifact_identity: str,
    ) -> SelectStrategyResult | None:
        ...

    def list_events(self, symbol: str) -> tuple[SelectionEventType, ...]:
        ...


class AuditedRegimeSelectionStateRepositoryPort(
    RegimeSelectionStateRepositoryPort, Protocol
):
    """Atomically stores the canonical result and its required audit envelope."""

    def commit_audited(
        self,
        expected_state_version: int,
        result: AuditedSelectStrategyResult,
    ) -> AuditedSelectStrategyResult:
        ...

    def find_committed_audited(
        self,
        symbol: str,
        boundary_at: datetime,
        evaluated_artifact_identity: str,
    ) -> AuditedSelectStrategyResult | None:
        ...


__all__ = [
    "AuditedRegimeSelectionStateRepositoryPort",
    "ConcurrentSelectionStateError",
    "RegimeSelectionStateRepositoryPort",
]
