from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Literal, Mapping

from src.domain.regime.model import ClusterAssignment
from src.domain.regime.selection import (
    RegimeSelectionState,
    SelectStrategyResult,
    SelectionEventType,
)
from src.domain.regime.temporal import is_regime_boundary


ModelType = Literal["gmm", "kmeans"]


def _probability(value: object, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"{field} must be finite and between zero and one")
    return float(value)


def _distance(value: object, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{field} must be finite and nonnegative")
    return float(value)


def _canonical(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a nonempty canonical string")
    return value


@dataclass(frozen=True)
class SelectionConfidenceThresholds:
    model_type: ModelType
    gmm_probability_min: float | None = None
    gmm_margin_min: float | None = None
    kmeans_max_standardized_distance: float | None = None

    def __post_init__(self) -> None:
        if self.model_type == "gmm":
            if self.gmm_probability_min is None or self.gmm_margin_min is None:
                raise ValueError("GMM confidence thresholds are required")
            _probability(self.gmm_probability_min, "gmm_probability_min")
            _probability(self.gmm_margin_min, "gmm_margin_min")
            if self.kmeans_max_standardized_distance is not None:
                raise ValueError("GMM thresholds cannot contain a KMeans distance")
        elif self.model_type == "kmeans":
            if self.kmeans_max_standardized_distance is None:
                raise ValueError("KMeans maximum distance is required")
            _distance(
                self.kmeans_max_standardized_distance,
                "kmeans_max_standardized_distance",
            )
            if self.gmm_probability_min is not None or self.gmm_margin_min is not None:
                raise ValueError("KMeans thresholds cannot contain GMM probabilities")
        else:
            raise ValueError("confidence threshold model type must be gmm or kmeans")


@dataclass(frozen=True)
class SelectStrategyCommand:
    previous_state: RegimeSelectionState | None
    symbol: str
    boundary_at: object
    target_artifact_version: str
    model_type: ModelType
    confidence_thresholds: SelectionConfidenceThresholds
    assignment: ClusterAssignment
    cluster_strategy_mapping: Mapping[str, str | None]

    def __post_init__(self) -> None:
        symbol = _canonical(self.symbol, "symbol")
        if symbol != symbol.upper():
            raise ValueError("symbol must be canonical uppercase")
        _canonical(self.target_artifact_version, "target_artifact_version")
        if self.model_type not in {"gmm", "kmeans"}:
            raise ValueError("model type must be gmm or kmeans")
        if not isinstance(self.confidence_thresholds, SelectionConfidenceThresholds):
            raise ValueError("confidence thresholds are required")
        if self.confidence_thresholds.model_type != self.model_type:
            raise ValueError("confidence threshold model type must match command model type")
        if not isinstance(self.assignment, ClusterAssignment):
            raise ValueError("assignment must be a ClusterAssignment")
        if not is_regime_boundary(self.boundary_at):
            raise ValueError("boundary_at must be a four-hour UTC boundary")
        if self.previous_state is not None:
            if not isinstance(self.previous_state, RegimeSelectionState):
                raise ValueError("previous_state must be a RegimeSelectionState")
            if self.previous_state.symbol != self.symbol:
                raise ValueError("previous state symbol must match command symbol")
            if self.boundary_at <= self.previous_state.last_boundary_at:
                raise ValueError("boundary_at must be strictly after the previous boundary")

        mapping = dict(self.cluster_strategy_mapping)
        if not mapping:
            raise ValueError("cluster strategy mapping cannot be empty")
        for fingerprint, strategy in mapping.items():
            _canonical(fingerprint, "mapping fingerprint")
            if strategy is not None:
                _canonical(strategy, "strategy profile id")
        if self.assignment.fingerprint not in mapping:
            raise ValueError("assignment fingerprint must exist in the mapping")
        if (
            self.previous_state is not None
            and self.target_artifact_version == self.previous_state.artifact_version
            and self.previous_state.current_cluster_fingerprint is not None
            and self.previous_state.current_cluster_fingerprint not in mapping
        ):
            raise ValueError("committed artifact mapping must contain the current cluster")
        object.__setattr__(self, "cluster_strategy_mapping", MappingProxyType(mapping))


class SelectStrategyUseCase:
    def execute(self, command: SelectStrategyCommand) -> SelectStrategyResult:
        high_confidence = _is_high_confidence(
            command.model_type,
            command.confidence_thresholds,
            command.assignment,
        )
        previous = command.previous_state
        expected_version = 0 if previous is None else previous.state_version

        if previous is None:
            state, events = _initial_transition(command, high_confidence)
        elif command.target_artifact_version != previous.artifact_version:
            state, events = _replacement_transition(command, high_confidence)
        elif high_confidence:
            state, events = _confident_transition(command)
        else:
            state, events = _low_confidence_transition(command)

        return SelectStrategyResult(expected_version, state, events)


def _is_high_confidence(
    model_type: ModelType,
    thresholds: SelectionConfidenceThresholds,
    assignment: ClusterAssignment,
) -> bool:
    if model_type == "gmm":
        if assignment.distance is not None:
            raise ValueError("GMM assignment distance must be None")
        return (
            assignment.dominant_probability >= thresholds.gmm_probability_min
            and assignment.dominant_probability - assignment.second_probability
            >= thresholds.gmm_margin_min
        )
    if assignment.distance is None:
        raise ValueError("KMeans assignment distance is required")
    return assignment.distance <= thresholds.kmeans_max_standardized_distance


def _make_state(
    command: SelectStrategyCommand,
    *,
    artifact: str,
    current: str | None,
    active: str | None,
    pending_cluster: str | None = None,
    pending_count: int = 0,
    pending_artifact: str | None = None,
    low_count: int = 0,
    entries: bool = False,
) -> RegimeSelectionState:
    previous_version = 0 if command.previous_state is None else command.previous_state.state_version
    return RegimeSelectionState(
        symbol=command.symbol,
        artifact_version=artifact,
        current_cluster_fingerprint=current,
        active_strategy_profile_id=active,
        pending_cluster_fingerprint=pending_cluster,
        pending_confirmation_count=pending_count,
        consecutive_low_confidence_count=low_count,
        new_entries_enabled=entries,
        last_boundary_at=command.boundary_at,
        state_version=previous_version + 1,
        pending_artifact_version=pending_artifact,
    )


def _initial_transition(command: SelectStrategyCommand, high: bool):
    if not high:
        return (
            _make_state(
                command,
                artifact=command.target_artifact_version,
                current=None,
                active=None,
                low_count=1,
            ),
            (SelectionEventType.CLASSIFICATION,),
        )
    fingerprint = command.assignment.fingerprint
    strategy = command.cluster_strategy_mapping[fingerprint]
    return (
        _make_state(
            command,
            artifact=command.target_artifact_version,
            current=fingerprint,
            active=strategy,
            entries=strategy is not None,
        ),
        (SelectionEventType.CLASSIFICATION,),
    )


def _confident_transition(command: SelectStrategyCommand):
    previous = command.previous_state
    fingerprint = command.assignment.fingerprint
    if fingerprint == previous.current_cluster_fingerprint:
        strategy = command.cluster_strategy_mapping[fingerprint]
        events = _strategy_events(previous.active_strategy_profile_id, strategy)
        return (
            _make_state(
                command,
                artifact=previous.artifact_version,
                current=fingerprint,
                active=strategy,
                entries=strategy is not None,
            ),
            events or (SelectionEventType.CLASSIFICATION,),
        )

    confirms = (
        previous.pending_artifact_version is None
        and previous.pending_cluster_fingerprint == fingerprint
        and previous.pending_confirmation_count == 1
    )
    if not confirms:
        return (
            _make_state(
                command,
                artifact=previous.artifact_version,
                current=previous.current_cluster_fingerprint,
                active=previous.active_strategy_profile_id,
                pending_cluster=fingerprint,
                pending_count=1,
                entries=previous.new_entries_enabled,
            ),
            (SelectionEventType.CLASSIFICATION,),
        )

    strategy = command.cluster_strategy_mapping[fingerprint]
    events = (SelectionEventType.CLUSTER_TRANSITION,) + _strategy_events(
        previous.active_strategy_profile_id, strategy
    )
    return (
        _make_state(
            command,
            artifact=previous.artifact_version,
            current=fingerprint,
            active=strategy,
            entries=strategy is not None,
        ),
        events,
    )


def _low_confidence_transition(command: SelectStrategyCommand):
    previous = command.previous_state
    low_count = min(previous.consecutive_low_confidence_count + 1, 2)
    if low_count >= 2:
        events = (
            (SelectionEventType.CASH_TRANSITION,)
            if previous.active_strategy_profile_id is not None
            else (SelectionEventType.CLASSIFICATION,)
        )
        active = None
    else:
        events = (
            (SelectionEventType.ENTRY_SUSPENDED,)
            if previous.new_entries_enabled
            else (SelectionEventType.CLASSIFICATION,)
        )
        active = previous.active_strategy_profile_id
    return (
        _make_state(
            command,
            artifact=previous.artifact_version,
            current=previous.current_cluster_fingerprint,
            active=active,
            low_count=low_count,
            entries=False,
        ),
        events,
    )


def _replacement_transition(command: SelectStrategyCommand, high: bool):
    previous = command.previous_state
    if not high:
        return _low_confidence_transition(command)

    fingerprint = command.assignment.fingerprint
    confirms = (
        previous.pending_artifact_version == command.target_artifact_version
        and previous.pending_cluster_fingerprint == fingerprint
        and previous.pending_confirmation_count == 1
    )
    if not confirms:
        return (
            _make_state(
                command,
                artifact=previous.artifact_version,
                current=previous.current_cluster_fingerprint,
                active=previous.active_strategy_profile_id,
                pending_cluster=fingerprint,
                pending_count=1,
                pending_artifact=command.target_artifact_version,
                entries=False,
            ),
            (SelectionEventType.ENTRY_SUSPENDED,),
        )

    strategy = command.cluster_strategy_mapping[fingerprint]
    events = [SelectionEventType.ARTIFACT_REPLACED]
    if previous.current_cluster_fingerprint != fingerprint:
        events.append(SelectionEventType.CLUSTER_TRANSITION)
    events.extend(_strategy_events(previous.active_strategy_profile_id, strategy))
    return (
        _make_state(
            command,
            artifact=command.target_artifact_version,
            current=fingerprint,
            active=strategy,
            entries=strategy is not None,
        ),
        tuple(events),
    )


def _strategy_events(old: str | None, new: str | None) -> tuple[SelectionEventType, ...]:
    if old == new:
        return ()
    if new is None:
        return (SelectionEventType.CASH_TRANSITION,)
    return (SelectionEventType.STRATEGY_TRANSITION,)


__all__ = [
    "SelectStrategyCommand",
    "SelectStrategyUseCase",
    "SelectionConfidenceThresholds",
]
