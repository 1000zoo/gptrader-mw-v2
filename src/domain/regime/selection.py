from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.domain.regime.temporal import is_regime_boundary


class SelectionEventType(Enum):
    CLASSIFICATION = "classification"
    ENTRY_SUSPENDED = "entry_suspended"
    CLUSTER_TRANSITION = "cluster_transition"
    STRATEGY_TRANSITION = "strategy_transition"
    CASH_TRANSITION = "cash_transition"
    ARTIFACT_REPLACED = "artifact_replaced"


def _canonical_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a nonempty canonical string")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _canonical_text(value, field)


def _nonnegative_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


@dataclass(frozen=True)
class RegimeSelectionState:
    symbol: str
    artifact_version: str
    current_cluster_fingerprint: str | None
    active_strategy_profile_id: str | None
    pending_cluster_fingerprint: str | None
    pending_confirmation_count: int
    consecutive_low_confidence_count: int
    new_entries_enabled: bool
    last_boundary_at: datetime
    state_version: int
    pending_artifact_version: str | None = None

    def __post_init__(self) -> None:
        symbol = _canonical_text(self.symbol, "symbol")
        if symbol != symbol.upper():
            raise ValueError("symbol must be canonical uppercase")
        _canonical_text(self.artifact_version, "artifact_version")
        _optional_text(self.current_cluster_fingerprint, "current_cluster_fingerprint")
        _optional_text(self.active_strategy_profile_id, "active_strategy_profile_id")
        _optional_text(self.pending_cluster_fingerprint, "pending_cluster_fingerprint")
        _optional_text(self.pending_artifact_version, "pending_artifact_version")
        _nonnegative_integer(self.pending_confirmation_count, "pending_confirmation_count")
        _nonnegative_integer(
            self.consecutive_low_confidence_count,
            "consecutive_low_confidence_count",
        )
        _nonnegative_integer(self.state_version, "state_version")
        if type(self.new_entries_enabled) is not bool:
            raise ValueError("new_entries_enabled must be a strict boolean")
        if not is_regime_boundary(self.last_boundary_at):
            raise ValueError("last_boundary_at must be a four-hour UTC boundary")

        has_pending = self.pending_confirmation_count > 0
        if has_pending != (self.pending_cluster_fingerprint is not None):
            raise ValueError("pending count and cluster fingerprint must be consistent")
        if self.pending_confirmation_count > 1:
            raise ValueError("only one uncommitted confirmation may be persisted")
        if (
            self.pending_artifact_version is not None
            and self.pending_artifact_version == self.artifact_version
        ):
            raise ValueError("pending artifact must differ from the committed artifact")
        if self.pending_artifact_version is not None and not has_pending:
            raise ValueError("pending artifact requires a pending confirmation")
        if self.consecutive_low_confidence_count and has_pending:
            raise ValueError("low confidence and pending confirmation cannot coexist")
        if self.current_cluster_fingerprint is None and (
            self.active_strategy_profile_id is not None or self.new_entries_enabled
        ):
            raise ValueError("an active selection requires a current cluster")
        if self.active_strategy_profile_id is None and self.new_entries_enabled:
            raise ValueError("cash cannot enable new entries")


@dataclass(frozen=True)
class SelectStrategyResult:
    expected_state_version: int
    state: RegimeSelectionState
    events: tuple[SelectionEventType, ...]

    def __post_init__(self) -> None:
        expected = _nonnegative_integer(
            self.expected_state_version, "expected_state_version"
        )
        if self.state.state_version != expected + 1:
            raise ValueError("proposed state version must increment expected state version")
        events = tuple(self.events)
        if not events or any(not isinstance(event, SelectionEventType) for event in events):
            raise ValueError("selection events must be nonempty and known")
        if len(set(events)) != len(events):
            raise ValueError("selection events must be unique")
        if SelectionEventType.CLASSIFICATION in events and len(events) != 1:
            raise ValueError("classification cannot accompany a material event")
        if SelectionEventType.ENTRY_SUSPENDED in events and len(events) != 1:
            raise ValueError("entry suspension must be a standalone event")
        material_order = (
            SelectionEventType.ARTIFACT_REPLACED,
            SelectionEventType.CLUSTER_TRANSITION,
            SelectionEventType.STRATEGY_TRANSITION,
            SelectionEventType.CASH_TRANSITION,
        )
        if all(event in material_order for event in events):
            positions = tuple(material_order.index(event) for event in events)
            if positions != tuple(sorted(positions)):
                raise ValueError("selection events must use deterministic order")
            if (
                SelectionEventType.STRATEGY_TRANSITION in events
                and SelectionEventType.CASH_TRANSITION in events
            ):
                raise ValueError("strategy and cash transitions are mutually exclusive")
        object.__setattr__(self, "events", events)


__all__ = [
    "RegimeSelectionState",
    "SelectStrategyResult",
    "SelectionEventType",
]
